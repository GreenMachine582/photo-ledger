"""The overview page's numbers: what's catalogued, how much is duplicated, and review progress."""

import sqlite3
from dataclasses import dataclass, field

from photo_ledger.sources import service as source_service


@dataclass
class Overview:
    files: int = 0
    contents: int = 0
    reclaimable_bytes: int = 0
    marked_bytes: int = 0
    pairs: dict[str, int] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    scans: list[dict] = field(default_factory=list)


def overview(conn: sqlite3.Connection) -> Overview:
    result = Overview()
    present = conn.execute("SELECT COUNT(*) FROM files WHERE status != 'missing'")
    result.files = present.fetchone()[0]
    result.contents = conn.execute(
        "SELECT COUNT(DISTINCT content_id) FROM files WHERE status = 'present'"
    ).fetchone()[0]
    # Every copy beyond the first of a content, at present: the most a clean-up could free.
    result.reclaimable_bytes = conn.execute(
        """
        SELECT COALESCE(SUM(size_bytes * (copies - 1)), 0) FROM (
            SELECT MAX(size_bytes) AS size_bytes, COUNT(*) AS copies FROM files
            WHERE status = 'present' AND content_id IS NOT NULL
            GROUP BY content_id HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    # Copies the active decisions reject: what a plan would act on.
    result.marked_bytes = conn.execute(
        """
        SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f
        WHERE f.status != 'missing' AND (
            f.id IN (SELECT rejected_id FROM decisions
                     WHERE superseded_at IS NULL AND rejected_kind = 'file')
            OR f.content_id IN (SELECT rejected_id FROM decisions
                                WHERE superseded_at IS NULL AND rejected_kind = 'content'))
        """
    ).fetchone()[0]
    result.pairs = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM review_pairs GROUP BY status"
        ).fetchall()
    }
    for source in conn.execute(
        """
        SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.source_id = s.id
                     AND f.status != 'missing') AS file_count,
               (SELECT MAX(finished_at) FROM scan_sources ss WHERE ss.source_id = s.id) AS last_scan
        FROM sources s ORDER BY s.label
        """
    ).fetchall():
        result.sources.append(
            {
                "label": source["label"],
                "online": source_service.is_online(source),
                "type": source["source_type"],
                "files": source["file_count"],
                "last_scan": (source["last_scan"] or "")[:16].replace("T", " "),
                "root": source["root_path"],
            }
        )
    for scan in conn.execute(
        """
        SELECT s.name, s.status, group_concat(src.label, ', ') AS labels
        FROM scans s JOIN scan_sources ss ON ss.scan_id = s.id
        JOIN sources src ON src.id = ss.source_id
        GROUP BY s.id ORDER BY s.created_at
        """
    ).fetchall():
        result.scans.append(dict(scan))
    return result
