"""A whole crawl run against fake HTTP responses (no network): state, files, logs."""

import logging
from pathlib import Path

import pytest
import requests

from animanga.crawler import config, core
from animanga.crawler.sites import ann, mangaupdates
from animanga.tsv import read_rows

BASE = "https://www.animenewsnetwork.com"
PAGES: dict[str, tuple[int, dict[str, str], bytes]] = {
    f"{BASE}/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n"),
    f"{BASE}/encyclopedia/anime.php?id=1": (
        200,
        {"x-render-time": "120"},
        b'<title>Anime 1</title><a href="people.php?id=7">Someone</a>',
    ),
    f"{BASE}/encyclopedia/anime.php?id=2": (
        302,
        {"location": f"{BASE}/encyclopedia/manga.php?id=2"},
        b"",
    ),
    f"{BASE}/encyclopedia/manga.php?id=2": (200, {}, b"<title>Manga 2</title>"),
    f"{BASE}/encyclopedia/anime.php?id=3": (404, {}, b""),
}


@pytest.fixture(autouse=True)
def no_site_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The site modules set their own delay (ANN 2 s, MU 1 s): no real waiting in tests."""
    for site in (ann, mangaupdates):
        monkeypatch.setattr(site, "MIN_DELAY", 0.0)
        monkeypatch.setattr(site, "JITTER", 0.0)


def fake_get(_session: requests.Session, url: str, **_kw: object) -> requests.Response:
    status, headers, body = PAGES[url]
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers)
    r._content = body
    r.url = url
    return r


def test_run_logs_every_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)
    caplog.set_level(logging.INFO)

    reason = core.Crawler(ann, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    assert (tmp_path / "raw/anime/000/1.html").exists()
    assert (tmp_path / "raw/manga/000/2.html").exists()
    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    assert [(r["id"], r["status"], r["outcome"]) for r in log] == [
        ("1", "200", "saved"),
        ("2", "302", "manga"),
        ("2", "200", "saved"),
        ("3", "404", "missing"),  # no recheck: checked less than RECHECK_AFTER ago
    ]
    text = caplog.text
    assert "run 1 start: site ann" in text
    assert "ID 1 /encyclopedia/anime.php?id=1 -> 200 saved" in text
    assert "ID 3 /encyclopedia/anime.php?id=3 -> 404 missing" in text
    assert "run 1 ended: finished" in text and "saved 2 pages" in text
    runs = list(read_rows(tmp_path / "crawl/runs.tsv"))
    assert [r["event"] for r in runs] == ["start", "end"]
    assert "'saved': 2" in runs[1]["info"]
    pages = list(read_rows(tmp_path / "crawl/pages.tsv"))
    assert [(p["id"], p["kind"], p["title"], p["people"]) for p in pages] == [
        ("1", "anime", "Anime 1", "1"),
        ("2", "manga", "Manga 2", "0"),
    ]


def test_run_waits_through_outage_and_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wi-Fi down 7 times (more than MAX_ATTEMPTS), then a 503: the crawl waits and never stops."""
    failures = {f"{BASE}/encyclopedia/anime.php?id=1": 7, f"{BASE}/encyclopedia/anime.php?id=3": 1}

    def flaky_get(session: requests.Session, url: str, **kw: object) -> requests.Response:
        if failures.get(url, 0) > 0:
            failures[url] -= 1
            if url.endswith("id=1"):
                raise requests.ConnectionError("Wi-Fi down")
            r = requests.Response()
            r.status_code = 503
            r.url = url
            r._content = b"upstream connect error"
            return r
        return fake_get(session, url, **kw)

    monkeypatch.setattr(requests.Session, "get", flaky_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "RETRY_WAIT", 0)
    monkeypatch.setattr(config, "QUICK_RETRY_WAIT", 0)
    monkeypatch.setattr(config, "OFFLINE_WAIT", 0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)

    reason = core.Crawler(ann, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    one = [(r["attempt"], r["outcome"]) for r in log if r["id"] == "1"]
    assert one == [("1", "offline")] * 7 + [("1", "saved")]
    three = [(r["status"], r["outcome"]) for r in log if r["id"] == "3"]
    assert three == [("503", "blocked"), ("404", "missing")]
    assert core.load_state(tmp_path, ann).attempts[1] == 1  # offline rows not counted on resume


def test_page_refused_every_time_is_failed_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ID 1 answers 429 every time, the site works: failed after 2 tries, the crawl goes on."""

    def refusing_get(session: requests.Session, url: str, **kw: object) -> requests.Response:
        if url.endswith("anime.php?id=1"):
            return _response((429, {}, b"Too Many Requests"), url)
        return fake_get(session, url, **kw)

    monkeypatch.setattr(requests.Session, "get", refusing_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "RETRY_WAIT", 0)
    monkeypatch.setattr(config, "QUICK_RETRY_WAIT", 0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)

    reason = core.Crawler(ann, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    one = [(r["url"].removeprefix(BASE), r["outcome"]) for r in log if r["id"] == "1"]
    assert one == [
        ("/encyclopedia/anime.php?id=1", "blocked"),
        ("/encyclopedia/anime.php?id=1", "blocked"),
        ("/robots.txt", "health_ok"),  # nothing saved yet: robots.txt
        ("/encyclopedia/anime.php?id=1", "failed"),
    ]
    assert [r["outcome"] for r in log if r["id"] != "1"] == ["manga", "saved", "missing"]
    assert "ID 1 failed 2 times" in (tmp_path / "problems/ann.md").read_text()
    assert core.load_state(tmp_path, ann).done[1] == "failed"


def test_site_down_never_fails_the_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The site answers 502 for 5 requests: ID 2 waits (health check fails), then is saved."""
    down = {"left": 5, "on": False, "seen": False}
    sleeps: list[float] = []

    def outage_get(session: requests.Session, url: str, **kw: object) -> requests.Response:
        if url.endswith("anime.php?id=1"):
            down["on"] = down["left"] > 0  # the outage starts right after ID 1 is saved
            if down["seen"]:
                return _bad(url)
            down["seen"] = True
        elif down["on"] and url != f"{BASE}/robots.txt":
            return _bad(url)
        return fake_get(session, url, **kw)

    def _bad(url: str) -> requests.Response:
        down["left"] -= 1
        down["on"] = down["left"] > 0
        return _response((502, {}, b"Bad Gateway"), url)

    monkeypatch.setattr(requests.Session, "get", outage_get)
    monkeypatch.setattr(core.Crawler, "_sleep", lambda _self, s: sleeps.append(s))
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)

    core.Crawler(ann, tmp_path).run()

    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    two = [(r["id"], r["url"].removeprefix(BASE), r["outcome"]) for r in log if r["id"] == "2"]
    assert two == [
        ("2", "/encyclopedia/anime.php?id=2", "retry"),
        ("2", "/encyclopedia/anime.php?id=2", "retry"),
        ("2", "/encyclopedia/anime.php?id=1", "health_bad"),  # the last saved page
        ("2", "/encyclopedia/anime.php?id=2", "retry"),
        ("2", "/encyclopedia/anime.php?id=1", "health_bad"),
        ("2", "/encyclopedia/anime.php?id=2", "manga"),
        ("2", "/encyclopedia/manga.php?id=2", "saved"),
    ]
    assert [s for s in sleeps if s >= 30] == [30, 300, 300]  # quick retry, then site down twice
    state = core.load_state(tmp_path, ann)
    assert state.done[2] == "saved"
    assert state.kind[2] == "manga"  # health rows (anime.php?id=1) don't change the kind of ID 2


def test_recheck_finds_page_that_appeared_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing ID is requested again at the end of the next run; a new page there is saved."""
    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)
    core.Crawler(ann, tmp_path).run()

    pages = {**PAGES, f"{BASE}/encyclopedia/anime.php?id=3": (200, {}, b"<title>New</title>")}
    monkeypatch.setattr(requests.Session, "get", lambda _s, url, **_kw: _response(pages[url], url))
    reason = core.Crawler(ann, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    run2 = [(r["id"], r["outcome"]) for r in log if r["run_id"] == "2"]
    assert run2 == [("3", "saved")]  # saved pages are never requested again
    assert (tmp_path / "raw/anime/000/3.html").exists()
    assert core.load_state(tmp_path, ann).done[3] == "saved"


def test_recheck_in_the_same_run_when_old_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With RECHECK_AFTER passed, a missing ID is requested again at the end of the same run."""
    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)
    monkeypatch.setattr(core, "RECHECK_AFTER", -1)

    core.Crawler(ann, tmp_path).run()

    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    assert [r["outcome"] for r in log if r["id"] == "3"] == ["missing", "missing"]


def test_site_recheck_skips_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A site's own RECHECK (MangaUpdates: errors only) leaves missing IDs alone."""
    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(config, "MIN_DELAY", 0.0)
    monkeypatch.setattr(config, "JITTER", 0.0)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(ann, "SEED_MAX", 3)
    monkeypatch.setattr(ann, "TAIL", 0)
    monkeypatch.setattr(ann, "RECHECK", ("failed",), raising=False)
    monkeypatch.setattr(core, "RECHECK_AFTER", -1)

    core.Crawler(ann, tmp_path).run()

    log = list(read_rows(tmp_path / "crawl/fetch_log.tsv"))
    assert [r["outcome"] for r in log if r["id"] == "3"] == ["missing"]


def _response(page: tuple[int, dict[str, str], bytes], url: str) -> requests.Response:
    status, headers, body = page
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers)
    r._content = body
    r.url = url
    return r


def test_robots_change_stops_before_any_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """robots.txt disallows a URL pattern we crawl: the run stops at once and requests nothing."""
    pages = {
        **PAGES,
        f"{BASE}/robots.txt": (200, {}, b"User-agent: *\nDisallow: /encyclopedia/manga\n"),
    }
    asked: list[str] = []

    def get(_s: requests.Session, url: str, **_kw: object) -> requests.Response:
        asked.append(url)
        return _response(pages[url], url)

    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")

    reason = core.Crawler(ann, tmp_path).run()

    assert reason.startswith("robots.txt disallows URLs this crawl requests")
    assert "manga.php?id=1" in reason
    assert asked == [f"{BASE}/robots.txt"]
    assert "crawl stopped: robots.txt" in (tmp_path / "problems/ann.md").read_text()


MU = "https://www.mangaupdates.com"


def _row(b36: str, slug: str) -> str:
    return (
        f'<a title="Click for Series Info" href="{MU}/series/{b36}/{slug}"><span>{slug}</span></a>'
    )


def _rows(*b36: str) -> tuple[int, dict[str, str], bytes]:
    """A catalog page that lists these series (slug: the last letter 3 times)."""
    return 200, {}, "".join(_row(b, b[-1] * 3) for b in b36).encode()


def _list(series_type: str, page: int, genre: str = "") -> str:
    return mangaupdates.CatalogPage(2024, "yes", series_type, genre, page).url()


def _mu_pages() -> dict[str, tuple[int, dict[str, str], bytes]]:
    """Legacy ID 1 is series aaaaaaa; the 2024 manga list has it and two new ones (2 per page).

    Page 2 answers 429 every time, like page 31 on MangaUpdates (18 Oct); page 3 works.
    """
    pages = {
        f"{MU}/robots.txt": (200, {}, b"User-agent: *\nDisallow: /*&orderby=*\n"),
        f"{MU}/series.html?id=1": (308, {"location": f"{MU}/series/aaaaaaa/one"}, b""),
        f"{MU}/series/aaaaaaa/one": (200, {}, b"<title>One</title>"),
        _list("manga", 1): _rows("aaaaaaa", "0bbbbbb"),
        _list("manga", 2): (429, {}, b"Too Many Requests"),
        _list("manga", 3): _rows("ccccccc"),
        _list("manhwa", 1): (200, {}, b"<title>Series</title>no rows"),
    }
    for b in ("0bbbbbb", "ccccccc", "ddddddd", "eeeeeee", "fffffff", "ggggggg", "hhhhhhh"):
        pages[f"{MU}/series/{b}/{b[-1] * 3}"] = (200, {}, b"<title>S</title>")
    return pages


def _mu_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str], pages: dict | None = None
) -> None:
    """2024, licensed=yes, types manga and manhwa, no genre lists unless the test sets them."""
    monkeypatch.setattr(mangaupdates, "PER_PAGE", 2)  # before the URLs: they carry perpage
    monkeypatch.setattr(mangaupdates, "CATALOG_YEARS", range(2024, 2025))
    monkeypatch.setattr(mangaupdates, "LICENSED", ("yes",))
    monkeypatch.setattr(mangaupdates, "TYPES", ("manga", "manhwa"))
    monkeypatch.setattr(mangaupdates, "BY_GENRE", ())
    pages = pages or _mu_pages()

    def get(_s: requests.Session, url: str, **_kw: object) -> requests.Response:
        asked.append(url.removeprefix(MU))
        return _response(pages[url], url)

    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(config, "PROBLEMS_DIR", tmp_path / "problems")
    monkeypatch.setattr(config, "QUICK_RETRY_WAIT", 0)
    monkeypatch.setattr(mangaupdates, "SEED_MAX", 1)
    monkeypatch.setattr(mangaupdates, "TAIL", 0)


Q = "/series?year=2024&perpage=2&display=list&page="


def test_catalog_finds_new_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy IDs, then the catalog page by page (a broken page skipped), then the new series."""
    asked: list[str] = []
    _mu_setup(tmp_path, monkeypatch, asked)

    reason = core.Crawler(mangaupdates, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    assert asked == [
        "/robots.txt",
        "/series.html?id=1",
        "/series/aaaaaaa/one",
        f"{Q}1&licensed=yes&type=manga",  # full: next page
        f"{Q}2&licensed=yes&type=manga",  # 429
        f"{Q}2&licensed=yes&type=manga",  # 429 again
        f"{Q}1&licensed=yes&type=manga",  # health check: OK
        f"{Q}3&licensed=yes&type=manga",  # page 2 skipped
        f"{Q}1&licensed=yes&type=manhwa",  # empty: the end, not a problem
        "/series/0bbbbbb/bbb",  # the catalog's URL with the slug; aaaaaaa is saved already
        "/series/ccccccc/ccc",
    ]
    assert (tmp_path / "raw/catalog_by_type/2024-yes/manga/003.html").exists()
    assert (tmp_path / "raw/series_b36/0b/0bbbbbb.html").exists()

    table = list(read_rows(tmp_path / "crawl/catalog_by_type.tsv"))
    assert [(r["type"], r["page"], r["series"], r["last"]) for r in table] == [
        ("manga", "1", "2", "0"),
        ("manga", "2", "", "0"),  # failed
        ("manga", "3", "1", "1"),
        ("manhwa", "1", "0", "1"),
    ]
    problems = (tmp_path / "problems/mangaupdates.md").read_text()
    assert "page 2 failed, so series 3-4 of this list are missing" in problems
    assert "lists no series" not in problems

    pages = list(read_rows(tmp_path / "crawl/pages.tsv"))
    assert [p["kind"] for p in pages] == ["series"] + ["catalog_by_type"] * 3 + ["series_b36"] * 2


def test_catalog_resumes_from_saved_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second run requests nothing new (only the failed page once more, in the recheck); a lost
    catalog_by_type.tsv is rebuilt from raw/catalog_by_type."""
    asked: list[str] = []
    _mu_setup(tmp_path, monkeypatch, asked)
    core.Crawler(mangaupdates, tmp_path).run()
    first = list(read_rows(tmp_path / "crawl/catalog_by_type.tsv"))
    (tmp_path / "crawl/catalog_by_type.tsv").unlink()
    asked.clear()

    core.Crawler(mangaupdates, tmp_path).run()

    page2 = f"{Q}2&licensed=yes&type=manga"
    assert asked == ["/robots.txt", page2, page2, "/robots.txt"]  # health check: robots.txt
    again = list(read_rows(tmp_path / "crawl/catalog_by_type.tsv"))
    keep = ("year", "licensed", "type", "genre", "page", "series", "last", "path")
    assert sorted(tuple(r[k] for k in keep) for r in again) == sorted(
        tuple(r[k] for k in keep) for r in first
    )


def test_catalog_by_genre(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A type in BY_GENRE is also read genre by genre (2 pages per list here): the type list may
    fill its last page, a genre list that does goes to problems. `status_lines` shows that the
    genre lists cover the type list."""
    monkeypatch.setattr(mangaupdates, "PER_PAGE", 2)  # before the URLs: they carry perpage
    pages = {
        **_mu_pages(),
        _list("manga", 1): _rows("aaaaaaa", "ccccccc"),
        _list("manga", 2): _rows("ddddddd", "eeeeeee"),  # full last page: genre lists have more
        _list("manga", 1, "Action"): _rows("aaaaaaa", "ccccccc"),
        _list("manga", 2, "Action"): _rows("ddddddd"),
        _list("manga", 1, "Romance"): _rows("eeeeeee", "ggggggg"),
        _list("manga", 2, "Romance"): _rows("hhhhhhh", "0bbbbbb"),  # full: a problem
        _list("manhwa", 1): _rows("fffffff"),
    }
    asked: list[str] = []
    _mu_setup(tmp_path, monkeypatch, asked, pages)
    monkeypatch.setattr(mangaupdates, "MAX_PAGES", 2)
    monkeypatch.setattr(mangaupdates, "GENRES", ("Action", "Romance"))
    monkeypatch.setattr(mangaupdates, "BY_GENRE", ("manga",))

    reason = core.Crawler(mangaupdates, tmp_path).run()

    assert reason == "finished: frontier empty, tail probe and rechecks done"
    assert asked == [
        "/robots.txt",
        "/series.html?id=1",
        "/series/aaaaaaa/one",
        f"{Q}1&licensed=yes&type=manga",
        f"{Q}2&licensed=yes&type=manga",
        f"{Q}1&licensed=yes&type=manga&genre=Action",
        f"{Q}2&licensed=yes&type=manga&genre=Action",
        f"{Q}1&licensed=yes&type=manga&genre=Romance",
        f"{Q}2&licensed=yes&type=manga&genre=Romance",
        f"{Q}1&licensed=yes&type=manhwa",
    ] + [f"/series/{b}/{b[-1] * 3}" for b in ("0bbbbbb", "ccccccc", "ddddddd", "eeeeeee")] + [
        f"/series/{b}/{b[-1] * 3}" for b in ("fffffff", "ggggggg", "hhhhhhh")
    ]
    assert (tmp_path / "raw/catalog_by_type/2024-yes/manga/romance/002.html").exists()

    problems = (tmp_path / "problems/mangaupdates.md").read_text()
    assert "type=manga, genre=Romance fills all 2 pages" in problems
    assert "type=manga fills" not in problems

    status = mangaupdates.status_lines(tmp_path)
    assert status[1] == "  2024 yes types          :   2 of  2 lists done,    3 pages,     5 series"
    assert status[2] == (
        "           manga by genre :   2 of  2 lists done,    4 pages,     7 series; "
        "4 of the 4 on the type list"
    )
    assert status[3:] == [
        "  full at page 2: 2024 yes manga Romance (series past 4 are missing)",
        "  failed pages    : none",
        "  catalog series  : 8 different",
    ]
