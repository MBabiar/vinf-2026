from pathlib import Path
from types import ModuleType

import pytest
import requests

from animanga import ROOT
from animanga.crawler import config, robots
from animanga.crawler.sites import ann, mangaupdates

ROBOTS = Path(__file__).parent / "robots"
ANN = "https://www.animenewsnetwork.com"
MU = "https://www.mangaupdates.com"


def _resp(
    status: int, headers: dict[str, str] | None = None, body: bytes = b""
) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.headers.update(headers or {})
    r._content = body
    return r


# ---------- Anime News Network ----------


def test_ann_robots() -> None:
    rules = robots.parse((ROBOTS / "ann.txt").read_text(encoding="utf-8"), "VI2026-student-crawler")
    assert rules.crawl_delay == 2
    assert rules.allowed(f"{ANN}/encyclopedia/anime.php?id=13")
    assert not rules.allowed(f"{ANN}/encyclopedia/anime.php?id=13&lookup=error")
    assert not rules.allowed(f"{ANN}/encyclopedia/anime-list.php")
    assert not rules.allowed(f"{ANN}/encyclopedia/releases.php?id=1&format=dvd")
    assert not rules.allowed(f"{ANN}/search?q=bebop")


def test_ann_links_and_urls() -> None:
    page = (
        '<a href="people.php?id=774">Shinichir&#333; <b>Watanabe</b></a>'
        '<a href="people.php?id=774">Shinichir&#333; <b>Watanabe</b></a>'
        '<a href="/encyclopedia/anime.php?id=353">Cowboy Bebop: The Movie</a>'
        '<a href="/encyclopedia/manga.php?id=1555">Cowboy Bebop (manga)</a>'
        '<a href="/encyclopedia/anime.php?id=13&amp;page=25">We have 27</a>'
        '<a href="company.php?id=415">Satelight</a>'
    )
    links = ann.extract_links(page)
    assert links == [
        ("people", 774, "Shinichirō Watanabe"),
        ("anime", 353, "Cowboy Bebop: The Movie"),
        ("manga", 1555, "Cowboy Bebop (manga)"),
        ("company", 415, "Satelight"),
    ]
    assert ann.discovered_keys(links) == [("anime", 353), ("manga", 1555)]
    assert ann.raw_path(4395, "manga") == Path("raw/manga/004/4395.html")
    assert ann.url_for(4395, "manga") == f"{ANN}/encyclopedia/manga.php?id=4395"
    assert ann.kind_of_url(f"{ANN}/encyclopedia/manga.php?id=4395") == "manga"
    assert ann.canonical("anime.php?id=5") == f"{ANN}/encyclopedia/anime.php?id=5"
    assert ann.canonical("http://animenewsnetwork.com/x#y") == f"{ANN}/x"


def test_ann_classify() -> None:
    manga = {"location": f"{ANN}/encyclopedia/manga.php?id=12000"}
    step = ann.classify(12000, _resp(302, manga))
    assert (step.action, step.outcome) == ("switch", "manga")
    back = ann.classify(12, _resp(302, {"location": "/encyclopedia/anime.php?id=12"}))
    assert (back.action, back.outcome) == ("switch", "anime")
    alias = ann.classify(5, _resp(302, {"location": "/encyclopedia/anime.php?id=7"}))
    assert (alias.outcome, alias.new_keys, alias.new_kind) == ("alias", [7], "anime")
    malias = ann.classify(5, _resp(302, {"location": "manga.php?id=9"}))
    assert (malias.outcome, malias.new_keys, malias.new_kind) == ("alias", [9], "manga")
    assert ann.classify(42000, _resp(404)).outcome == "missing"
    assert ann.classify(13, _resp(200, body=b"<title>Cowboy Bebop</title>")).action == "save"
    assert ann.classify(13, _resp(502)).action == "retry"
    assert ann.classify(13, _resp(503)).action == "retry"
    assert ann.classify(13, _resp(429)).action == "retry"
    assert ann.classify(13, _resp(403, {"cf-mitigated": "challenge"})).action == "retry"
    assert ann.classify(13, _resp(403, body=b"<title>Just a moment...</title>")).action == "retry"
    assert ann.classify(13, _resp(403, {"cf-mitigated": "challenge"})).outcome == "challenge"
    passive = (
        b'<title>Cowboy Bebop</title><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
    )
    assert ann.classify(13, _resp(200, body=passive)).action == "save"


# ---------- MangaUpdates ----------


def test_mangaupdates_robots() -> None:
    text = (ROBOTS / "mangaupdates.txt").read_text(encoding="utf-8")
    rules = robots.parse(text, "VI2026-student-crawler")
    assert rules.crawl_delay is None
    assert rules.allowed(f"{MU}/series.html?id=1")
    assert rules.allowed(f"{MU}/series/pb8uwds/one-piece")
    assert not rules.allowed(f"{MU}/series/pb8uwds/one-piece/-comment")
    assert not rules.allowed(f"{MU}/releases")
    assert not rules.allowed(f"{MU}/series?letter=A")
    page = mangaupdates.CatalogPage(2024, "no", "manga", "Romance", 1).url()
    assert rules.allowed(page)
    assert not rules.allowed(page + "&orderby=year")
    assert not robots.parse(text, "GPTBot").allowed(f"{MU}/series.html?id=1")


def test_mangaupdates_links_and_urls() -> None:
    page = (
        '<a href="https://www.mangaupdates.com/author/8a4bq2j/eiichiro-oda">Eiichiro <b>Oda</b></a>'
        '<a href="/publisher/abc12/shueisha">Shueisha</a>'
        '<a href="https://www.mangaupdates.com/series/pb8uwds/one-piece">One Piece</a>'
        '<a href="https://www.mangaupdates.com/series/pb8uwds/one-piece">One Piece</a>'
        '<a href="https://www.mangaupdates.com/releases">Releases</a>'
    )
    links = mangaupdates.extract_links(page)
    assert links == [
        ("author", "8a4bq2j", "Eiichiro Oda"),
        ("publisher", "abc12", "Shueisha"),
        ("series", "pb8uwds", "One Piece"),
    ]
    assert mangaupdates.discovered_keys(links) == []
    assert mangaupdates.canonical("/series/x1") == f"{MU}/series/x1"
    assert mangaupdates.raw_path(1234) == Path("raw/series/001/1234.html")
    assert mangaupdates.url_for(1234) == f"{MU}/series.html?id=1234"


def test_mangaupdates_classify() -> None:
    legacy = mangaupdates.classify(1, _resp(308, {"location": f"{MU}/series/pb8uwds/one-piece"}))
    assert (legacy.action, legacy.url) == ("follow", f"{MU}/series/pb8uwds/one-piece")
    assert mangaupdates.classify(230000, _resp(307, {"location": "/series"})).outcome == "missing"
    assert mangaupdates.classify(1, _resp(200, body=b"<title>One Piece</title>")).action == "save"
    assert mangaupdates.classify(1, _resp(503)).action == "retry"
    assert mangaupdates.classify(1, _resp(502)).action == "retry"
    assert mangaupdates.classify(1, _resp(403)).action == "retry"
    assert mangaupdates.classify(1, _resp(503)).outcome == "blocked"  # waited, counted
    assert mangaupdates.classify(1, _resp(502)).outcome == "retry"  # a counted attempt
    assert mangaupdates.classify(1, _resp(404)).outcome == "missing"


def test_mangaupdates_ids() -> None:
    """Legacy IDs, catalog pages and base36 series each have their own ID range and file."""
    page = mangaupdates.CatalogPage(2023, "no", "manga", "", 7)
    key = page.key()
    assert key == 100_232_010_007
    assert mangaupdates.catalog_of_key(key) == page
    assert mangaupdates.kind_of_key(key) == "catalog_by_type"
    assert mangaupdates.url_for(key) == (
        f"{MU}/series?year=2023&perpage=100&display=list&page=7&licensed=no&type=manga"
    )
    assert mangaupdates.raw_path(key) == Path("raw/catalog_by_type/2023-no/manga/007.html")

    last = mangaupdates.CatalogPage(2026, "yes", "russian", "Yuri", 30)  # last type, last genre
    assert mangaupdates.CATALOG_KEY < last.key() < mangaupdates.SERIES_KEY
    assert mangaupdates.catalog_of_key(last.key()) == last
    genre = mangaupdates.CatalogPage(2024, "no", "manga", "Slice of Life", 2).key()
    assert mangaupdates.url_for(genre) == (
        f"{MU}/series?year=2024&perpage=100&display=list&page=2&licensed=no"
        "&type=manga&genre=Slice+of+Life"
    )
    assert mangaupdates.raw_path(genre) == Path(
        "raw/catalog_by_type/2024-no/manga/slice-of-life/002.html"
    )
    typed = mangaupdates.CatalogPage(2024, "no", "drama_cd", "", 1).key()
    assert mangaupdates.raw_path(typed) == Path("raw/catalog_by_type/2024-no/drama_cd/001.html")

    new = mangaupdates.series_key("0abc123")  # leading zero: kept
    assert mangaupdates.base36_of_key(new) == "0abc123"
    assert mangaupdates.kind_of_key(new) == "series_b36"
    assert mangaupdates.raw_path(new) == Path("raw/series_b36/0a/0abc123.html")
    assert mangaupdates.url_for(new) == f"{MU}/series/0abc123"
    assert mangaupdates.key_of_url(f"{MU}/series/0abc123/some-slug") == new
    assert mangaupdates.key_of_url(f"{MU}/series.html?id=5") is None

    assert mangaupdates.kind_of_key(205_000) == "series"
    assert mangaupdates.kind_of_url(mangaupdates.url_for(key)) == "catalog_by_type"


def test_mangaupdates_catalog_lists() -> None:
    """Every year x licensed x type (no doujinshi) is a list; manga also every genre."""
    page = mangaupdates.CatalogPage
    genres = len(mangaupdates.GENRES)
    lists = mangaupdates.catalog_lists()

    assert "doujinshi" not in mangaupdates.TYPES
    assert len(lists) == len(mangaupdates.CATALOG_YEARS) * 2 * (len(mangaupdates.TYPES) + genres)
    assert lists[:2] == [page(2020, "yes", "manga", "", 1), page(2020, "yes", "manga", "Action", 1)]
    assert lists[1 + genres] == page(2020, "yes", "manhwa", "", 1)
    keys = [c.key() for c in lists]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)  # crawl order = ID order


def _full_page(n: int = 100) -> str:
    row = '<a title="Click for Series Info" href="https://www.mangaupdates.com/series/{}/s-{}">'
    return "".join(row.format(f"{i:07d}", i) for i in range(n))


def test_mangaupdates_catalog_page() -> None:
    """A full page leads to its series and the next page; a short one is the last."""
    full = _full_page() + _full_page(1)  # a series twice: once
    key = mangaupdates.CatalogPage(2024, "yes", "manhwa", "", 1).key()

    found = mangaupdates.found_on_page(key, "catalog_by_type", full)

    assert len(found.keys) == 101  # 100 unique series + page 2
    assert found.keys[0] == (
        "series_b36",
        mangaupdates.series_key("0000000"),
        f"{MU}/series/0000000/s-0",
    )
    assert found.keys[-1] == ("catalog_by_type", key + 1, "")
    assert found.rows == [
        {
            "year": 2024,
            "licensed": "yes",
            "type": "manhwa",
            "genre": "",
            "page": 1,
            "series": 100,
            "last": 0,
            "path": "raw/catalog_by_type/2024-yes/manhwa/001.html",
        }
    ]

    short = mangaupdates.found_on_page(key + 1, "catalog_by_type", _full_page(1))
    assert [k[0] for k in short.keys] == ["series_b36"] and short.rows[0]["last"] == 1

    empty = mangaupdates.found_on_page(key, "catalog_by_type", "no rows")
    assert empty.keys == [] and empty.problem == ""  # a small type can have no series
    manga = mangaupdates.CatalogPage(2024, "yes", "manga", "", 1).key()
    assert (
        "page 1 lists no series" in mangaupdates.found_on_page(manga, "catalog_by_type", "").problem
    )

    assert mangaupdates.found_on_page(1, "series", full).keys == []


def test_mangaupdates_catalog_full_list() -> None:
    """Page 30 full ends the list: a problem, unless genre lists have the rest of the type."""
    page = mangaupdates.CatalogPage
    last = mangaupdates.MAX_PAGES

    manga = mangaupdates.found_on_page(
        page(2024, "no", "manga", "", last).key(), "catalog_by_type", _full_page()
    )
    assert len(manga.keys) == 100 and manga.problem == "" and manga.rows[0]["last"] == 1

    manhwa = mangaupdates.found_on_page(
        page(2024, "no", "manhwa", "", last).key(), "catalog_by_type", _full_page()
    )
    assert "type=manhwa fills all 30 pages" in manhwa.problem and "BY_GENRE" in manhwa.problem

    romance = page(2024, "no", "manga", "Romance", last).key()
    problem = mangaupdates.found_on_page(romance, "catalog_by_type", _full_page()).problem
    assert "type=manga, genre=Romance fills all 30 pages" in problem
    assert problem.endswith("series past 3000 are missing.")


def test_mangaupdates_failed_catalog_page(tmp_path: Path) -> None:
    """A failed page is skipped (the next page is queued); page 30 failed ends the list."""
    page = mangaupdates.CatalogPage(2021, "no", "manga", "Romance", 7).key()

    skip = mangaupdates.found_on_fail(tmp_path, page, "catalog_by_type")
    assert skip.keys == [("catalog_by_type", page + 1, "")]
    assert skip.rows[0]["series"] == "" and skip.rows[0]["last"] == 0
    assert skip.rows[0]["genre"] == "Romance"
    assert (
        "genre=Romance: page 7 failed, so series 601-700 of this list are missing" in skip.problem
    )

    end = mangaupdates.CatalogPage(2021, "no", "manga", "", 30).key()
    found = mangaupdates.found_on_fail(tmp_path, end, "catalog_by_type")
    assert found.keys == [] and found.rows[0]["last"] == 1

    assert mangaupdates.found_on_fail(tmp_path, 5, "series").keys == []


@pytest.mark.parametrize("site", [ann, mangaupdates])
def test_robots_allows_every_url_we_crawl(site: ModuleType) -> None:
    """The saved robots.txt (newest copy in data/, else tests/robots/) allows every SAMPLE_URLS."""
    copies = sorted((ROOT / "data" / site.NAME / "robots").glob("*.txt"))
    path = copies[-1] if copies else ROBOTS / f"{site.NAME}.txt"
    rules = robots.parse(path.read_text(encoding="utf-8"), config.PRODUCT)

    assert [u for u in site.SAMPLE_URLS if not rules.allowed(u)] == []
