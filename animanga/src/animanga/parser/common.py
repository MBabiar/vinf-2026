"""Text helpers shared by the site parsers: HTML fragment -> plain text, years, JSON strings."""

import html
import json
import re

_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)  # React puts <!-- --> between text nodes
# inline tags vanish ("<i>Bebop</i>'s" -> "Bebop's"), every other tag is a word break
_INLINE = re.compile(
    r"</?(?:a|b|i|u|em|strong|span|cite|small|nobr|font|sup|sub|abbr|time)\b[^>]*>", re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def text(fragment: str) -> str:
    """Turn an HTML fragment into plain text on one line.

    Parameters
    ----------
    fragment : str
        HTML; scripts, styles and comments are dropped, inline tags removed, other tags become a
        space, entities are decoded and whitespace collapsed.

    Returns
    -------
    str
        The text, stripped.
    """
    fragment = _COMMENT.sub("", _SCRIPT.sub(" ", fragment))
    fragment = _TAG.sub(" ", _INLINE.sub("", fragment))
    return _SPACE.sub(" ", html.unescape(fragment)).strip()


def drop_scripts(page: str) -> str:
    """Remove ``<script>``/``<style>`` blocks and HTML comments from a page.

    Parameters
    ----------
    page : str
        A whole HTML page.

    Returns
    -------
    str
        The page without them (on MangaUpdates about a quarter of the bytes remains).
    """
    return _COMMENT.sub("", _SCRIPT.sub(" ", page))


def unparen(value: str) -> str:
    """Strip one pair of surrounding parentheses: ``"(eps 1-3)"`` -> ``"eps 1-3"``.

    Parameters
    ----------
    value : str
        Plain text.

    Returns
    -------
    str
        The text without the outer parentheses, stripped.
    """
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    return value.strip()


def first_year(values: list[str]) -> str:
    """Return the earliest year (1800-2099) named in any of the values.

    Parameters
    ----------
    values : list[str]
        Plain texts such as ``"1998-04-03 to 1998-06-19 (first run)"``.

    Returns
    -------
    str
        The year as four digits, or ``""`` if none is named.
    """
    years = [int(m.group(1)) for v in values for m in _YEAR.finditer(v)]
    return str(min(years)) if years else ""


def json_string(raw: str) -> str:
    r"""Decode a string taken from JSON that is itself inside a JavaScript string.

    Parameters
    ----------
    raw : str
        The characters between the escaped quotes, e.g. ``Protagonist\\u0027s``.

    Returns
    -------
    str
        The decoded string; `raw` itself if it has no escapes or does not decode.
    """
    if "\\" not in raw:
        return raw

    try:
        return json.loads('"' + json.loads('"' + raw + '"') + '"')
    except ValueError:
        return raw
