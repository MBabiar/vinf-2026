"""Console script `index`: documents -> our own TF index on disk (``data/index/``).

The index stores term frequencies only; the IDF is applied at query time (`search`), so the one
index serves both IDF variants. Files (JSON, no database):

- ``docs.jsonl``: one line per document, ``{"n", "id", "title", "type", "year", "tokens",
  "norm", "file", "offset", "length"}``; ``n`` is the document number the postings use, ``norm``
  the length of its weight vector ``sqrt(sum (1 + log10 tf)²)``; ``file``, ``offset`` and
  ``length`` (bytes) point to the whole document in ``data/docs/``, so a search reads only its
  hits;
- ``postings.jsonl``: one line per term, sorted by term, ``{"term", "df", "postings": [[n, tf],
  ...]}`` with ascending document numbers;
- ``terms.json``: the dictionary, ``{term: {"df", "offset", "length"}}``; offset and length (bytes)
  point to the term's line in ``postings.jsonl``, so a search reads only its terms' lines.

The whole index is built in memory in one pass and written at the end (~230 thousand documents);
every run rebuilds it from ``data/docs/``.
"""

import argparse
import json
import math
import re
import time
from array import array
from collections import Counter
from collections.abc import Iterator

from animanga import DATA_DIR
from animanga.docs.run import DOCS_DIR, FILES
from animanga.normalize import tokens

INDEX_DIR = DATA_DIR / "index"

# Anime staff in the index: the main credits only. A TV series credits hundreds of key animators,
# in-betweeners and painters (Cowboy Bebop: 333 staff entries); their names made long documents
# whose vector length buried the title (the series ranked 56th for "cowboy bebop"). Manga and MU
# documents keep all their staff (a few authors).
MAIN_ROLE = re.compile(
    r"director|script|screenplay|series composition|original|creator|character design|music|"
    r"composer|mechanical design|producer|planning|author|\bart\b|story",
    re.IGNORECASE,
)
MINOR_ROLE = re.compile(
    r"assistant|animation director|episode|unit director|photography|theme song|storyboard|"
    r"sound effects|background",
    re.IGNORECASE,
)


def main_credit(role: str) -> bool:
    """Return True for an anime staff role that goes into the index (`MAIN_ROLE`, not minor).

    Parameters
    ----------
    role : str
        The role as ANN writes it: ``Series Director``, ``Key Animation``.

    Returns
    -------
    bool
        ``Series Director`` -> True, ``Key Animation`` / ``Episode Director`` -> False.
    """
    return bool(MAIN_ROLE.search(role)) and not MINOR_ROLE.search(role)


def index_text(doc: dict) -> str:
    """Return the text of a document that goes into the index (v1).

    Titles, type, year, genres and themes, plot or description, staff (of an anime only the main
    credits, `main_credit`) and companies with their roles. Not (yet): MU user comments,
    categories and ANN article headlines (wait for an analysis), cast, ratings and statistics.

    Parameters
    ----------
    doc : dict
        A document of ``data/docs/``.

    Returns
    -------
    str
        One text, fields separated by new lines.
    """
    parts = [t["title"] for t in doc["titles"]] or [doc["title"]]
    parts += [doc["type"], str(doc["year"]), *doc["genres"], *doc["themes"], doc["text"]]
    anime = doc["kind"] == "anime"
    parts += [
        f"{s['role']} {s['name']}" for s in doc["staff"] if not anime or main_credit(s["role"])
    ]
    parts += [f"{c['role']} {c['name']}" for c in doc["companies"]]
    return "\n".join(p for p in parts if p)


def documents() -> Iterator[tuple[dict, str, int, int]]:
    """Yield every document, ANN anime, ANN manga, then MangaUpdates, with its place on disk.

    Yields
    ------
    tuple[dict, str, int, int]
        The document, its file in ``data/docs/``, the byte offset and length of its line.
    """
    for name in FILES:
        offset = 0
        with (DOCS_DIR / f"{name}.jsonl").open("rb") as f:
            for line in f:
                yield json.loads(line), f"{name}.jsonl", offset, len(line)
                offset += len(line)


def build() -> dict[str, int]:
    """Build the index into `INDEX_DIR`.

    Returns
    -------
    dict[str, int]
        Documents, terms, postings and tokens.
    """
    postings: dict[str, array] = {}  # term -> doc, tf, doc, tf, ... (unsigned ints)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    total = 0

    with (INDEX_DIR / "docs.jsonl.part").open("w", encoding="utf-8", newline="\n") as docs:
        n = -1
        for n, (doc, file, offset, length) in enumerate(documents()):
            terms = tokens(index_text(doc))
            counts = Counter(terms)
            total += len(terms)

            for term, tf in counts.items():
                if term not in postings:
                    postings[term] = array("I")
                postings[term].extend((n, tf))

            norm = math.sqrt(sum((1 + math.log10(tf)) ** 2 for tf in counts.values()))
            row = {"n": n, "id": doc["id"], "title": doc["title"], "type": doc["type"],
                   "year": doc["year"], "tokens": len(terms), "norm": round(norm, 6),
                   "file": file, "offset": offset, "length": length}  # fmt: skip
            docs.write(json.dumps(row, ensure_ascii=False) + "\n")

    entries = 0
    dictionary: dict[str, dict[str, int]] = {}
    with (INDEX_DIR / "postings.jsonl.part").open("wb") as out:
        for term in sorted(postings):
            values = postings[term]
            pairs = [[values[i], values[i + 1]] for i in range(0, len(values), 2)]
            line = (json.dumps({"term": term, "df": len(pairs), "postings": pairs},
                               separators=(",", ":")) + "\n").encode()  # fmt: skip
            dictionary[term] = {"df": len(pairs), "offset": out.tell(), "length": len(line)}
            out.write(line)
            entries += len(pairs)

    with (INDEX_DIR / "terms.json.part").open("w", encoding="utf-8") as terms_file:
        json.dump(dictionary, terms_file, separators=(",", ":"))

    for part in INDEX_DIR.glob("*.part"):
        part.replace(part.with_suffix(""))
    return {"documents": n + 1, "terms": len(postings), "postings": entries, "tokens": total}


def main(argv: list[str] | None = None) -> None:
    """Run the `index` command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(prog="index", description="Build the TF index in data/index/.")
    parser.parse_args(argv)

    started = time.monotonic()
    counts = build()
    print(f"index in {INDEX_DIR} ({time.monotonic() - started:.0f} s)")
    for what, n in counts.items():
        print(f"  {what:<10} {n:>12,}")


if __name__ == "__main__":
    main()
