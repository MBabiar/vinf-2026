"""Normalisation, documents and the ANN <-> MangaUpdates join on small hand-made inputs."""

from animanga.docs.documents import ann_document, mu_document
from animanga.docs.join import join_anime, join_manga
from animanga.normalize import fold, person_key, title_key, tokens


def test_fold_and_tokens() -> None:
    assert fold("Shōji Kawamori") == "shoji kawamori"
    assert tokens("The Black Swordsman's 2nd journey, in 1997!") == [
        "black", "swordsman", "s", "2nd", "journey", "1997"
    ]  # fmt: skip
    assert tokens("カウボーイビバップ") == []  # non-Latin scripts drop out


def test_title_key() -> None:
    assert title_key("Ōkami to Kōshinryō") == title_key("Ookami to Koushinryou (Novel)")
    assert title_key("Shingeki no Kyojin (Japanese)") == "shingekinokyojin"
    assert title_key("Akane-chan Over Drive") == title_key("Akane-chan Overdrive")
    assert title_key("D.N") == ""  # shorter than 4 characters


def test_person_key() -> None:
    assert person_key("Norihiro Yagi") == person_key("YAGI Norihiro") == "norihiro yagi"
    assert person_key("Shōji Kawamori") == person_key("KAWAMORI Shouji")
    assert person_key("Koge-Donbo") == "donbo koge"
    assert person_key("鈴木") == ""


def _ann_page(
    key: int,
    kind: str,
    title: str,
    type_: str,
    staff: list[tuple[str, str, str]],
    relations: list[dict] | None = None,
    titles: tuple[str, ...] = (),
) -> dict:
    return {
        "id": key, "kind": kind, "type": type_, "title": title, "year": "2001",
        "genres": "action; drama", "plot": "A story.",
        "titles": [{"title": title, "language": "", "main": 1}]
        + [{"title": t, "language": "Japanese", "main": 0} for t in titles],
        "credits": [{"language": lang, "section": "staff", "role": role, "ref": "people",
                     "ref_id": "1", "name": name} for lang, role, name in staff],
        "relations": relations or [],
    }  # fmt: skip


def _mu_page(key: int, b36: str, title: str, type_: str, authors: list[str],
             names: tuple[str, ...] = ()) -> dict:  # fmt: skip
    return {
        "id": key, "mu_id": b36, "slug": "x", "title": title, "type": type_, "year": "2001",
        "genres": "Action; Drama", "description": "A story.",
        "titles": [{"title": title, "main": 1}] + [{"title": n, "main": 0} for n in names],
        "people": [{"role": "author", "author_id": "", "name": a, "note": ""} for a in authors],
        "publishers": [], "related": [],
    }  # fmt: skip


def test_ann_document_uses_origin_staff_and_both_relation_directions() -> None:
    page = _ann_page(
        7028, "anime", "Claymore", "TV",
        [("JP", "Director", "Hiroyuki Tanaka"), ("EN", "ADR Director", "Someone Else")],
        [{"src_kind": "anime", "src": 7028, "relation": "adaptation", "dst_kind": "manga",
          "dst": "5743", "other_title": "Claymore (manga)"},
         {"src_kind": "anime", "src": "37939", "relation": "remake", "dst_kind": "anime",
          "dst": 7028, "other_title": "Claymore (live-action TV)"}],
    )  # fmt: skip
    doc = ann_document(page)

    assert doc is not None
    assert doc["id"] == "ann-anime-7028"
    assert doc["url"] == "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=7028"
    assert [s["name"] for s in doc["staff"]] == ["Hiroyuki Tanaka"]
    assert doc["genres"] == ["action", "drama"]
    assert [(r["relation"], r["direction"], r["id"]) for r in doc["relations"]] == [
        ("adaptation", "out", "ann-manga-5743"),
        ("remake", "in", "ann-anime-37939"),
    ]


def test_mu_document_skips_doujinshi_and_keeps_legacy_id() -> None:
    assert mu_document(_mu_page(68, "2kelfy4", "Some dj", "Doujinshi", ["X"])) is None

    doc = mu_document(_mu_page(1037, "xti92gy", "Claymore", "Manga", ["YAGI Norihiro"]))
    assert doc is not None
    assert (doc["id"], doc["legacy_id"]) == ("mu-xti92gy", 1037)
    new = mu_document(_mu_page(10**12 + 5, "00iuid1", "New series", "Manga", ["A"]))
    assert new is not None
    assert new["legacy_id"] == ""


def _docs():
    def staff(name: str, role: str = "Story & Art") -> list[tuple[str, str, str]]:
        return [("JP", role, name)]

    ann_manga = [
        ann_document(_ann_page(5743, "manga", "Claymore", "manga", staff("Norihiro Yagi"))),
        ann_document(_ann_page(1, "manga", "Spice and Wolf", "light novel",
                               staff("Isuna Hasekura", "Story"), titles=("Ōkami to Kōshinryō",))),
        ann_document(_ann_page(2, "manga", "Monster", "manga", staff("Somebody"))),
        ann_document(_ann_page(3, "manga", "Twins", "manga", staff("Same Author"))),
    ]  # fmt: skip
    mu = [
        mu_document(_mu_page(1037, "xti92gy", "Claymore", "Manga", ["YAGI Norihiro"])),
        mu_document(_mu_page(10, "manga01", "Ookami to Koushinryou", "Manga", ["HASEKURA Isuna"])),
        mu_document(_mu_page(11, "novel01", "Ookami to Koushinryou (Novel)", "Novel",
                             ["HASEKURA Isuna"], names=("Spice and Wolf",))),
        mu_document(_mu_page(12, "monster", "Monster", "Manga", ["URASAWA Naoki"])),
        mu_document(_mu_page(13, "twins01", "Twins", "Manga", ["AUTHOR Same"])),
        mu_document(_mu_page(14, "twins02", "Twins", "Manga", ["AUTHOR Same"])),
    ]  # fmt: skip
    return [d for d in ann_manga if d], [d for d in mu if d]


def test_join_manga_levels_class_and_ambiguity() -> None:
    ann_manga, mu = _docs()
    links, candidates = join_manga(ann_manga, mu)

    assert [(x["ann"], x["mu"], x["confidence"]) for x in links] == [
        ("ann-manga-5743", "mu-xti92gy", "high"),  # main title + author
        ("ann-manga-1", "mu-novel01", "medium"),  # alternative title + author, novel only
    ]
    reasons = {(c.ann, c.mu): c.reason for c in candidates}
    assert reasons[("ann-manga-2", "mu-monster")] == "no-person"
    assert (
        reasons[("ann-manga-3", "mu-twins01")]
        == reasons[("ann-manga-3", "mu-twins02")]
        == ("ambiguous")
    )


def test_join_anime_through_its_source_manga() -> None:
    ann_manga, mu = _docs()
    manga_links, _ = join_manga(ann_manga, mu)
    anime = ann_document(_ann_page(
        7028, "anime", "Claymore", "TV", [],
        [{"src_kind": "anime", "src": 7028, "relation": "adaptation", "dst_kind": "manga",
          "dst": 5743, "other_title": "Claymore"}],
    ))  # fmt: skip

    assert anime is not None
    assert join_anime([anime], manga_links) == [
        {"ann": "ann-anime-7028", "mu": "mu-xti92gy", "method": "via-ann-manga",
         "confidence": "high", "via": "ann-manga-5743"}
    ]  # fmt: skip
