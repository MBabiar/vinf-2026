"""Our own TF index and search (Part 1; Part 2 moves to PyLucene).

``build.py`` (`uv run index`) writes the index from ``data/docs/``, ``search.py``
(`uv run search`) answers queries with two IDF variants, ``stats.py`` (`uv run stats`) counts
pages, documents, text and tokens. Terms come from `animanga.normalize.tokens`.
"""
