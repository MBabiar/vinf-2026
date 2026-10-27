"""Anime + manga search engine (VI 2026): crawler, later parser and index."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the animanga/ project folder
DATA_DIR = ROOT / "data"  # one subfolder per site: data/ann, data/mangaupdates
