"""Queries for the ``library`` and ``library_entries`` tables."""

import sqlite3

from photo_ledger.db import now_iso

#: An entry joined with the copy it comes from and that copy's source.
ENTRY_ROWS = """
    SELECT e.*, f.rel_path AS source_rel_path, f.mtime_ns, f.source_id,
           s.label AS source_label, s.root_path, s.volume_id, s.state AS source_state
    FROM library_entries e
    JOIN files f ON f.id = e.file_id
    JOIN sources s ON s.id = f.source_id
"""


def get(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM library WHERE id = 1").fetchone()


def save(conn: sqlite3.Connection, *, root_path: str, volume_id: str | None, layout: str) -> None:
    conn.execute(
        """
        INSERT INTO library (id, root_path, volume_id, layout, created_at)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET root_path = excluded.root_path,
            volume_id = excluded.volume_id, layout = excluded.layout
        """,
        (root_path, volume_id, layout, now_iso()),
    )


def entries(conn: sqlite3.Connection, *states: str) -> list[sqlite3.Row]:
    if not states:
        return conn.execute(f"{ENTRY_ROWS} ORDER BY e.id").fetchall()
    marks = ",".join("?" * len(states))
    return conn.execute(f"{ENTRY_ROWS} WHERE e.state IN ({marks}) ORDER BY e.id", states).fetchall()


def entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    return conn.execute(f"{ENTRY_ROWS} WHERE e.id = ?", (entry_id,)).fetchone()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT state, COUNT(*) FROM library_entries GROUP BY state")
    return {row[0]: row[1] for row in rows}


def insert_entry(conn: sqlite3.Connection, **values) -> int:
    columns = ", ".join(values)
    marks = ", ".join("?" * len(values))
    return conn.execute(
        f"INSERT INTO library_entries ({columns}) VALUES ({marks})", tuple(values.values())
    ).lastrowid


def set_state(
    conn: sqlite3.Connection, entry_id: int, state: str, *, error: str | None = None
) -> None:
    column = "started_at" if state == "started" else "finished_at"
    conn.execute(
        f"UPDATE library_entries SET state = ?, error = ?, {column} = ? WHERE id = ?",
        (state, error, now_iso(), entry_id),
    )


def set_sidecar(conn: sqlite3.Connection, entry_id: int, sidecar_blake3: str) -> None:
    conn.execute(
        "UPDATE library_entries SET sidecar_blake3 = ? WHERE id = ?", (sidecar_blake3, entry_id)
    )


def set_applied_date(conn: sqlite3.Connection, entry_id: int, applied_date: str | None) -> None:
    conn.execute(
        "UPDATE library_entries SET applied_date = ? WHERE id = ?", (applied_date, entry_id)
    )


def forget_unbuilt(conn: sqlite3.Connection) -> None:
    """Drop entries with no file in the library yet, so the next plan picks them afresh."""
    conn.execute("DELETE FROM library_entries WHERE state IN ('pending', 'failed')")


def forget_all(conn: sqlite3.Connection) -> None:
    """A new library folder starts empty. The old folder and its files are left as they are."""
    conn.execute("DELETE FROM library_entries")
