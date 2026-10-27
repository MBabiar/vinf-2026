"""What each `crawl` subcommand does; args.py binds them to the parser (``func``).

Every command takes the parsed arguments and returns the process exit code.
"""

import argparse
import logging
import logging.handlers
import sys
import time
from collections import Counter
from pathlib import Path
from types import ModuleType

from animanga import DATA_DIR
from animanga.crawler import background
from animanga.crawler import watch as watcher
from animanga.crawler.core import Crawler, StopCrawl, alive
from animanga.crawler.sites import SITES
from animanga.tsv import read_rows


def setup_logging(data: Path) -> None:
    """Log to stderr, crawl.log (everything) and errors.log (warnings), all in UTC.

    Parameters
    ----------
    data : Path
        The site's data folder; logs go to its ``crawl/`` folder.
    """
    folder = data / "crawl"
    folder.mkdir(parents=True, exist_ok=True)
    # UTC like the TSV files, so log lines and fetch_log.tsv rows line up

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S"
    )
    fmt.converter = time.gmtime

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stderr)
    # in a terminal show everything; detached (`crawl --start` -> stdout.log) only warnings,
    # because crawl.log already has every line
    console.setLevel(logging.INFO if sys.stderr.isatty() else logging.WARNING)

    handlers: list[logging.Handler] = [
        console,
        logging.handlers.RotatingFileHandler(
            folder / "crawl.log", maxBytes=20_000_000, backupCount=5, encoding="utf-8"
        ),
        logging.handlers.RotatingFileHandler(
            folder / "errors.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        ),
    ]

    handlers[2].setLevel(logging.WARNING)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)

    logging.getLogger("urllib3").setLevel(logging.WARNING)


def print_status(site: ModuleType, data: Path) -> None:
    """Print crawl statistics from the logs, without any network request.

    Parameters
    ----------
    site : ModuleType
        The site module.
    data : Path
        The site's data folder.
    """
    crawl = data / "crawl"
    last: dict[str, dict[str, str]] = {}
    requests = 0

    for row in read_rows(crawl / "fetch_log.tsv"):
        requests += 1
        last[row["id"]] = row

    outcomes = Counter(r["outcome"] for r in last.values())
    saved = [r for r in last.values() if r["outcome"] == "saved"]
    size = sum(int(r["bytes"] or 0) for r in saved)

    frontier = {r["id"] for r in read_rows(crawl / "frontier.tsv")}
    pending = frontier - last.keys()
    links = sum(1 for _ in read_rows(crawl / "links.tsv"))

    print(f"site            : {site.NAME} ({data})")
    print(f"crawler         : {running(crawl / 'crawl.lock')}")
    print(f"requests logged : {requests}")
    print(f"IDs in frontier : {len(frontier)} (all IDs queued so far, not what is left)")
    print(f"IDs with result : {len(last)}")

    for outcome, n in outcomes.most_common():
        print(f"  {outcome:15} {n}")

    print(f"IDs pending     : {len(pending)}")
    print(f"saved pages     : {len(saved)}, {size / 1e6:.1f} MB on disk (uncompressed)")

    if len(site.KINDS) > 1:
        for kind in site.KINDS:
            part = [r for r in saved if r["path"].startswith(f"raw/{kind}/")]
            mb = sum(int(r["bytes"] or 0) for r in part) / 1e6
            print(f"  {kind:15} {len(part)}, {mb:.1f} MB")

    if saved:
        print(f"avg page size   : {size / len(saved) / 1e3:.0f} kB")

    print(f"links.tsv rows  : {links}")
    if last:
        print(f"last request    : {max(r['ts'] for r in last.values())}")

    progress = last_progress(crawl / "crawl.log")
    if progress:
        print(f"last progress   : {progress}")

    if hasattr(site, "status_lines"):  # MangaUpdates: the catalog groups
        for line in site.status_lines(data):
            print(line)


def running(lock: Path) -> str:
    """Tell whether the crawler holding a lock file is alive.

    Parameters
    ----------
    lock : Path
        The site's ``crawl.lock``.

    Returns
    -------
    str
        ``running, PID n since ts`` if the lock names a live process, else ``not running``.
    """
    try:
        pid, since = lock.read_text().split()
    except OSError, ValueError:
        return "not running"

    if not pid.isdigit() or not alive(int(pid)):
        return "not running"

    return f"running, PID {pid} since {since}"


def last_progress(log: Path) -> str:
    """Return the newest progress line of crawl.log (speed, delay, ETA).

    Parameters
    ----------
    log : Path
        The site's ``crawl.log``.

    Returns
    -------
    str
        Timestamp and progress text without the logger prefix; ``""`` if there is none.
    """
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    for line in reversed(lines):
        if ": progress: " in line:
            return line[:24] + " " + line.split(": progress: ", 1)[1]

    return ""


def run(args: argparse.Namespace) -> int:
    """Crawl one site in the foreground (`crawl --run <site>`).

    Parameters
    ----------
    args : argparse.Namespace
        ``sites``: exactly one site.

    Returns
    -------
    int
        0 finished or stopped by a signal, 1 crawl refused, 2 stopped by a block or errors.
    """
    site = SITES[args.sites[0]]
    data = DATA_DIR / site.NAME
    setup_logging(data)

    try:
        reason = Crawler(site, data).run()
    except StopCrawl as e:
        logging.getLogger(__name__).error("%s", e)
        return 1

    bad = (
        reason.startswith(("challenge", "blocked", "robots.txt")) or "consecutive errors" in reason
    )
    return 2 if bad else 0


def status(args: argparse.Namespace) -> int:
    """Print the statistics of each site (`crawl --status [site ...]`).

    Parameters
    ----------
    args : argparse.Namespace
        ``sites``.

    Returns
    -------
    int
        Always 0.
    """
    for i, name in enumerate(args.sites):
        if i:
            print()

        print_status(SITES[name], DATA_DIR / name)

    return 0


def start(args: argparse.Namespace) -> int:
    """Start crawlers in the background, restarting running ones (`crawl`, `crawl --start`).

    Parameters
    ----------
    args : argparse.Namespace
        ``sites``.

    Returns
    -------
    int
        0 if every crawler runs, else 1.
    """
    results = [background.start(name, DATA_DIR / name) for name in args.sites]
    return 0 if all(results) else 1


def stop(args: argparse.Namespace) -> int:
    """Stop crawlers cleanly (`crawl --stop`).

    Parameters
    ----------
    args : argparse.Namespace
        ``sites``.

    Returns
    -------
    int
        0 if no crawler runs any more, else 1.
    """
    results = [background.stop(name, DATA_DIR / name) for name in args.sites]
    return 0 if all(results) else 1


def watch(args: argparse.Namespace) -> int:
    """Follow running crawlers until Ctrl+C (`crawl --watch`, `watch`).

    Parameters
    ----------
    args : argparse.Namespace
        ``sites``.

    Returns
    -------
    int
        Always 0.
    """
    watcher.watch({name: DATA_DIR / name for name in args.sites})
    return 0
