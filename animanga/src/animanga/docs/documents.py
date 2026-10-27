"""One parsed page -> one document (pure functions; `run.py` reads and writes the files).

A document is one work: what the index reads and what a search returns. Both sites get the same
fields (`FIELDS`), so later steps need not know where a document came from. Only facts about the
work go in: on ANN the credits of the work's own country (`ORIGIN`; not the translators of the
English release), no cast, ratings or article headlines; on MangaUpdates no statistics,
categories, recommendations or user comments (they stay in ``parsed/`` until analysed).
"""

ANN_URL = "https://www.animenewsnetwork.com/encyclopedia/{kind}.php?id={id}"
MU_URL = "https://www.mangaupdates.com/series/{mu_id}/{slug}"

FIELDS = (
    "id", "source", "kind", "url", "title", "titles", "type", "year", "genres", "themes", "text",
    "staff", "companies", "relations", "anime_chapters", "legacy_id", "links",
)  # fmt: skip

# credit blocks of the country a work comes from, in this order: Japan, Korea, China, Taiwan,
# then English (an American work has only EN blocks; a Japanese one has EN blocks of the dub)
ORIGIN = ("JP", "KR", "CN", "TW", "EN")

SKIPPED_TYPES = frozenset({"Doujinshi"})  # MangaUpdates types without a document (user 21 Oct)


def ann_id(kind: str, number: object) -> str:
    """Return the document ID of an ANN work: ``ann-anime-13``, ``ann-manga-12308``.

    Parameters
    ----------
    kind : str
        ``anime`` or ``manga``.
    number : object
        The ANN ID.

    Returns
    -------
    str
        The document ID.
    """
    return f"ann-{kind}-{number}"


def mu_id(base36: str) -> str:
    """Return the document ID of a MangaUpdates series: ``mu-<base36>``.

    Parameters
    ----------
    base36 : str
        The series ID in the URL (``t8zu40m``).

    Returns
    -------
    str
        The document ID.
    """
    return f"mu-{base36}"


def _split(value: object) -> list[str]:
    """Split a ``"; "``-joined list: ``"action; drama"`` -> ``["action", "drama"]``."""
    return [v.strip() for v in str(value or "").split(";") if v.strip()]


def _ref(prefix: str, value: object) -> str:
    """``prefix + value``, or ``""`` when there is no value (a name without a page)."""
    return f"{prefix}{value}" if value else ""


def _origin(credits: list[dict]) -> str:
    """Return the first `ORIGIN` language with staff, else with companies (``""`` if none).

    Staff decide: a Korean manhwa has its author in ``KR staff`` but also a ``JP company`` block
    (the Japanese publisher of the translation).
    """
    for section in ("staff", "company"):
        languages = {c["language"] for c in credits if c.get("section") == section}
        for language in ORIGIN:
            if language in languages:
                return language
    return ""


def ann_document(page: dict) -> dict | None:
    """Build the document of one ANN page.

    Parameters
    ----------
    page : dict
        One line of ``parsed/anime.jsonl`` or ``manga.jsonl``.

    Returns
    -------
    dict or None
        The document (fields `FIELDS`, ``links`` empty until the join), or ``None`` for a page
        without a title.
    """
    if not page.get("title"):
        return None
    kind = page["kind"]

    credits = page.get("credits", [])
    origin = _origin(credits)
    staff, companies = [], []
    for c in credits:
        if c["language"] != origin or c["section"] not in ("staff", "company"):
            continue
        entry = {
            "role": c["role"],
            "name": c["name"],
            "id": _ref(f"ann-{c['ref']}-", c.get("ref_id")),
        }
        (staff if c["section"] == "staff" else companies).append(entry)

    relations, seen = [], set()
    for r in page.get("relations", []):
        if str(r["src"]) == str(page["id"]) and r["src_kind"] == kind:
            other, direction = ann_id(r["dst_kind"], r["dst"]), "out"
        else:
            other, direction = ann_id(r["src_kind"], r["src"]), "in"
        edge = (r["relation"], direction, other)
        if edge not in seen:
            seen.add(edge)
            relations.append(
                {"relation": r["relation"], "direction": direction, "id": other,
                 "title": r["other_title"]}
            )  # fmt: skip

    return {
        "id": ann_id(kind, page["id"]),
        "source": "ann",
        "kind": kind,
        "url": ANN_URL.format(kind=kind, id=page["id"]),
        "title": page["title"],
        "titles": [{"title": t["title"], "language": t["language"]} for t in page["titles"]],
        "type": page.get("type", ""),
        "year": page.get("year", ""),
        "genres": _split(page.get("genres")),
        "themes": _split(page.get("themes")),
        "text": page.get("plot", ""),
        "staff": staff,
        "companies": companies,
        "relations": relations,
        "anime_chapters": {},
        "legacy_id": "",
        "links": [],
    }


def mu_document(page: dict) -> dict | None:
    """Build the document of one MangaUpdates series page.

    Parameters
    ----------
    page : dict
        One line of ``parsed/series.jsonl``.

    Returns
    -------
    dict or None
        The document, or ``None`` for a doujinshi (`SKIPPED_TYPES`) or a page without a title
        or base36 ID.
    """
    if not page.get("title") or not page.get("mu_id") or page.get("type") in SKIPPED_TYPES:
        return None
    legacy = page["id"] if page["id"] < 10**11 else ""  # catalog series have no legacy ID

    staff = [
        {"role": p["role"], "name": p["name"], "id": _ref("mu-author-", p.get("author_id"))}
        for p in page.get("people", [])
    ]
    companies = [
        {"role": p["role"], "name": p["name"], "id": _ref("mu-publisher-", p.get("publisher_id")),
         "note": p.get("note", "")}
        for p in page.get("publishers", [])
    ]  # fmt: skip
    # MU writes what the other series is to this one ("Sequel", "Adapted From" = the source): "in"
    relations = [
        {"relation": r["relation"], "direction": "in", "id": _ref("mu-", r.get("other_mu_id")),
         "title": r["other_title"]}
        for r in page.get("related", [])
        if r["relation"] != "recommended"
    ]  # fmt: skip
    chapters = {
        k: page[k] for k in ("anime", "anime_start", "anime_end", "anime_end_vol") if page.get(k)
    }

    return {
        "id": mu_id(page["mu_id"]),
        "source": "mu",
        "kind": "manga",
        "url": MU_URL.format(mu_id=page["mu_id"], slug=page.get("slug", "")),
        "title": page["title"],
        "titles": [{"title": t["title"], "language": ""} for t in page["titles"]],
        "type": page.get("type", ""),
        "year": page.get("year", ""),
        "genres": _split(page.get("genres")),
        "themes": [],
        "text": page.get("description", ""),
        "staff": staff,
        "companies": companies,
        "relations": relations,
        "anime_chapters": chapters,
        "legacy_id": legacy,
        "links": [],
    }
