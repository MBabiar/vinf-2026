"""Console script `docs`: parsed pages -> documents + ANN <-> MangaUpdates links.

Reads ``data/ann/parsed/{anime,manga}.jsonl`` and ``data/mangaupdates/parsed/series.jsonl`` and
writes ``data/docs/``:

- ``ann-anime.jsonl``, ``ann-manga.jsonl``, ``mu.jsonl``: one document per line (`documents`);
- ``links.jsonl``: every link with its method and confidence (`join`);
- ``join-candidates.jsonl``: title matches that were not linked, for checking the join;
- ``summary.json``: pages read, documents written, pages without a document and why.

Where each document starts in its file is kept by the index (`animanga.index.build`).

Derived data: every run replaces it (``.part`` files, renamed at the end).
"""

import argparse
import json
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from animanga import DATA_DIR
from animanga.docs.documents import ann_document, mu_document
from animanga.docs.join import attach, join_anime, join_manga

DOCS_DIR = DATA_DIR / "docs"
FILES = ("ann-anime", "ann-manga", "mu")


def read_jsonl(path: Path, limit: int | None = None) -> Iterator[dict]:
    """Yield the objects of a JSON-lines file.

    Parameters
    ----------
    path : Path
        The file.
    limit : int or None
        Stop after this many lines.

    Yields
    ------
    dict
        One object per line.
    """
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f):
            if limit is not None and n >= limit:
                return
            yield json.loads(line)


def build(limit: int | None = None) -> dict[str, int]:
    """Build all documents and links into `DOCS_DIR`.

    Parameters
    ----------
    limit : int or None
        Read only the first `limit` pages of each parsed file (a quick sample).

    Returns
    -------
    dict[str, int]
        The counts written to ``summary.json``.
    """
    counts: Counter[str] = Counter()
    parts: dict[str, list[dict]] = {name: [] for name in FILES}

    for kind in ("anime", "manga"):
        for page in read_jsonl(DATA_DIR / "ann" / "parsed" / f"{kind}.jsonl", limit):
            counts[f"pages ann-{kind}"] += 1
            doc = ann_document(page)
            if doc is None:
                counts[f"skipped ann-{kind}: no title"] += 1
            else:
                parts[f"ann-{kind}"].append(doc)

    seen: set[str] = set()
    for page in read_jsonl(DATA_DIR / "mangaupdates" / "parsed" / "series.jsonl", limit):
        counts["pages mu"] += 1
        doc = mu_document(page)
        if doc is None:
            reason = page.get("type") if page.get("title") and page.get("mu_id") else "no title"
            counts[f"skipped mu: {reason}"] += 1
        elif doc["id"] in seen:
            counts["skipped mu: same series twice"] += 1
        else:
            seen.add(doc["id"])
            parts["mu"].append(doc)

    manga_links, candidates = join_manga(parts["ann-manga"], parts["mu"])
    anime_links = join_anime(parts["ann-anime"], manga_links)
    docs = {doc["id"]: doc for part in parts.values() for doc in part}
    attach(docs, manga_links + anime_links)

    for link in manga_links + anime_links:
        kind = "anime" if link["ann"].startswith("ann-anime") else "manga"
        counts[f"links {kind} {link['confidence']}"] += 1
    for c in candidates:
        counts[f"not linked: {c.reason}"] += 1

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for name, part in parts.items():
        counts[f"documents {name}"] = len(part)
        _write_jsonl(DOCS_DIR / f"{name}.jsonl.part", part)

    _write_jsonl(DOCS_DIR / "links.jsonl.part", manga_links + anime_links)
    _write_jsonl(
        DOCS_DIR / "join-candidates.jsonl.part",
        [
            {"ann": c.ann, "ann_title": docs[c.ann]["title"], "mu": c.mu,
             "mu_title": docs[c.mu]["title"], "level": c.level, "reason": c.reason}
            for c in candidates
        ],
    )  # fmt: skip
    with (DOCS_DIR / "summary.json.part").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(counts.items())), f, indent=2)
        f.write("\n")

    for part in DOCS_DIR.glob("*.part"):
        part.replace(part.with_suffix(""))
    return dict(counts)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write objects to a new JSON-lines file, one per line."""
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    """Run the `docs` command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog="docs", description="Build documents and ANN <-> MangaUpdates links in data/docs/."
    )
    parser.add_argument("--limit", type=int, help="only the first N pages of each parsed file")
    args = parser.parse_args(argv)

    started = time.monotonic()
    counts = build(args.limit)
    print(f"documents in {DOCS_DIR} ({time.monotonic() - started:.0f} s)")
    for what, n in sorted(counts.items()):
        print(f"  {what:<40} {n:>9,}")


if __name__ == "__main__":
    main()
