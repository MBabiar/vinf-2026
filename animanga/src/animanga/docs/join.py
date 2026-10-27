"""Join ANN and MangaUpdates: which ANN manga is which MU series (pure functions).

A link needs the same title key (`title_key`) *and* at least one shared person (`person_key`) on
works of the same class (comic or novel: ANN lists light novels on ``manga.php`` too, MU has
"Novel" series of the same name). A sample showed that a title alone is not enough (30
alternative-title matches, 1 right). Every link says how it was found:

========  ===================================================  ==============
level     match                                                ``confidence``
========  ===================================================  ==============
main      main title on both sides + a shared person           ``high``
alt       an alternative title on one side + a shared person    ``medium``
========  ===================================================  ==============

Of several candidates the best level wins; two or more at the best level are not linked
(ambiguous). Matches without a shared person and ambiguous ones become `Candidate` rows for the
analysis file. An anime gets the links of the ANN manga it is adapted from (``via-ann-manga``).
"""

from collections import defaultdict
from dataclasses import dataclass

from animanga.normalize import person_key, title_key

CONFIDENCE = {"main": "high", "alt": "medium"}
_RANK = {"main": 2, "alt": 1}
NO_JOIN_TYPES = frozenset({"magazine"})  # ANN entries of a magazine, not of a work


@dataclass(frozen=True)
class Candidate:
    """A title match that did not become a link (written to ``join-candidates.jsonl``)."""

    ann: str
    mu: str
    level: str
    reason: str  # no-person, ambiguous


def work_class(doc: dict) -> str:
    """Return ``novel`` for a novel or light novel, else ``comic``.

    Parameters
    ----------
    doc : dict
        A document.

    Returns
    -------
    str
        ``novel`` or ``comic``.
    """
    return "novel" if "novel" in str(doc.get("type", "")).lower() else "comic"


def title_keys(doc: dict) -> dict[str, str]:
    """Return the title keys of a document with their level.

    Parameters
    ----------
    doc : dict
        A document.

    Returns
    -------
    dict[str, str]
        Key -> ``main`` (the main title) or ``alt`` (any other title).
    """
    keys: dict[str, str] = {}
    for t in doc.get("titles", []):
        key = title_key(t["title"])
        if key and key not in keys:
            keys[key] = "alt"
    main = title_key(doc["title"])
    if main:
        keys[main] = "main"
    return keys


def person_keys(doc: dict) -> set[str]:
    """Return the person keys of a document's staff (authors, artists, other staff).

    Parameters
    ----------
    doc : dict
        A document.

    Returns
    -------
    set[str]
        The non-empty `person_key` of every staff name.
    """
    return {k for s in doc.get("staff", []) if (k := person_key(s["name"]))}


def join_manga(ann_manga: list[dict], mu: list[dict]) -> tuple[list[dict], list[Candidate]]:
    """Link ANN manga to MangaUpdates series.

    Parameters
    ----------
    ann_manga : list[dict]
        Documents of ``manga.php`` pages.
    mu : list[dict]
        MangaUpdates documents.

    Returns
    -------
    tuple[list[dict], list[Candidate]]
        Links ``{"ann", "mu", "method", "confidence"}`` and the matches that were not linked.
    """
    by_title: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for i, doc in enumerate(mu):
        for key, level in title_keys(doc).items():
            by_title[key].append((i, level))
    mu_people = [person_keys(doc) for doc in mu]
    mu_class = [work_class(doc) for doc in mu]

    links: list[dict] = []
    candidates: list[Candidate] = []
    for doc in ann_manga:
        if doc.get("type") in NO_JOIN_TYPES:
            continue
        people = person_keys(doc)
        cls = work_class(doc)

        best: dict[int, str] = {}  # MU index -> best level of the title match
        for key, ann_level in title_keys(doc).items():
            for i, mu_level in by_title.get(key, ()):
                if mu_class[i] != cls:
                    continue
                level = "main" if ann_level == mu_level == "main" else "alt"
                if _RANK[level] > _RANK.get(best.get(i, ""), 0):
                    best[i] = level

        matched = {i: level for i, level in best.items() if people & mu_people[i]}
        candidates.extend(
            Candidate(doc["id"], mu[i]["id"], level, "no-person")
            for i, level in best.items()
            if i not in matched
        )
        if not matched:
            continue

        top = max(_RANK[level] for level in matched.values())
        winners = [i for i, level in matched.items() if _RANK[level] == top]
        if len(winners) > 1:
            candidates.extend(
                Candidate(doc["id"], mu[i]["id"], matched[i], "ambiguous") for i in winners
            )
            continue

        level = matched[winners[0]]
        links.append(
            {"ann": doc["id"], "mu": mu[winners[0]]["id"], "method": f"title-{level}+person",
             "confidence": CONFIDENCE[level]}
        )  # fmt: skip
    return links, candidates


def join_anime(anime: list[dict], manga_links: list[dict]) -> list[dict]:
    """Link anime to MangaUpdates through the ANN manga they are adapted from.

    Parameters
    ----------
    anime : list[dict]
        Documents of ``anime.php`` pages.
    manga_links : list[dict]
        Links from `join_manga`.

    Returns
    -------
    list[dict]
        Links ``{"ann", "mu", "method": "via-ann-manga", "confidence", "via"}``; the confidence
        is that of the manga's link.
    """
    by_manga = {link["ann"]: link for link in manga_links}

    links: list[dict] = []
    for doc in anime:
        seen = set()
        for r in doc["relations"]:
            link = by_manga.get(r["id"])
            if r["relation"] != "adaptation" or r["direction"] != "out" or not link:
                continue
            if link["mu"] in seen:
                continue
            seen.add(link["mu"])
            links.append(
                {"ann": doc["id"], "mu": link["mu"], "method": "via-ann-manga",
                 "confidence": link["confidence"], "via": r["id"]}
            )  # fmt: skip
    return links


def attach(docs: dict[str, dict], links: list[dict]) -> None:
    """Write each link into the ``links`` field of both its documents.

    Parameters
    ----------
    docs : dict[str, dict]
        Documents by ID; changed in place.
    links : list[dict]
        Links from `join_manga` and `join_anime`.
    """
    for link in links:
        extra = {k: v for k, v in link.items() if k in ("method", "confidence", "via")}
        docs[link["ann"]]["links"].append({"id": link["mu"], **extra})
        docs[link["mu"]]["links"].append({"id": link["ann"], **extra})
