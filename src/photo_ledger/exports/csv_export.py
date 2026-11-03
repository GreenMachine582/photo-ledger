"""Export the catalogue as CSV: one row per file, with its content details.

Exports are read-only with respect to sources, and refuse to write inside one.
"""

import sqlite3
from pathlib import Path

from photo_ledger.exports.guard import ExportError, ensure_outside_sources, write_csv
from photo_ledger.scanner.engine import get_scan

__all__ = ["COLUMNS", "ExportError", "export_files"]

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


def export_files(conn: sqlite3.Connection, out: Path, scan_name: str | None = None) -> int:
    """Write the catalogue, or one scan's sources, to ``out``. Returns the number of rows."""
    ensure_outside_sources(conn, out)
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
    return write_csv(conn, out, COLUMNS, ([row[column] for column in COLUMNS] for row in rows))
