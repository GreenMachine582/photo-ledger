"""Queries for the ``sources`` table."""

import sqlite3

from photo_ledger.db import now_iso


def insert(conn: sqlite3.Connection, *, label: str, root_path: str, device: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO sources (label, root_path, source_type, volume_id, volume_root, device_label,
                             filesystem, capacity_bytes, state, created_at)
        VALUES (:label, :root_path, :source_type, :volume_id, :volume_root, :device_label,
                :filesystem, :capacity_bytes, 'online', :created_at)
        """,
        {"label": label, "root_path": root_path, "created_at": now_iso(), **device},
    )
    return cursor.lastrowid


def all_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sources ORDER BY label").fetchall()


def by_label(conn: sqlite3.Connection, label: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE label = ?", (label,)).fetchone()


def by_id(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


def update_root(conn: sqlite3.Connection, source_id: int, *, root_path: str, device: dict) -> None:
    conn.execute(
        """
        UPDATE sources
        SET root_path = :root_path, source_type = :source_type, volume_id = :volume_id,
            volume_root = :volume_root, device_label = :device_label, filesystem = :filesystem,
            capacity_bytes = :capacity_bytes, state = 'online'
        WHERE id = :id
        """,
        {"id": source_id, "root_path": root_path, **device},
    )


def set_state(conn: sqlite3.Connection, source_id: int, state: str) -> None:
    conn.execute("UPDATE sources SET state = ? WHERE id = ?", (state, source_id))


def set_quarantine(
    conn: sqlite3.Connection, source_id: int, *, path: str | None, volume_id: str | None
) -> None:
    conn.execute(
        "UPDATE sources SET quarantine_enabled = ?, quarantine_path = ?, quarantine_volume_id = ?"
        " WHERE id = ?",
        (int(path is not None), path, volume_id, source_id),
    )


def set_priority(conn: sqlite3.Connection, source_id: int, priority: int) -> None:
    conn.execute("UPDATE sources SET priority = ? WHERE id = ?", (priority, source_id))
