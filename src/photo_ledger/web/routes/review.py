"""The comparison screen: one pair at a time, side by side, driven from the keyboard.

Every decision saves at once and only records what to do: no file is touched here.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.review import decisions
from photo_ledger.review.pairs_view import FIELDS, pair_view
from photo_ledger.review.queue import queue
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/review")

ACTIONS = (
    ("keep_left", "A", "Keep left"),
    ("keep_right", "D", "Keep right"),
    ("keep_both", "B", "Keep both"),
    ("skip", "S", "Skip"),
)


@router.get("", response_class=HTMLResponse)
def review(
    request: Request, pair: int | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    pending = queue(conn)
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
        },
    )


@router.post("/{pair_id}/decide", dependencies=[Depends(require_csrf)])
def decide(
    pair_id: int, action: str = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    decisions.decide(conn, pair_id, action)
    return RedirectResponse("/review", status_code=303)
