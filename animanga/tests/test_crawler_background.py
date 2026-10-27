"""`uv run crawl` waits for the start checks of the detached crawler and prints the result."""

from pathlib import Path

import pytest

from animanga.crawler import background


class FakeProc:
    def __init__(self, code: int | None) -> None:
        self.pid = 4242
        self.returncode = code

    def poll(self) -> int | None:
        return self.returncode


def _setup(tmp_path: Path, log: str, runs: str = "") -> Path:
    crawl = tmp_path / "crawl"
    crawl.mkdir()
    (crawl / "crawl.log").write_text("old line: robots.txt allows all 2 URL patterns\n" + log)
    if runs:
        (crawl / "runs.tsv").write_text("run_id\tevent\tts\tpid\tinfo\n" + runs)
    return crawl / "crawl.log"


def test_ready_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    line = "2026-10-18T10:00:00.000Z INFO    crawl.ann: robots.txt allows all 2 URL patterns\n"
    log = _setup(tmp_path, line)
    offset = len("old line: robots.txt allows all 2 URL patterns\n")

    ok = background._wait_ready("ann", tmp_path, FakeProc(None), log, offset)

    assert ok
    assert "ann: started, robots.txt allows all 2 URL patterns" in capsys.readouterr().out


def test_stop_at_start_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """robots.txt forbids our URLs: the crawler exits, `crawl` prints why and fails."""
    why = "robots.txt disallows URLs this crawl requests: X"
    runs = f"3\tend\t2026-10-18T10:00:01Z\t4242\t{why}; requests=1\n"
    log = _setup(tmp_path, "", runs)
    offset = log.stat().st_size  # only the old line, which must not count as ready

    ok = background._wait_ready("ann", tmp_path, FakeProc(0), log, offset)

    out = capsys.readouterr().out
    assert not ok
    assert "ann: ERROR, the crawler stopped at start: robots.txt disallows URLs" in out


def test_site_down_warns_and_keeps_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = (
        "2026-10-18T10:00:00.000Z WARNING crawl.ann: robots.txt HTTP 503 (RFC 9309: disallow all);"
        " trying again in 300 s\n"
    )
    log = _setup(tmp_path, line)
    offset = len("old line: robots.txt allows all 2 URL patterns\n")
    monkeypatch.setattr(background, "READY_WAIT", 1)

    ok = background._wait_ready("ann", tmp_path, FakeProc(None), log, offset)

    out = capsys.readouterr().out
    assert ok
    assert "ann: WARNING, robots.txt HTTP 503" in out
    assert "robots.txt is not loaded after 1 s" in out
