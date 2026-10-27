"""Console script `parse [site ...] [--limit N] [--workers N]`: saved pages -> JSON lines.

Reads ``data/<site>/raw/<kind>/NNN/N.html`` (never changes them) and writes
``data/<site>/parsed/<file>.jsonl`` with one JSON object per page, ordered by ID (`record`),
``errors.jsonl`` (pages that failed) and ``summary.json`` (pages, rows per table, bytes per file).
The output is derived data: every run replaces it (written to ``.part`` files first, renamed at
the end).
"""

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from types import ModuleType

from animanga import DATA_DIR
from animanga.parser import ann, mangaupdates

SITES: dict[str, ModuleType] = {"ann": ann, "mangaupdates": mangaupdates}


def pages(raw: Path, module: ModuleType) -> list[tuple[int, str, Path]]:
    """List the saved pages of a site that its parser reads.

    Parameters
    ----------
    raw : Path
        The site's ``raw/`` folder.
    module : ModuleType
        The site's parser: optional ``KINDS`` (the ``raw/`` folders it reads; default all) and
        ``page_key(name, kind)`` (the ID of a file name; default the number in it).

    Returns
    -------
    list[tuple[int, str, Path]]
        (ID, kind, path) of every page, ordered by ID.
    """
    kinds = getattr(module, "KINDS", None)
    page_key = getattr(module, "page_key", lambda name, _kind: int(name))

    found = [
        (page_key(path.stem, kind.name), kind.name, path)
        for kind in raw.iterdir()
        if kind.is_dir() and (kinds is None or kind.name in kinds)
        for path in kind.glob("*/*.html")
    ]
    return sorted(found)


def parse_file(job: tuple[str, int, str, Path]) -> tuple[int, dict[str, list[dict]], str]:
    """Parse one saved page (runs in a worker process).

    Parameters
    ----------
    job : tuple[str, int, str, Path]
        Site name, ID, kind and path of the page.

    Returns
    -------
    tuple[int, dict[str, list[dict]], str]
        The ID, rows per table, and an error message (``""`` if the page parsed).
    """
    site, key, kind, path = job
    try:
        page = path.read_text(encoding="utf-8", errors="replace")
        return key, SITES[site].parse(page, key, kind), ""
    except Exception as e:  # one bad page must not stop the run; it goes to errors.jsonl
        return key, {}, f"{type(e).__name__}: {e}"


def record(rows: dict[str, list[dict]], main: str) -> dict[str, object]:
    """Join the rows of one page into one object.

    Parameters
    ----------
    rows : dict[str, list[dict]]
        Rows per table, as ``parse`` returns them.
    main : str
        The table with one row per page (``works``, ``series``).

    Returns
    -------
    dict[str, object]
        The main row's fields, then one list per other table, its rows without ``id`` / ``page``
        (they repeat the page's ID).
    """
    out: dict[str, object] = dict(rows[main][0]) if rows.get(main) else {}
    for table, table_rows in rows.items():
        if table != main:
            out[table] = [
                {k: v for k, v in r.items() if k not in ("id", "page")} for r in table_rows
            ]
    return out


def parse_site(name: str, limit: int | None = None, workers: int | None = None) -> int:
    """Parse every saved page of one site into ``data/<site>/parsed/``.

    Parameters
    ----------
    name : str
        ``ann`` or ``mangaupdates``.
    limit : int or None
        Parse only the first `limit` pages (by ID), e.g. for a quick sample.
    workers : int or None
        Worker processes; ``None`` = one per CPU.

    Returns
    -------
    int
        The number of pages that failed.
    """
    module = SITES[name]
    data = DATA_DIR / name
    out = data / "parsed"
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    jobs = [(name, key, kind, path) for key, kind, path in pages(data / "raw", module)[:limit]]
    main = next(iter(module.TABLES))
    names = getattr(module, "FILES", {})  # kind -> output file; default the kind
    stems = sorted({names.get(job[2], job[2]) for job in jobs})
    files = {s: (out / f"{s}.jsonl.part").open("w", encoding="utf-8", newline="\n") for s in stems}
    errors = (out / "errors.jsonl.part").open("w", encoding="utf-8", newline="\n")
    counts = dict.fromkeys([*module.TABLES, "errors"], 0)

    print(f"{name}: parsing {len(jobs)} pages -> {out}", flush=True)
    with Pool(workers) as pool:
        results = pool.imap(parse_file, jobs, chunksize=64)
        for done, ((key, rows, error), job) in enumerate(zip(results, jobs, strict=True), 1):
            if error:
                failure = {"id": key, "kind": job[2], "path": str(job[3]), "error": error}
                errors.write(json.dumps(failure, ensure_ascii=False) + "\n")
                counts["errors"] += 1
            else:
                for table, table_rows in rows.items():
                    counts[table] += len(table_rows)
                line = json.dumps(record(rows, main), ensure_ascii=False)
                files[names.get(job[2], job[2])].write(line + "\n")
            if done % 20000 == 0:
                print(f"  {done}/{len(jobs)} pages, {time.monotonic() - started:.0f} s", flush=True)

    for stem, f in files.items():
        f.close()
        (out / f"{stem}.jsonl.part").replace(out / f"{stem}.jsonl")
    errors.close()
    (out / "errors.jsonl.part").replace(out / "errors.jsonl")

    sizes = {f"{s}.jsonl": (out / f"{s}.jsonl").stat().st_size for s in stems}
    _write_summary(out / "summary.json", len(jobs), counts, sizes)

    print(f"{name}: {len(jobs)} pages in {time.monotonic() - started:.0f} s")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>10,} rows")
    for file, size in sizes.items():
        print(f"  {file:<16} {size / 1e6:>9.1f} MB")
    return counts["errors"]


def _write_summary(path: Path, pages: int, counts: dict[str, int], sizes: dict[str, int]) -> None:
    """Write summary.json: the number of pages, rows per table, bytes per output file."""
    summary = {"pages": pages}
    summary |= {f"rows {table}": rows for table, rows in counts.items()}
    summary |= {f"bytes {file}": size for file, size in sizes.items()}
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> None:
    """Run the `parse` command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog="parse",
        description="Extract works from the saved pages into data/<site>/parsed/*.jsonl.",
    )
    parser.add_argument(
        "sites", nargs="*", choices=sorted(SITES), metavar="site", help="default: all"
    )
    parser.add_argument("--limit", type=int, help="only the first N pages per site (a sample)")
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="default: all CPUs")
    args = parser.parse_args(argv)

    failed = sum(parse_site(s, args.limit, args.workers) for s in args.sites or sorted(SITES))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
