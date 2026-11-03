"""Queries for ``collections`` and ``collection_folders``."""

import sqlite3

from photo_ledger.db.pairs import ELIGIBLE_STATUSES


def mapped_folders(conn: sqlite3.Connection) -> dict[tuple[int, str], int]:
    rows = conn.execute("SELECT source_id, folder_path, collection_id FROM collection_folders")
    return {(row[0], row[1]): row[2] for row in rows}


def photo_folders(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Each ``(source_id, folder)`` holding at least one catalogued photo."""
    rows = conn.execute(
        "SELECT DISTINCT source_id, rel_path FROM files WHERE content_id IS NOT NULL"
    )
    return sorted({(row[0], row[1].rpartition("/")[0]) for row in rows})


def content_files(conn: sqlite3.Connection) -> list[tuple[int, int, str]]:
    """``(content_id, source_id, rel_path)`` for every copy that takes part in matching."""
    marks = ",".join("?" * len(ELIGIBLE_STATUSES))
    return conn.execute(
        f"SELECT content_id, source_id, rel_path FROM files"
        f" WHERE content_id IS NOT NULL AND status IN ({marks})",
        ELIGIBLE_STATUSES,
    ).fetchall()


def find(conn: sqlite3.Connection, name: str, parent_id: int | None) -> int | None:
    row = conn.execute(
        "SELECT id FROM collections WHERE COALESCE(parent_id, 0) = ? AND name = ? COLLATE NOCASE",
        (parent_id or 0, name),
    ).fetchone()
    return row[0] if row else None


def insert(conn: sqlite3.Connection, name: str, parent_id: int | None, created_at: str) -> int:
    return conn.execute(
        "INSERT INTO collections (name, parent_id, created_at) VALUES (?, ?, ?)",
        (name, parent_id, created_at),
    ).lastrowid


def map_folder(conn: sqlite3.Connection, source_id: int, folder: str, collection_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO collection_folders (source_id, folder_path, collection_id)"
        " VALUES (?, ?, ?)",
        (source_id, folder, collection_id),
    )


def all_collections(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM collections ORDER BY id").fetchall()


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
