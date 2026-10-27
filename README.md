# VI 2026 project: anime + manga search

Semester project for *Vyhľadávanie informácií* (Information Retrieval,
FIIT STU): anime (ANN), manga (MangaUpdates) and English Wikipedia.

## Quick start

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/) (or the devcontainer below, which has both) and
[7-Zip](https://www.7-zip.org/) for the data.

```sh
cd animanga
uv sync                                  # creates .venv with all dependencies
7z x ../dist/animanga-data.7z.001 -o.    # unpacks the data into animanga/data/ (all parts, ~1.8 GB)

uv run search "claymore yagi"            # search right away
uv run search "dark fantasy manga" --compare   # both IDF variants and no IDF side by side
```

In the submission ZIP the data is already unpacked in `animanga/data/`: skip the `7z` line.
Otherwise the archive (parsed pages, documents, index) is in `dist/` at the repo root as parts
`animanga-data.7z.001`, `.002`, …; 7-Zip finds the other parts itself. Paths inside start with
`data/`, so it lands where the commands expect it.

Pack the data again (after `uv run parse`, `docs`, `index`, `stats`; parts of 90 MB, under
GitHub's 100 MB file limit):

```sh
cd animanga
rm -f ../dist/animanga-data.7z.*
7z a -t7z -mx=9 -v90m ../dist/animanga-data.7z \
  data/ann/parsed data/mangaupdates/parsed data/docs data/index data/stats.json
```

Rebuild from the parsed pages instead of using the packed documents and index:
`uv run docs && uv run index && uv run stats` (~3 min). Crawling and parsing need the saved
HTML (35 GB, not shared); all commands: [animanga/README.md](animanga/README.md).

## Development environment

The project runs in a devcontainer (Docker container opened by VS Code). Setup,
contents and how to add your own mounts: [.devcontainer/README.md](.devcontainer/README.md).

## Where to look

| What | Where |
| --- | --- |
| How to run the code | [animanga/README.md](animanga/README.md) |
| Project report (wiki pages: K1, K2a, Odovzdanie 1 with K2b) | [docs/wiki/md/](docs/wiki/md/) |
