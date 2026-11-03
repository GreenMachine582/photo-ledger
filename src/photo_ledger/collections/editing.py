"""Renaming, merging and hiding collections. These change the ledger only, never a folder."""

import sqlite3

from photo_ledger.db import collections as queries
from photo_ledger.errors import PhotoLedgerError


class CollectionError(PhotoLedgerError):
    """A collection can't be renamed, merged or hidden as asked."""


def _get(conn: sqlite3.Connection, collection_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if row is None:
        raise CollectionError(f"There's no collection {collection_id}.")
    return row


def rename(conn: sqlite3.Connection, collection_id: int, name: str) -> None:
    """Rename a collection. Its folders stay mapped, so the name survives every rescan."""
    name = name.strip()
    if not name or "/" in name or len(name) > 200:
        raise CollectionError("A collection name needs 1-200 characters and no slashes.")
    row = _get(conn, collection_id)
    clash = queries.find(conn, name, row["parent_id"])
    if clash is not None and clash != collection_id:
        raise CollectionError(
            f"There's already a collection called '{name}' there. Merge into it instead."
        )
    with conn:
        conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))


def set_hidden(conn: sqlite3.Connection, collection_id: int, hidden: bool) -> None:
    _get(conn, collection_id)
    with conn:
        conn.execute("UPDATE collections SET hidden = ? WHERE id = ?", (int(hidden), collection_id))


def _is_inside(conn: sqlite3.Connection, collection_id: int, ancestor_id: int) -> bool:
    current = collection_id
    while current is not None:
        if current == ancestor_id:
            return True
        current = conn.execute(
            "SELECT parent_id FROM collections WHERE id = ?", (current,)
        ).fetchone()[0]
    return False


def _merge(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    conn.execute(
        "UPDATE collection_folders SET collection_id = ? WHERE collection_id = ?",
        (target_id, source_id),
    )
    children = conn.execute(
        "SELECT id, name FROM collections WHERE parent_id = ?", (source_id,)
    ).fetchall()
    for child in children:
        same_name = queries.find(conn, child["name"], target_id)
        if same_name is None:
            conn.execute(
                "UPDATE collections SET parent_id = ? WHERE id = ?", (target_id, child["id"])
            )
        else:
            _merge(conn, child["id"], same_name)
    # Only the now-empty ledger row goes. No folder or file is touched.
    conn.execute("DELETE FROM collections WHERE id = ?", (source_id,))


def merge(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    """Fold one collection into another, with its folders and sub-collections."""
    _get(conn, source_id)
    _get(conn, target_id)
    if source_id == target_id:
        raise CollectionError("A collection can't be merged into itself.")
    if _is_inside(conn, target_id, source_id):
        raise CollectionError("A collection can't be merged into one of its own sub-collections.")
    with conn:
        _merge(conn, source_id, target_id)
