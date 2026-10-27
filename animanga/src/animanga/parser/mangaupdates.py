"""MangaUpdates: one series page -> rows per table.

All ``<script>`` blocks are dropped first (about 74 % of the bytes; the Next.js data repeats the
page). Every field is a pair ``data-cy="info-box-X-header"`` (the label) + ``data-cy="info-box-X"``
(the value); many fields share ``X = unknown``, so a field is chosen by its label. The only thing
read from the scripts is the full category list with votes (the page shows only the top ones).
CSS classes carry a build hash (``linked-name-module__9zptFq__name_underline``), so regexes
match only their stable end (``name_underline``).
"""

import re

from animanga.crawler.sites.mangaupdates import series_key
from animanga.parser.common import drop_scripts, json_string, text, unparen

# series pages: by legacy ID and by base36 ID (new series from the catalog); not the catalog pages
KINDS = ("series", "series_b36")
FILES = {"series": "series", "series_b36": "series"}  # both go to parsed/series.jsonl


def page_key(name: str, kind: str) -> int:
    """Return the ID of a saved page from its file name (the crawler's ID).

    Parameters
    ----------
    name : str
        File name without ``.html``: a legacy ID, or a base36 ID in ``raw/series_b36/``.
    kind : str
        The ``raw/`` folder.

    Returns
    -------
    int
        The legacy ID, or ``series_key(base36)`` (the ``mu_id`` column has the base36 ID).
    """
    return series_key(name) if kind == "series_b36" else int(name)


TABLES = {
    # one row per series: the document the index is built from
    "series": [
        "id", "mu_id", "slug", "title", "type", "year", "status", "completed", "licensed",
        "genres", "description", "anime", "anime_start", "anime_end", "anime_end_vol", "rating",
        "votes", "reading", "updated",
    ],
    "titles": ["id", "title", "main"],
    "people": ["id", "role", "author_id", "name", "note"],
    # original / english publisher, magazine (serialized in) with the chapters or the publisher
    "publishers": ["id", "role", "publisher_id", "name", "note"],
    # related series (relation from the page), user recommendations (relation "recommended")
    "related": ["id", "relation", "other_mu_id", "other_title"],
    "categories": ["id", "category", "votes", "votes_plus", "votes_minus"],
    "comments": ["id", "comment_id", "user", "date", "subject", "text"],
}  # fmt: skip

_TITLE = re.compile(r"<title>(.*?)(?:\s*-\s*MangaUpdates)?\s*</title>", re.DOTALL)
_CANONICAL = re.compile(
    r'<link rel="canonical" href="https://www\.mangaupdates\.com/series/([0-9a-z]+)/?([^"]*)"'
)
_PAIR = re.compile(
    r'data-cy="info-box-([a-z_]+)-header"[^>]*>(.*?)</div>.*?data-cy="info-box-\1"[^>]*>(.*?)'
    r'(?=<div[^>]*data-cy="info-box-[a-z_]+-header"|data-cy="comment-row"|<footer|$)',
    re.DOTALL,
)
_ITEM = re.compile(r"<div>(.*?)</div>", re.DOTALL)
_NAME = re.compile(r'<span class="[^"]*name_underline[^"]*">(.*?)</span>', re.DOTALL)
_ADD = re.compile(r"\[\s*<a [^>]*>.*?</a>\s*\]", re.DOTALL)  # "[Add]" next to an unknown name
_FIRST_LINK = re.compile(r"<a\b[^>]*>(.*?)</a>(.*)$", re.DOTALL)
_GENRE = re.compile(r'<a href="/series\?genre=[^"]*"><span><u>(.*?)</u>', re.DOTALL)
_VISIBLE_CATEGORY = re.compile(
    r'<a [^>]*title="Score: (-?\d+) \((\d+),(\d+)\)"[^>]*href="/series\?category=[^"]*">(.*?)</a>',
    re.DOTALL,
)
_CATEGORY = re.compile(
    r'\\"category\\":\\"((?:[^"\\]|\\\\.)*?)\\",\\"votes\\":(-?\d+),'
    r'\\"votes_plus\\":(\d+),\\"votes_minus\\":(\d+)'
)
_BAYESIAN = re.compile(r"Bayesian Average:\s*([\d.]+)")
_VOTES = re.compile(r"\(\s*(\d+)\s+votes?\s*\)")
_READING = re.compile(r"On (\d+) reading lists?")
_DATETIME = re.compile(r'dateTime="([^"]+)"')
_CHAPTER = re.compile(r"\bCh(?:ap(?:ter)?)?\.?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_VOLUME = re.compile(r"\bVol(?:ume)?\.?\s*(\d+)", re.IGNORECASE)
# Where one entry of the Ends line ends: the first volume (with the chapter right after it) or
# chapter ("Vol 5 (2008 S2) Skips Vol 4, OVAs adapt Vol 7, Chap 2&3" -> volume 5, no chapter;
# "2001: Vol 9, Chap 78"; the typo "Volu 4, Chap 28").
_END = re.compile(
    r"\bVol\w*\.?\s*(\d+)(?:[,\s]*Ch(?:ap(?:ter)?)?\.?\s*(\d+(?:\.\d+)?))?"
    r"|\bCh(?:ap(?:ter)?)?\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_COMMENT = re.compile(r'data-cy="comment-row"(.*?)(?=data-cy="comment-row"|$)', re.DOTALL)
_COMMENT_ID = re.compile(r'id="comment(\d+)"')
_COMMENT_TITLE = re.compile(r'class="[^"]*comment_title[^"]*">(.*?)</div>', re.DOTALL)
_COMMENT_USER = re.compile(r'class="[^"]*newsname[^"]*">(.*?)</span>', re.DOTALL)
_COMMENT_TEXT = re.compile(
    r'<div class="[^"]*mu_markdown[^"]*">(.*?)<em>Was this comment useful\?', re.DOTALL
)

_SCALARS = {
    "Type": "type",
    "Year": "year",
    "Status in Country of Origin": "status",
    "Completely Scanlated?": "completed",
    "Licensed (in English)": "licensed",
    "Description": "description",
}
_PEOPLE = {"Author(s)": "author", "Artist(s)": "artist"}
_PUBLISHERS = {"Original Publisher": "original", "English Publisher": "english"}


def parse(page: str, key: int, kind: str = "series") -> dict[str, list[dict[str, object]]]:
    """Extract one MangaUpdates series.

    Parameters
    ----------
    page : str
        The saved HTML of ``/series/<base36>/<slug>``.
    key : int
        The crawler's ID: the legacy ID (``series.html?id=N``), or ``series_key(base36)`` for a
        new series from the catalog.
    kind : str
        ``series`` or ``series_b36`` (not used: both have the same template).

    Returns
    -------
    dict[str, list[dict[str, object]]]
        Rows per table of `TABLES`.
    """
    body = drop_scripts(page)
    out: dict[str, list[dict[str, object]]] = {table: [] for table in TABLES}

    title = _TITLE.search(body)
    canonical = _CANONICAL.search(page)
    series: dict[str, object] = {
        "id": key,
        "mu_id": canonical.group(1) if canonical else "",
        "slug": canonical.group(2) if canonical else "",
        "title": text(title.group(1)) if title else "",
    }
    out["series"].append(series)
    out["titles"].append({"id": key, "title": series["title"], "main": 1})

    shown_categories = ""
    for _, header, value in _PAIR.findall(body):
        label = text(header)
        plain = text(value)
        if plain == "N/A":
            continue

        if label in _SCALARS:
            series[_SCALARS[label]] = plain
        elif label == "Associated Names":
            names = (text(n) for n in _ITEM.findall(value))
            out["titles"].extend({"id": key, "title": n, "main": 0} for n in names if n)
        elif label == "Genre":
            series["genres"] = "; ".join(text(g) for g in _GENRE.findall(value))
        elif label in _PEOPLE:
            out["people"].extend(_people(key, _PEOPLE[label], value))
        elif label in _PUBLISHERS:
            out["publishers"].extend(_publishers(key, _PUBLISHERS[label], value))
        elif label == "Serialized In (magazine)":
            out["publishers"].extend(_magazines(key, value))
        elif label == "Related Series":
            out["related"].extend(_related(key, value, ""))
        elif label == "Recommendations":
            out["related"].extend(_related(key, value, "recommended"))
        elif label == "Anime Start/End Chapter":
            series.update(_anime(value))
        elif label == "User Rating":
            series.update(_rating(plain))
        elif label == "List Stats":
            m = _READING.search(plain)
            series["reading"] = m.group(1) if m else ""
        elif label == "Last Updated":
            m = _DATETIME.search(value)
            series["updated"] = m.group(1) if m else plain
        elif label == "Categories":
            shown_categories = value

    out["categories"] = categories(page, key) or _visible_categories(key, shown_categories)
    out["comments"] = comments(body, key)
    return out


def _entries(value: str) -> list[tuple[str, str, str]]:
    """Split a list field into (link, name, note) per ``<div>`` item.

    The name is the ``name_underline`` span (else the item's text), the note is the text after it
    without the parentheses (``Viz (27 Vols - Complete)`` -> ``27 Vols - Complete``).
    """
    out: list[tuple[str, str, str]] = []
    for item in _ITEM.findall(_ADD.sub(" ", value)):
        m = _NAME.search(item)
        if m:
            name, rest = text(m.group(1)), item[m.end() :]
        else:
            name, rest = text(item), ""
        href = re.search(r'href="([^"]*)"', item)
        out.append((href.group(1) if href else "", name, unparen(text(rest))))
    return out


def _ref_id(href: str, what: str) -> str:
    """Return the base36 ID in ``https://www.mangaupdates.com/<what>/<id>/<slug>`` (or ``""``)."""
    m = re.search(rf"/{what}/([0-9a-z]+)", href)
    return m.group(1) if m else ""


def _people(key: int, role: str, value: str) -> list[dict[str, object]]:
    """Rows of Author(s) / Artist(s); an author without an MU page has no ``author_id``."""
    return [
        {"id": key, "role": role, "author_id": _ref_id(h, "author"), "name": n, "note": note}
        for h, n, note in _entries(value)
        if n
    ]


def _publishers(key: int, role: str, value: str) -> list[dict[str, object]]:
    """Rows of Original Publisher / English Publisher (note: volumes, status)."""
    return [
        {"id": key, "role": role, "publisher_id": _ref_id(h, "publisher"), "name": n, "note": note}
        for h, n, note in _entries(value)
        if n
    ]


def _magazines(key: int, value: str) -> list[dict[str, object]]:
    """Rows of Serialized In: ``<a><u>Jump SQ</u></a> (Chap 74 - 155)`` (note: chapters)."""
    rows: list[dict[str, object]] = []
    for item in _ITEM.findall(value):
        m = _FIRST_LINK.search(item)
        name, rest = (text(m.group(1)), m.group(2)) if m else (text(item), "")
        if name:
            rows.append({"id": key, "role": "magazine", "name": name, "note": unparen(text(rest))})
    return rows


def _related(key: int, value: str, relation: str) -> list[dict[str, object]]:
    """Rows of Related Series (relation in the parenthesis) or Recommendations."""
    return [
        {
            "id": key,
            "relation": relation or note,
            "other_mu_id": _ref_id(h, "series"),
            "other_title": n,
        }
        for h, n, note in _entries(value)
        if n
    ]


def _anime(value: str) -> dict[str, object]:
    """Read Anime Start/End Chapter: ``Starts at Vol 1, Chap 1`` / ``Ends at Vol 11, Chap 59``.

    The Starts and the Ends line list one entry per adaptation (season, film), separated by
    `` / ``: ``Ends at Vol 7, Chap 38 (2001) / Vol 6, Chap 35 (S1) / Vol 23, Chap 136 (S3)``.
    ``anime`` keeps all lines (free text such as "Diverges after Ep 15"); ``anime_start`` is the
    first chapter on the Starts line; ``anime_end`` / ``anime_end_vol`` are the chapter and volume
    of the furthest Ends entry (the highest volume, then chapter), so where to read on after every
    adaptation (Fruits Basket: 136, not 38 of the first series).
    """
    lines = [text(i) for i in _ITEM.findall(value)] or [text(value)]
    out: dict[str, object] = {"anime": " / ".join(line for line in lines if line)}

    ends: list[tuple[float, float, str, str]] = []
    for line in lines:
        chapter = _CHAPTER.search(line)
        if line.startswith("Starts at") and chapter and "anime_start" not in out:
            out["anime_start"] = chapter.group(1)
        elif line.startswith("Ends at"):
            for entry in line.split(" / "):
                if m := _END.search(entry):
                    vol, ch = m.group(1) or "", m.group(2) or m.group(3) or ""
                    ends.append((float(vol or -1), float(ch or -1), ch, vol))

    if ends:
        _, _, out["anime_end"], out["anime_end_vol"] = max(ends)
    return out


def _rating(plain: str) -> dict[str, object]:
    """Bayesian average and number of votes from the User Rating text."""
    bayesian = _BAYESIAN.search(plain)
    votes = _VOTES.search(plain)
    return {
        "rating": bayesian.group(1) if bayesian else "",
        "votes": votes.group(1) if votes else "",
    }


def categories(page: str, key: int) -> list[dict[str, object]]:
    """Extract every category with its votes from the page data (the page shows only some).

    Parameters
    ----------
    page : str
        The whole page, scripts included.
    key : int
        The legacy ID.

    Returns
    -------
    list[dict[str, object]]
        Rows of the ``categories`` table, each category once.
    """
    rows: dict[str, dict[str, object]] = {}
    for raw, votes, plus, minus in _CATEGORY.findall(page):
        name = json_string(raw)
        if name not in rows:
            rows[name] = {
                "id": key,
                "category": name,
                "votes": votes,
                "votes_plus": plus,
                "votes_minus": minus,
            }
    return list(rows.values())


def _visible_categories(key: int, value: str) -> list[dict[str, object]]:
    """Return the categories shown on the page (fallback when the page data has none)."""
    return [
        {
            "id": key,
            "category": text(name),
            "votes": score,
            "votes_plus": plus,
            "votes_minus": minus,
        }
        for score, plus, minus, name in _VISIBLE_CATEGORY.findall(value)
    ]


def comments(body: str, key: int) -> list[dict[str, object]]:
    """Extract the user comments shown on the series page.

    Parameters
    ----------
    body : str
        The page without scripts.
    key : int
        The legacy ID.

    Returns
    -------
    list[dict[str, object]]
        Rows of the ``comments`` table (user, date, subject, text; the rating is always N/A).
    """
    rows: list[dict[str, object]] = []
    for chunk in _COMMENT.findall(body):
        content = _COMMENT_TEXT.search(chunk)
        if not content:
            continue

        rows.append(
            {
                "id": key,
                "comment_id": _first(_COMMENT_ID, chunk),
                "user": _first(_COMMENT_USER, chunk),
                "date": _first(_DATETIME, chunk),
                "subject": _first(_COMMENT_TITLE, chunk),
                "text": text(content.group(1)),
            }
        )
    return rows


def _first(pattern: re.Pattern[str], chunk: str) -> str:
    """Text of the first group of the first match, else ``""``."""
    m = pattern.search(chunk)
    return text(m.group(1)) if m else ""
