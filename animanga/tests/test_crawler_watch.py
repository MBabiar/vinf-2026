"""`uv run watch` shows the progress of the newest run only."""

from pathlib import Path

from animanga.crawler import watch

OLD = (
    "2026-10-17T23:38:40.909Z INFO    crawl.mangaupdates: progress: done 179227, pending 25773, "
    "{}; this run 540 req (1996/h), saved 0 (0.0 MB); delay 1.0 s, avg response 0.41 s, "
    "errors in a row 0; ETA 12.9 h\n"
)
START = "2026-10-18T00:14:57.000Z INFO    crawl.mangaupdates: run 46 start: site mangaupdates\n"
NEW = OLD.replace("179227, pending 25773", "204997, pending 3").replace("12.9 h", "0.0 h")


def _log(tmp_path: Path, text: str) -> Path:
    (tmp_path / "crawl").mkdir()
    (tmp_path / "crawl" / "crawl.log").write_text(text)
    return tmp_path


def test_new_run_without_progress_ignores_the_old_run(tmp_path: Path) -> None:
    block = watch.status_block("mangaupdates", _log(tmp_path, OLD + START))

    assert "no progress yet in this run" in block
    assert "25773" not in block


def test_progress_of_the_newest_run(tmp_path: Path) -> None:
    block = watch.status_block("mangaupdates", _log(tmp_path, OLD + START + NEW))

    assert "3 IDs left, ETA 0.0 h" in block
