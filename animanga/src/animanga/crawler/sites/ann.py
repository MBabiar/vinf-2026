"""Everything specific to Anime News Network: URLs, file names, response classes, links.

Anime and manga share one ID space: `anime.php?id=N` of a manga answers 302 to `manga.php?id=N`
(Step "switch"), and the manga page is fetched next.
"""

import html
import re
from pathlib import Path

import requests

from animanga.crawler.sites.base import Step, text

NAME = "ann"
TITLE = "ANN"
BASE = "https://www.animenewsnetwork.com"
ROBOTS_URL = f"{BASE}/robots.txt"
SEED_MAX = 41_000  # anime and manga share one ID space; 40000 exists, 42000 is 404 (27 Sep)
TAIL = 1000  # probe past the highest existing ID until this many in a row are missing
# robots.txt Crawl-delay: 2; user (18 Oct): 2 s + 0-2 s (before: 3 s + 0-2 s)
MIN_DELAY = 2.0
JITTER = 2.0
RENDER_HEADER = "x-render-time"
KINDS = ("anime", "manga")  # an ID is either an anime or a manga page; anime is tried first
LINK_KINDS = ("anime", "manga", "people", "company")
# every URL pattern we request; robots.txt must allow them (checked before crawling)
SAMPLE_URLS = (f"{BASE}/encyclopedia/anime.php?id=1", f"{BASE}/encyclopedia/manga.php?id=1")

ANIME_URL = re.compile(r"^https://www\.animenewsnetwork\.com/encyclopedia/anime\.php\?id=(\d+)$")
MANGA_URL = re.compile(r"^https://www\.animenewsnetwork\.com/encyclopedia/manga\.php\?id=(\d+)$")

# e.g. <a href="people.php?id=774">Shinichirō Watanabe</a>
#      <a href="/encyclopedia/anime.php?id=353">Cowboy Bebop: The Movie</a>
_LINK = re.compile(
    r'<a\s[^>]*?href="(?:(?:https?:)?//www\.animenewsnetwork\.com)?(?:/encyclopedia/)?'
    r'(anime|manga|people|company)\.php\?id=(\d+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_CHALLENGE = re.compile(r"<title>\s*Just a moment", re.IGNORECASE)


def url_for(key: int, kind: str = "anime") -> str:
    """Return the URL fetched for an ID.

    Parameters
    ----------
    key : int
        The ID.
    kind : str
        One of `KINDS`.

    Returns
    -------
    str
        The absolute URL.
    """
    return f"{BASE}/encyclopedia/{kind}.php?id={key}"


def raw_path(key: int, kind: str = "anime") -> Path:
    """Return where the page of an ID is stored, relative to the site's data folder.

    Parameters
    ----------
    key : int
        The ID.
    kind : str
        One of `KINDS`.

    Returns
    -------
    Path
        ``raw/<kind>/<thousands>/<key>.html``.
    """
    return Path("raw") / kind / f"{key // 1000:03d}" / f"{key}.html"


def kind_of_url(url: str) -> str:
    """Return the kind of page a URL points to.

    Parameters
    ----------
    url : str
        A URL of this site.

    Returns
    -------
    str
        One of `KINDS`.
    """
    return "manga" if "/manga.php" in url else "anime"


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
    elif not url.startswith("http"):
        url = f"{BASE}/encyclopedia/{url}"

    return url.replace("http://", "https://", 1).replace(
        "://animenewsnetwork", "://www.animenewsnetwork"
    )


def classify(key: int, resp: requests.Response) -> Step:
    """Decide what to do with a response.

    Outcomes ``manga`` / ``anime`` (action ``switch``) mean: this ID is the other kind, fetch it
    again with that URL. Cloudflare challenges and 403/429/503 are retried later, never bypassed.

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
        return Step("retry", "challenge", note=f"HTTP {status}, Cloudflare challenge")

    if status == 200:
        if _CHALLENGE.search(resp.text[:5000]):
            return Step("retry", "challenge", note="HTTP 200 with a challenge page")
        return Step("save", "saved")

    if status in (301, 302, 303, 307, 308):
        target = canonical(resp.headers.get("location", ""))
        for kind, pattern in (("anime", ANIME_URL), ("manga", MANGA_URL)):
            if m := pattern.match(target):
                other = int(m.group(1))
                if other == key:
                    return Step("switch", kind, note=target)
                return Step("final", "alias", [other], f"alias of {kind} {other}", kind)
        return Step("final", "redirect_other", note=target)

    if status in (404, 410):
        return Step("final", "missing")
    if status in (403, 429, 503):  # refusal: wait (core retry rules), never push through it
        return Step("retry", "blocked", note=f"HTTP {status}")
    if status >= 500:
        return Step("retry", "retry", note=f"HTTP {status}")
    return Step("final", "unexpected", note=f"HTTP {status}")


def extract_links(page: str) -> list[tuple[str, int, str]]:
    """Find the encyclopedia links of a page.

    Parameters
    ----------
    page : str
        A whole HTML page.

    Returns
    -------
    list[tuple[str, int, str]]
        (kind, id, anchor text), unique within the page, in page order.
    """
    seen: set[tuple[str, int, str]] = set()
    out = []

    for kind, ident, anchor in _LINK.findall(page):
        item = (kind.lower(), int(ident), text(anchor))
        if item not in seen:
            seen.add(item)
            out.append(item)

    return out


def discovered_keys(links: list[tuple[str, int, str]]) -> list[tuple[str, int]]:
    """Pick the links that add IDs to the crawl.

    Only anime and manga pages; the people/company links only go to links.tsv.

    Parameters
    ----------
    links : list[tuple[str, int, str]]
        Output of `extract_links`.

    Returns
    -------
    list[tuple[str, int]]
        Sorted, unique (kind, id) pairs.
    """
    return sorted({(kind, ident) for kind, ident, _ in links if kind in KINDS})
