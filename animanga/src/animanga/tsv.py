"""Append-only TSV files: UTF-8, header row, no quoting, one record per line."""

import os
import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

_BAD = re.compile(r"[\t\r\n]+")


def clean(value: object) -> str:
    """Make a value safe for one TSV cell.

    Tabs and line breaks inside a value would break the row, so they become one space.

    Parameters
    ----------
    value : object
        Any value; ``None`` becomes an empty string.

    Returns
    -------
    str
        The value as text without tabs or line breaks.
    """
    return _BAD.sub(" ", "" if value is None else str(value))


class TsvWriter:
    """Append rows to a TSV file and fsync each one.

    A crash loses at most the row being written. A new or empty file gets the header row; an
    existing file first loses a torn last row (see `_drop_torn_row`).

    Parameters
    ----------
    path : Path
        The TSV file; missing parent folders are created.
    columns : Sequence[str]
        Column names, in file order.
    """

    def __init__(self, path: Path, columns: Sequence[str]) -> None:
        self.path = path
        self.columns = list(columns)

        path.parent.mkdir(parents=True, exist_ok=True)

        new = not path.exists() or path.stat().st_size == 0
        if not new:
            _drop_torn_row(path)

        self._f = path.open("a", encoding="utf-8", newline="\n")
        if new:
            self._write_line(self.columns)

    def append(self, row: dict[str, object]) -> None:
        """Append one row and fsync it.

        Parameters
        ----------
        row : dict[str, object]
            Values by column name; missing columns are written empty, unknown keys are ignored.
        """
        self._write_line([row.get(c, "") for c in self.columns])

    def append_many(self, rows: Iterable[dict[str, object]]) -> None:
        """Append many rows with a single fsync (used for seeding).

        Parameters
        ----------
        rows : Iterable[dict[str, object]]
            Rows as in `append`.
        """
        for row in rows:
            self._f.write("\t".join(clean(row.get(c, "")) for c in self.columns) + "\n")

        self._f.flush()
        os.fsync(self._f.fileno())

    def _write_line(self, values: Sequence[object]) -> None:
        self._f.write("\t".join(clean(v) for v in values) + "\n")
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self) -> None:
        """Close the file."""
        self._f.close()


def _drop_torn_row(path: Path) -> None:
    """Cut off a last row that has no newline.

    A crash can leave the last row without its newline. That row is incomplete metadata (the
    page itself is re-checked by file existence), so it is cut off before appending.

    Parameters
    ----------
    path : Path
        An existing, non-empty TSV file.
    """
    with path.open("rb+") as f:
        size = f.seek(0, os.SEEK_END)
        tail = max(0, size - 65536)
        f.seek(tail)
        chunk = f.read()

        if chunk.endswith(b"\n"):
            return

        cut = chunk.rfind(b"\n")
        f.truncate(tail + cut + 1 if cut >= 0 else 0)


def read_rows(path: Path) -> Iterator[dict[str, str]]:
    """Read the rows of a TSV file as dicts.

    Rows with a wrong column count or without a final newline (torn by a crash) are skipped.

    Parameters
    ----------
    path : Path
        The TSV file; a missing file yields nothing.

    Yields
    ------
    dict[str, str]
        One row, keyed by the header's column names.
    """
    if not path.exists():
        return

    with path.open(encoding="utf-8", newline="\n") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            if not line.endswith("\n"):
                continue
            values = line.rstrip("\n").split("\t")
            if len(values) == len(header):
                yield dict(zip(header, values, strict=True))
