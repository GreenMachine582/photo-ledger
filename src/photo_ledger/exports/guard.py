"""Exports and reports write files, but never inside a source."""

import csv
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from photo_ledger.db import sources as source_queries
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.sources.service import overlaps


class ExportError(PhotoLedgerError):
    """An export can't be written where it was asked to go."""


def ensure_outside_sources(conn: sqlite3.Connection, out: Path | str) -> Path:
    """The resolved output path, refusing one inside any mapped source."""
    resolved = Path(out).expanduser().resolve()
    for source in source_queries.all_sources(conn):
        if overlaps(resolved, source["root_path"]):
            raise ExportError(
                f"{resolved} is inside source '{source['label']}'. Exports never write to a source."
            )
    return resolved


def write_csv(
    conn: sqlite3.Connection, out: Path | str, columns: Sequence[str], rows: Iterable[Sequence]
) -> int:
    """Write rows to a CSV outside every source, and return how many were written."""
    path = ensure_outside_sources(conn, out)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
            count += 1
    return count
