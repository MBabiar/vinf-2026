"""Regex extractors on 20 whole saved pages (10 ANN, 10 MangaUpdates).

The expected values were checked against the pages and against what is known about the works
(Cowboy Bebop: Shinichirō Watanabe, Sunrise, 1998; Claymore: anime ends at chapter 59). The pages
are not in git (copyright), so the tests skip where ``data/<site>/raw/`` is missing.
"""

from pathlib import Path

import pytest

from animanga import DATA_DIR
from animanga.docs.documents import ann_document, mu_document
from animanga.parser import ann, mangaupdates
from animanga.parser.run import record

ANN_RAW = DATA_DIR / "ann" / "raw"
MU_RAW = DATA_DIR / "mangaupdates" / "raw"


def _page(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path} is not here (pages are not in git)")
    return path.read_text(encoding="utf-8", errors="replace")


def _ann(kind: str, key: int) -> dict:
    page = _page(ANN_RAW / kind / f"{key // 1000:03d}" / f"{key}.html")
    return record(ann.parse(page, key, kind), "works")


def _staff(work: dict, role: str) -> list[str]:
    return [c["name"] for c in work["credits"] if c["section"] == "staff" and c["role"] == role
            and c["language"] in ("JP", "KR")]  # fmt: skip


def _companies(work: dict, role: str) -> list[str]:
    companies = [c for c in work["credits"] if c["section"] == "company" and c["language"] == "JP"]
    return [c["name"] for c in companies if c["role"] == role]


def _out(work: dict, relation: str) -> list[str]:
    return [f"{r['dst_kind']}-{r['dst']}" for r in work["relations"]
            if r["relation"] == relation and str(r["src"]) == str(work["id"])]  # fmt: skip


# ---------- Anime News Network: 6 anime, 4 manga ----------

ANN_PAGES = [
    # kind, ID, title, type, year, first genres, episodes / volumes, (role, person), studio, source
    ("anime", 13, "Cowboy Bebop", "TV", "1998", "action; drama", "26",
     ("Series Director", "Shinichirō Watanabe"), "Sunrise", None),
    ("anime", 7028, "Claymore", "TV", "2007", "action; drama", "26",
     ("Director", "Hiroyuki Tanaka"), "Madhouse", "manga-5743"),
    ("anime", 328, "Berserk", "TV", "1997", "action; drama", "25",
     ("Chief Director", "Naohito Takahashi"), None, "manga-2298"),
    ("anime", 348, "Fruits Basket", "TV", "2001", "comedy; drama", "26",
     ("Director", "Akitarō Daichi"), "Studio DEEN", "manga-2335"),
    ("anime", 13262, "Hunter \u00d7 Hunter", "TV", "2011", "adventure; comedy", "148",
     ("Director", "Hiroshi Kōjina"), "Madhouse", "manga-1899"),
    ("anime", 5838, "Baby Blue", "movie", "2007", None, None,
     ("Director", "Shinichirō Watanabe"), None, None),
    ("manga", 5743, "Claymore", "manga", "2001", "adventure; drama", "27",
     ("Story & Art", "Norihiro Yagi"), None, None),
    ("manga", 1555, "Cowboy Bebop", "manga", "1998", "action; comedy", "3",
     ("Story", "Hajime Yatate"), None, None),
    ("manga", 2335, "Fruits Basket", "manga", "1998", "comedy; drama", "23",
     ("Story & Art", "Natsuki Takaya"), None, None),
    ("manga", 1573, "Priest", "manhwa", "2002", "adventure; drama", None,
     ("Story & Art", "Min-Woo Hyung"), None, None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("kind", "key", "title", "type_", "year", "genres", "count", "credit", "studio", "source"),
    ANN_PAGES,
    ids=[f"ann-{p[0]}-{p[1]}" for p in ANN_PAGES],
)
def test_ann_page(kind, key, title, type_, year, genres, count, credit, studio, source) -> None:
    work = _ann(kind, key)

    assert (work["title"], work["type"], work["year"]) == (title, type_, year)
    if genres:
        assert work["genres"].startswith(genres)
    assert work.get("episodes" if kind == "anime" else "volumes") == count
    assert credit[1] in _staff(work, credit[0])
    if studio:
        assert studio in _companies(work, "Animation Production")
    if source:
        assert source in _out(work, "adaptation")
    assert work["titles"][0] == {"title": title, "language": "", "main": 1}


def test_ann_plot_titles_and_articles() -> None:
    work = _ann("anime", 13)

    assert work["plot"].startswith("Spike Spiegel, a bounty Hunter with a dark past")
    assert {"title": "カウボーイビバップ", "language": "Japanese", "main": 0} in work["titles"]
    assert any(a["level"] == "S0" and a["section"] == "Reviews" for a in work["articles"])


def test_ann_manhwa_document_takes_korean_staff() -> None:
    doc = ann_document(_ann("manga", 1573))

    assert doc is not None
    assert {"role": "Story & Art", "name": "Min-Woo Hyung", "id": doc["staff"][0]["id"]} in doc[
        "staff"
    ]
    assert all(
        c["name"] != "Enterbrain" for c in doc["companies"]
    )  # JP publisher of the translation


# ---------- MangaUpdates: 10 series ----------


def _mu(key: int, b36: str = "") -> dict:
    if b36:
        path, kind = MU_RAW / "series_b36" / b36[:2] / f"{b36}.html", "series_b36"
        key = mangaupdates.page_key(b36, kind)
    else:
        path, kind = MU_RAW / "series" / f"{key // 1000:03d}" / f"{key}.html", "series"
    return record(mangaupdates.parse(_page(path), key, kind), "series")


MU_PAGES = [
    # legacy ID, base36, title, type, year, first genre, author, magazine (note), anime end
    # (the furthest adaptation: the highest volume and chapter on the Ends line)
    (3, "a2ax9yb", "Fruits Basket", "Manga", "1998", "Comedy", "TAKAYA Natsuki",
     ("Hana to Yume", "Hakusensha"), "136"),  # S3; 2001 series 38
    (88, "njeqwry", "Berserk", "Manga", "1989", "Action", "MIURA Kentaro",
     ("Young Animal", "Hakusensha; since 1992"), "249"),  # 2016; 1997: 87
    (452, "wur2b13", "Mushishi", "Manga", "1999", "Adventure", "URUSHIBARA Yuki",
     ("Afternoon", "Kodansha"), "50"),  # S2; S1: 26
    (1000, "n3wzyo2", "Kiseijuu", "Manga", "1988", "Action", "IWAAKI Hitoshi",
     ("Afternoon", "Kodansha"), "64"),
    (1037, "xti92gy", "Claymore", "Manga", "2001", "Action", "YAGI Norihiro",
     ("Gekkan Shounen Jump", "Chap 1 - 73"), "59"),
    (1933, "y3c334b", "Priest", "Manhwa", "1998", "Action", "HYUNG Min-Woo", None, None),
    (27374, "84kpbno", "Ookami to Koushinryou (Novel)", "Novel", "2006", "Adventure",
     "HASEKURA Isuna", None, ""),  # ends at Vol 5, no chapter
    # S2; S1: 45
    (151349, "6z1uqw7", "Solo Leveling", "Manhwa", "2018", "Action", "Chugong", None, "110"),
    (68, "2kelfy4", "Fullmetal Alchemist dj - Sugar Milky Baby", "Doujinshi", "2004", "Adult",
     "Hysterics38.", None, None),
    (None, "00iuid1", "Toilet no Hanako-san, Reiwa Apude Shitara Kawai Sugin ka!?", "Manga", "2025",
     "Comedy", "Syotaro", ("Trahison", "wwwave comics"), None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("key", "b36", "title", "type_", "year", "genre", "author", "magazine", "anime_end"),
    MU_PAGES,
    ids=[f"mu-{p[1]}" for p in MU_PAGES],
)
def test_mu_page(key, b36, title, type_, year, genre, author, magazine, anime_end) -> None:
    series = _mu(key) if key else _mu(0, b36)

    assert (series["mu_id"], series["title"], series["type"], series["year"]) == (
        b36, title, type_, year
    )  # fmt: skip
    assert series["genres"].startswith(genre)
    assert author in [p["name"] for p in series["people"] if p["role"] == "author"]
    if magazine:
        assert {
            "role": "magazine",
            "publisher_id": "",
            "name": magazine[0],
            "note": magazine[1],
        } in [{"publisher_id": "", **p} for p in series["publishers"]]
    assert series.get("anime_end") == anime_end
    assert series["titles"][0] == {"title": title, "main": 1}

    doc = mu_document(series)
    if type_ == "Doujinshi":
        assert doc is None
    else:
        assert doc is not None
        assert doc["id"] == f"mu-{b36}"
        assert doc["legacy_id"] == (key or "")


def test_mu_claymore_details() -> None:
    series = _mu(1037)

    assert series["anime_end_vol"] == "11"
    assert series["status"].startswith("27 Volumes (Complete)")
    assert {"role": "magazine", "name": "Jump SQ", "note": "Chap 74 - 155 + Extra 5"} in series[
        "publishers"
    ]
    assert len(series["categories"]) > 100  # the full list from the page data, not the top 10
    assert len(series["comments"]) == 10  # the series page shows the first 10
