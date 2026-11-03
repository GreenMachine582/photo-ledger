"""Read-only reports over the catalogue and its pairs.

Each report returns a ``Report`` of columns and rows. With a scan, a report covers anything with
at least one copy in that scan's sources, including its matches in other sources.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from photo_ledger.collections.folders import collection_paths, collections_by_content, folder_of
from photo_ledger.db import collections as collection_queries
from photo_ledger.matching.scoring import best_copy
from photo_ledger.matching.sides import Catalogue, label_path, scan_source_ids, touches

#: File and capture dates further apart than this count as disagreeing. Wide enough for any
#: time zone, since many cameras record local time with no offset.
DATE_TOLERANCE = timedelta(hours=24)


@dataclass
class Report:
    title: str
    columns: tuple[str, ...]
    rows: list[tuple] = field(default_factory=list)
    note: str | None = None


_scope = scan_source_ids
_in_scope = touches
_path = label_path


def _copies(conn):
    catalogue = Catalogue.load(conn)
    return list(catalogue.by_id.values()), catalogue.by_id, catalogue.by_content


def pairs_report(
    conn: sqlite3.Connection,
    scan: str | None = None,
    kind: str | None = None,
    status: str | None = "open",
) -> Report:
    """Pairs with their suggested keeper and its reasons."""
    scope = _scope(conn, scan)
    catalogue = Catalogue.load(conn)
    report = Report(
        "Pairs",
        (
            "id",
            "kind",
            "status",
            "distance",
            "left",
            "right",
            "keep",
            "because",
            "against",
            "collections",
        ),
    )
    inherited = collections_by_content(conn)
    query, params = "SELECT * FROM review_pairs WHERE 1 = 1", []
    if kind:
        query, params = query + " AND kind = ?", [*params, kind]
    if status:
        query, params = query + " AND status = ?", [*params, status]
    for pair in conn.execute(query + " ORDER BY kind, id", params):
        sides = catalogue.sides(pair)
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
                "; ".join(
                    sorted(
                        set().union(
                            *(inherited.get(f["content_id"], set()) for f in sides[0] + sides[1])
                        )
                    )
                ),
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


def collections_report(conn: sqlite3.Connection, scan: str | None = None) -> Report:
    """Collections from folder names, with what maps to each directly."""
    scope = _scope(conn, scan)
    report = Report("Collections", ("collection", "hidden", "folders", "files", "contents"))
    paths = collection_paths(conn)
    mapped = collection_queries.mapped_folders(conn)
    folders, files, contents = defaultdict(set), defaultdict(int), defaultdict(set)
    for (source_id, folder), collection_id in mapped.items():
        if scope is None or source_id in scope:
            folders[collection_id].add((source_id, folder))
    for content_id, source_id, rel_path in collection_queries.content_files(conn):
        collection_id = mapped.get((source_id, folder_of(rel_path)))
        if collection_id is not None and (scope is None or source_id in scope):
            files[collection_id] += 1
            contents[collection_id].add(content_id)
    hidden = {row["id"]: bool(row["hidden"]) for row in collection_queries.all_collections(conn)}
    for collection_id, path in sorted(paths.items(), key=lambda item: item[1].casefold()):
        if (
            scope is not None
            and not folders[collection_id]
            and not any(
                other.startswith(path + "/") and folders[cid] for cid, other in paths.items()
            )
        ):
            continue
        report.rows.append(
            (
                path,
                "yes" if hidden[collection_id] else "",
                len(folders[collection_id]),
                files[collection_id],
                len(contents[collection_id]),
            )
        )
    return report


REPORTS = {
    "summary": summary_report,
    "pairs": pairs_report,
    "renamed": renamed_report,
    "dates": dates_report,
    "single-source": single_source_report,
    "corrupt": corrupt_report,
    "collections": collections_report,
}
