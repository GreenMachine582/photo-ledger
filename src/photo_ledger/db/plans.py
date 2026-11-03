"""Queries for the ``plans`` and ``plan_actions`` tables."""

import sqlite3

from photo_ledger.db import now_iso

#: An action joined with its file and source, which every stage of a plan needs.
ACTION_ROWS = """
    SELECT a.*, f.rel_path, f.mtime_ns, f.size_bytes AS file_size, f.source_id,
           s.label AS source_label, s.root_path, s.volume_id, s.state AS source_state
    FROM plan_actions a
    JOIN files f ON f.id = a.file_id
    JOIN sources s ON s.id = f.source_id
"""


def get(conn: sqlite3.Connection, plan_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()


def latest(conn: sqlite3.Connection, *statuses: str) -> sqlite3.Row | None:
    marks = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT * FROM plans WHERE status IN ({marks}) ORDER BY id DESC LIMIT 1", statuses
    ).fetchone()


def actions(conn: sqlite3.Connection, plan_id: int) -> list[sqlite3.Row]:
    return conn.execute(f"{ACTION_ROWS} WHERE a.plan_id = ? ORDER BY a.id", (plan_id,)).fetchall()


def action(conn: sqlite3.Connection, action_id: int) -> sqlite3.Row:
    return conn.execute(f"{ACTION_ROWS} WHERE a.id = ?", (action_id,)).fetchone()


def insert_plan(conn: sqlite3.Connection, *, undoes: int | None = None) -> int:
    return conn.execute(
        "INSERT INTO plans (status, undoes_plan_id, created_at) VALUES ('draft', ?, ?)",
        (undoes, now_iso()),
    ).lastrowid


def insert_action(conn: sqlite3.Connection, plan_id: int, **values) -> int:
    columns = ", ".join(["plan_id", *values])
    marks = ", ".join("?" * (len(values) + 1))
    return conn.execute(
        f"INSERT INTO plan_actions ({columns}) VALUES ({marks})", (plan_id, *values.values())
    ).lastrowid


def set_status(conn: sqlite3.Connection, plan_id: int, status: str, **columns) -> None:
    sets = "".join(f", {name} = ?" for name in columns)
    conn.execute(
        f"UPDATE plans SET status = ?{sets} WHERE id = ?", (status, *columns.values(), plan_id)
    )


def set_checked(conn: sqlite3.Connection, plan_id: int, checked_at: str | None) -> None:
    conn.execute("UPDATE plans SET checked_at = ? WHERE id = ?", (checked_at, plan_id))


def set_action_state(
    conn: sqlite3.Connection, action_id: int, state: str, *, error: str | None = None
) -> None:
    column = "started_at" if state == "started" else "finished_at"
    conn.execute(
        f"UPDATE plan_actions SET state = ?, error = ?, {column} = ? WHERE id = ?",
        (state, error, now_iso(), action_id),
    )


def delete_drafts(conn: sqlite3.Connection) -> None:
    """Forget unapplied drafts. They hold no journal yet, so nothing is lost."""
    conn.execute("DELETE FROM plans WHERE status = 'draft'")
