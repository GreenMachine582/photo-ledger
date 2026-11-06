"""Queries for ``scans``, ``scan_sources`` and ``scan_errors``."""

import sqlite3

from photo_ledger.db import now_iso, now_ns


def insert(conn: sqlite3.Connection, name: str, source_ids: list[int]) -> int:
    scan_id = conn.execute(
        "INSERT INTO scans (name, status, created_at) VALUES (?, 'new', ?)", (name, now_iso())
    ).lastrowid
    conn.executemany(
        "INSERT INTO scan_sources (scan_id, source_id) VALUES (?, ?)",
        [(scan_id, source_id) for source_id in source_ids],
    )
    return scan_id


def by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM scans WHERE name = ?", (name,)).fetchone()


def all_scans(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT s.*, group_concat(src.label, ', ') AS source_labels
        FROM scans s
        JOIN scan_sources ss ON ss.scan_id = s.id
        JOIN sources src ON src.id = ss.source_id
        GROUP BY s.id
        ORDER BY s.created_at, s.id
        """
    ).fetchall()


def scan_sources(conn: sqlite3.Connection, scan_id: int) -> list[sqlite3.Row]:
    """The scan's sources with their progress, in label order."""
    return conn.execute(
        """
        SELECT ss.*, src.label, src.root_path,
               (SELECT COUNT(*) FROM scan_errors e
                WHERE e.scan_id = ss.scan_id AND e.source_id = ss.source_id) AS error_count
        FROM scan_sources ss JOIN sources src ON src.id = ss.source_id
        WHERE ss.scan_id = ?
        ORDER BY src.label
        """,
        (scan_id,),
    ).fetchall()


def scan_source(conn: sqlite3.Connection, scan_id: int, source_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM scan_sources WHERE scan_id = ? AND source_id = ?", (scan_id, source_id)
    ).fetchone()


def live_claims(
    conn: sqlite3.Connection, source_ids: list[int], fresh_after_ns: int
) -> list[sqlite3.Row]:
    """Running scan_sources rows for these sources whose heartbeat is newer than the cut-off."""
    marks = ",".join("?" * len(source_ids))
    return conn.execute(
        f"""
        SELECT ss.scan_id, ss.source_id, s.name AS scan_name, src.label
        FROM scan_sources ss
        JOIN scans s ON s.id = ss.scan_id
        JOIN sources src ON src.id = ss.source_id
        WHERE ss.source_id IN ({marks}) AND ss.status = 'running' AND ss.heartbeat_at > ?
        """,
        (*source_ids, fresh_after_ns),
    ).fetchall()


def update_scan_source(conn: sqlite3.Connection, scan_id: int, source_id: int, **fields) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    conn.execute(
        f"UPDATE scan_sources SET {assignments}"
        " WHERE scan_id = :scan_id AND source_id = :source_id",
        {**fields, "scan_id": scan_id, "source_id": source_id},
    )


def set_status(conn: sqlite3.Connection, scan_id: int, status: str) -> None:
    conn.execute(
        "UPDATE scans SET status = ?, last_opened_at = ? WHERE id = ?", (status, now_iso(), scan_id)
    )


def add_error(
    conn: sqlite3.Connection, scan_id: int, source_id: int, rel_path: str, stage: str, message: str
) -> None:
    conn.execute(
        "INSERT INTO scan_errors (scan_id, source_id, rel_path, stage, message, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (scan_id, source_id, rel_path, stage, message, now_ns()),
    )


def clear_decode_errors(conn: sqlite3.Connection, source_id: int, rel_path: str) -> None:
    """Forget a file's earlier decode and EXIF errors, once it has been read again."""
    conn.execute(
        "DELETE FROM scan_errors WHERE source_id = ? AND rel_path = ? "
        "AND stage IN ('decode', 'exif')",
        (source_id, rel_path),
    )


def errors(conn: sqlite3.Connection, scan_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.*, src.label FROM scan_errors e JOIN sources src ON src.id = e.source_id
        WHERE e.scan_id = ? ORDER BY e.id DESC LIMIT ?
        """,
        (scan_id, limit),
    ).fetchall()


def walk_error_paths(
    conn: sqlite3.Connection, scan_id: int, source_id: int, since_ns: int
) -> list[str]:
    """Paths the walk couldn't read during the pass that started at ``since_ns``."""
    rows = conn.execute(
        "SELECT rel_path FROM scan_errors"
        " WHERE scan_id = ? AND source_id = ? AND stage = 'walk' AND created_at >= ?",
        (scan_id, source_id, since_ns),
    )
    return [row[0] for row in rows]


def by_id(conn: sqlite3.Connection, scan_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()


def delete(conn: sqlite3.Connection, scan_id: int) -> None:
    """Remove a saved scan. Its progress and errors cascade, and files and pairs keep their rows,
    with the scan IDs that named it set to NULL by the foreign keys."""
    conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
