"""Everything specific to MangaUpdates: URLs, file names, response classes, links.

Series are enumerated by their legacy numeric ID: `series.html?id=N` answers 308 with the
canonical `/series/<base36>/<slug>` URL, which is then fetched (a second polite request).
A missing ID answers 307 to `/series`.

Series added since ~2022 have no legacy ID. They come from the series catalog
(`/series?year=Y&perpage=100&display=list&page=P&licensed=yes|no&type=T[&genre=G]`; robots.txt
allows these parameters, not `letter`/`orderby`). A direct request for page 31 or later of any
list answers 429 at once (the site's edge proxy, envoy: all 770 pages 31-100 of 11 lists, 18 Oct),
so a list shows at most MAX_PAGES = 30 pages (3 000 series). The lists are fixed in advance, none
depends on what a page shows (user, 19 Oct): every year x licensed x type (TYPES, no doujinshi),
and for the types in BY_GENRE also every genre (GENRES). Genres overlap, so a series can be on
several lists; it is fetched once. A list that still fills page 30 goes to problems; `status_lines`
checks that the genre lists cover their type list. Series of a catalog page that we don't have
yet are fetched by their base36 ID (`/series/<id>/<slug>`, one request). The ID (key) says what
a page is:

- legacy series ID: 1 .. ~205 000 (kind ``series``, ``raw/series/NNN/<id>.html``)
- catalog page (kind ``catalog_by_type``, one row per page in ``crawl/catalog_by_type.tsv``):
  CATALOG_KEY + ((((year - 2000) * 10 + licensed) * 100 + type) * 100 + genre) * 100 + page
  (licensed 1 yes, 2 no; type, genre: position in TYPES, GENRES from 1; genre 0 = none),
  ``raw/catalog_by_type/<year>-<yes|no>/<type>[/<genre>]/<page>.html``
- series by base36 ID: SERIES_KEY + int(base36, 36) (kind ``series_b36``,
  ``raw/series_b36/<first 2 chars>/<base36>.html``)

The saved catalog pages are the record of where the catalog crawl is: every start reads them again
(`found_on_start`), so nothing depends on the logs alone.

A failed catalog page is skipped like a failed series (`found_on_fail`): the next page is queued,
its 100 series are missing (problems/mangaupdates.md).
"""

import html
import re
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote_plus, urlsplit

import requests

from animanga.crawler.sites.base import Found, Step, text
from animanga.tsv import read_rows

NAME = "mangaupdates"
TITLE = "MangaUpdates"
BASE = "https://www.mangaupdates.com"
ROBOTS_URL = f"{BASE}/robots.txt"
SEED_MAX = 205_000  # legacy IDs: 200000 exists, 230000 is missing (27 Sep)
TAIL = 1000  # probe past the highest existing ID until this many in a row are missing
# no Crawl-delay in robots.txt; user (30 Sep): 1 s, watch errors.log for 403/429/503
MIN_DELAY = 1.0
JITTER = 0.2
# end-of-run recheck: errors only, not the ~26,000 missing legacy IDs (~11 h on every run; deleted
# or merged series, and new series have no legacy ID anyway). User, 18 Oct; ANN keeps all.
RECHECK = ("failed", "unexpected")
RENDER_HEADER = "x-envoy-upstream-service-time"
KINDS = ("series", "catalog_by_type", "series_b36")
LINK_KINDS = ("series", "author", "publisher", "group")

CATALOG_YEARS = range(2020, 2027)  # the legacy IDs have 7 864 series of 2020, 125 of 2022
LICENSED = ("yes", "no")
PER_PAGE = 100
MAX_PAGES = 30  # page 31+ of any list answers 429 (18 Oct)
# type= values of the catalog: the series types in our pages, lower case, without doujinshi (the
# index leaves it out, so its lists and series cost no request; user, 19 Oct). On 19 Oct (2024,
# licensed=no) the first 12 listed series, those of a known type all of that type; vietnamese ...
# german listed none (no such series, or a wrong value), russian was not tried. Never reorder,
# append only: the position is part of the page IDs
TYPES = (
    "manga", "manhwa", "manhua", "novel", "oel", "artbook", "indonesian", "thai", "french",
    "malaysian", "vietnamese", "filipino", "drama_cd", "nordic", "spanish", "german", "russian",
)  # fmt: skip
# types with more than 3 000 series in a year x licensed list, so also listed genre by genre:
# manga (licensed=no: 4 089 series of 2020 in the legacy IDs alone, Romance 44 % of them;
# licensed=yes 1 088, also by genre, so no list depends on a count we don't know). The type list
# stays: it has the series without a genre, and its first 3 000 check the genre lists
BY_GENRE = ("manga",)
# genre= values, as the site's own genre links write them (36 genres in our pages); append only
GENRES = (
    "Action", "Adult", "Adventure", "Comedy", "Doujinshi", "Drama", "Ecchi", "Fantasy",
    "Gender Bender", "Harem", "Hentai", "Historical", "Horror", "Josei", "Lolicon",
    "Martial Arts", "Mature", "Mecha", "Mystery", "Psychological", "Romance", "School Life",
    "Sci-fi", "Seinen", "Shotacon", "Shoujo", "Shoujo Ai", "Shounen", "Shounen Ai",
    "Slice of Life", "Smut", "Sports", "Supernatural", "Tragedy", "Yaoi", "Yuri",
)  # fmt: skip
CATALOG_KEY = 10**11  # above every legacy ID
SERIES_KEY = 10**12  # above every catalog key; 36**7 (all base36 IDs have 7 chars) < SERIES_KEY
TAIL_BELOW = CATALOG_KEY  # the tail probe is for legacy IDs only
TABLE = (
    "catalog_by_type",
    ["ts", "year", "licensed", "type", "genre", "page", "series", "last", "path"],
)

# one path segment after the ID, so /series/<id>/<slug>/-comment (robots.txt) never matches
SERIES_URL = re.compile(r"^https://www\.mangaupdates\.com/series/[0-9a-z]+(/[^/?#]*)?$")

# <a href="https://www.mangaupdates.com/author/abcd123/eiichiro-oda">Eiichiro Oda</a>
_LINK = re.compile(
    r'<a\s[^>]*?href="(?:https://www\.mangaupdates\.com)?/(series|author|publisher|group)/'
    r'([0-9a-z]+)(?:/[^"]*)?"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_CHALLENGE = re.compile(r"<title>\s*(Just a moment|Attention Required)", re.IGNORECASE)
_SERIES_ID = re.compile(r"^https://www\.mangaupdates\.com/series/([0-9a-z]{7})(?:/|$)")
# one row of the catalog list (the Next.js data in <script> escapes its quotes, so never matches):
# <a title="Click for Series Info" href="https://www.mangaupdates.com/series/4mip49m/24-ten-...">
_CATALOG_ROW = re.compile(
    r'<a title="Click for Series Info" href="(https://www\.mangaupdates\.com/series/'
    r'([0-9a-z]{7})/[^"]*)"'
)
# raw/catalog_by_type/2024-no/manga/012.html, .../2024-no/manga/slice-of-life/012.html
_CATALOG_FILE = re.compile(r"(\d{4})-(yes|no)/([a-z_]+)/(?:([a-z-]+)/)?(\d+)\.html$")


def genre_slug(genre: str) -> str:
    """Return the folder name of a genre: ``Slice of Life`` -> ``slice-of-life``.

    Parameters
    ----------
    genre : str
        One of `GENRES`.

    Returns
    -------
    str
        Lower case, spaces as ``-``.
    """
    return genre.lower().replace(" ", "-")


class CatalogPage(NamedTuple):
    """One page of a catalog list: year x licensed x type, maybe narrowed to a genre."""

    year: int
    licensed: str  # yes or no (licensed in English)
    series_type: str  # one of TYPES
    genre: str  # one of GENRES, or "" for all genres
    page: int  # from 1

    def list_name(self) -> str:
        """Return the list in words (problems, status): ``year 2024, licensed=no, type=manga``."""
        name = f"year {self.year}, licensed={self.licensed}, type={self.series_type}"
        return name + (f", genre={self.genre}" if self.genre else "")

    def url(self) -> str:
        """Return the URL (parameters in the order the site's own links use, ``Slice+of+Life``)."""
        url = (
            f"{BASE}/series?year={self.year}&perpage={PER_PAGE}&display=list&page={self.page}"
            f"&licensed={self.licensed}&type={self.series_type}"
        )
        return url + (f"&genre={quote_plus(self.genre)}" if self.genre else "")

    def key(self) -> int:
        """Return the ID (formula in the module docstring; inverse of `catalog_of_key`)."""
        lic = LICENSED.index(self.licensed) + 1
        kind = TYPES.index(self.series_type) + 1
        gen = GENRES.index(self.genre) + 1 if self.genre else 0
        inner = (((self.year - 2000) * 10 + lic) * 100 + kind) * 100 + gen
        return CATALOG_KEY + inner * 100 + self.page

    def path(self) -> Path:
        """Return the file: ``raw/catalog_by_type/2024-no/manga[/slice-of-life]/003.html``."""
        folder = Path("raw") / "catalog_by_type" / f"{self.year}-{self.licensed}"
        folder /= self.series_type
        if self.genre:
            folder /= genre_slug(self.genre)
        return folder / f"{self.page:03d}.html"


def catalog_lists() -> list[CatalogPage]:
    """Return page 1 of every catalog list, in crawl order (the order of their IDs).

    Returns
    -------
    list[CatalogPage]
        Every year x licensed x type; a type in BY_GENRE is followed by its genre lists.
    """
    return [
        CatalogPage(year, lic, t, g, 1)
        for year in CATALOG_YEARS
        for lic in LICENSED
        for t in TYPES
        for g in (("", *GENRES) if t in BY_GENRE else ("",))
    ]


def catalog_of_key(key: int) -> CatalogPage:
    """Return the list and page of a catalog page ID (inverse of `CatalogPage.key`).

    Parameters
    ----------
    key : int
        A catalog page ID.

    Returns
    -------
    CatalogPage
        Year, ``yes`` or ``no``, type, genre (``""``: all genres), page.
    """
    rest, page = divmod(key - CATALOG_KEY, 100)
    rest, gen = divmod(rest, 100)
    rest, kind = divmod(rest, 100)
    year, lic = divmod(rest, 10)
    genre = GENRES[gen - 1] if gen else ""
    return CatalogPage(2000 + year, LICENSED[lic - 1], TYPES[kind - 1], genre, page)


# robots.txt must allow every URL pattern we request: legacy ID, its redirect target, a type
# list, a genre list (checked at start, else the crawl does not start)
SAMPLE_URLS = (
    f"{BASE}/series.html?id=1",
    f"{BASE}/series/tvb7av1/vampire-lovers",
    CatalogPage(2024, "no", "manga", "", 1).url(),
    CatalogPage(2024, "no", "manga", "Slice of Life", 1).url(),
)


def series_key(base36: str) -> int:
    """Return the ID of a series known by its base36 ID.

    Parameters
    ----------
    base36 : str
        The 7-character ID of ``/series/<base36>/<slug>`` (may start with 0).

    Returns
    -------
    int
        ``SERIES_KEY + int(base36, 36)``.
    """
    return SERIES_KEY + int(base36, 36)


def base36_of_key(key: int) -> str:
    """Return the base36 ID of a series ID (inverse of `series_key`, leading zeros kept).

    Parameters
    ----------
    key : int
        A series ID from `series_key`.

    Returns
    -------
    str
        The 7-character base36 ID.
    """
    n = key - SERIES_KEY
    digits = ""
    while n:
        n, d = divmod(n, 36)
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[d] + digits
    return digits.rjust(7, "0")


def kind_of_key(key: int) -> str:
    """Return what an ID is: legacy series, catalog page or series by base36 ID.

    Parameters
    ----------
    key : int
        Any ID of this site.

    Returns
    -------
    str
        One of `KINDS`.
    """
    if key >= SERIES_KEY:
        return "series_b36"
    if key >= CATALOG_KEY:
        return "catalog_by_type"
    return "series"


def url_for(key: int, kind: str = "series") -> str:
    """Return the URL fetched for an ID.

    Parameters
    ----------
    key : int
        The ID; its range decides the kind (`kind_of_key`).
    kind : str
        Unused: the ID says it.

    Returns
    -------
    str
        Legacy ``series.html?id=N`` (answers 308 to the canonical URL), a catalog page, or
        ``/series/<base36>`` (the crawler uses the URL with the slug from the catalog instead).
    """
    match kind_of_key(key):
        case "catalog_by_type":
            return catalog_of_key(key).url()
        case "series_b36":
            return f"{BASE}/series/{base36_of_key(key)}"
    return f"{BASE}/series.html?id={key}"


def raw_path(key: int, kind: str = "series") -> Path:
    """Return where the page of an ID is stored, relative to the site's data folder.

    Parameters
    ----------
    key : int
        The ID; its range decides the kind (`kind_of_key`).
    kind : str
        Unused: the ID says it.

    Returns
    -------
    Path
        ``raw/series/<thousands>/<key>.html``, ``raw/catalog_by_type/...`` (`CatalogPage.path`)
        or ``raw/series_b36/<first 2 chars>/<base36>.html``.
    """
    match kind_of_key(key):
        case "catalog_by_type":
            return catalog_of_key(key).path()
        case "series_b36":
            b36 = base36_of_key(key)
            return Path("raw") / "series_b36" / b36[:2] / f"{b36}.html"
    return Path("raw") / "series" / f"{key // 1000:03d}" / f"{key}.html"


def kind_of_url(url: str) -> str:
    """Return the kind of page a URL points to.

    Parameters
    ----------
    url : str
        A URL of this site.

    Returns
    -------
    str
        ``catalog_by_type`` for a catalog page, else ``series`` (a legacy ID ends at its base36
        URL, so the kind of an ID comes from `kind_of_key`, not from its URL).
    """
    return "catalog_by_type" if urlsplit(url).path == "/series" else "series"


def key_of_url(url: str) -> int | None:
    """Return the ID of the series a saved page's URL stands for.

    A legacy ID's page is saved from ``/series/<base36>/<slug>``: that series is not fetched again
    by its base36 ID.

    Parameters
    ----------
    url : str
        The URL a page was saved from.

    Returns
    -------
    int | None
        `series_key` of the base36 ID, or None for other URLs.
    """
    m = _SERIES_ID.match(url)
    return series_key(m.group(1)) if m else None


def canonical(href: str) -> str:
    """Make a link absolute: https, www, without fragment, `&amp;` decoded.

    Parameters
    ----------
    href : str
        An ``href`` value as found in the HTML (relative, protocol-relative or absolute).

    Returns
    -------
    str
        The canonical URL.
    """
    url = html.unescape(href.strip()).split("#", 1)[0]

    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = BASE + url

    return url.replace("http://", "https://", 1).replace("://mangaupdates", "://www.mangaupdates")


def classify(key: int, resp: requests.Response) -> Step:
    """Decide what to do with a response.

    308 to ``/series/<base36>/<slug>`` is followed (action ``follow``); 307 to ``/series`` means
    the ID is missing. Bot challenges and 403/429/503 are retried later, never bypassed.

    Parameters
    ----------
    key : int
        The ID that was requested.
    resp : requests.Response
        The response, redirects not followed.

    Returns
    -------
    Step
        What the crawler does next.
    """
    status = resp.status_code
    if resp.headers.get("cf-mitigated") or (status in (403, 503) and _CHALLENGE.search(resp.text)):
        return Step("retry", "challenge", note=f"HTTP {status}, bot challenge")

    if status == 200:
        if _CHALLENGE.search(resp.text[:5000]):
            return Step("retry", "challenge", note="HTTP 200 with a challenge page")
        return Step("save", "saved")

    if status in (301, 302, 303, 307, 308):
        target = canonical(resp.headers.get("location", ""))
        if urlsplit(target).path.rstrip("/") == "/series":
            return Step("final", "missing", note="redirect to /series")
        if SERIES_URL.match(target):
            return Step("follow", "redirect", note=target, url=target)
        return Step("final", "redirect_other", note=target)

    if status in (404, 410):
        return Step("final", "missing")
    if status in (403, 429, 503):  # refusal: wait (core retry rules), never push through it
        return Step("retry", "blocked", note=f"HTTP {status}")
    if status >= 500:
        return Step("retry", "retry", note=f"HTTP {status}")
    return Step("final", "unexpected", note=f"HTTP {status}")


def extract_links(page: str) -> list[tuple[str, str, str]]:
    """Find links to series, authors, publishers and groups.

    Parameters
    ----------
    page : str
        A whole HTML page.

    Returns
    -------
    list[tuple[str, str, str]]
        (kind, base36 id, anchor text), unique, non-empty anchor, in page order.
    """
    seen: set[tuple[str, str, str]] = set()
    out = []

    for kind, ident, anchor in _LINK.findall(page):
        item = (kind.lower(), ident, text(anchor))
        if item not in seen and item[2]:
            seen.add(item)
            out.append(item)

    return out


def discovered_keys(links: list[tuple[str, str, str]]) -> list[tuple[str, int]]:
    """Pick the links that add IDs to the crawl: none.

    Links use the new base36 IDs, not legacy IDs, so they add nothing to the ID scan.

    Parameters
    ----------
    links : list[tuple[str, str, str]]
        Output of `extract_links` (unused).

    Returns
    -------
    list[tuple[str, int]]
        Always empty.
    """
    return []


def catalog_series(page: str) -> list[tuple[str, str]]:
    """Return the series listed on a catalog page.

    Parameters
    ----------
    page : str
        A whole catalog page.

    Returns
    -------
    list[tuple[str, str]]
        (base36 ID, URL with slug), unique, in page order.
    """
    seen: dict[str, str] = {}
    for url, b36 in _CATALOG_ROW.findall(page):
        seen.setdefault(b36, html.unescape(url))
    return list(seen.items())


def _row(c: CatalogPage, series: object, last: int, path: str) -> dict[str, object]:
    """Return the catalog_by_type.tsv row of a page (``series`` and ``path`` empty: failed)."""
    return {
        "year": c.year,
        "licensed": c.licensed,
        "type": c.series_type,
        "genre": c.genre,
        "page": c.page,
        "series": series,
        "last": last,
        "path": path,
    }


def _next_page(c: CatalogPage) -> tuple[str, int, str]:
    """Return the next page of the same list, as a key to queue."""
    return ("catalog_by_type", c._replace(page=c.page + 1).key(), "")


def found_on_page(key: int, kind: str, page: str) -> Found:
    """Return what a saved catalog page leads to: its series, the next page, its table row.

    A full page (PER_PAGE series) has a next page, up to MAX_PAGES. A list that fills page
    MAX_PAGES goes to problems (the site shows no more), unless it is the type list of a type in
    BY_GENRE (its genre lists have the rest). An empty page 1 is a problem only for such a type
    list (manga has series in every year): a smaller type can have none.

    Parameters
    ----------
    key : int
        The ID of the saved page.
    kind : str
        Its kind; only ``catalog_by_type`` pages lead anywhere.
    page : str
        The saved page.

    Returns
    -------
    Found
        Series as ``series_b36`` with their URL, the next page, one row for catalog_by_type.tsv
        (``last`` 1: the list ends here).
    """
    if kind != "catalog_by_type":
        return Found()

    c = catalog_of_key(key)
    series = catalog_series(page)
    full = len(series) >= PER_PAGE
    split = c.series_type in BY_GENRE and not c.genre

    keys = [("series_b36", series_key(b36), url) for b36, url in series]
    problem = ""
    if full and c.page < MAX_PAGES:
        keys.append(_next_page(c))
    elif full and not split:
        problem = (
            f"catalog {c.list_name()} fills all {MAX_PAGES} pages: the site shows no more, so its "
            f"series past {MAX_PAGES * PER_PAGE} are missing"
            + ("." if c.genre else " (list this type by genre too: BY_GENRE).")
        )
    elif c.page == 1 and not series and split:
        problem = f"catalog {c.list_name()}: page 1 lists no series (page changed?)."

    row = _row(c, len(series), 0 if full and c.page < MAX_PAGES else 1, c.path().as_posix())
    return Found(keys, [row], problem)


def found_on_fail(data: Path, key: int, kind: str) -> Found:
    """Return what to do when a catalog page failed: go on with the next page.

    A list ends only at a saved page with fewer than `PER_PAGE` series or at page `MAX_PAGES`
    (user, 18 Oct). Each failed page costs 2 tries and a health check.

    Parameters
    ----------
    data : Path
        The site's data folder.
    key : int
        The failed ID.
    kind : str
        Its kind; only ``catalog_by_type`` pages are skipped this way.

    Returns
    -------
    Found
        The next page (none after page MAX_PAGES); a table row for the failed page (``series``
        and ``path`` empty) and a problem, unless the table has that row already (a recheck, a
        restart).
    """
    if kind != "catalog_by_type":
        return Found()

    c = catalog_of_key(key)
    first = (c.page - 1) * PER_PAGE + 1
    missing = (
        f"catalog {c.list_name()}: page {c.page} failed, so series {first}-{first + PER_PAGE - 1}"
        " of this list are missing"
    )
    if c.page < MAX_PAGES:
        found = Found(
            [_next_page(c)], [_row(c, "", 0, "")], f"{missing}; went on with page {c.page + 1}."
        )
    else:
        found = Found([], [_row(c, "", 1, "")], f"{missing}; it is the last page.")

    logged = {
        (r["year"], r["licensed"], r["type"], r["genre"], r["page"])
        for r in read_rows(data / "crawl" / f"{TABLE[0]}.tsv")
        if not r["path"]
    }
    if (str(c.year), c.licensed, c.series_type, c.genre, str(c.page)) in logged:
        found.rows, found.problem = [], ""

    return found


def found_on_start(data: Path) -> Found:
    """Return page 1 of every catalog list and what the saved catalog pages lead to.

    The saved pages are the record: a page saved just before a crash (log rows lost) still
    queues its series and the next page, and gets its catalog_by_type.tsv row if that is missing.

    Parameters
    ----------
    data : Path
        The site's data folder.

    Returns
    -------
    Found
        Keys to queue (duplicates are skipped by the crawler) and the missing table rows.
    """
    found = Found([("catalog_by_type", c.key(), "") for c in catalog_lists()])
    logged = {r["path"] for r in read_rows(data / "crawl" / f"{TABLE[0]}.tsv")}
    genres = {genre_slug(g): g for g in GENRES}

    for path in sorted((data / "raw" / "catalog_by_type").rglob("*.html")):
        m = _CATALOG_FILE.search(path.as_posix())
        if not m:
            continue
        year, licensed, series_type, slug, number = m.groups()
        if series_type not in TYPES or (slug and slug not in genres):
            continue

        c = CatalogPage(int(year), licensed, series_type, genres[slug] if slug else "", int(number))
        page = path.read_text(encoding="utf-8", errors="replace")
        saved = found_on_page(c.key(), "catalog_by_type", page)
        found.keys.extend(saved.keys)
        found.rows.extend(r for r in saved.rows if r["path"] not in logged)

    return found


class _ListState(NamedTuple):
    """How far one list is, from its catalog_by_type.tsv rows."""

    done: bool  # a row with last = 1: a short page or page MAX_PAGES (saved or failed)
    pages: int  # saved pages
    failed: list[int]  # failed pages, not saved since
    full: bool  # page MAX_PAGES saved full: the list may have more series than the site shows


def _list_state(rows: list[dict[str, str]]) -> _ListState:
    """Return the state of one list from its rows (none: not started)."""
    saved = {int(r["page"]): int(r["series"]) for r in rows if r["path"]}
    failed = sorted({int(r["page"]) for r in rows if not r["path"]} - set(saved))
    full = saved.get(MAX_PAGES, 0) >= PER_PAGE
    return _ListState(any(r["last"] == "1" for r in rows), len(saved), failed, full)


def _list_series(data: Path, rows: list[dict[str, str]]) -> set[str]:
    """Return the base36 IDs on the saved pages of one list (read from raw/)."""
    paths = {r["path"] for r in rows if r["path"]}
    series: set[str] = set()
    for path in paths:
        if (data / path).exists():
            page = (data / path).read_text(encoding="utf-8", errors="replace")
            series.update(b36 for b36, _ in catalog_series(page))
    return series


def status_lines(data: Path) -> list[str]:
    """Describe the catalog crawl for `crawl --status`: lists done, pages and series.

    Per year x licensed one line for the type lists and one per type in BY_GENRE for its genre
    lists, with how many series of the type list (its first 3 000) the genre lists have: all,
    unless a genre value is wrong or a series has no genre. Then the lists that fill page
    MAX_PAGES without genre lists below them, and the failed pages. Reads the saved catalog
    pages (a few seconds).

    Parameters
    ----------
    data : Path
        The site's data folder.

    Returns
    -------
    list[str]
        The lines to print.
    """
    lists: dict[tuple[int, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_rows(data / "crawl" / f"{TABLE[0]}.tsv"):
        lists[(int(row["year"]), row["licensed"], row["type"], row["genre"])].append(row)
    series = {name: _list_series(data, rows) for name, rows in lists.items()}

    lines = [
        f"catalog         : {TABLE[0]}.tsv, {CATALOG_YEARS[0]}-{CATALOG_YEARS[-1]} x licensed x "
        f"{len(TYPES)} types (no doujinshi), {', '.join(BY_GENRE)} also by {len(GENRES)} genres"
    ]
    full: list[str] = []
    failed: list[str] = []
    everything: set[str] = set()
    for year in CATALOG_YEARS:
        for lic in LICENSED:
            groups = [("types", [(year, lic, t, "") for t in TYPES])]
            groups += [(f"{t} by genre", [(year, lic, t, g) for g in GENRES]) for t in BY_GENRE]

            for label, names in groups:
                states = [_list_state(lists.get(name, [])) for name in names]
                found = set().union(*(series.get(name, set()) for name in names))
                everything |= found

                head = f"{year} {lic}" if label == "types" else ""
                line = (
                    f"  {head:9}{label:15}: {sum(s.done for s in states):3} of {len(names):2} "
                    f"lists done, {sum(s.pages for s in states):4} pages, {len(found):5} series"
                )
                if label != "types":
                    whole = series.get((year, lic, label.split()[0], ""), set())
                    line += f"; {len(whole & found)} of the {len(whole)} on the type list"
                lines.append(line)

                for (_, _, t, g), s in zip(names, states, strict=True):
                    name = " ".join(filter(None, (f"{year} {lic}", t, g)))
                    if s.full and (g or t not in BY_GENRE):
                        full.append(name)
                    failed.extend(f"{name} page {p}" for p in s.failed)

    more = f" (series past {MAX_PAGES * PER_PAGE} are missing)" if full else ""
    lines.append(f"  full at page {MAX_PAGES}: {', '.join(full) or 'none'}{more}")
    shown = ", ".join(failed[:10]) + (f" and {len(failed) - 10} more" if len(failed) > 10 else "")
    lines.append(f"  failed pages    : {shown or 'none'}")
    lines.append(f"  catalog series  : {len(everything)} different")
    return lines
