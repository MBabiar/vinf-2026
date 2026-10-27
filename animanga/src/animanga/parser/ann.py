"""Anime News Network: one encyclopedia page (anime.php / manga.php) -> rows per table.

Only the work's own blocks are read, never the whole page (the sidebar with news is on every
page): the ``infotype-N`` blocks with a ``<strong>Label:</strong>``, the related-works block, the
headline lists of articles, and the ``data-encyc-credits="JP staff"`` (… cast, company, in up to
20 languages) blocks. Anime and manga share one ID space, so ``id`` is unique on ANN.
"""

import re
from datetime import datetime

from animanga.parser.common import first_year, text, unparen

TABLES = {
    # one row per page: the document the index is built from
    "works": [
        "id", "kind", "type", "title", "name", "year", "genres", "themes", "plot", "episodes",
        "running_time", "pages", "volumes", "objectionable", "comment", "rating", "votes", "seen",
    ],
    "titles": ["id", "title", "language", "main"],
    # every other info field, one value per row (Vintage lines, songs, websites, ...)
    "fields": ["id", "field", "value"],
    # one row per credited person / company (staff, company) or per role played (cast)
    "credits": [
        "id", "language", "section", "role", "ref", "ref_id", "name", "character", "note",
    ],
    # edge "src is <relation> of dst", found on page `page` (each edge is usually on both pages)
    "relations": ["page", "src_kind", "src", "relation", "dst_kind", "dst", "other_title", "note"],
    # headline lists (News, Reviews, Interest, ...); level S0 = about this work, S1 = references
    # it, S2 = unverified reference
    "articles": ["id", "section", "level", "date", "url", "title"],
}  # fmt: skip

_H1 = re.compile(r'<h1 id="page_header"[^>]*>(.*?)</h1>', re.DOTALL)
_TITLE = re.compile(r"<title>(.*?)(?: - Anime News Network.*)?</title>", re.DOTALL)
_SUFFIX = re.compile(r"^(.*\S)\s*\(([^()]+)\)$")
_TYPE_IN_TITLE = re.compile(
    r"\b(movie|motion picture|film|OVA|OAV|ONA|TV|specials?|manga|novel)\b", re.IGNORECASE
)
_TYPE_WORD = {
    "ova": "OAV",
    "oav": "OAV",
    "ona": "ONA",
    "tv": "TV",
    "motion picture": "movie",
    "film": "movie",
    "specials": "special",
}

# an info block runs until the next block, the image/releases table, or the credits
_BLOCK = re.compile(
    r'<div (?:id="infotype-(\d+)" )?class="encyc-info-type([^"]*)"[^>]*>(.*?)'
    r'(?=<div (?:id="infotype-\d+" )?class="encyc-info-type|<table|$)',
    re.DOTALL,
)
_LABEL = re.compile(r"<strong>(.*?):?</strong>", re.DOTALL)
_TAB = re.compile(r'<div class="tab">(.*?)</div>', re.DOTALL)
_LINK_TEXT = re.compile(r"<a\b[^>]*>(.*?)</a>", re.DOTALL)
_HREF = re.compile(r'href="([^"]+)"')
_SUBPAGE = re.compile(r"^We have \d+$")  # "Trivia: We have 189" links to a page we do not crawl
_LANGUAGE = re.compile(r"^(.*?)\s*\(((?:[^()]|\([^()]*\))*)\)$")  # "星際牛仔 (Chinese (Taiwan))"

_BAYESIAN = re.compile(r"Bayesian estimate:\s*([\d.]+)")
_WEIGHTED = re.compile(r"Weighted mean:\s*([\d.]+)")
_VOTES = re.compile(r"(\d+) ratings? ha(?:ve|s) been given")
_SEEN = re.compile(r"Seen in part or in whole by (\d+) users")

_ARTICLE = re.compile(
    r'<div class="tab (S\d)[^"]*"><a href="([^"]+)"[^>]*>(.*?)</a>\s*<small>\(([^)]*)\)</small>',
    re.DOTALL,
)

_RELATED = re.compile(r'<div id="infotype-related">(.*?)</div>', re.DOTALL)
_BRACKET = re.compile(r"<small>\[(.*?)\]\s*<br>", re.DOTALL)
_WORK_LINK = r'<a [^>]*?href="/encyclopedia/(anime|manga)\.php\?id=(\d+)"[^>]*>(.*?)</a>'
_OUT = re.compile(r"([a-z][a-z ]*?)\s+" + _WORK_LINK, re.DOTALL)
_IN = re.compile(_WORK_LINK + r"\s*(?:\(([^()]*)\))?", re.DOTALL)
_HEADING = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_RELATION_WORD = re.compile(r"[a-z][a-z \-]*")
# "[ sequel of <a>X</a> ]" on the page of the sequel -> relation name used in the lists
_OUT_RELATION = {
    "adapted from": "adaptation",
    "sequel of": "sequel",
    "prequel of": "prequel",
    "spinoff of": "spinoff",
    "side story of": "side story",
    "alternate retelling of": "alternate retelling",
    "alternate ending for": "alternate ending",
    "compilation of": "compilation",
    "remake of": "remake",
    "remixed from": "remix",
    "amalgam of": "amalgam",
    "related to": "related",
}

_CREDITS = re.compile(
    r'data-encyc-credits="([A-Z]{2}) (staff|cast|company)">(.*?)'
    r"(?=<div[^>]*data-encyc-credits|</td>)",
    re.DOTALL,
)
# "<b>Role</b>:", also "<b title="…">Role</b>:" and "<a href="reports.php…"><b>Role</b></a>:"
_ROLE = re.compile(r"^\s*(?:<a\b[^>]*>)?<b\b[^>]*>(.*?)</b>(?:</a>)?\s*:(.*)$", re.DOTALL)
_REF = re.compile(
    r'<a [^>]*?href="(people|company)\.php\?id=(\d+)"[^>]*>(.*?)</a>(.*)$', re.DOTALL
)  # some links have class="discreet" before href
_CHARACTER = re.compile(r"<nobr><b\b[^>]*>(.*?)</b></nobr>\s*(?:<small>(.*?)</small>)?", re.DOTALL)
_SUMMARY = re.compile(r"<u>.*?</u>", re.DOTALL)  # "9 episodes" before the full episode list
_BR = re.compile(r"<br\s*/?>")

_WORK_COLUMNS = {
    "Plot Summary": "plot",
    "Number of episodes": "episodes",
    "Running time": "running_time",
    "Number of pages": "pages",
    "Number of tankoubon": "volumes",
    "Objectionable content": "objectionable",
}


def parse(page: str, key: int, kind: str) -> dict[str, list[dict[str, object]]]:
    """Extract one ANN work.

    Parameters
    ----------
    page : str
        The saved HTML of ``anime.php?id=N`` or ``manga.php?id=N``.
    key : int
        The ANN ID.
    kind : str
        ``anime`` or ``manga`` (which script the page came from).

    Returns
    -------
    dict[str, list[dict[str, object]]]
        Rows per table of `TABLES`.
    """
    name = _name(page)
    title, type_ = split_title(name, kind)
    work: dict[str, object] = {"id": key, "kind": kind, "type": type_, "title": title, "name": name}
    out: dict[str, list[dict[str, object]]] = {table: [] for table in TABLES}
    out["works"].append(work)
    out["titles"].append({"id": key, "title": title, "language": "", "main": 1})

    main = page[max(page.find('id="maincontent"'), 0) :]
    end = main.find("data-encyc-credits")
    info = main[:end] if end >= 0 else main

    dates: list[str] = []
    for m in _BLOCK.finditer(info):
        number, css, body = m.groups()
        if "articles" in css:
            out["articles"].extend(_articles(key, body))
            continue

        label_match = _LABEL.search(body)
        if not label_match or number in ("19", "36", "38"):  # image, "find similar", JustWatch
            continue

        label = text(label_match.group(1))
        body = body[label_match.end() :]
        tabs = [text(t) for t in _TAB.findall(body)]
        value = text(body)

        if _SUBPAGE.match(value):
            continue
        if label == "Alternative title":
            out["titles"].extend(_alt_title(key, t) for t in tabs)
        elif label in ("Genres", "Themes"):
            names = (text(a) for a in _LINK_TEXT.findall(body))
            work[label.lower()] = "; ".join(dict.fromkeys(names))  # unique, in page order
        elif label in _WORK_COLUMNS:
            work[_WORK_COLUMNS[label]] = value
        elif label == "Comment":
            work["comment"] = " ".join(tabs) or value
        elif label == "User Ratings":
            work.update(_rating(value))
        elif label == "Official website":
            out["fields"].extend(
                {"id": key, "field": label, "value": u} for u in _HREF.findall(body)
            )
        else:
            values = tabs or [value]
            out["fields"].extend({"id": key, "field": label, "value": v} for v in values if v)
            if label in ("Vintage", "Premiere date"):
                dates.extend(values)

    work["year"] = first_year(dates)
    out["relations"] = relations(page, key, kind)
    out["credits"] = credits(page, key)
    return out


def _name(page: str) -> str:
    """Return the page heading, e.g. ``Cowboy Bebop (TV)`` (``<title>`` if there is no h1)."""
    m = _H1.search(page) or _TITLE.search(page)
    return text(m.group(1)) if m else ""


def split_title(name: str, kind: str) -> tuple[str, str]:
    """Split an ANN heading into the title and the type of work.

    Parameters
    ----------
    name : str
        The heading: ``Fruits Basket (TV 2)``, ``Claymore (manga)``, ``[Jump Square]``.
    kind : str
        ``anime`` or ``manga``.

    Returns
    -------
    tuple[str, str]
        The title without the suffix and the type: the suffix without a trailing number or year
        (``TV``, ``movie``, ``light novel``), ``magazine`` / ``franchise`` for a ``[bracketed]``
        manga / anime entry, else the last type word in the title (``The Motion Picture`` ->
        ``movie``), else ``""``.
    """
    if name.startswith("[") and name.endswith("]"):
        return name[1:-1].strip(), "magazine" if kind == "manga" else "franchise"

    m = _SUFFIX.match(name)
    if m:
        suffix = m.group(2).split(",")[0].strip()  # "manga, Yu Asagiri" names the author
        return m.group(1), re.sub(r"\s+[\d/]+$", "", suffix)  # "TV 2", "TV 1/1973" -> "TV"

    words = _TYPE_IN_TITLE.findall(name)
    if not words:
        return name, ""
    word = words[-1].lower()
    return name, _TYPE_WORD.get(word, word)


def _alt_title(key: int, value: str) -> dict[str, object]:
    """One alternative title; the language is the last parenthesis (may nest)."""
    m = _LANGUAGE.match(value)
    if m and m.group(1):
        return {"id": key, "title": m.group(1), "language": m.group(2), "main": 0}
    return {"id": key, "title": value, "language": "", "main": 0}


def _rating(value: str) -> dict[str, object]:
    """Bayesian estimate (or weighted mean), number of ratings and of users who saw it."""
    out: dict[str, object] = {}

    m = _BAYESIAN.search(value) or _WEIGHTED.search(value)
    if m:
        out["rating"] = m.group(1)
    m = _VOTES.search(value)
    if m:
        out["votes"] = m.group(1)
    m = _SEEN.search(value)
    if m:
        out["seen"] = m.group(1)
    return out


def _articles(key: int, body: str) -> list[dict[str, object]]:
    """Rows of one headline list (News, Reviews, ...)."""
    label = _LABEL.search(body)
    section = text(label.group(1)) if label else ""
    if section and not section.endswith("s") and section != "Interest":
        section += "s"  # a list with one headline says "Review:", else "Reviews:"

    rows: list[dict[str, object]] = []
    for level, url, title, date in _ARTICLE.findall(body):
        rows.append(
            {
                "id": key,
                "section": section,
                "level": level,
                "date": _iso_date(date),
                "url": url,
                "title": text(title),
            }
        )
    return rows


def _iso_date(value: str) -> str:
    """``Dec 15, 2014`` -> ``2014-12-15``; anything else is returned as it is."""
    value = " ".join(value.split())
    try:
        return datetime.strptime(value, "%b %d, %Y").date().isoformat()
    except ValueError:
        return value


def relations(page: str, key: int, kind: str) -> list[dict[str, object]]:
    """Extract the related works as edges ``src is <relation> of dst``.

    ``[ sequel of <a>X</a> ]`` gives ``this -> X``; a list ``<b>Related anime:</b> <a>Y</a>
    (sequel)`` gives ``Y -> this`` (``Contains:`` lists the members of a magazine or franchise).
    A list entry without a relation word is ``related`` (``part of`` under Contains); a date in
    the parenthesis goes to ``note``.

    Parameters
    ----------
    page : str
        The whole page.
    key : int
        Its ANN ID.
    kind : str
        ``anime`` or ``manga``.

    Returns
    -------
    list[dict[str, object]]
        Rows of the ``relations`` table.
    """
    m = _RELATED.search(page)
    if not m:
        return []
    block = m.group(1)

    rows: list[dict[str, object]] = []
    for bracket in _BRACKET.findall(block):
        for phrase, other_kind, other, title in _OUT.findall(bracket):
            phrase = " ".join(phrase.split())
            rows.append(
                {
                    "page": key,
                    "src_kind": kind,
                    "src": key,
                    "relation": _OUT_RELATION.get(phrase, phrase),
                    "dst_kind": other_kind,
                    "dst": other,
                    "other_title": text(title),
                }
            )

    lists = _BRACKET.sub(" ", block)
    parts = _HEADING.split(lists)  # [before, heading, entries, heading, entries, ...]
    for heading, entries in zip(parts[1::2], parts[2::2], strict=True):
        default = "part of" if heading.startswith("Contains") else "related"
        for other_kind, other, title, paren in _IN.findall(entries):
            relation, note = _list_relation(paren, default)
            rows.append(
                {
                    "page": key,
                    "src_kind": other_kind,
                    "src": other,
                    "relation": relation,
                    "dst_kind": kind,
                    "dst": key,
                    "other_title": text(title),
                    "note": note,
                }
            )
    return rows


def _list_relation(paren: str, default: str) -> tuple[str, str]:
    """``2000-03-04, sequel`` -> (``sequel``, ``2000-03-04``); ``2027`` -> (default, ``2027``)."""
    parts = [p.strip() for p in text(paren).split(",") if p.strip()]
    if parts and _RELATION_WORD.fullmatch(parts[-1]):
        return parts[-1], ", ".join(parts[:-1])
    return default, ", ".join(parts)


def credits(page: str, key: int) -> list[dict[str, object]]:
    """Extract staff, cast and companies of every language block.

    Staff and company entries are ``<b>Role</b>: <a href="people.php?id=N">Name</a> <small>(eps
    1-3)</small><br>…``; cast entries are ``<a>Actor</a> <i>as</i> <nobr><b>Character</b></nobr>``,
    one row per character. A name without a link gets an empty ``ref_id``.

    Parameters
    ----------
    page : str
        The whole page.
    key : int
        Its ANN ID.

    Returns
    -------
    list[dict[str, object]]
        Rows of the ``credits`` table.
    """
    rows: list[dict[str, object]] = []
    for language, section, block in _CREDITS.findall(page):
        base = {"id": key, "language": language, "section": section}
        for entry in block.split('<div class="ENTAB">')[1:]:
            if section == "cast":
                rows.extend(_cast(base, entry))
            else:
                rows.extend(_staff(base, entry))
    return rows


def _staff(base: dict[str, object], entry: str) -> list[dict[str, object]]:
    """Rows of one staff/company role: every person or company after ``<b>Role</b>:``."""
    m = _ROLE.match(entry)
    if not m:
        return []
    role = text(m.group(1))

    rows: list[dict[str, object]] = []
    for part in _BR.split(m.group(2)):
        ref = _REF.search(part)
        if ref:
            note = unparen(text(_SUMMARY.sub("", ref.group(4))))
            row = {"ref": ref.group(1), "ref_id": ref.group(2), "name": text(ref.group(3))}
            rows.append({**base, "role": role, **row, "note": note})
        elif name := text(part):  # no page on ANN: "Maki Kitada (Bass)"
            note = ""
            m = _LANGUAGE.match(name)
            if m and m.group(1):
                name, note = m.group(1), m.group(2)
            rows.append({**base, "role": role, "name": name, "note": note})
    return rows


def _cast(base: dict[str, object], entry: str) -> list[dict[str, object]]:
    """Rows of one cast entry: the actor once per character played."""
    ref = _REF.search(entry)
    if not ref:
        return []
    actor = {"ref": ref.group(1), "ref_id": ref.group(2), "name": text(ref.group(3))}

    roles = _CHARACTER.findall(entry)
    if not roles:
        return [{**base, **actor}]

    rows: list[dict[str, object]] = []
    for character, note in roles:
        note = unparen(text(_SUMMARY.sub("", note)))
        rows.append({**base, **actor, "character": text(character), "note": note})
    return rows
