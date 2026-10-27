# animanga

Anime (Anime News Network) + manga (MangaUpdates) search engine for the VI 2026 course project (FIIT STU).
How it works and why is described on the course wiki; this file only says how to run it.

## Setup

Python 3.14 and [uv](https://docs.astral.sh/uv/) (the devcontainer has both). In this folder:

```sh
uv sync
```

## Run

Each step reads the output of the previous one and replaces its own output (`data/` is never committed).

```sh
uv run crawl ann                 # 1. download the pages in the background (resumes where it stopped)
uv run crawl --status            #    how many pages, size on disk (no network)
uv run crawl --stop ann          #    stop it
uv run parse                     # 2. regex extraction: saved pages -> data/<site>/parsed/*.jsonl (~3.5 min)
uv run docs                      # 3. one document per work + ANN <-> MangaUpdates links -> data/docs/ (40 s)
uv run index                     # 4. TF index -> data/index/ (50 s)
uv run search "claymore yagi"    # 5. search
uv run stats                     #    counts, sizes, tokens -> data/stats.json (45 s)
```

Search options:

```sh
uv run search "bounty hunter in space" -n 10       # top 10 (default)
uv run search "claymore" --source mu               # only ann or mu documents
uv run search "dark fantasy manga" --idf smooth    # IDF log10(N/df) (log, default) or log10(1+N/df) (smooth)
uv run search "dark fantasy manga" --compare       # both IDF and no IDF (control) side by side
uv run search "cowboy bebop" --norm pivot          # experiment: pivoted document length
```

## Modules (`src/animanga/`)

| Module | What it does |
| --- | --- |
| `crawler/` | polite crawler: robots.txt, pauses, retries; one file per site in `sites/` |
| `parser/` | regex extraction of fields from the saved HTML |
| `docs/` | documents and the ANN <-> MangaUpdates join (title + person) |
| `index/` | own TF index, search (lnc.ltc, 2 IDF), statistics |
| `normalize.py`, `tsv.py` | tokens and keys for the join; TSV logs of the crawler |

## Checks

```sh
uv run ruff format && uv run ruff check && uv run ty check src tests && uv run pytest
```
