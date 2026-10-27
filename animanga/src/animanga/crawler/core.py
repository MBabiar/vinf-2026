"""The crawl loop: frontier -> politeness -> fetch -> classify -> store -> links.

Shared by all sites; everything site-specific is in `sites/<name>.py`, passed in as a module.
State lives only in append-only TSV files and in the raw page files, so a stopped or crashed
crawl resumes by replaying them. Nothing is ever overwritten or deleted.
"""

import hashlib
import heapq
import json
import logging
import os
import random
import signal
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import requests

from animanga.crawler import config, robots
from animanga.crawler.sites.base import Found, page_title
from animanga.tsv import TsvWriter, read_rows

log = logging.getLogger(__name__)

FETCH_COLUMNS = [
    "ts",
    "run_id",
    "url",
    "id",
    "attempt",
    "status",
    "outcome",
    "location",
    "bytes",
    "sha256",
    "elapsed_ms",
    "render_ms",
    "path",
    "error",
]
FRONTIER_COLUMNS = ["ts", "url", "id", "source"]
LINK_COLUMNS = ["from_id", "to_kind", "to_id", "anchor"]
RUN_COLUMNS = ["run_id", "event", "ts", "pid", "info"]
# every HTTP response with all its headers (Set-Cookie left out), for the K2a/Odovzdanie 1 metadata
RESPONSE_COLUMNS = ["ts", "run_id", "id", "url", "status", "headers"]
# pages.tsv: ts, id, kind, title, bytes, <one count column per site.LINK_KINDS>, path
# waits that are not the page's fault: they don't count as attempts of the ID (also on resume).
# Refusals (blocked, challenge) count since 8 Oct (user): MU answered 429 for one page for 13 h and
# the crawl hung on it; now the ID is failed after MAX_ATTEMPTS and the crawl goes on.
NOT_COUNTED = {"offline"}
# the health check after an ID failed twice: a page that worked, requested again (not saved).
# Logged under the failing ID, but neither an attempt nor a kind of it.
HEALTH = {"health_ok", "health_bad"}
# a redirect hop (MU series.html?id=N -> /series/...) is part of the attempt that follows it
HOPS = {"redirect"}
# a kind switch (ANN anime.php?id=N -> manga.php?id=N) is not final: the other URL is fetched next
FINAL = {
    "saved",
    "alias",
    "missing",
    "redirect_other",
    "unexpected",
    "too_large",
    "failed",
}
# checked once more at the end of every run, after all new IDs: errors and missing pages
# (user, 4 Oct: the crawl is a one-time job of about a week, so no minimum age).
# A site module may set its own RECHECK (MangaUpdates: errors only, user 18 Oct)
RECHECK = {"missing", "failed", "unexpected"}
RECHECK_AFTER = 3600  # s; an ID checked more recently in this run is not rechecked
EXISTS = {"saved", "manga", "alias", "redirect_other"}  # the ID is in use (for the tail probe)
# outcomes that are logged as warnings (errors.log); everything else is info (crawl.log only)
WARN_OUTCOMES = {
    "retry",
    "offline",
    "failed",
    "too_large",
    "unexpected",
    "redirect_other",
    "challenge",
    "blocked",
    "health_bad",
}
SLOW_SINGLE = 10.0  # s; one response slower than this is logged as a warning


def page_columns(site: ModuleType) -> list[str]:
    """Return the columns of pages.tsv for a site.

    Parameters
    ----------
    site : ModuleType
        A site module (see `sites/base.py`).

    Returns
    -------
    list[str]
        Fixed columns plus one link-count column per kind in ``site.LINK_KINDS``.
    """
    return ["ts", "id", "kind", "title", "bytes", *site.LINK_KINDS, "path"]


def now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``.

    Returns
    -------
    str
        The timestamp used in every TSV file.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class StopCrawl(Exception):
    """End the crawl; the message is the stop reason written to runs.tsv."""


class Lock:
    """Hold ``crawl.lock`` while a crawler runs: one crawler per data dir.

    A second crawler would double the request rate. The file holds ``<PID> <start time>``; a lock
    of a dead process is taken over.

    Parameters
    ----------
    path : Path
        The lock file.

    Raises
    ------
    StopCrawl
        On enter, if a live process holds the lock.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Lock:
        """Create the lock file with our PID; take over a stale one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = int(self.path.read_text().split()[0] or 0)
            if alive(pid):
                raise StopCrawl(f"another crawler (PID {pid}) holds {self.path}") from None
            log.warning("taking over a stale lock of PID %s", pid)
            self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

        os.write(fd, f"{os.getpid()} {now_iso()}\n".encode())
        os.close(fd)
        return self

    def __exit__(self, *exc: object) -> None:
        """Remove the lock file."""
        self.path.unlink(missing_ok=True)


def alive(pid: int) -> bool:
    """Tell whether a process exists and has not exited.

    A process of another user (or outside our sandbox) answers PermissionError: it exists.
    An exited process that nobody has reaped yet (zombie) still exists but is dead: in the
    devcontainer PID 1 is `sleep infinity`, which never reaps a detached crawler.

    Parameters
    ----------
    pid : int
        Process ID; 0 or less is never alive.

    Returns
    -------
    bool
        True if the process exists and is not a zombie.
    """
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass

    try:
        # /proc/<pid>/stat: "pid (name) state ..."; the name may contain spaces and ")"
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError, IndexError:
        return True  # no /proc (not Linux): os.kill said it exists
    return state != "Z"


@dataclass
class State:
    """Crawl progress rebuilt from the TSV logs, so a crawl resumes where it stopped.

    Attributes
    ----------
    done : dict[int, str]
        ID -> final outcome.
    attempts : dict[int, int]
        ID -> counted attempts of its current URL.
    kind : dict[int, str]
        ID -> kind, only when it is not the site's default kind.
    frontier : set[int]
        Every ID queued so far.
    known : set[int]
        IDs whose page is already saved under another ID (site hook ``key_of_url``; MangaUpdates:
        a series saved via its legacy ID is not fetched again by its base36 ID).
    urls : dict[int, str]
        ID -> URL to fetch, when a page gave a better one than ``url_for`` (MangaUpdates: the
        catalog's URL with the slug saves a redirect). Rebuilt on start by ``found_on_start``.
    last_request : float
        Epoch seconds of the last logged request.
    run_id : int
        Number of the run that starts now.
    """

    done: dict[int, str]  # id -> final outcome
    attempts: dict[int, int]
    kind: dict[int, str]  # id -> kind, only when it is not the site's default kind
    frontier: set[int]
    last_request: float  # epoch seconds of the last logged request
    run_id: int
    known: set[int] = field(default_factory=set)
    urls: dict[int, str] = field(default_factory=dict)


def load_state(data: Path, site: ModuleType) -> State:
    """Rebuild the crawl state from fetch_log, links, frontier and runs TSV files.

    Parameters
    ----------
    data : Path
        The site's data folder (``data/<site>``).
    site : ModuleType
        The site module.

    Returns
    -------
    State
        The state to resume from; empty on the first run.
    """
    crawl = data / "crawl"
    default = site.KINDS[0]
    done: dict[int, str] = {}
    attempts: dict[int, int] = {}
    kind: dict[int, str] = {}
    known: set[int] = set()
    key_of_url = getattr(site, "key_of_url", None)
    last = 0.0

    def set_kind(key: int, k: str) -> None:
        if k == default:
            kind.pop(key, None)
        else:
            kind[key] = k

    for row in read_rows(crawl / "fetch_log.tsv"):
        key = int(row["id"])
        last = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        if row["outcome"] in HEALTH:
            continue

        if row["outcome"] not in NOT_COUNTED | HOPS:
            attempts[key] = attempts.get(key, 0) + 1
        if row["outcome"] in FINAL:
            done[key] = row["outcome"]
        if row["outcome"] == "saved" and key_of_url:
            same = key_of_url(row["url"])
            if same is not None and same != key:
                known.add(same)
        if row["outcome"] in site.KINDS:  # a switch: the ID is this kind
            set_kind(key, row["outcome"])
            attempts[key] = 0  # attempts count per URL; the other kind's URL starts from 0
        elif site.kind_of_url(row["url"]) != default:
            set_kind(key, site.kind_of_url(row["url"]))

    # links to pages of a non-default kind never requested: use that kind's URL (saves a redirect)
    for row in read_rows(crawl / "links.tsv"):
        k = row["to_kind"]
        if k in site.KINDS and k != default and int(row["to_id"]) not in attempts:
            kind[int(row["to_id"])] = k

    frontier = {int(r["id"]) for r in read_rows(crawl / "frontier.tsv")}
    runs = [int(r["run_id"]) for r in read_rows(crawl / "runs.tsv")]
    return State(done, attempts, kind, frontier, last, max(runs, default=0) + 1, known)


class Crawler:
    """The polite crawler of one site; `run` crawls until finished or stopped.

    Parameters
    ----------
    site : ModuleType
        The site module (see `sites/base.py`).
    data : Path
        The site's data folder; pages go to ``raw/``, logs to ``crawl/``.
    """

    def __init__(
        self,
        site: ModuleType,
        data: Path,
    ) -> None:
        self.site = site
        self.default_kind: str = site.KINDS[0]
        self.data = data
        self.crawl_dir = data / "crawl"
        self.problems_file = config.PROBLEMS_DIR / f"{site.NAME}.md"
        self.stop_reason = ""

        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)

        # a site module may set its own MIN_DELAY / JITTER (MangaUpdates: 1 s, user 30 Sep)
        self.min_delay: float = getattr(site, "MIN_DELAY", config.MIN_DELAY)
        self.jitter: float = getattr(site, "JITTER", config.JITTER)
        self.delay = self.min_delay
        self.recheck: set[str] = set(getattr(site, "RECHECK", RECHECK))

        self.recent: deque[float] = deque(maxlen=20)
        self.consecutive_errors = 0
        self.last_good_url = ""  # the last saved page: the health check requests it again
        self.saved_this_run = 0
        self.requests_this_run = 0

        self.rules = robots.Rules(disallow_all=True)

        self._stop_signal = False
        self.last_request = 0.0
        self.last_elapsed = 0.0
        self.run_id = 0

        self.next_short = time.time() + config.SHORT_BREAK[0]
        self.next_long = time.time() + config.LONG_BREAK[0]

        self.switched: set[int] = set()  # IDs that changed kind in this run (no redirect loops)
        self.checked_at: dict[int, float] = {}  # ID -> time of its last request in this run

        self.log = logging.getLogger(f"crawl.{site.NAME}")

        self.started = time.time()
        self.outcomes_this_run: Counter[str] = Counter()
        self.statuses_this_run: Counter[str] = Counter()
        self.bytes_this_run = 0
        self.elapsed_this_run = 0.0
        self.breaks_this_run = 0.0

        self.fetch_log: TsvWriter
        self.responses_log: TsvWriter
        self.pages_log: TsvWriter
        self.frontier_log: TsvWriter
        self.links_log: TsvWriter
        self.table_log: TsvWriter | None = None  # the site's TABLE, if it has one

    def _problem(self, title: str, details: str) -> None:
        """Append a problem to problems/<site>.md, visible without reading the whole log."""
        self.problems_file.parent.mkdir(parents=True, exist_ok=True)
        new = not self.problems_file.exists()
        with self.problems_file.open("a", encoding="utf-8") as f:
            if new:
                f.write(
                    f"# Problems ({self.site.TITLE} crawler)\n\nNewest at the bottom. "
                    "Automatic entries come from the crawler.\n"
                )
            f.write(f"\n## {now_iso()} {title}\n\n{details}\n")

        self.log.warning("PROBLEM: %s - %s", title, details)

    def _render_ms(self, resp: requests.Response | None) -> object:
        if resp is None:
            return ""
        return round(float(resp.headers.get(self.site.RENDER_HEADER, 0) or 0))

    # ---------- politeness ----------

    def _on_signal(self, signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        self.log.warning("signal %s: stopping after the current request", name)
        self._stop_signal = True

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while not self._stop_signal and (left := end - time.time()) > 0:
            time.sleep(min(left, 1.0))

    def _wait_turn(self) -> None:
        now = time.time()
        if now >= self.next_long:
            self.log.info("hourly break %d s", config.LONG_BREAK[1])
            self.breaks_this_run += config.LONG_BREAK[1]
            self._sleep(config.LONG_BREAK[1])
            self.next_long = time.time() + config.LONG_BREAK[0]
            self.next_short = time.time() + config.SHORT_BREAK[0]
        elif now >= self.next_short:
            self.log.info("5-minute break %d s", config.SHORT_BREAK[1])
            self.breaks_this_run += config.SHORT_BREAK[1]
            self._sleep(config.SHORT_BREAK[1])
            self.next_short = time.time() + config.SHORT_BREAK[0]

        wait = self.last_request + self.delay + random.uniform(0, self.jitter) - time.time()
        if wait > 0:
            self._sleep(wait)

    def _get(self, url: str) -> requests.Response:
        """Make one polite request (waits its turn first).

        ``self.last_elapsed`` is set to the request time without the wait.
        """
        self._wait_turn()

        t0 = time.time()
        try:
            return self.session.get(
                url, allow_redirects=False, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT)
            )
        finally:
            self.last_request = time.time()
            self.last_elapsed = self.last_request - t0
            self.requests_this_run += 1

    def _load_robots(self) -> None:
        """Fetch robots.txt; until it answers, crawl nothing.

        Asks again every RETRY_WAIT, or every OFFLINE_WAIT while our network is down.
        """
        while True:
            offline = False
            try:
                resp = self._get(self.site.ROBOTS_URL)
            except requests.RequestException as e:
                why = f"not reachable ({type(e).__name__}: {e})"[:300]
                offline = isinstance(e, requests.ConnectionError)
            else:
                self.log.info("robots.txt: HTTP %s, %d bytes", resp.status_code, len(resp.content))
                if resp.status_code == 200:
                    text = resp.text
                    self.rules = robots.parse(text, config.PRODUCT)
                    self._keep_robots_copy(text)
                    break
                if 400 <= resp.status_code < 500:
                    self.rules = (
                        robots.Rules()
                    )  # RFC 9309: unavailable robots.txt = no restrictions
                    break
                why = f"HTTP {resp.status_code} (RFC 9309: disallow all)"

            if self._stop_signal:
                raise StopCrawl("signal while waiting for robots.txt")
            self.rules = robots.Rules(disallow_all=True)
            wait = config.OFFLINE_WAIT if offline else config.RETRY_WAIT
            self.log.warning("robots.txt %s; trying again in %d s", why, wait)
            self._sleep(wait)

        self.delay = max(self.min_delay, self.rules.crawl_delay or 0.0)
        self.log.info(
            "robots.txt loaded: crawl-delay %s, using delay %.1f s",
            self.rules.crawl_delay,
            self.delay,
        )

        # checked once, at start (user, 18 Oct): every URL pattern we request must be allowed
        blocked = [u for u in self.site.SAMPLE_URLS if not self.rules.allowed(u)]
        if blocked:
            self._problem(
                "crawl stopped: robots.txt",
                f"robots.txt disallows URLs this crawl requests: {', '.join(blocked)}. Check the "
                f"newest copy in data/{self.site.NAME}/robots/; nothing was requested.",
            )
            raise StopCrawl(f"robots.txt disallows URLs this crawl requests: {', '.join(blocked)}")
        self.log.info("robots.txt allows all %d URL patterns", len(self.site.SAMPLE_URLS))

    def _keep_robots_copy(self, text: str) -> None:
        folder = self.data / "robots"
        folder.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(text.encode()).hexdigest()
        if any(p.read_text(encoding="utf-8") == text for p in folder.glob("*.txt")):
            return

        self.log.warning("robots.txt changed (or first copy): saved %s", digest[:8])
        (folder / f"{datetime.now(UTC):%Y-%m-%dT%H%M%SZ}-{digest[:8]}.txt").write_text(
            text, encoding="utf-8"
        )

    # ---------- storage ----------

    def _save_page(self, key: int, kind: str, body: bytes) -> Path:
        rel = self.site.raw_path(key, kind)
        path = self.data / rel
        path.parent.mkdir(parents=True, exist_ok=True)

        part = path.with_name(path.name + ".part")
        with part.open("wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())

        os.link(part, path)  # fails if the page already exists: never overwrite
        part.unlink()
        return rel

    # ---------- main loop ----------

    def run(self) -> str:
        """Crawl until the frontier is empty or the crawl stops.

        Resumes from the TSV logs. SIGINT/SIGTERM stop it after the current request.

        Returns
        -------
        str
            The stop reason (also written to runs.tsv).

        Raises
        ------
        StopCrawl
            If another crawler holds the lock.
        """
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        with Lock(self.crawl_dir / "crawl.lock"):
            state = load_state(self.data, self.site)
            self.last_request = state.last_request

            self.fetch_log = TsvWriter(self.crawl_dir / "fetch_log.tsv", FETCH_COLUMNS)
            self.frontier_log = TsvWriter(self.crawl_dir / "frontier.tsv", FRONTIER_COLUMNS)
            self.links_log = TsvWriter(self.crawl_dir / "links.tsv", LINK_COLUMNS)
            self.responses_log = TsvWriter(self.crawl_dir / "responses.tsv", RESPONSE_COLUMNS)
            self.pages_log = TsvWriter(self.crawl_dir / "pages.tsv", page_columns(self.site))
            if hasattr(self.site, "TABLE"):
                name, columns = self.site.TABLE
                self.table_log = TsvWriter(self.crawl_dir / f"{name}.tsv", columns)
            runs = TsvWriter(self.crawl_dir / "runs.tsv", RUN_COLUMNS)

            self.run_id = state.run_id
            runs.append(
                {
                    "run_id": self.run_id,
                    "event": "start",
                    "ts": now_iso(),
                    "pid": os.getpid(),
                    "info": f"delay={self.min_delay}+0..{self.jitter}s "
                    f"breaks={config.SHORT_BREAK},{config.LONG_BREAK} ua={config.USER_AGENT}",
                }
            )

            self.log.info(
                "run %s start: site %s, PID %s, data %s; delay %.1f+0..%.1f s, breaks %s/%s, "
                "timeouts %s/%s s; requests %s; UA %s",
                self.run_id,
                self.site.NAME,
                os.getpid(),
                self.data,
                self.min_delay,
                self.jitter,
                config.SHORT_BREAK,
                config.LONG_BREAK,
                config.CONNECT_TIMEOUT,
                config.READ_TIMEOUT,
                requests.__version__,
                config.USER_AGENT,
            )

            try:
                self._crawl(state)
            except StopCrawl as e:
                self.stop_reason = str(e)
            except Exception as e:
                self.stop_reason = f"crash: {type(e).__name__}: {e}"
                self.log.exception("run %s crashed", self.run_id)
                self._problem(
                    "crawler crashed", f"{type(e).__name__}: {e} (traceback in errors.log)"
                )
                raise
            finally:
                if not self.stop_reason:
                    self.stop_reason = "signal" if self._stop_signal else "unknown"

                summary = self._summary()
                runs.append(
                    {
                        "run_id": self.run_id,
                        "event": "end",
                        "ts": now_iso(),
                        "pid": os.getpid(),
                        "info": f"{self.stop_reason}; requests={self.requests_this_run} "
                        f"saved={self.saved_this_run}; {summary}",
                    }
                )

                logs = (self.fetch_log, self.frontier_log, self.links_log, self.responses_log)
                for w in (*logs, self.pages_log, runs):
                    w.close()
                if self.table_log:
                    self.table_log.close()

                level = (
                    logging.INFO
                    if self.stop_reason.startswith(("signal", "finished"))
                    else logging.WARNING
                )
                self.log.log(level, "run %s ended: %s; %s", self.run_id, self.stop_reason, summary)
            return self.stop_reason

    def _summary(self) -> str:
        """Return one line with what this run did (for crawl.log and runs.tsv)."""
        hours = (time.time() - self.started) / 3600
        n = self.requests_this_run
        avg = self.elapsed_this_run / n if n else 0.0
        return (
            f"{hours:.2f} h, {n} requests ({n / hours if hours else 0:.0f}/h), "
            f"saved {self.saved_this_run} pages / {self.bytes_this_run / 1e6:.1f} MB, "
            f"avg response {avg:.2f} s, breaks {self.breaks_this_run:.0f} s, "
            f"outcomes {dict(self.outcomes_this_run.most_common())}, "
            f"HTTP {dict(self.statuses_this_run.most_common())}"
        )

    def _kind(self, state: State, key: int) -> str:
        """Return the kind of an ID: from the site if its ID ranges say it, else from the logs."""
        if hasattr(self.site, "kind_of_key"):
            return self.site.kind_of_key(key)
        return state.kind.get(key, self.default_kind)

    def _url(self, state: State, key: int) -> str:
        """Return the URL to fetch for an ID: the one a page gave, else the site's `url_for`."""
        return state.urls.get(key) or self.site.url_for(key, self._kind(state, key))

    def _enqueue(
        self, state: State, heap: list[int], key: int, source: str, kind: str = "", url: str = ""
    ) -> bool:
        """Queue an ID unless it is queued or saved under another ID; True if it was queued."""
        if key in state.known:
            return False
        if url:
            state.urls[key] = url
        if kind and kind != self.default_kind and key not in state.attempts:
            state.kind[key] = kind

        if key in state.frontier:
            return False
        state.frontier.add(key)

        self.frontier_log.append(
            {"ts": now_iso(), "url": self._url(state, key), "id": key, "source": source}
        )

        if key not in state.done:
            heapq.heappush(heap, key)
        return True

    def _found(self, state: State, heap: list[int], found: Found, source: str) -> int:
        """Queue what pages lead to (site hooks found_on_page/start), write its rows and problem.

        Returns
        -------
        int
            How many IDs were new to the crawl.
        """
        queued = sum(
            self._enqueue(state, heap, key, source, kind, url) for kind, key, url in found.keys
        )

        if self.table_log:
            ts = now_iso()
            self.table_log.append_many({"ts": ts, **row} for row in found.rows)
        if found.problem:
            self._problem("site", found.problem)

        return queued

    def _crawl(self, state: State) -> None:
        if not state.frontier:
            self.log.info("first run: seeding IDs 1..%d", self.site.SEED_MAX)
            ts = now_iso()
            state.frontier.update(range(1, self.site.SEED_MAX + 1))
            self.frontier_log.append_many(
                {"ts": ts, "url": self.site.url_for(k), "id": k, "source": "seed"}
                for k in range(1, self.site.SEED_MAX + 1)
            )

        heap = [k for k in state.frontier if k not in state.done]

        heapq.heapify(heap)

        if hasattr(self.site, "found_on_start"):  # MangaUpdates: catalog pages and their series
            found = self.site.found_on_start(self.data)
            queued = self._found(state, heap, found, "seed")
            self.log.info("start: %d IDs queued from the saved pages (found_on_start)", queued)
        if hasattr(self.site, "found_on_fail"):  # a crash right after a failed page lost its next
            for key in sorted(k for k, o in state.done.items() if o == "failed"):
                found = self.site.found_on_fail(self.data, key, self._kind(state, key))
                self._found(state, heap, found, f"failed:{key}")

        other = sum(1 for k in heap if k in state.kind)
        self.log.info(
            "resume: %d IDs done, %d pending (%d of a non-default kind)",
            len(state.done),
            len(heap),
            other,
        )

        self._load_robots()
        last_progress = time.time()
        started = time.time()

        # order: pending IDs -> probe past the highest ID (new entries) -> recheck (`recheck`)
        rechecked = False
        while not self._stop_signal:
            if not heap and not self._extend_tail(state, heap):
                if rechecked:
                    raise StopCrawl("finished: frontier empty, tail probe and rechecks done")

                rechecked = True
                self._recheck(state, heap)
                continue

            key = heapq.heappop(heap)
            if key in state.done:
                continue
            self._process(state, heap, key)

            if time.time() - last_progress >= 60:
                last_progress = time.time()
                self._progress(state, heap, started)

    def _recheck(self, state: State, heap: list[int]) -> None:
        """Queue every ID with an outcome in `recheck` once more, after new IDs and the tail probe.

        A page can appear later (a restored one, a late entry) and an error can be gone. Each ID
        gets fresh attempts. IDs checked less than `RECHECK_AFTER` ago (e.g. the tail probe just
        before) are skipped. Runs once per run, so a run always ends.

        Parameters
        ----------
        state : State
            The crawl state; the IDs leave ``state.done``.
        heap : list[int]
            The empty queue to fill.
        """
        recent = time.time() - RECHECK_AFTER
        keys = sorted(
            k
            for k, o in state.done.items()
            if o in self.recheck and self.checked_at.get(k, 0.0) < recent
        )
        counts = Counter(state.done[k] for k in keys)

        for key in keys:
            del state.done[key]
            state.attempts[key] = 0
            heapq.heappush(heap, key)

        self.log.info("recheck: %d IDs again %s", len(keys), dict(counts))

    def _extend_tail(self, state: State, heap: list[int]) -> bool:
        """Queue IDs past the highest existing one, until TAIL IDs in a row are missing.

        New entries appear over time, so the end of the ID range is probed, not fixed.
        """
        below = getattr(self.site, "TAIL_BELOW", None)  # MangaUpdates: legacy IDs only

        def numeric(k: int) -> bool:
            return below is None or k < below

        highest = max((k for k, o in state.done.items() if o in EXISTS and numeric(k)), default=0)
        tried = max((k for k in state.frontier if numeric(k)), default=0)

        if tried - highest >= self.site.TAIL:
            return False
        self._enqueue(state, heap, tried + 1, "tail")
        return True

    def _log(
        self,
        key: int,
        url: str,
        attempt: int,
        outcome: str,
        resp: requests.Response | None = None,
        body: bytes = b"",
        rel: Path | None = None,
        error: str = "",
        elapsed: float = 0.0,
    ) -> None:
        ts = now_iso()
        self.checked_at[key] = time.time()
        status = resp.status_code if resp is not None else ""
        self.outcomes_this_run[outcome] += 1
        self.statuses_this_run[str(status or "none")] += 1
        self.elapsed_this_run += elapsed
        if rel:
            self.bytes_this_run += len(body)

        short = url.split("://", 1)[-1].split("/", 1)[-1]
        level = logging.WARNING if outcome in WARN_OUTCOMES else logging.INFO
        if elapsed > SLOW_SINGLE:
            level = logging.WARNING
        self.log.log(
            level,
            "ID %s /%s -> %s %s%s, %.2f s, attempt %s%s",
            key,
            short,
            status or "-",
            outcome,
            f" {len(body) / 1e3:.0f} kB" if rel else "",
            elapsed,
            attempt,
            f" ({error})" if error else "",
        )

        if resp is not None:
            headers = {k: v for k, v in resp.headers.items() if k.lower() != "set-cookie"}
            self.responses_log.append(
                {
                    "ts": ts,
                    "run_id": self.run_id,
                    "id": key,
                    "url": url,
                    "status": resp.status_code,
                    "headers": json.dumps(headers, ensure_ascii=False, sort_keys=True),
                }
            )

        self.fetch_log.append(
            {
                "ts": ts,
                "run_id": self.run_id,
                "url": url,
                "id": key,
                "attempt": attempt,
                "status": status,
                "outcome": outcome,
                "location": resp.headers.get("location", "") if resp is not None else "",
                "bytes": len(body) if rel else "",
                "sha256": hashlib.sha256(body).hexdigest() if rel else "",
                "elapsed_ms": round(elapsed * 1000),
                "render_ms": self._render_ms(resp),
                "path": rel or "",
                "error": error,
            }
        )

    def _process(self, state: State, heap: list[int], key: int) -> None:
        kind = self._kind(state, key)
        url = self._url(state, key)
        rel = self.site.raw_path(key, kind)
        if (self.data / rel).exists():  # saved before a crash, but the log row was lost
            body = (self.data / rel).read_bytes()
            self._log(
                key,
                url,
                state.attempts.get(key, 0),
                "saved",
                body=body,
                rel=rel,
                error="recovered existing file",
            )
            state.done[key] = "saved"
            return

        attempt = state.attempts.get(key, 0) + 1
        state.attempts[key] = attempt
        try:
            resp = self._get(url)
        except requests.RequestException as e:
            self._request_failed(state, heap, key, url, attempt, e)
            return

        elapsed = self.last_elapsed
        self.recent.append(elapsed)
        step = self.site.classify(key, resp)

        hops = 0
        while step.action == "follow":
            # MangaUpdates series.html?id=N -> /series/<base36>/<slug>: log the hop, then fetch it
            self._log(key, url, attempt, "redirect", resp, elapsed=elapsed)
            hops += 1
            if hops > config.MAX_HOPS:
                self._log(key, step.url, attempt, "redirect_other", error="too many redirects")
                state.done[key] = "redirect_other"
                return

            url = step.url
            try:
                resp = self._get(url)
            except requests.RequestException as e:
                self._request_failed(state, heap, key, url, attempt, e)
                return
            elapsed = self.last_elapsed
            self.recent.append(elapsed)
            step = self.site.classify(key, resp)

        if step.action == "stop":
            self._log(key, url, attempt, step.outcome, resp, error=step.note, elapsed=elapsed)
            self._problem(
                f"crawl stopped: {step.outcome}",
                f"ID {key}, {step.note}. The crawler stopped and does not try to get around it.",
            )
            raise StopCrawl(f"{step.outcome}: {step.note}")

        if step.action == "retry":  # outcome retry (page error) or blocked/challenge (refusal)
            self._log(key, url, attempt, step.outcome, resp, error=step.note, elapsed=elapsed)
            self._retry_later(
                state,
                heap,
                key,
                attempt,
                f"{step.outcome}, {step.note}",
                resp.headers.get("retry-after"),
                counted=step.outcome not in NOT_COUNTED,
            )
            return

        self.consecutive_errors = 0
        if step.action == "save":
            self._store(state, heap, key, kind, url, attempt, resp, elapsed)
            return

        self._log(key, url, attempt, step.outcome, resp, error=step.note, elapsed=elapsed)

        if step.action == "switch":  # the ID is the other kind: fetch it again with that URL
            if key in self.switched:
                state.done[key] = "redirect_other"
                self._problem("redirect loop", f"ID {key}: the kinds' URLs redirect to each other")
                return
            self.switched.add(key)
            state.attempts[key] = 0
            if step.outcome == self.default_kind:
                state.kind.pop(key, None)
            else:
                state.kind[key] = step.outcome
            heapq.heappush(heap, key)
            return

        state.done[key] = step.outcome
        for other in step.new_keys:
            self._enqueue(state, heap, other, f"alias:{key}", step.new_kind)

    def _store(
        self,
        state: State,
        heap: list[int],
        key: int,
        kind: str,
        url: str,
        attempt: int,
        resp: requests.Response,
        elapsed: float,
    ) -> None:
        body = resp.content
        if len(body) > config.MAX_PAGE_BYTES:
            err = f"{len(body)} bytes"
            self._log(key, url, attempt, "too_large", resp, error=err, elapsed=elapsed)
            state.done[key] = "too_large"
            return

        rel = self._save_page(key, kind, body)
        self._log(key, url, attempt, "saved", resp, body=body, rel=rel, elapsed=elapsed)
        state.done[key] = "saved"
        self.saved_this_run += 1
        self.last_good_url = url

        text = resp.text
        links = self.site.extract_links(text)
        per_kind = dict.fromkeys(self.site.LINK_KINDS, 0)
        for to_kind, ident, anchor in links:
            self.links_log.append(
                {"from_id": key, "to_kind": to_kind, "to_id": ident, "anchor": anchor}
            )
            per_kind[to_kind] += 1

        self.pages_log.append(
            {
                "ts": now_iso(),
                "id": key,
                "kind": kind,
                "title": page_title(text),
                "bytes": len(body),
                **per_kind,
                "path": rel,
            }
        )

        for other_kind, other in self.site.discovered_keys(links):
            self._enqueue(state, heap, other, f"link:{key}", other_kind)

        if hasattr(self.site, "key_of_url"):  # the same page under another ID: never again
            same = self.site.key_of_url(url)
            if same is not None and same != key:
                state.known.add(same)
        if hasattr(self.site, "found_on_page"):
            found = self.site.found_on_page(key, kind, text)
            queued = self._found(state, heap, found, f"link:{key}")
            if found.rows:
                self.log.info("ID %s: %d new IDs queued from the page", key, queued)

    def _request_failed(
        self, state: State, heap: list[int], key: int, url: str, attempt: int, e: Exception
    ) -> None:
        """Handle a request that got no HTTP response.

        A connection error (Wi-Fi down, DNS, refused, connect timeout) is our network: outcome
        offline, not counted. Anything else (read timeout...) is the page's.
        """
        offline = isinstance(e, requests.ConnectionError)
        outcome = "offline" if offline else "retry"
        err = f"{type(e).__name__}: {e}"[:300]
        self._log(key, url, attempt, outcome, error=err, elapsed=self.last_elapsed)

        why = f"{outcome}, {type(e).__name__}"
        self._retry_later(
            state, heap, key, attempt, why, None, counted=not offline, offline=offline
        )

    def _retry_later(
        self,
        state: State,
        heap: list[int],
        key: int,
        attempt: int,
        why: str,
        retry_after: str | None,
        *,
        counted: bool = True,
        offline: bool = False,
    ) -> None:
        """Wait, then try the same ID again, or fail it if only this page is broken.

        Our network down: wait OFFLINE_WAIT, not counted. First error of the ID: wait
        QUICK_RETRY_WAIT (or a longer Retry-After). From MAX_ATTEMPTS on, the health check decides:
        the site answers -> the ID is failed (rechecked at the end of the run) and the crawl goes
        on; the site is down -> wait RETRY_WAIT and try the ID again. Never stops the crawl.
        """
        self.consecutive_errors += 1
        wait = float(config.OFFLINE_WAIT if offline else config.QUICK_RETRY_WAIT)
        if retry_after and retry_after.isdigit():
            wait = max(wait, float(retry_after))

        if not counted:
            state.attempts[key] = attempt - 1
            heapq.heappush(heap, key)
        elif attempt < config.MAX_ATTEMPTS:
            heapq.heappush(heap, key)
        elif self._site_healthy(key):
            self._fail(state, heap, key, attempt, why)
            return  # only this page is broken: next ID after the normal delay
        else:
            state.attempts[key] = config.MAX_ATTEMPTS - 1  # the next error checks the site again
            heapq.heappush(heap, key)
            wait = max(wait, config.RETRY_WAIT)

        if self.consecutive_errors in (1, 12, 144):  # first error, then after many in a row
            self._problem(
                "errors",
                f"{self.consecutive_errors} error(s) in a row (last: ID {key}, {why}); "
                f"waiting {wait:.0f} s, the crawl does not stop.",
            )

        self.log.warning(
            "ID %s: %s (attempt %d, %d errors in a row); waiting %.0f s",
            key,
            why,
            attempt,
            self.consecutive_errors,
            wait,
        )
        self._sleep(wait)

    def _fail(self, state: State, heap: list[int], key: int, attempt: int, why: str) -> None:
        url = self._url(state, key)
        self._log(key, url, attempt, "failed", error=why)
        state.done[key] = "failed"
        self._problem(
            "page failed",
            f"ID {key} failed {attempt} times ({why}); the site answered, so the crawl went on.",
        )

        if hasattr(self.site, "found_on_fail"):  # MangaUpdates: skip a broken catalog page
            found = self.site.found_on_fail(self.data, key, self._kind(state, key))
            self._found(state, heap, found, f"failed:{key}")

    def _site_healthy(self, key: int) -> bool:
        """Request a page that worked before; True if the site answers it normally.

        The last saved page, or robots.txt before anything is saved.
        Logged under `key` as ``health_ok`` / ``health_bad``; the page is not saved again.
        """
        url = self.last_good_url or self.site.ROBOTS_URL
        try:
            resp = self._get(url)
        except requests.RequestException as e:
            err = f"health check of ID {key}: {type(e).__name__}: {e}"[:300]
            self._log(key, url, 0, "health_bad", error=err, elapsed=self.last_elapsed)
            return False

        ok = resp.status_code == 200 and (
            url == self.site.ROBOTS_URL or self.site.classify(key, resp).action == "save"
        )
        outcome = "health_ok" if ok else "health_bad"
        self._log(
            key, url, 0, outcome, resp, error=f"health check of ID {key}", elapsed=self.last_elapsed
        )
        return ok

    def _progress(self, state: State, heap: list[int], started: float) -> None:
        hours = max((time.time() - started) / 3600, 1e-9)
        rate = self.requests_this_run / hours
        eta = len(heap) / rate if rate else float("inf")

        counts: dict[str, int] = {}
        for outcome in state.done.values():
            counts[outcome] = counts.get(outcome, 0) + 1

        avg = sum(self.recent) / len(self.recent) if self.recent else 0.0

        self.log.info(
            "progress: done %d, pending %d, %s; this run %d req (%.0f/h), saved %d (%.1f MB); "
            "delay %.1f s, avg response %.2f s, errors in a row %d; ETA %.1f h",
            len(state.done),
            len(heap),
            counts,
            self.requests_this_run,
            rate,
            self.saved_this_run,
            self.bytes_this_run / 1e6,
            self.delay,
            avg,
            self.consecutive_errors,
            eta,
        )
