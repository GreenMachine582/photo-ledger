"""The comparison screen: one pair at a time, side by side, driven from the keyboard.

A review session is a set of filters kept in the URL: a scan or all scans, which pairs to show,
a kind, and whether matches must sit inside the scan. Every decision saves at once and only
records what to do: no file is touched here.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.review import decisions
from photo_ledger.review.pairs_view import FIELDS, pair_view
from photo_ledger.review.queue import KINDS, Filters, counts, queue
from photo_ledger.scanner.engine import get_scan, list_scans
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/review")

ACTIONS = (
    ("keep_left", "A", "Keep left"),
    ("keep_right", "D", "Keep right"),
    ("keep_both", "B", "Keep both"),
    ("skip", "S", "Skip"),
)
SHOW_LABELS = {
    "open": "Open",
    "new": "New since the scan last ran",
    "skipped": "Skipped",
    "needs_review": "Needs review",
}
EMPTY = {
    "open": "Nothing left to review here. Run `photo-ledger match` after a scan to find more.",
    "new": "No new pairs since this scan last ran.",
    "skipped": "Nothing skipped.",
    "needs_review": "Nothing needs another look.",
}


def _filters(
    scan: str | None = None,
    show: str | None = None,
    kind: str | None = None,
    matches: str | None = None,
) -> Filters:
    return Filters.parse(scan=scan, show=show, kind=kind, matches=matches)


@router.get("", response_class=HTMLResponse)
def review(
    request: Request,
    pair: int | None = None,
    filters: Filters = Depends(_filters),
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    if filters.scan:
        get_scan(conn, filters.scan)  # an unknown scan is explained, not ignored
    pending = queue(conn, filters)
    current = pair if pair is not None else (pending[0] if pending else None)
    view = pair_view(conn, current) if current is not None else None
    position = pending.index(current) + 1 if current in pending else None
    return render(
        request,
        "review.html",
        {
            "view": view,
            "fields": FIELDS,
            "actions": ACTIONS,
            "position": position,
            "total": len(pending),
            "filters": filters,
            "query": filters.query(),
            "counts": counts(conn, filters),
            "show_labels": SHOW_LABELS,
            "kinds": KINDS,
            "scans": [row["name"] for row in list_scans(conn)],
            "empty_message": EMPTY[filters.show],
            "can_undo": bool(decisions.decision_counts(conn)),
        },
    )


@router.post("/{pair_id}/decide", dependencies=[Depends(require_csrf)])
def decide(
    pair_id: int,
    action: str = Form(...),
    filters: Filters = Depends(_filters),
    conn: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    decisions.decide(conn, pair_id, action)
    return RedirectResponse("/review" + filters.query(), status_code=303)


@router.post("/undo", dependencies=[Depends(require_csrf)])
def undo(
    filters: Filters = Depends(_filters), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    pair_id = decisions.undo_last(conn)
    query = filters.query(pair=pair_id) if pair_id is not None else filters.query()
    return RedirectResponse("/review" + query, status_code=303)
