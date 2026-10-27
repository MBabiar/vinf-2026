"""Console script `stats`: counts and sizes of every step, per source (for Odovzdanie 1).

Pages and HTML on disk (``raw/``), documents and pages without one, text in the index, tokens of
our tokenizer and of tiktoken (``o200k_base``, the GPT-4o encoding; bonus of K2b), terms and
postings, links between the sites. Prints a table and writes ``data/stats.json``.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import tiktoken

from animanga import DATA_DIR
from animanga.docs.run import DOCS_DIR, FILES, read_jsonl
from animanga.index.build import INDEX_DIR, index_text
from animanga.index.search import table
from animanga.normalize import tokens

ENCODING = "o200k_base"
RAW = {  # source -> (site folder, raw/ folders of its document pages)
    "ann-anime": ("ann", ("anime",)),
    "ann-manga": ("ann", ("manga",)),
    "mu": ("mangaupdates", ("series", "series_b36")),
}


def folder_size(path: Path) -> tuple[int, int]:
    """Return the number of files under `path` and their bytes.

    Parameters
    ----------
    path : Path
        A folder (missing = empty).

    Returns
    -------
    tuple[int, int]
        Files and bytes.
    """
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    return len(files), sum(p.stat().st_size for p in files)


def collect() -> list[tuple[str, dict[str, object]]]:
    """Count everything, per source.

    Returns
    -------
    list[tuple[str, dict[str, object]]]
        Rows ``(what, {source: value})``; sources are `FILES` and ``total``.
    """
    encoding = tiktoken.get_encoding(ENCODING)
    with (DOCS_DIR / "summary.json").open(encoding="utf-8") as f:
        summary: dict[str, int] = json.load(f)
    rows: dict[str, dict[str, object]] = {}

    def put(what: str, source: str, value: object) -> None:
        rows.setdefault(what, {})[source] = value

    for source, (site, kinds) in RAW.items():
        pages, size = 0, 0
        for kind in kinds:
            n, b = folder_size(DATA_DIR / site / "raw" / kind)
            pages, size = pages + n, size + b
        put("pages (HTML files)", source, pages)
        put("HTML on disk (MB)", source, round(size / 1e6))

        docs = with_text = text_bytes = plot_bytes = own = gpt = linked = 0
        links: Counter[str] = Counter()
        batch: list[str] = []
        for doc in read_jsonl(DOCS_DIR / f"{source}.jsonl"):
            docs += 1
            with_text += bool(doc["text"])
            linked += bool(doc["links"])
            links.update(link["confidence"] for link in doc["links"])
            text = index_text(doc)
            text_bytes += len(text.encode())
            plot_bytes += len(doc["text"].encode())
            own += len(tokens(text))
            batch.append(text)
            if len(batch) >= 5000:
                gpt += sum(map(len, encoding.encode_ordinary_batch(batch)))
                batch = []
        gpt += sum(map(len, encoding.encode_ordinary_batch(batch)))

        skipped = sum(v for k, v in summary.items() if k.startswith(f"skipped {source}"))
        put("documents", source, docs)
        put("pages without a document (doujinshi, no title)", source, skipped)
        put("documents with a plot / description", source, with_text)
        put("documents linked to the other site", source, linked)
        put("links high / medium", source, f"{links['high']:,} / {links['medium']:,}")
        put("text in the index (MB)", source, round(text_bytes / 1e6, 1))
        put("of it plot / description (MB)", source, round(plot_bytes / 1e6, 1))
        put("tokens, own tokenizer (no stop words)", source, own)
        put(f"tokens, tiktoken {ENCODING}", source, gpt)

    for values in rows.values():
        numbers = [v for v in values.values() if isinstance(v, int | float)]
        if len(numbers) == len(values):
            values["total"] = round(sum(numbers), 1)
    with (INDEX_DIR / "terms.json").open(encoding="utf-8") as f:
        terms = len(json.load(f))
    put("terms in the index", "total", terms)
    put("index on disk (MB)", "total", round(folder_size(INDEX_DIR)[1] / 1e6, 1))
    put("documents on disk (MB)", "total", round(folder_size(DOCS_DIR)[1] / 1e6, 1))
    return list(rows.items())


def main(argv: list[str] | None = None) -> None:
    """Run the `stats` command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(prog="stats", description="Counts for every step.")
    parser.parse_args(argv)

    started = time.monotonic()
    rows = collect()
    columns = [*FILES, "total"]
    cells = [[what] + [f"{v.get(c, ''):,}" if isinstance(v.get(c), int) else str(v.get(c, ""))
                       for c in columns] for what, v in rows]  # fmt: skip

    print(table(cells, ["", *columns]))
    with (DATA_DIR / "stats.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(rows), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n{DATA_DIR / 'stats.json'} ({time.monotonic() - started:.0f} s)")


if __name__ == "__main__":
    main()
