"""The collections page: folder names as collections, renamed, merged or hidden in the ledger."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.collections import editing
from photo_ledger.collections.folders import collection_paths
from photo_ledger.matching.reports import collections_report
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/collections")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "renamed": "Renamed. The new name will survive every rescan.",
    "merged": "Merged, with its folders and sub-collections.",
    "hidden": "Hidden.",
    "shown": "Shown again.",
}


@router.get("", response_class=HTMLResponse)
def collections(
    request: Request, notice: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    ids = {path: collection_id for collection_id, path in collection_paths(conn).items()}
    rows = [
        {
            "id": ids[row[0]],
            "path": row[0],
            "hidden": bool(row[1]),
            "folders": row[2],
            "files": row[3],
            "contents": row[4],
        }
        for row in collections_report(conn).rows
    ]
    return render(
        request,
        "collections.html",
        {
            "rows": rows,
            "options": [(row["id"], row["path"]) for row in rows],
            "notice": NOTICES.get(notice or ""),
        },
    )


@router.post("/rename", dependencies=[Depends(require_csrf)])
def rename(
    collection: int = Form(...), name: str = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    editing.rename(conn, collection, name)
    return RedirectResponse("/collections?notice=renamed", status_code=303)


@router.post("/merge", dependencies=[Depends(require_csrf)])
def merge(
    source: int = Form(...), target: int = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    editing.merge(conn, source, target)
    return RedirectResponse("/collections?notice=merged", status_code=303)


@router.post("/{collection_id}/hidden", dependencies=[Depends(require_csrf)])
def hide(
    collection_id: int, hidden: bool = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    editing.set_hidden(conn, collection_id, hidden)
    notice = "hidden" if hidden else "shown"
    return RedirectResponse(f"/collections?notice={notice}", status_code=303)
