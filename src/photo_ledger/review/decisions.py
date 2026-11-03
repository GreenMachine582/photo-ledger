"""Review decisions on stable pairs. Reviewing never touches files: decisions only build a plan.

| Action       | Pair becomes | Also                                                          |
|--------------|--------------|---------------------------------------------------------------|
| ``keep_left``  | ``resolved``   | rejects the right side and closes its other open pairs        |
| ``keep_right`` | ``resolved``   | rejects the left side and closes its other open pairs         |
| ``keep_both``  | ``resolved``   | not a duplicate, and won't come back                          |
| ``skip``       | ``skipped``    | stays open on the skip list                                   |

Closing the rejected item's other pairs is what makes N copies take N - 1 reviews. Rejecting a
similar image's content rejects every copy of it. Decisions belong to pairs, never to scans or
sessions, so resolving a pair in one scan resolves it in all of them.
"""

import sqlite3

from photo_ledger.db import now_iso
from photo_ledger.errors import PhotoLedgerError

ACTIONS = ("keep_left", "keep_right", "keep_both", "skip")
#: Pair statuses a rejection closes. Resolved pairs keep their own decision.
CLOSABLE = ("open", "skipped", "needs_review")


class DecisionError(PhotoLedgerError):
    """A decision can't be recorded or undone."""


def _pair(conn: sqlite3.Connection, pair_id: int) -> sqlite3.Row:
    pair = conn.execute("SELECT * FROM review_pairs WHERE id = ?", (pair_id,)).fetchone()
    if pair is None:
        raise DecisionError(f"There's no pair {pair_id}.")
    return pair


def _active(conn: sqlite3.Connection, pair_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM decisions WHERE pair_id = ? AND superseded_at IS NULL ORDER BY id DESC",
        (pair_id,),
    ).fetchone()


def _record(conn, pair, action, *, rejected=(None, None), caused_by=None, status) -> int:
    decision_id = conn.execute(
        """
        INSERT INTO decisions (pair_id, action, rejected_kind, rejected_id, caused_by,
                               previous_status, decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pair["id"], action, *rejected, caused_by, pair["status"], now_iso()),
    ).lastrowid
    conn.execute(
        "UPDATE review_pairs SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), pair["id"]),
    )
    return decision_id


def _revert(conn: sqlite3.Connection, decision: sqlite3.Row, *, with_closures: bool = True) -> None:
    """Supersede a decision and the closures it caused, restoring each pair's earlier status."""
    now = now_iso()
    rows = conn.execute(
        "SELECT * FROM decisions WHERE (id = ? OR (caused_by = ? AND ?)) AND superseded_at IS NULL"
        " ORDER BY id DESC",
        (decision["id"], decision["id"], int(with_closures)),
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE decisions SET superseded_at = ? WHERE id = ?", (now, row["id"]))
        conn.execute(
            "UPDATE review_pairs SET status = ?, updated_at = ? WHERE id = ?",
            (row["previous_status"], now, row["pair_id"]),
        )


def _pairs_touching(conn, kind: str, item_id: int, exclude: int) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(CLOSABLE))
    if kind == "file":
        query = (
            f"SELECT * FROM review_pairs WHERE kind = 'exact' AND status IN ({marks})"
            " AND (left_id = ? OR right_id = ?) AND id != ?"
        )
        return conn.execute(query, (*CLOSABLE, item_id, item_id, exclude)).fetchall()
    content_pairs = conn.execute(
        f"SELECT * FROM review_pairs WHERE kind != 'exact' AND status IN ({marks})"
        " AND (left_id = ? OR right_id = ?) AND id != ?",
        (*CLOSABLE, item_id, item_id, exclude),
    ).fetchall()
    # Every copy of a rejected content is rejected, so exact pairs among its copies close too.
    exact_pairs = conn.execute(
        f"""
        SELECT p.* FROM review_pairs p
        WHERE p.kind = 'exact' AND p.status IN ({marks}) AND p.id != ?
          AND (p.left_id IN (SELECT id FROM files WHERE content_id = ?)
               OR p.right_id IN (SELECT id FROM files WHERE content_id = ?))
        """,
        (*CLOSABLE, exclude, item_id, item_id),
    ).fetchall()
    return content_pairs + exact_pairs


def decide(conn: sqlite3.Connection, pair_id: int, action: str) -> int:
    """Record a decision on a pair, replacing any earlier one, and return its ID."""
    if action not in ACTIONS:
        raise DecisionError(f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}.")
    with conn:
        pair = _pair(conn, pair_id)
        if pair["status"] == "obsolete":
            raise DecisionError(
                f"Pair {pair_id} no longer matches, as a copy has gone. Run `match` to refresh."
            )
        earlier = _active(conn, pair_id)
        if earlier is not None:
            # A closure only drops itself; the decision that caused it stands.
            _revert(conn, earlier, with_closures=earlier["action"] != "closed")
            pair = _pair(conn, pair_id)

        if action == "skip":
            return _record(conn, pair, action, status="skipped")
        if action == "keep_both":
            return _record(conn, pair, action, status="resolved")

        rejected_side = "right_id" if action == "keep_left" else "left_id"
        kind = "file" if pair["kind"] == "exact" else "content"
        rejected = (kind, pair[rejected_side])
        decision_id = _record(conn, pair, action, rejected=rejected, status="resolved")
        for other in _pairs_touching(conn, kind, pair[rejected_side], exclude=pair_id):
            _record(conn, other, "closed", caused_by=decision_id, status="resolved")
        return decision_id


def undo_last(conn: sqlite3.Connection) -> int | None:
    """Revert the most recent decision, and the closures it caused. Returns its pair's ID."""
    with conn:
        last = conn.execute(
            "SELECT * FROM decisions WHERE superseded_at IS NULL AND action != 'closed'"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is None:
            return None
        _revert(conn, last)
        return last["pair_id"]


def active_decision(conn: sqlite3.Connection, pair_id: int) -> sqlite3.Row | None:
    return _active(conn, pair_id)


def rejected_items(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """``(kind, id)`` for every file or content an active decision rejects. M4 plans from these."""
    rows = conn.execute(
        "SELECT DISTINCT rejected_kind, rejected_id FROM decisions"
        " WHERE superseded_at IS NULL AND rejected_kind IS NOT NULL"
        " ORDER BY rejected_kind, rejected_id"
    )
    return [(row[0], row[1]) for row in rows]


def decision_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT action, COUNT(*) FROM decisions WHERE superseded_at IS NULL GROUP BY action"
    )
    return {row[0]: row[1] for row in rows}
