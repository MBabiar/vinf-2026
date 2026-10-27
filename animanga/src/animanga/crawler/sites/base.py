"""What every site module shares: the Step returned by `classify` and small text helpers.

A site module defines: NAME, TITLE, BASE, ROBOTS_URL, SEED_MAX, TAIL, RENDER_HEADER, KINDS (the
first one is the default kind of an ID), LINK_KINDS, SAMPLE_URLS (one URL of every pattern the
crawl requests; robots.txt must allow all of them, else the crawl does not start), and the
functions url_for, raw_path, kind_of_url, classify, extract_links, discovered_keys.
Optional: MIN_DELAY and JITTER (s) override the defaults in config.py for this site; RECHECK
(outcomes requested again at the end of a run) overrides `core.RECHECK`.

Optional for IDs that are not one numeric range (MangaUpdates: legacy IDs, catalog pages, series
by base36 ID): TAIL_BELOW (the tail probe only looks at IDs below it), kind_of_key (the kind is
a function of the ID), key_of_url (the ID a saved page stands for, so it is not fetched twice),
found_on_page and found_on_start (IDs and table rows that saved pages lead to, as `Found`),
found_on_fail (what to queue instead of a failed page), status_lines (extra lines for
``crawl --status``) and TABLE (name and columns of the table those rows go to,
``crawl/<name>.tsv``).
"""

import html
import re
from dataclasses import dataclass, field

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass
class Step:
    """What to do with one HTTP response.

    Attributes
    ----------
    action : str
        ``save``: store the page; ``final``: record `outcome`, done; ``retry``: back off and try
        again; ``stop``: end the crawl; ``follow``: fetch `url` for the same ID (a redirect hop);
        ``switch``: the ID is of kind `outcome`, fetch it again with that kind's URL.
    outcome : str
        The outcome written to fetch_log.tsv (e.g. ``saved``, ``missing``, ``blocked``).
    new_keys : list[int]
        IDs discovered by this response (e.g. the target of an alias).
    note : str
        Free text for the log (status, redirect target).
    new_kind : str
        Kind of `new_keys`; ``""`` means the site's default kind.
    url : str
        The URL to fetch next for action ``follow``.
    """

    action: str
    outcome: str
    new_keys: list[int] = field(default_factory=list)
    note: str = ""
    new_kind: str = ""  # kind of new_keys; "" means the site's default kind
    url: str = ""


@dataclass
class Found:
    """What saved pages lead to, beyond their links (site hooks found_on_page, found_on_start).

    Attributes
    ----------
    keys : list[tuple[str, int, str]]
        (kind, ID, URL) to queue; URL ``""`` means ``url_for(ID, kind)``. IDs already queued or
        saved are skipped by the crawler.
    rows : list[dict[str, object]]
        Rows for the site's TABLE (the crawler adds ``ts``).
    problem : str
        Written to problems/<site>.md if not empty.
    """

    keys: list[tuple[str, int, str]] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)
    problem: str = ""


def text(fragment: str) -> str:
    """Turn an HTML fragment into plain text on one line.

    Parameters
    ----------
    fragment : str
        HTML; tags are dropped, entities decoded, whitespace collapsed.

    Returns
    -------
    str
        The text, stripped.
    """
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()


def page_title(page: str) -> str:
    """Return the page's ``<title>`` as plain text.

    Parameters
    ----------
    page : str
        A whole HTML page.

    Returns
    -------
    str
        The title, or ``""`` if the page has none.
    """
    m = _TITLE.search(page)
    return text(m.group(1)) if m else ""
