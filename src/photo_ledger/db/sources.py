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


def rename(conn: sqlite3.Connection, source_id: int, label: str) -> None:
    conn.execute("UPDATE sources SET label = ? WHERE id = ?", (label, source_id))


#: Plans whose files are back where they started: an undone plan, and the undo that reversed it.
#: Their journals are history only, as there is nothing left to undo or recover.
SETTLED_PLANS = """
    SELECT id FROM plans WHERE status = 'undone'
    UNION
    SELECT id FROM plans WHERE status = 'applied'
      AND undoes_plan_id IN (SELECT id FROM plans WHERE status = 'undone')
"""


def usage(conn: sqlite3.Connection, source_id: int) -> dict[str, int]:
    """How much of the ledger refers to a source's files: what forgetting it would touch."""
    files = "SELECT id FROM files WHERE source_id = :id"
    return dict(
        conn.execute(
            f"""
            SELECT
              (SELECT COUNT(*) FROM files WHERE source_id = :id) AS files,
              (SELECT COUNT(*) FROM plan_actions a JOIN plans p ON p.id = a.plan_id
                 WHERE p.status != 'draft' AND p.id NOT IN ({SETTLED_PLANS})
                   AND a.file_id IN ({files})) AS plan_actions,
              (SELECT COUNT(*) FROM plan_actions WHERE plan_id IN ({SETTLED_PLANS})
                 AND file_id IN ({files})) AS undone_plan_actions,
              (SELECT COUNT(*) FROM library_entries WHERE state IN ('started', 'done')
                 AND file_id IN ({files})) AS library_entries,
              (SELECT COUNT(*) FROM scan_sources WHERE source_id = :id AND status = 'running')
                AS running_scans,
              (SELECT COUNT(*) FROM review_pairs WHERE kind = 'exact'
                 AND (left_id IN ({files}) OR right_id IN ({files}))) AS pairs,
              (SELECT COUNT(*) FROM decisions d JOIN review_pairs p ON p.id = d.pair_id
                 WHERE d.superseded_at IS NULL AND d.action != 'closed' AND p.kind = 'exact'
                   AND (p.left_id IN ({files}) OR p.right_id IN ({files}))) AS decisions
            """,
            {"id": source_id},
        ).fetchone()
    )


def exact_pair_ids(conn: sqlite3.Connection, source_id: int) -> list[int]:
    """Exact pairs with a copy in the source. Content pairs don't name files, so aren't here."""
    files = "SELECT id FROM files WHERE source_id = ?"
    rows = conn.execute(
        f"SELECT id FROM review_pairs WHERE kind = 'exact'"
        f" AND (left_id IN ({files}) OR right_id IN ({files}))",
        (source_id, source_id),
    )
    return [row[0] for row in rows]


def delete_pairs(conn: sqlite3.Connection, pair_ids: list[int]) -> None:
    conn.executemany("DELETE FROM review_pairs WHERE id = ?", [(pair_id,) for pair_id in pair_ids])


def delete(conn: sqlite3.Connection, source_id: int) -> None:
    """Remove a source's catalogue rows and the source. Its pairs must be gone already.

    Unapplied drafts and unbuilt library entries are dropped too: they're rebuilt from the
    catalogue the next time you plan, so nothing is lost. So are its rows in the journals of
    undone plans and their undos, which nothing reads again, and any such plan left empty. A
    live plan's journal is never touched: the caller refuses the source first.
    """
    files = "SELECT id FROM files WHERE source_id = ?"
    conn.execute("DELETE FROM plans WHERE status = 'draft'")
    conn.execute(
        f"DELETE FROM plan_actions WHERE plan_id IN ({SETTLED_PLANS}) AND file_id IN ({files})",
        (source_id,),
    )
    # Undo plans first, as nothing cascades from the plan they point at.
    empty = (
        f"id IN ({SETTLED_PLANS})"
        " AND NOT EXISTS (SELECT 1 FROM plan_actions a WHERE a.plan_id = plans.id)"
    )
    conn.execute(f"DELETE FROM plans WHERE undoes_plan_id IS NOT NULL AND {empty}")
    conn.execute(
        f"DELETE FROM plans WHERE status = 'undone' AND {empty}"
        " AND id NOT IN (SELECT undoes_plan_id FROM plans WHERE undoes_plan_id IS NOT NULL)"
    )
    conn.execute(
        "DELETE FROM library_entries WHERE state IN ('pending', 'failed')"
        f" AND file_id IN ({files})",
        (source_id,),
    )
    for table in ("collection_folders", "scan_errors", "scan_sources", "files"):
        conn.execute(f"DELETE FROM {table} WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
