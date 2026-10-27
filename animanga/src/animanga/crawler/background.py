"""Start and stop crawlers in the background: `uv run crawl [--start|--stop] [site ...]`.

A started crawler runs in its own session, detached from the terminal, so it survives closing
it. Its stderr goes to ``crawl/stdout.log`` (warnings and errors before logging starts).
The running crawler is found through ``crawl.lock`` (``<PID> <start time>``).
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

from animanga.crawler.core import alive
from animanga.tsv import read_rows

STOP_WAIT = 90  # s; SIGTERM ends the crawl after the current request (timeout 10/30 s)
START_WAIT = 10  # s; time for a new crawler to write its lock
READY_WAIT = 60  # s; time to load robots.txt and check our URL patterns (shown in the terminal)
READY = "robots.txt allows all"  # crawl.log line: the start checks passed


def lock_pid(data: Path) -> int:
    """Return the PID in a site's ``crawl.lock`` if that process is alive.

    Parameters
    ----------
    data : Path
        The site's data folder.

    Returns
    -------
    int
        The PID of the running crawler, or 0 if none runs.
    """
    try:
        pid = int((data / "crawl" / "crawl.lock").read_text().split()[0])
    except OSError, ValueError, IndexError:
        return 0

    return pid if alive(pid) else 0


def stop(name: str, data: Path) -> bool:
    """Stop a site's crawler with SIGTERM and wait until it has exited.

    Parameters
    ----------
    name : str
        The site name, for messages.
    data : Path
        The site's data folder.

    Returns
    -------
    bool
        True if no crawler runs any more.
    """
    pid = lock_pid(data)
    if not pid:
        print(f"{name}: not running")
        return True

    print(f"{name}: stopping PID {pid}")

    try:
        os.kill(pid, signal.SIGTERM)
    except PermissionError:
        print(f"{name}: PID {pid} belongs to another user (root?), stop it as that user")
        return False

    deadline = time.time() + STOP_WAIT
    while time.time() < deadline:
        if not alive(pid):
            print(f"{name}: stopped")
            return True
        time.sleep(1)

    print(f"{name}: PID {pid} did not stop within {STOP_WAIT} s")
    return False


def start(name: str, data: Path) -> bool:
    """Start a site's crawler in the background; a running one is restarted.

    Parameters
    ----------
    name : str
        The site name.
    data : Path
        The site's data folder.

    Returns
    -------
    bool
        True if the new crawler is running.
    """
    if lock_pid(data) and not stop(name, data):
        print(f"{name}: not restarted")
        return False

    out = data / "crawl" / "stdout.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    crawl_log = data / "crawl" / "crawl.log"
    offset = crawl_log.stat().st_size if crawl_log.exists() else 0

    with out.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "animanga.crawler.entrypoint", "--run", name],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,  # own session: survives closing the terminal
        )

    deadline = time.time() + START_WAIT
    while time.time() < deadline:
        if lock_pid(data) == proc.pid:
            return _wait_ready(name, data, proc, crawl_log, offset)
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    print(f"{name}: did not start; last output of {out}:")
    print("".join(out.read_text(encoding="utf-8", errors="replace").splitlines(True)[-5:]))
    return False


class _Process(Protocol):
    pid: int
    returncode: int | None

    def poll(self) -> int | None: ...


def _wait_ready(name: str, data: Path, proc: _Process, crawl_log: Path, offset: int) -> bool:
    """Wait until the new crawler passed its start checks (robots.txt), or say why it stopped.

    The crawler runs detached, so without this a robots.txt problem would only be in the logs.
    """
    print(f"{name}: PID {proc.pid}, loading robots.txt...")
    warned = False
    deadline = time.time() + READY_WAIT

    while time.time() < deadline:
        new = _read_from(crawl_log, offset)
        if READY in new:
            line = next(x for x in new.splitlines() if READY in x)
            print(f"{name}: started, {line.split(': ', 1)[-1]}. Stop: uv run crawl --stop {name}")
            return True

        if proc.poll() is not None:
            ends = [r for r in read_rows(data / "crawl" / "runs.tsv") if r["event"] == "end"]
            why = ends[-1]["info"].split(";")[0] if ends else f"exit code {proc.returncode}"
            print(f"{name}: ERROR, the crawler stopped at start: {why}")
            print(f"{name}: details in local_docs/problems/{name}.md and {crawl_log}")
            return False

        if not warned and "robots.txt" in new and "trying again" in new:
            line = next(x for x in new.splitlines() if "trying again" in x)
            print(f"{name}: WARNING, {line.split(': ', 1)[-1]} (the site may be down)")
            warned = True
        time.sleep(0.5)

    print(
        f"{name}: running, but robots.txt is not loaded after {READY_WAIT} s; the crawler keeps "
        f"trying and requests nothing else. Watch: uv run watch {name}"
    )
    return True


def _read_from(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as f:
            if path.stat().st_size >= offset:  # else the log rotated: read it from the start
                f.seek(offset)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
