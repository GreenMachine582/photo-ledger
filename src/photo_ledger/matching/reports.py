"""Read-only reports over the catalogue and its pairs.

Each report returns a ``Report`` of columns and rows. With a scan, a report covers anything with
at least one copy in that scan's sources, including its matches in other sources.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from photo_ledger.db import pairs as pair_queries
from photo_ledger.matching.scoring import best_copy
from photo_ledger.scanner.engine import get_scan

#: File and capture dates further apart than this count as disagreeing. Wide enough for any
#: time zone, since many cameras record local time with no offset.
DATE_TOLERANCE = timedelta(hours=24)


@dataclass
class Report:
    title: str
    columns: tuple[str, ...]
    rows: list[tuple] = field(default_factory=list)
    note: str | None = None


def _scope(conn: sqlite3.Connection, scan: str | None) -> set[int] | None:
    if scan is None:
        return None
    scan_id = get_scan(conn, scan)["id"]
    rows = conn.execute("SELECT source_id FROM scan_sources WHERE scan_id = ?", (scan_id,))
    return {row[0] for row in rows}


def _in_scope(files, scope) -> bool:
    return scope is None or any(f["source_id"] in scope for f in files)


def _path(row) -> str:
    return f"{row['source_label']}/{row['rel_path']}"


def _copies(conn):
    files = pair_queries.eligible_files(conn)
    by_id = {row["id"]: row for row in files}
    by_content = defaultdict(list)
    for row in files:
        by_content[row["content_id"]].append(row)
    return files, by_id, by_content


def pairs_report(
    conn: sqlite3.Connection,
    scan: str | None = None,
    kind: str | None = None,
    status: str | None = "open",
) -> Report:
    """Pairs with their suggested keeper and its reasons."""
    scope = _scope(conn, scan)
    _, by_id, by_content = _copies(conn)
    report = Report(
        "Pairs",
        ("id", "kind", "status", "distance", "left", "right", "keep", "because", "against"),
    )
    query, params = "SELECT * FROM review_pairs WHERE 1 = 1", []
    if kind:
        query, params = query + " AND kind = ?", [*params, kind]
    if status:
        query, params = query + " AND status = ?", [*params, status]
    for pair in conn.execute(query + " ORDER BY kind, id", params):
        if pair["kind"] == "exact":
            sides = [[by_id[i]] if i in by_id else [] for i in (pair["left_id"], pair["right_id"])]
        else:
            sides = [by_content.get(pair["left_id"], []), by_content.get(pair["right_id"], [])]
        if not all(sides) or not _in_scope(sides[0] + sides[1], scope):
            continue  # an obsolete pair whose copies are gone, or out of scope
        names = []
        for files in sides:
            others = len(files) - 1
            extra = f" (+{others} {'copy' if others == 1 else 'copies'})" if others else ""
            names.append(_path(best_copy(files)) + extra)
        score = json.loads(pair["score_reasons"]) if pair["score_reasons"] else {}
        report.rows.append(
            (
                pair["id"],
                pair["kind"],
                pair["status"],
                pair["distance"],
                names[0],
                names[1],
                score.get("keep") or "",
                "; ".join(score.get("reasons", [])),
                "; ".join(score.get("against", [])),
            )
        )
    return report


def renamed_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """The same content under different filenames or in different folders."""
    scope = _scope(conn, scan)
    _, _, by_content = _copies(conn)
    report = Report(
        "Same content, different name or folder", ("blake3", "copies", "names", "paths")
    )
    for files in by_content.values():
        if len(files) < 2 or not _in_scope(files, scope):
            continue
        names = sorted({f["filename"] for f in files})
        folders = {f["rel_path"].rpartition("/")[0] for f in files}
        if len(names) > 1 or len(folders) > 1:
            report.rows.append(
                (
                    files[0]["blake3"][:16],
                    len(files),
                    "; ".join(names),
                    "; ".join(sorted(map(_path, files))),
                )
            )
    report.rows.sort(key=lambda row: row[3])
    return report


def _capture_utc(captured_at: str, offset: str | None) -> datetime:
    moment = datetime.fromisoformat(captured_at)
    if offset:
        try:
            sign = -1 if offset.startswith("-") else 1
            hours, minutes = offset.lstrip("+-").split(":")
            return (moment - sign * timedelta(hours=int(hours), minutes=int(minutes))).replace(
                tzinfo=UTC
            )
        except ValueError:
            pass
    return moment.replace(tzinfo=UTC)


def dates_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """Files whose file date disagrees with their EXIF capture date, as after a restore."""
    scope = _scope(conn, scan)
    report = Report(
        "File date and capture date disagree",
        ("path", "captured_at", "capture_date_source", "file_date_utc", "difference_days"),
    )
    rows = conn.execute(
        """
        SELECT f.source_id, f.rel_path, f.mtime_ns, s.label AS source_label, c.captured_at,
               c.capture_offset, c.capture_date_source
        FROM files f JOIN contents c ON c.id = f.content_id JOIN sources s ON s.id = f.source_id
        WHERE f.status IN ('present', 'corrupt') AND c.captured_at IS NOT NULL
        ORDER BY s.label, f.rel_path
        """
    )
    for row in rows:
        if scope is not None and row["source_id"] not in scope:
            continue
        captured = _capture_utc(row["captured_at"], row["capture_offset"])
        file_date = datetime.fromtimestamp(row["mtime_ns"] / 1e9, tz=UTC)
        difference = abs(file_date - captured)
        if difference > DATE_TOLERANCE:
            report.rows.append(
                (
                    _path(row),
                    row["captured_at"] + (row["capture_offset"] or ""),
                    row["capture_date_source"],
                    file_date.isoformat(timespec="seconds"),
                    round(difference.total_seconds() / 86400, 1),
                )
            )
    return report


def single_source_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """Content seen in only one source. Neutral: backups often cover different periods."""
    scope = _scope(conn, scan)
    report = Report("Seen in only one source", ("source", "paths", "blake3"))
    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    if source_count < 2:
        report.note = "Only one source is mapped, so every file is in only one source."
        return report
    _, _, by_content = _copies(conn)
    for files in by_content.values():
        labels = {f["source_label"] for f in files}
        if len(labels) == 1 and _in_scope(files, scope):
            report.rows.append(
                (
                    labels.pop(),
                    "; ".join(sorted(f["rel_path"] for f in files)),
                    files[0]["blake3"][:16],
                )
            )
    report.rows.sort()
    report.note = "Not a claim that anything is missing: backups often cover different periods."
    return report


def corrupt_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """Files that failed to decode or couldn't be read, for checking by hand."""
    scope = _scope(conn, scan)
    report = Report("Corrupt or unreadable", ("path", "status", "error"))
    rows = conn.execute(
        """
        SELECT f.source_id, f.rel_path, f.status, s.label AS source_label, c.decode_error,
               (SELECT e.message FROM scan_errors e
                WHERE e.source_id = f.source_id AND e.rel_path = f.rel_path
                ORDER BY e.id DESC LIMIT 1) AS last_error
        FROM files f JOIN sources s ON s.id = f.source_id
        LEFT JOIN contents c ON c.id = f.content_id
        WHERE f.status IN ('corrupt', 'unreadable')
        ORDER BY s.label, f.rel_path
        """
    )
    for row in rows:
        if scope is None or row["source_id"] in scope:
            report.rows.append(
                (_path(row), row["status"], row["decode_error"] or row["last_error"] or "")
            )
    return report


def summary_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """Counts of files, contents and pairs, as a starting point."""
    scope = _scope(conn, scan)
    report = Report("Summary", ("measure", "value"))
    where, params = "", ()
    if scope is not None:
        where = f"WHERE source_id IN ({','.join('?' * len(scope))})"
        params = tuple(scope)
    for row in conn.execute(
        f"SELECT status, COUNT(*) AS n, SUM(size_bytes) AS bytes FROM files {where}"
        " GROUP BY status ORDER BY status",
        params,
    ):
        report.rows.append((f"files {row['status']}", row["n"]))
    contents = conn.execute(
        f"SELECT COUNT(DISTINCT content_id) FROM files {where}"
        + (" AND" if where else " WHERE")
        + " content_id IS NOT NULL",
        params,
    ).fetchone()[0]
    report.rows.append(("unique contents", contents))
    for kind in ("exact", "similar", "name_conflict"):
        rows = pairs_report(conn, scan, kind=kind, status=None).rows
        by_status = defaultdict(int)
        for row in rows:
            by_status[row[2]] += 1
        for status in sorted(by_status):
            report.rows.append((f"{kind} pairs {status}", by_status[status]))
    for name, builder in (
        ("same content, different name or folder", renamed_report),
        ("date disagreements", dates_report),
        ("seen in only one source", single_source_report),
        ("corrupt or unreadable", corrupt_report),
    ):
        report.rows.append((name, len(builder(conn, scan).rows)))
    return report


REPORTS = {
    "summary": summary_report,
    "pairs": pairs_report,
    "renamed": renamed_report,
    "dates": dates_report,
    "single-source": single_source_report,
    "corrupt": corrupt_report,
}
