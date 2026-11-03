"""Export the catalogue as CSV: one row per file, with its content details.

Exports are read-only with respect to sources, and refuse to write inside one.
"""

import csv
import sqlite3
from pathlib import Path

from photo_ledger.db import sources as source_queries
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.scanner.engine import get_scan
from photo_ledger.sources.service import overlaps

COLUMNS = (
    "source",
    "rel_path",
    "filename",
    "extension",
    "status",
    "size_bytes",
    "mtime_ns",
    "blake3",
    "format",
    "width",
    "height",
    "captured_at",
    "capture_offset",
    "capture_date_source",
    "camera_make",
    "camera_model",
    "phash",
    "exif_error",
    "decode_error",
    "last_verified_at",
)


class ExportError(PhotoLedgerError):
    """An export can't be written where it was asked to go."""


def export_files(conn: sqlite3.Connection, out: Path, scan_name: str | None = None) -> int:
    """Write the catalogue, or one scan's sources, to ``out``. Returns the number of rows."""
    out = Path(out).expanduser().resolve()
    for source in source_queries.all_sources(conn):
        if overlaps(out, source["root_path"]):
            raise ExportError(
                f"{out} is inside source '{source['label']}'. Exports never write to a source."
            )
    where, params = "", ()
    if scan_name is not None:
        scan = get_scan(conn, scan_name)
        where = "WHERE f.source_id IN (SELECT source_id FROM scan_sources WHERE scan_id = ?)"
        params = (scan["id"],)
    rows = conn.execute(
        f"""
        SELECT s.label AS source, f.rel_path, f.filename, f.extension, f.status, f.size_bytes,
               f.mtime_ns, c.blake3, c.format, c.width, c.height, c.captured_at, c.capture_offset,
               c.capture_date_source, c.camera_make, c.camera_model, c.phash, c.exif_error,
               c.decode_error, f.last_verified_at
        FROM files f
        JOIN sources s ON s.id = f.source_id
        LEFT JOIN contents c ON c.id = f.content_id
        {where}
        ORDER BY s.label, f.rel_path
        """,
        params,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([row[column] for column in COLUMNS])
            count += 1
    return count
