"""Which pairs a review session shows, and in what order.

A session is only a set of filters, kept in the page's URL. Decisions belong to pairs, so a pair
resolved in one session or scan is resolved in every other.

- ``scan``: a saved scan's name, or every scan
- ``show``: ``open``, ``new`` (open since the scan last ran), ``skipped`` or ``needs_review``
- ``kind``: ``exact``, ``similar`` or ``name_conflict``, or every kind
- ``matches``: ``any`` (a copy in the scan's sources) or ``inside`` (both sides there)
"""

import sqlite3
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from photo_ledger.matching.sides import Catalogue, scan_source_ids, touches

KIND_ORDER = "CASE kind WHEN 'exact' THEN 0 WHEN 'similar' THEN 1 ELSE 2 END"
SHOW = ("open", "new", "skipped", "needs_review")
KINDS = ("exact", "similar", "name_conflict")
MATCHES = ("any", "inside")
STATUS_FOR = {"open": "open", "new": "open", "skipped": "skipped", "needs_review": "needs_review"}


@dataclass(frozen=True)
class Filters:
    scan: str | None = None
    show: str = "open"
    kind: str | None = None
    matches: str = "any"

    @classmethod
    def parse(cls, scan=None, show=None, kind=None, matches=None) -> "Filters":
        """Filters from query parameters, falling back to the defaults for unknown values."""
        return cls(
            scan=scan or None,
            show=show if show in SHOW else "open",
            kind=kind if kind in KINDS else None,
            matches=matches if matches in MATCHES else "any",
        )

    def query(self, **overrides) -> str:
        """The filters as a query string (with a leading ``?``), leaving out defaults."""
        values = {**asdict(self), **overrides}
        defaults = asdict(Filters())
        kept = {k: v for k, v in values.items() if v is not None and v != defaults.get(k)}
        return "?" + urlencode(kept) if kept else ""


def round_started(conn: sqlite3.Connection, scan: str | None) -> str | None:
    """When the scan's latest round started, or the latest round of any scan."""
    if scan:
        row = conn.execute(
            "SELECT MIN(ss.started_at) FROM scan_sources ss JOIN scans s ON s.id = ss.scan_id"
            " WHERE s.name = ?",
            (scan,),
        ).fetchone()
        return row[0]
    row = conn.execute(
        "SELECT MAX(started) FROM (SELECT MIN(started_at) AS started FROM scan_sources"
        " GROUP BY scan_id)"
    ).fetchone()
    return row[0]


def queue(conn: sqlite3.Connection, filters: Filters = Filters()) -> list[int]:
    """The session's pairs, exact duplicates first, then similar images, then name conflicts."""
    query, params = "SELECT * FROM review_pairs WHERE status = ?", [STATUS_FOR[filters.show]]
    if filters.kind:
        query, params = query + " AND kind = ?", [*params, filters.kind]
    rows = conn.execute(f"{query} ORDER BY {KIND_ORDER}, id", params).fetchall()

    scope = scan_source_ids(conn, filters.scan)
    since = round_started(conn, filters.scan) if filters.show == "new" else None
    if filters.show == "new":
        rows = [row for row in rows if since is not None and row["created_at"] >= since]
    if scope is None:
        return [row["id"] for row in rows]

    catalogue = Catalogue.load(conn)
    found = []
    for row in rows:
        left, right = catalogue.sides(row)
        if filters.matches == "inside":
            in_scope = touches(left, scope) and touches(right, scope) and left and right
        else:
            in_scope = touches(left + right, scope) and (left or right)
        if in_scope:
            found.append(row["id"])
    return found


def counts(conn: sqlite3.Connection, filters: Filters) -> dict[str, int]:
    """How many pairs each ``show`` option holds, for the session's scan, kind and matches."""
    return {show: len(queue(conn, Filters(**{**asdict(filters), "show": show}))) for show in SHOW}
