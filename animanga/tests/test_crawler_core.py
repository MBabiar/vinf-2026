import os
import subprocess
import time
from pathlib import Path

from animanga.crawler import core, robots
from animanga.crawler.core import FETCH_COLUMNS, FRONTIER_COLUMNS, LINK_COLUMNS, load_state
from animanga.crawler.sites import ann, mangaupdates
from animanga.crawler.sites.base import page_title
from animanga.tsv import TsvWriter, read_rows


def test_robots_longest_match_and_anchor() -> None:
    rules = robots.parse("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /*.pdf$\n", "x")
    assert not rules.allowed("https://h/a/x")
    assert rules.allowed("https://h/a/b/c")
    assert not rules.allowed("https://h/doc.pdf")
    assert rules.allowed("https://h/doc.pdf?x=1")


def test_robots_own_group_wins() -> None:
    rules = robots.parse(
        "User-agent: *\nDisallow: /\n\nUser-agent: VI2026-student-crawler\nAllow: /\n",
        "VI2026-student-crawler",
    )
    assert rules.allowed("https://h/anything")


def test_tsv_clean_and_torn_row(tmp_path: Path) -> None:
    path = tmp_path / "t.tsv"
    w = TsvWriter(path, ["a", "b"])
    w.append({"a": "x\ty", "b": "line1\nline2"})
    w.close()
    with path.open("a", encoding="utf-8") as f:
        f.write("torn\trow-without-newline")
    w = TsvWriter(path, ["a", "b"])
    w.append({"a": "1", "b": "2"})
    w.close()
    assert list(read_rows(path)) == [{"a": "x y", "b": "line1 line2"}, {"a": "1", "b": "2"}]


def test_page_title() -> None:
    assert page_title("<title>Claymore (TV) - Anime News Network</title>") == (
        "Claymore (TV) - Anime News Network"
    )


def _seed(crawl: Path) -> None:
    f = TsvWriter(crawl / "frontier.tsv", FRONTIER_COLUMNS)
    f.append_many(
        {"ts": "2026-09-28T00:00:00Z", "url": "u", "id": k, "source": "seed"} for k in (1, 2, 3)
    )
    f.close()


def test_resume_state_ann(tmp_path: Path) -> None:
    crawl = tmp_path / "crawl"
    _seed(crawl)
    base = "https://www.animenewsnetwork.com/encyclopedia"
    log = TsvWriter(crawl / "fetch_log.tsv", FETCH_COLUMNS)
    log.append({"ts": "2026-09-28T00:00:01Z", "id": 1, "outcome": "saved", "url": ""})
    log.append({"ts": "2026-09-28T00:00:03Z", "id": 2, "outcome": "retry", "url": ""})
    log.append({"ts": "2026-09-28T00:00:05Z", "id": 3, "outcome": "manga", "url": ""})
    log.append(
        {"ts": "2026-09-28T00:00:07Z", "id": 4, "outcome": "retry", "url": f"{base}/manga.php?id=4"}
    )
    log.close()
    links = TsvWriter(crawl / "links.tsv", LINK_COLUMNS)
    links.append({"from_id": 1, "to_kind": "manga", "to_id": 50, "anchor": "x (manga)"})
    links.append({"from_id": 1, "to_kind": "manga", "to_id": 1, "anchor": "wrong hint"})
    links.append({"from_id": 1, "to_kind": "people", "to_id": 774, "anchor": "Watanabe"})
    links.close()
    state = load_state(tmp_path, ann)
    assert state.done == {1: "saved"}  # manga (302) is not final: the manga page comes next
    assert state.attempts == {1: 1, 2: 1, 3: 0, 4: 1}
    assert state.kind == {3: "manga", 4: "manga", 50: "manga"}
    assert state.frontier == {1, 2, 3}
    assert state.run_id == 1


def test_resume_state_mangaupdates(tmp_path: Path) -> None:
    crawl = tmp_path / "crawl"
    _seed(crawl)
    log = TsvWriter(crawl / "fetch_log.tsv", FETCH_COLUMNS)
    log.append({"ts": "2026-09-28T00:00:01Z", "id": 1, "outcome": "saved", "url": ""})
    log.append({"ts": "2026-09-28T00:00:03Z", "id": 2, "outcome": "retry", "url": ""})
    for outcome in ["redirect", "blocked", "redirect", "blocked"]:  # 308 hop, then 429: 2 tries
        log.append({"ts": "2026-09-28T00:00:05Z", "id": 3, "outcome": outcome, "url": ""})
    log.close()
    links = TsvWriter(crawl / "links.tsv", LINK_COLUMNS)
    links.append({"from_id": 1, "to_kind": "series", "to_id": "pb8uwds", "anchor": "One Piece"})
    links.close()
    state = load_state(tmp_path, mangaupdates)
    assert state.done == {1: "saved"}
    assert state.attempts == {1: 1, 2: 1, 3: 2}
    assert state.kind == {}
    assert state.frontier == {1, 2, 3}
    assert state.run_id == 1


def test_alive_treats_zombie_as_dead() -> None:
    proc = subprocess.Popen(["true"])
    deadline = time.time() + 5
    while time.time() < deadline and Path(f"/proc/{proc.pid}/stat").read_text().split()[2] != "Z":
        time.sleep(0.05)
    assert not core.alive(proc.pid)  # exited, not reaped yet
    proc.wait()
    assert not core.alive(proc.pid)
    assert core.alive(os.getpid())
    assert not core.alive(0)
