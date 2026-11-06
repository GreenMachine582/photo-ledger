"""Queries for ``files`` and ``contents``."""

import sqlite3

#: Columns of ``contents`` filled from scanner.metadata.ImageInfo.
CONTENT_INFO_COLUMNS = (
    "phash",
    "width",
    "height",
    "format",
    "captured_at",
    "capture_offset",
    "capture_date_source",
    "camera_make",
    "camera_model",
    "gps_lat",
    "gps_lon",
    "exif_json",
    "exif_error",
    "decode_error",
)


def by_path(conn: sqlite3.Connection, source_id: int, rel_path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM files WHERE source_id = ? AND rel_path = ?", (source_id, rel_path)
    ).fetchone()


def by_id(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()


def insert(conn: sqlite3.Connection, **fields) -> int:
    columns = ", ".join(fields)
    marks = ", ".join(f":{column}" for column in fields)
    return conn.execute(f"INSERT INTO files ({columns}) VALUES ({marks})", fields).lastrowid


def update(conn: sqlite3.Connection, file_id: int, **fields) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    conn.execute(f"UPDATE files SET {assignments} WHERE id = :id", {**fields, "id": file_id})


def remove_row(conn: sqlite3.Connection, file_id: int) -> None:
    """Drop a catalogue row (never a file on disk), used when a move merges two rows."""
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))


def pending_hash_count(conn: sqlite3.Connection, source_id: int) -> int:
    """How many of a source's files are still waiting to be hashed."""
    return conn.execute(
        "SELECT COUNT(*) FROM files WHERE source_id = ? AND pending_hash = 1", (source_id,)
    ).fetchone()[0]


def pending_hash_ids(conn: sqlite3.Connection, source_id: int) -> list[int]:
    """Files waiting to be hashed, those sharing a size with another file first."""
    rows = conn.execute(
        """
        SELECT f.id FROM files f
        WHERE f.source_id = ? AND f.pending_hash = 1
        ORDER BY (SELECT COUNT(*) FROM files g WHERE g.size_bytes = f.size_bytes) > 1 DESC,
                 f.size_bytes DESC, f.id
        """,
        (source_id,),
    )
    return [row[0] for row in rows]


def vanished(conn: sqlite3.Connection, source_id: int, pass_started_ns: int) -> list[sqlite3.Row]:
    """Rows not seen since the pass started, other than those already missing."""
    return conn.execute(
        "SELECT * FROM files WHERE source_id = ? AND status != 'missing' AND last_seen_at < ?"
        " ORDER BY rel_path",
        (source_id, pass_started_ns),
    ).fetchall()


def first_seen_since(
    conn: sqlite3.Connection, source_id: int, pass_started_ns: int
) -> list[sqlite3.Row]:
    """Rows created during the pass that have a content, oldest first."""
    return conn.execute(
        "SELECT * FROM files WHERE source_id = ? AND first_seen_at >= ? AND content_id IS NOT NULL"
        " ORDER BY id",
        (source_id, pass_started_ns),
    ).fetchall()


def content_by_blake3(conn: sqlite3.Connection, digest: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM contents WHERE blake3 = ?", (digest,)).fetchone()


def content_by_id(conn: sqlite3.Connection, content_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM contents WHERE id = ?", (content_id,)).fetchone()


def insert_content(conn: sqlite3.Connection, digest: str, size_bytes: int, info: dict) -> int:
    fields = {column: info.get(column) for column in CONTENT_INFO_COLUMNS}
    columns = ", ".join(("blake3", "size_bytes", *fields))
    marks = ", ".join((":blake3", ":size_bytes", *(f":{c}" for c in fields)))
    return conn.execute(
        f"INSERT INTO contents ({columns}) VALUES ({marks})",
        {"blake3": digest, "size_bytes": size_bytes, **fields},
    ).lastrowid
