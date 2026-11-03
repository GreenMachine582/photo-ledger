"""Queries for ``review_pairs`` and the catalogue rows matching reads."""

import sqlite3

#: File statuses that take part in matching. Missing files drop out, which closes their pairs.
ELIGIBLE_STATUSES = ("present", "corrupt")


def eligible_files(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Catalogued copies with a content, joined to that content and their source."""
    marks = ",".join("?" * len(ELIGIBLE_STATUSES))
    return conn.execute(
        f"""
        SELECT f.id, f.source_id, f.content_id, f.rel_path, f.filename, f.size_bytes, f.mtime_ns,
               f.last_seen_scan_id, s.label AS source_label, s.priority AS source_priority,
               c.blake3, c.phash, c.width, c.height, c.captured_at, c.camera_make,
               c.camera_model, c.gps_lat, c.gps_lon, c.format, c.capture_offset,
               c.capture_date_source, f.status
        FROM files f
        JOIN contents c ON c.id = f.content_id
        JOIN sources s ON s.id = f.source_id
        WHERE f.status IN ({marks})
        ORDER BY f.id
        """,
        ELIGIBLE_STATUSES,
    ).fetchall()


def all_pairs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["pair_key"]: row for row in conn.execute("SELECT * FROM review_pairs")}


def insert(conn: sqlite3.Connection, **fields) -> int:
    columns = ", ".join(fields)
    marks = ", ".join(f":{column}" for column in fields)
    return conn.execute(f"INSERT INTO review_pairs ({columns}) VALUES ({marks})", fields).lastrowid


def update(conn: sqlite3.Connection, pair_id: int, **fields) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    conn.execute(f"UPDATE review_pairs SET {assignments} WHERE id = :id", {**fields, "id": pair_id})


def counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, status, COUNT(*) AS n FROM review_pairs GROUP BY kind, status"
        " ORDER BY kind, status"
    ).fetchall()
