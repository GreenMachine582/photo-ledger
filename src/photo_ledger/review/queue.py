"""Which pairs a review session shows, and in what order."""

import sqlite3

KIND_ORDER = "CASE kind WHEN 'exact' THEN 0 WHEN 'similar' THEN 1 ELSE 2 END"


def queue(conn: sqlite3.Connection) -> list[int]:
    """Open pairs, exact duplicates first."""
    rows = conn.execute(
        f"SELECT id FROM review_pairs WHERE status = 'open' ORDER BY {KIND_ORDER}, id"
    )
    return [row[0] for row in rows]
