"""Console script `search "query"`: rank documents with our own TF index and two IDF variants.

Scoring is lnc.ltc from the indexing lecture (7 Oct): a document term weighs ``1 + log10(tf)``,
normalised by the document's vector length (``norm`` in ``docs.jsonl``); a query term weighs
``(1 + log10(tf)) * idf``, normalised by the query's vector length; the score is the sum of the
products over the query terms (cosine similarity).

Pure cosine normalisation favours short documents: the median vector length of an anime is 11.1,
of an ANN manga 4.2 (Cowboy Bebop 17.9), and "cowboy bebop" put the series 23rd behind every short
page with that title. ``--norm pivot`` is an extra experiment beyond the lecture: the document
length is pivoted (Manning et al., Introduction to IR, 6.4.4),
``(1 - SLOPE) * pivot + SLOPE * norm``, the pivot being the average norm. The default ``cosine``
is the plain lnc.ltc. The IDF variants (`IDF`):

- ``log``: ``log10(N / df)``;
- ``smooth`` (smoothed): ``log10(1 + N / df)``, never 0: a term in every document still weighs
  ``log10(2)``, while a rare term weighs about the same as with ``log``;
- ``none``: 1 for every term, not a third method but the control in ``--compare``: it shows what
  the IDF changes in the ranking.

Only the postings of the query terms are read (seek to their offset in ``postings.jsonl``), and
only the documents shown (seek to their offset in ``data/docs/``, kept in ``docs.jsonl``).
"""

import argparse
import heapq
import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from animanga.docs.run import DOCS_DIR, read_jsonl
from animanga.index.build import INDEX_DIR
from animanga.normalize import tokens

IDF: dict[str, Callable[[int, int], float]] = {
    "log": lambda n, df: math.log10(n / df),
    "smooth": lambda n, df: math.log10(1 + n / df),
    "none": lambda n, df: 1.0,
}
IDF_NAMES = {"log": "log10(N/df)", "smooth": "log10(1+N/df)", "none": "none (1)"}
SLOPE = 0.3  # chosen on the K1 questions (docs/INDEXER.md 8): ranked the right anime highest


@dataclass(frozen=True)
class Hit:
    """One ranked document."""

    score: float
    n: int
    id: str
    title: str
    type: str
    year: str
    matched: tuple[str, ...]  # the query terms the document contains


class Index:
    """The index on disk: terms and documents in memory, postings read per query term.

    Parameters
    ----------
    folder : Path
        The folder `build` wrote (``data/index/``).
    documents : Path
        The documents the index points to (``data/docs/``).
    """

    def __init__(self, folder: Path = INDEX_DIR, documents: Path = DOCS_DIR) -> None:
        self.postings_path = folder / "postings.jsonl"
        self.documents = documents
        with (folder / "terms.json").open(encoding="utf-8") as f:
            self.terms = {t: (e["df"], e["offset"], e["length"]) for t, e in json.load(f).items()}
        self.docs = list(read_jsonl(folder / "docs.jsonl"))
        self.norms = [d["norm"] for d in self.docs]
        self.n = len(self.docs)
        self.numbers = {d["id"]: d["n"] for d in self.docs}
        pivot = sum(self.norms) / self.n if self.n else 0.0
        self.pivoted = [(1 - SLOPE) * pivot + SLOPE * norm for norm in self.norms]

    def postings(self, term: str) -> list[tuple[int, int]]:
        """Return the ``(document number, tf)`` pairs of a term (empty if unknown).

        Parameters
        ----------
        term : str
            An index term.

        Returns
        -------
        list[tuple[int, int]]
            Pairs in ascending document order.
        """
        if term not in self.terms:
            return []
        _, offset, length = self.terms[term]
        with self.postings_path.open("rb") as f:
            f.seek(offset)
            entry = json.loads(f.read(length))
        return [(d, tf) for d, tf in entry["postings"]]

    def document(self, doc_id: str) -> dict:
        """Read one whole document by its ID (seek to its line, not the whole file).

        Parameters
        ----------
        doc_id : str
            A document ID.

        Returns
        -------
        dict
            The document; ``{}`` if the ID is unknown.
        """
        if doc_id not in self.numbers:
            return {}
        row = self.docs[self.numbers[doc_id]]
        with (self.documents / row["file"]).open("rb") as f:
            f.seek(row["offset"])
            return json.loads(f.read(row["length"]))

    def query_weights(self, query: str, idf: str) -> dict[str, float]:
        """Return the normalised weight of each query term found in the index.

        Parameters
        ----------
        query : str
            The query text (tokenised like the documents).
        idf : str
            A key of `IDF`.

        Returns
        -------
        dict[str, float]
            Term -> ``(1 + log10 tf) * idf / |q|``; empty if no term is known or all weigh 0.
        """
        counts = Counter(t for t in tokens(query) if t in self.terms)
        weights = {
            t: (1 + math.log10(tf)) * IDF[idf](self.n, self.terms[t][0]) for t, tf in counts.items()
        }
        length = math.sqrt(sum(w * w for w in weights.values()))
        return {t: w / length for t, w in weights.items()} if length else {}

    def search(
        self, query: str, idf: str = "log", top: int = 10, source: str = "", norm: str = "cosine"
    ) -> list[Hit]:
        """Rank the documents for a query.

        Parameters
        ----------
        query : str
            The query text.
        idf : str
            ``log``, ``smooth`` or ``none`` (`IDF`).
        top : int
            How many hits to return.
        source : str
            ``ann`` or ``mu`` to keep only that site's documents; ``""`` = all.
        norm : str
            ``cosine`` (plain lnc.ltc, default) or ``pivot`` (pivoted document length).

        Returns
        -------
        list[Hit]
            The best `top` documents, best first.
        """
        lengths = self.pivoted if norm == "pivot" else self.norms
        scores: dict[int, float] = {}
        matched: dict[int, list[str]] = {}
        for term, weight in self.query_weights(query, idf).items():
            for d, tf in self.postings(term):
                scores[d] = scores.get(d, 0.0) + weight * (1 + math.log10(tf)) / lengths[d]
                matched.setdefault(d, []).append(term)

        prefix = f"{source}-" if source else ""
        best = heapq.nlargest(
            top,
            ((s, d) for d, s in scores.items() if self.docs[d]["id"].startswith(prefix)),
        )
        return [
            Hit(s, d, self.docs[d]["id"], self.docs[d]["title"], self.docs[d]["type"],
                str(self.docs[d]["year"] or ""), tuple(matched[d]))
            for s, d in best
        ]  # fmt: skip


def _cut(value: str, width: int) -> str:
    """Shorten text to `width` characters (with an ellipsis)."""
    return value if len(value) <= width else value[: width - 1] + "…"


def _links(index: Index, doc_id: str) -> str:
    """Return the IDs of the documents linked to `doc_id` (other site), comma separated."""
    links = index.document(doc_id).get("links", [])
    return ", ".join(f"{link['id']} ({link['confidence']})" for link in links[:3])


def table(rows: list[list[str]], header: list[str]) -> str:
    """Format rows as a text table with ``|`` columns (pastes into the wiki as it is).

    Parameters
    ----------
    rows : list[list[str]]
        Cells per row.
    header : list[str]
        Column names.

    Returns
    -------
    str
        The table, one line per row.
    """
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    lines = ["| " + " | ".join(str(c).ljust(w) for c, w in zip(header, widths, strict=True)) + " |"]
    lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    lines += [
        "| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)) + " |"
        for r in rows
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Run the `search` command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(prog="search", description="Search the TF index.")
    parser.add_argument("query", nargs="+", help="query words")
    parser.add_argument("--idf", choices=sorted(IDF), default="log", help="default: log")
    parser.add_argument("-n", type=int, default=10, help="number of hits (default 10)")
    parser.add_argument("--source", choices=["ann", "mu"], default="", help="only one site")
    parser.add_argument(
        "--norm",
        choices=["cosine", "pivot"],
        default="cosine",
        help="document length: cosine (lnc.ltc, default) or pivot (experiment)",
    )
    parser.add_argument(
        "--compare", action="store_true", help="both IDF variants and no IDF side by side"
    )
    args = parser.parse_args(argv)
    query = " ".join(args.query)

    index = Index()
    print(f"query: {query!r}  (N = {index.n:,} documents)")
    terms = [[t, f"{index.terms[t][0]:,}" if t in index.terms else "0",
              *(f"{IDF[v](index.n, index.terms[t][0]):.3f}" if t in index.terms else "-"
                for v in ("log", "smooth"))]
             for t in dict.fromkeys(tokens(query))]  # fmt: skip
    print(table(terms, ["term", "df", "idf log", "idf smooth"]))
    print()

    if args.compare:
        variants = ("log", "smooth", "none")
        hits = {v: index.search(query, v, args.n, args.source, args.norm) for v in variants}
        rows = []
        for i in range(args.n):
            row = [str(i + 1)]
            for v in variants:
                h = hits[v][i] if i < len(hits[v]) else None
                row += [f"{h.score:.4f}", f"{_cut(h.title, 34)} ({h.id})"] if h else ["", ""]
            rows.append(row)
        header = ["#"]
        for v in variants:
            header += ["score", f"IDF {IDF_NAMES[v]}"]
        print(table(rows, header))
        ids = {v: {h.id for h in hits[v]} for v in variants}
        print(f"\nlog and smooth: the same {len(ids['log'] & ids['smooth'])} of {args.n} documents;"
              f" log and none: {len(ids['log'] & ids['none'])}")  # fmt: skip
        return

    hits = index.search(query, args.idf, args.n, args.source, args.norm)
    rows = [
        [str(i), f"{h.score:.4f}", h.id, _cut(h.type, 12), h.year, _cut(h.title, 50),
         " ".join(h.matched), _links(index, h.id)]
        for i, h in enumerate(hits, 1)
    ]  # fmt: skip
    print(f"IDF {IDF_NAMES[args.idf]}")
    print(table(rows, ["#", "score", "id", "type", "year", "title", "matched", "linked"]))


if __name__ == "__main__":
    main()
