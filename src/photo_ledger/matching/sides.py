"""The copies on each side of a pair, shared by reports and the review screen.

An exact pair compares two files. A similar or name-conflict pair compares two contents, so each
side is every catalogued copy of its content.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from photo_ledger.db import pairs as pair_queries
from photo_ledger.scanner.engine import get_scan


@dataclass
class Catalogue:
    """The copies that take part in matching, by file ID and by content ID."""

    by_id: dict[int, sqlite3.Row]
    by_content: dict[int, list[sqlite3.Row]]

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "Catalogue":
        files = pair_queries.eligible_files(conn)
        by_content: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in files:
            by_content[row["content_id"]].append(row)
        return cls(by_id={row["id"]: row for row in files}, by_content=dict(by_content))

    def sides(self, pair) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
        """Each side's copies. A side is empty when its copies are no longer catalogued."""
        if pair["kind"] == "exact":
            left = [self.by_id[pair["left_id"]]] if pair["left_id"] in self.by_id else []
            right = [self.by_id[pair["right_id"]]] if pair["right_id"] in self.by_id else []
            return left, right
        return (
            list(self.by_content.get(pair["left_id"], [])),
            list(self.by_content.get(pair["right_id"], [])),
        )


def scan_source_ids(conn: sqlite3.Connection, scan: str | None) -> set[int] | None:
    """The source IDs in a scan, or ``None`` for every source."""
    if scan is None:
        return None
    scan_id = get_scan(conn, scan)["id"]
    rows = conn.execute("SELECT source_id FROM scan_sources WHERE scan_id = ?", (scan_id,))
    return {row[0] for row in rows}


def touches(files, scope: set[int] | None) -> bool:
    """At least one copy is in scope."""
    return scope is None or any(f["source_id"] in scope for f in files)


def label_path(row) -> str:
    return f"{row['source_label']}/{row['rel_path']}"
