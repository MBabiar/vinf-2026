"""Regex extraction of works from the saved pages into JSON lines (`uv run parse`).

One module per site (ann.py, mangaupdates.py) with ``TABLES`` (table name -> columns) and
``parse(page, key, kind)``: a pure function from one HTML page to rows per table, so later steps
(Spark) can call it without the file layout. run.py walks ``data/<site>/raw/`` and writes
``data/<site>/parsed/<kind>.jsonl`` (one object per page).
"""
