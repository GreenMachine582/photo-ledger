"""Turn the active decisions into a draft plan. Planning only writes to the catalogue.

A rejected copy becomes a ``quarantine`` action when its source has opted in to quarantine.
Otherwise it stays where it is, which is the default: nothing ever leaves a backup unless you
ask for it. A copy is also left alone when moving it would leave its picture without a kept
copy, however the decisions got there.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from photo_ledger.actions import PlanError
from photo_ledger.db import plans as queries

#: Where a quarantined copy goes, under the source's quarantine folder.
QUARANTINE_LAYOUT = "plan-{plan_id}/{label}/{rel_path}"


@dataclass
class PlanSummary:
    plan_id: int
    moves: int = 0
    move_bytes: int = 0
    stay: int = 0
    stay_bytes: int = 0
    #: Rejected copies left alone because no kept copy of the picture would remain.
    unsafe: list[str] = field(default_factory=list)


def _rejected_files(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Present files that active decisions on still-resolved pairs reject, with their keepers.

    ``keeper_content`` is the content that must keep a copy: the file's own content for an
    exact rejection, and the pair's other side for a content rejection.
    """
    return conn.execute(
        """
        SELECT f.id, f.rel_path, f.size_bytes, f.content_id, c.blake3,
               s.id AS source_id, s.label, s.quarantine_enabled, s.quarantine_path,
               s.quarantine_volume_id,
               CASE d.rejected_kind
                   WHEN 'file' THEN f.content_id
                   ELSE CASE WHEN p.left_id = d.rejected_id THEN p.right_id ELSE p.left_id END
               END AS keeper_content
        FROM decisions d
        JOIN review_pairs p ON p.id = d.pair_id AND p.status = 'resolved'
        JOIN files f ON (d.rejected_kind = 'file' AND f.id = d.rejected_id)
                     OR (d.rejected_kind = 'content' AND f.content_id = d.rejected_id)
        JOIN contents c ON c.id = f.content_id
        JOIN sources s ON s.id = f.source_id
        WHERE d.superseded_at IS NULL AND d.rejected_kind IS NOT NULL AND f.status = 'present'
        ORDER BY s.label, f.rel_path
        """
    ).fetchall()


def _kept_copies(conn: sqlite3.Connection, rejected: set[int]) -> dict[int, int]:
    """For each content, how many present copies no decision rejects."""
    counts: dict[int, int] = {}
    rows = conn.execute(
        "SELECT id, content_id FROM files WHERE status = 'present' AND content_id IS NOT NULL"
    )
    for file_id, content_id in rows:
        if file_id not in rejected:
            counts[content_id] = counts.get(content_id, 0) + 1
    return counts


def classify(conn: sqlite3.Connection, plan_id: int = 0) -> tuple[PlanSummary, list[sqlite3.Row]]:
    """Sort rejected copies into moves, copies that stay, and copies left alone. Read-only."""
    by_file: dict[int, list[sqlite3.Row]] = {}
    for row in _rejected_files(conn):
        by_file.setdefault(row["id"], []).append(row)
    kept = _kept_copies(conn, set(by_file))
    summary, moves = PlanSummary(plan_id), []
    for file_rows in by_file.values():
        row = file_rows[0]
        # Safe when any decision rejecting this copy left its kept picture with a copy.
        if not any(kept.get(r["keeper_content"]) for r in file_rows):
            summary.unsafe.append(f"{row['label']}/{row['rel_path']}")
        elif not (row["quarantine_enabled"] and row["quarantine_path"]):
            summary.stay += 1
            summary.stay_bytes += row["size_bytes"]
        else:
            moves.append(row)
            summary.moves += 1
            summary.move_bytes += row["size_bytes"]
    return summary, moves


def build_plan(conn: sqlite3.Connection) -> PlanSummary:
    """Replace the draft plan with one built from the current decisions."""
    busy = queries.latest(conn, "applying", "incomplete")
    if busy is not None:
        raise PlanError(
            f"Plan {busy['id']} didn't finish. Run `photo-ledger apply` to finish it, "
            "or `photo-ledger undo` to put its files back, before planning again."
        )
    with conn:
        queries.delete_drafts(conn)
        plan_id = queries.insert_plan(conn)
        summary, moves = classify(conn, plan_id)
        for row in moves:
            to_path = QUARANTINE_LAYOUT.format(
                plan_id=plan_id, label=row["label"], rel_path=row["rel_path"]
            )
            queries.insert_action(
                conn,
                plan_id,
                file_id=row["id"],
                op="quarantine",
                from_path=row["rel_path"],
                to_path=str(PurePosixPath(to_path)),
                quarantine_root=row["quarantine_path"],
                quarantine_volume_id=row["quarantine_volume_id"],
                expected_blake3=row["blake3"],
                size_bytes=row["size_bytes"],
            )
    return summary


def draft(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return queries.latest(conn, "draft")


def is_stale(conn: sqlite3.Connection, plan: sqlite3.Row) -> bool:
    """A decision was made or undone after the plan was built, so it needs rebuilding."""
    changed = conn.execute(
        "SELECT MAX(MAX(decided_at), COALESCE(MAX(superseded_at), '')) FROM decisions"
    ).fetchone()[0]
    return bool(changed) and changed > plan["created_at"]
