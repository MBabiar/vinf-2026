"""Supervise running crawlers: `uv run watch [site ...]` (= `crawl --watch`) (default: all sites).

Prints new warnings/errors at once, a status block per site at start and every 30 min, and one
alarm when a crawler stops or makes no request for 5 min. Reads the logs only, no network.
Ctrl+C ends it.
"""

import contextlib
import io
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from animanga.crawler.background import lock_pid

TICK = 30  # s between checks
STATUS_EVERY = 60  # ticks: a status line every 30 min
IDLE = 300  # s without a request before the alarm

# progress: done 5099, pending 199901, {...}; this run 63 req (1843/h), saved 29 (4.5 MB);
#           delay 1.0 s, avg response 0.61 s, errors in a row 0; ETA 108.5 h
_PROGRESS = re.compile(
    r"done (?P<done>\d+), pending (?P<pending>\d+).*this run \d+ req \((?P<rate>\d+)/h\), "
    r"saved (?P<saved>\d+) \((?P<mb>[\d.]+) MB\); delay (?P<delay>[\d.]+) s, "
    r"avg response (?P<resp>[\d.]+) s, errors in a row (?P<errs>\d+); ETA (?P<eta>[\d.]+) h"
)
# ... INFO    crawl.mangaupdates: run 46 start: site mangaupdates, PID 14601, ...
_RUN_START = re.compile(r": run \d+ start: ")
# 2026-10-04T22:42:25.123Z WARNING animanga.crawler.core: message -> 22:42:25 WARNING message
_LOG_LINE = re.compile(r"^[\d-]+T([\d:]+)\.\d+Z (\w+) +[\w.]+: ")


def size(n: int) -> str:
    """Format a byte count as ``734 MB`` or ``1.71 GB``.

    Parameters
    ----------
    n : int
        Bytes.

    Returns
    -------
    str
        The size with unit.
    """
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def folder_size(path: Path) -> int:
    """Return the total size of all files below a folder.

    Parameters
    ----------
    path : Path
        The folder; a missing folder has size 0.

    Returns
    -------
    int
        Bytes.
    """
    total = 0

    for root, _, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):  # a file renamed meanwhile (.part -> .html)
                total += (Path(root) / name).stat().st_size

    return total


def clock() -> str:
    """Return the local time as ``HH:MM``.

    Returns
    -------
    str
        The current time.
    """
    return time.strftime("%H:%M")


def lines(path: Path) -> list[str]:
    """Return the lines of a log file.

    Parameters
    ----------
    path : Path
        The log file; a missing file has no lines.

    Returns
    -------
    list[str]
        The lines without line ends.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def started(data: Path) -> str:
    """Return when the running crawler started, from ``crawl.lock``, in local time.

    Parameters
    ----------
    data : Path
        The site's data folder.

    Returns
    -------
    str
        ``DD.MM. HH:MM``, or ``""`` if no crawler runs.
    """
    if not lock_pid(data):
        return ""

    try:
        stamp = (data / "crawl" / "crawl.lock").read_text().split()[1]  # 2026-10-05T13:39:04Z
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except OSError, IndexError, ValueError:
        return "?"

    return when.astimezone().strftime("%d.%m. %H:%M")


def last_line(data: Path) -> str:
    """Return the last line of crawl.log without its timestamp (why a crawler ended).

    Parameters
    ----------
    data : Path
        The site's data folder.

    Returns
    -------
    str
        The message, at most 176 characters.
    """
    return (lines(data / "crawl" / "crawl.log") or [""])[-1][24:200]


def status_block(name: str, data: Path) -> str:
    """Summarise a site: running since when, the newest progress line, the size of ``raw/``.

    Parameters
    ----------
    name : str
        The site name.
    data : Path
        The site's data folder.

    Returns
    -------
    str
        A blank line, a header line with the site, then progress, size and speed on own lines.
    """
    since = started(data)
    if since:
        state = f"running since {since} (PID {lock_pid(data)})"
    else:
        state = f"NOT RUNNING | last: {last_line(data)}"
    head = f"\n{clock()} {name} | {state}"
    total = size(folder_size(data / "raw"))

    # only the newest run: a run that just started has no progress line yet, and the last line
    # of the run before (other pending, ETA) would look like this run's
    log = lines(data / "crawl" / "crawl.log")
    starts = [i for i, line in enumerate(log) if _RUN_START.search(line)]
    progress = [line for line in log[starts[-1] if starts else 0 :] if ": progress: " in line]

    m = _PROGRESS.search(progress[-1]) if progress else None
    if not m:
        return f"{head}\n      no progress yet in this run | total {total}"

    done, pending = int(m["done"]), int(m["pending"])
    pct = 100 * done / (done + pending) if done + pending else 0

    return (
        f"{head}\n"
        f"      {pct:.1f}% done, {pending} IDs left, ETA {m['eta']} h\n"
        f"      this run +{m['saved']} pages, {float(m['mb']):.0f} MB | total {total}\n"
        f"      {m['rate']} req/h, delay {m['delay']} s, response {m['resp']} s, "
        f"errors in a row {m['errs']}"
    )


class SiteWatch:
    """What the watcher remembers about one site between checks.

    Parameters
    ----------
    name : str
        The site name.
    data : Path
        The site's data folder.
    """

    def __init__(self, name: str, data: Path) -> None:
        self.name = name
        self.data = data
        self.crawl = data / "crawl"
        self.seen = len(lines(self.crawl / "errors.log"))  # old errors are not shown again
        self.running: bool | None = None  # unknown before the first check
        self.idle = False

    def check(self, tick: int) -> None:
        """Print what changed since the last check.

        Parameters
        ----------
        tick : int
            Number of the check; 0 is the first one.
        """
        errors = lines(self.crawl / "errors.log")
        if len(errors) < self.seen:  # rotated
            self.seen = 0
        for line in errors[self.seen :]:
            print(_LOG_LINE.sub(rf"\1 [{self.name}] \2 ", line)[:220])
        self.seen = len(errors)

        pid = lock_pid(self.data)
        if self.running is None:  # first check: the status block below says it
            self.running = bool(pid)
        if bool(pid) != self.running:
            if pid:
                print(f"{clock()} [{self.name}] running since {started(self.data)} (PID {pid})")
            else:
                print(f"{clock()} [{self.name}] NOT RUNNING | last: {last_line(self.data)}")
            self.running = bool(pid)

        try:
            age = time.time() - (self.crawl / "fetch_log.tsv").stat().st_mtime
        except OSError:
            age = 0
        if pid and age > IDLE and not self.idle:
            print(f"{clock()} [{self.name}] no request for {age:.0f}s (waiting on a retry?)")
            self.idle = True
        elif age <= IDLE:
            self.idle = False

        if tick == 0 or (tick % STATUS_EVERY == 0 and pid):
            print(status_block(self.name, self.data))


def watch(sites: dict[str, Path]) -> None:
    """Check the sites every `TICK` seconds until Ctrl+C.

    Parameters
    ----------
    sites : dict[str, Path]
        Site name -> data folder.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)  # lines show at once also in a pipe or file

    watches = [SiteWatch(name, data) for name, data in sites.items()]
    tick = 0

    try:
        while True:
            for w in watches:
                w.check(tick)
            tick += 1
            time.sleep(TICK)
    except KeyboardInterrupt:
        pass
