"""Text normalisation shared by the join (title and person keys) and the index (tokens).

Everything is folded the same way: Unicode NFKD, combining marks dropped (Shōji -> Shoji), lower
case. Non-Latin scripts (Japanese, Korean, Chinese) fold to nothing and drop out, which is what we
want: the index and the join work on English and romanised text only.
"""

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")
_PAREN_TAIL = re.compile(r"\s*\([^()]*\)\s*$")  # "Claymore (Novel)", "Bebop (Japanese)"
_LONG_VOWEL = re.compile(r"ou|oo|uu")

# A short English stop list of our own (no NLTK): function words that occur in nearly every
# plot summary or description and never decide a query.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "has",
        "have", "he", "her", "his", "i", "in", "into", "is", "it", "its", "of", "on", "or", "she",
        "so", "than", "that", "the", "their", "them", "they", "this", "to", "was", "were",
        "which", "while", "who", "will", "with",
    }
)  # fmt: skip


def fold(value: str) -> str:
    """Return `value` in lower case without diacritics.

    Parameters
    ----------
    value : str
        Any text.

    Returns
    -------
    str
        NFKD-decomposed text without combining marks, lower case (``Shōji`` -> ``shoji``;
        full-width letters become plain ones).
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def tokens(value: str) -> list[str]:
    """Split text into index terms.

    Parameters
    ----------
    value : str
        Any text.

    Returns
    -------
    list[str]
        The ``[a-z0-9]+`` runs of the folded text, without `STOPWORDS`, in order (no stemming).
    """
    return [t for t in _WORD.findall(fold(value)) if t not in STOPWORDS]


def title_key(title: str) -> str:
    """Return the key two titles of the same work share.

    Parameters
    ----------
    title : str
        A title: ``Claymore``, ``Shingeki no Kyojin (Novel)``, ``Ōkami to Kōshinryō``.

    Returns
    -------
    str
        Trailing parentheses removed, folded, only letters and digits kept, long vowels
        ``ou``/``oo``/``uu`` shortened as in `person_key` (``Ōkami to Kōshinryō`` and ``Ookami to
        Koushinryou`` -> ``okamitokoshinryo``); ``""`` if fewer than 4 characters remain (too
        short to trust).
    """
    while True:
        shorter = _PAREN_TAIL.sub("", title)
        if shorter == title or not shorter:
            break
        title = shorter

    key = _LONG_VOWEL.sub(lambda m: m.group(0)[0], "".join(_WORD.findall(fold(title))))
    return key if len(key) >= 4 else ""


def person_key(name: str) -> str:
    """Return the key two spellings of the same person share.

    ANN writes ``Norihiro Yagi`` / ``Shōji Kawamori``, MangaUpdates ``YAGI Norihiro`` / ``KAWAMORI
    Shouji``: folded, long vowels ``ou``/``oo``/``uu`` shortened, split on anything but letters
    and digits (also ``-``: ``Koge-Donbo``), the parts sorted.

    Parameters
    ----------
    name : str
        A person's name as either site writes it.

    Returns
    -------
    str
        The sorted parts joined by spaces (``norihiro yagi``); ``""`` for a name without Latin
        letters.
    """
    parts = (_LONG_VOWEL.sub(lambda m: m.group(0)[0], w) for w in _WORD.findall(fold(name)))
    return " ".join(sorted(parts))
