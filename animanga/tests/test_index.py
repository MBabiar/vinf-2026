"""TF index and search on a tiny corpus written to a temporary folder."""

import json
import math

import pytest

from animanga.index import build as build_module
from animanga.index.build import index_text, main_credit
from animanga.index.search import IDF, Index


def _doc(doc_id: str, title: str, text: str, kind: str = "manga", staff=()) -> dict:
    return {
        "id": doc_id, "source": doc_id.split("-")[0], "kind": kind, "url": "", "title": title,
        "titles": [{"title": title, "language": ""}], "type": "TV" if kind == "anime" else "manga",
        "year": "2001", "genres": [], "themes": [], "text": text,
        "staff": [{"role": r, "name": n, "id": ""} for r, n in staff], "companies": [],
        "relations": [], "anime_chapters": {}, "legacy_id": "", "links": [],
    }  # fmt: skip


DOCS = {
    "ann-anime": [
        _doc("ann-anime-1", "Cowboy Bebop", "bounty hunter in space", "anime",
             [("Series Director", "Shinichiro Watanabe"), ("Key Animation", "Many Animators")]),
    ],
    "ann-manga": [_doc("ann-manga-2", "Claymore", "monsters and a sword")],
    "mu": [
        _doc("mu-a", "Claymore", "a warrior hunts monsters, monsters everywhere"),
        _doc("mu-b", "Space Brothers", "brothers go to space"),
    ],
}  # fmt: skip


@pytest.fixture
def index(tmp_path, monkeypatch) -> Index:
    docs_dir, index_dir = tmp_path / "docs", tmp_path / "index"
    docs_dir.mkdir()
    for name, docs in DOCS.items():
        lines = [json.dumps(d) + "\n" for d in docs]
        (docs_dir / f"{name}.jsonl").write_text("".join(lines), encoding="utf-8")
    monkeypatch.setattr(build_module, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(build_module, "INDEX_DIR", index_dir)

    counts = build_module.build()
    assert counts["documents"] == 4
    return Index(index_dir, docs_dir)


def test_main_credit() -> None:
    assert main_credit("Series Director")
    assert main_credit("Original creator")
    assert not main_credit("Key Animation")
    assert not main_credit("Episode Director")


def test_index_text_leaves_out_minor_anime_credits() -> None:
    text = index_text(DOCS["ann-anime"][0])

    assert "Shinichiro Watanabe" in text
    assert "Many Animators" not in text


def test_postings_and_norm(index: Index) -> None:
    assert index.n == 4
    assert index.terms["monsters"][0] == 2  # df
    assert index.postings("monsters") == [(1, 1), (2, 2)]

    # mu-a: claymore, manga (type), 2001 (year), warrior, hunts, everywhere tf 1; monsters tf 2
    weights = [1.0] * 6 + [1 + math.log10(2)]
    assert index.norms[2] == pytest.approx(math.sqrt(sum(w * w for w in weights)), abs=1e-5)


def test_document_by_offset(index: Index) -> None:
    assert index.document("mu-b")["title"] == "Space Brothers"
    assert index.document("ann-anime-1")["staff"][0]["name"] == "Shinichiro Watanabe"
    assert index.document("mu-zzz") == {}


def test_idf_variants() -> None:
    assert IDF["log"](4, 1) == pytest.approx(math.log10(4))
    assert IDF["smooth"](4, 1) == pytest.approx(math.log10(5))
    assert IDF["smooth"](4, 4) == pytest.approx(math.log10(2))  # in every document: still a weight
    assert IDF["none"](4, 1) == IDF["none"](4, 4) == 1.0  # the control: no IDF at all


def test_search_ranks_and_filters(index: Index) -> None:
    hits = index.search("claymore monsters", "log", top=3)
    assert [h.id for h in hits][:2] == ["ann-manga-2", "mu-a"]  # cosine: the shorter document first
    hits = index.search("claymore monsters", "log", top=3, norm="pivot")
    assert [h.id for h in hits][:2] == ["mu-a", "ann-manga-2"]  # pivot: monsters tf 2 wins

    assert [h.id for h in index.search("claymore", source="ann")] == ["ann-manga-2"]
    assert index.search("claymore monsters", "log", top=1)[0].matched == ("claymore", "monsters")
    assert index.search("unknownword") == []
    assert index.search("space", norm="pivot")[0].id in ("ann-anime-1", "mu-b")


def test_smooth_idf_weighs_common_terms_more(index: Index) -> None:
    log = index.query_weights("space manga", "log")
    smooth = index.query_weights("space manga", "smooth")
    assert smooth["manga"] / smooth["space"] > log["manga"] / log["space"]
