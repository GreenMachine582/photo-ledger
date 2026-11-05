"""The Photos page: find one photo and its copies, and set or clear its capture date.

Searching only reads. Setting or clearing a date writes only ``date_fixes`` in the catalogue, the
same as ``photo-ledger date set|clear``. A date belongs to the picture, so every copy shares it.
Originals are never touched. The library copy picks the date up at the next library build.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.db import catalogue as queries
from photo_ledger.library import dates
from photo_ledger.web.deps import get_db, notify, render

router = APIRouter(prefix="/catalogue")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "set": "Date saved for every copy. Originals don't change: the next library build applies it "
    "to the library copy and its sidecar.",
    "cleared": "Forgot the date you set. The photo goes back to its EXIF date, or undated.",
    "nothing": "This photo had no date set by hand.",
}


@router.get("", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    undated: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    searched = bool(q.strip()) or undated
    rows = queries.search(conn, q, undated) if searched else []
    return render(
        request,
        "catalogue.html",
        {"q": q, "undated": undated, "searched": searched, "rows": rows},
    )


@router.get("/{content_id}", response_class=HTMLResponse)
def photo(
    request: Request,
    content_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    row = queries.photo(conn, content_id)
    if row is None:
        raise HTTPException(404, "No such photo")
    copies = queries.copies(conn, content_id)
    return render(
        request,
        "catalogue_photo.html",
        {
            "photo": row,
            "copies": copies,
            "preview_id": next((c["file_id"] for c in copies if c["status"] != "missing"), None),
        },
    )


def _done(content_id: int, notice: str) -> RedirectResponse:
    return notify(f"/catalogue/{content_id}", NOTICES, notice)


@router.post("/{content_id}/date", dependencies=[Depends(require_csrf)])
def set_date(
    content_id: int, value: str = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    dates.set_content_date(conn, content_id, value)
    return _done(content_id, "set")


@router.post("/{content_id}/date/clear", dependencies=[Depends(require_csrf)])
def clear_date(content_id: int, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    return _done(content_id, "cleared" if dates.clear_content_date(conn, content_id) else "nothing")
