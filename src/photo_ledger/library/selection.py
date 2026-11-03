"""Which pictures are settled, and which copy of each goes into the library. Read-only.

A picture (a content) is settled when no decision rejects it and none of its pairs is still
``open``, ``skipped`` or ``needs_review``, so the library never holds an undecided duplicate.
Its copy is the best of its present copies that no decision rejects, chosen by the same
``best_copy`` rule the reports use: higher source priority, then the tidiest path.
"""

import sqlite3
from dataclasses import dataclass, field

from photo_ledger.matching.scoring import best_copy
from photo_ledger.review.decisions import rejected_items

#: Pair statuses that mean the review isn't finished.
UNSETTLED = ("open", "skipped", "needs_review")


@dataclass
class Selection:
    #: The chosen copy of each settled picture, by content ID.
    chosen: dict[int, sqlite3.Row] = field(default_factory=dict)
    #: Pictures with an unfinished pair, by content ID.
    waiting: set[int] = field(default_factory=set)
    rejected: int = 0
    #: Pictures whose only copies can't be decoded.
    corrupt: int = 0


def _present_copies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT f.id, f.source_id, f.content_id, f.rel_path, f.filename, f.size_bytes, f.mtime_ns,
               f.status, s.label AS source_label, s.priority AS source_priority, c.blake3,
               c.captured_at, c.capture_offset
        FROM files f
        JOIN sources s ON s.id = f.source_id
        JOIN contents c ON c.id = f.content_id
        WHERE f.status IN ('present', 'corrupt')
        ORDER BY f.content_id, f.id
        """
    ).fetchall()


def _waiting(conn: sqlite3.Connection) -> set[int]:
    marks = ",".join("?" * len(UNSETTLED))
    waiting = set()
    for kind, left, right in conn.execute(
        f"SELECT kind, left_id, right_id FROM review_pairs WHERE status IN ({marks})", UNSETTLED
    ):
        if kind == "exact":
            # Exact pairs hold file IDs; both files share one content.
            row = conn.execute("SELECT content_id FROM files WHERE id = ?", (left,)).fetchone()
            if row and row[0] is not None:
                waiting.add(row[0])
        else:
            waiting.update((left, right))
    return waiting


def settled_pictures(conn: sqlite3.Connection) -> Selection:
    result = Selection()
    rejected_files, rejected_contents = set(), set()
    for kind, item_id in rejected_items(conn):
        (rejected_files if kind == "file" else rejected_contents).add(item_id)
    waiting = _waiting(conn)

    by_content: dict[int, list[sqlite3.Row]] = {}
    for row in _present_copies(conn):
        by_content.setdefault(row["content_id"], []).append(row)
    for content_id, copies in by_content.items():
        if content_id in rejected_contents:
            result.rejected += 1
            continue
        kept = [c for c in copies if c["id"] not in rejected_files]
        if not kept:
            result.rejected += 1
            continue
        readable = [c for c in kept if c["status"] == "present"]
        if not readable:
            result.corrupt += 1
            continue
        if content_id in waiting:
            result.waiting.add(content_id)
            continue
        result.chosen[content_id] = best_copy(readable)
    return result
