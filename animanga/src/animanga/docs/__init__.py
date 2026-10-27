"""Documents (one per work) and the ANN <-> MangaUpdates join (`uv run docs`).

``documents.py`` turns one parsed page into a document, ``join.py`` links ANN manga and anime to
MangaUpdates series (both pure functions, for Spark later), ``run.py`` reads ``parsed/`` and writes
``data/docs/``.
"""
