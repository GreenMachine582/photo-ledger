"""The Settings page: the similar threshold and the generic folder names a match uses.

Saving writes only the catalogue's ``settings`` table, and a saved value wins over the
``PHOTO_LEDGER_*`` environment variable. Both apply at the next match. Nothing on disk changes.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger import preferences
from photo_ledger.collections.folders import DEFAULT_GENERIC_FOLDERS
from photo_ledger.web.deps import get_db, notify, render

router = APIRouter(prefix="/settings")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "saved": "Settings saved. They apply at the next match: run it from the Overview.",
    "reset": "Back to the defaults. They apply at the next match.",
    "nothing": "Nothing was saved, so the defaults already apply.",
}


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    prefs = preferences.effective(conn, request.app.state.settings)
    return render(
        request,
        "settings.html",
        {
            "prefs": prefs,
            "minimum": preferences.THRESHOLD_MIN,
            "maximum": preferences.THRESHOLD_MAX,
            "default_folders": ", ".join(DEFAULT_GENERIC_FOLDERS),
        },
    )


@router.post("", dependencies=[Depends(require_csrf)])
def save(
    similar_threshold: str = Form(...),
    generic_folders: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    preferences.save(conn, similar_threshold=similar_threshold, generic_folders=generic_folders)
    return notify("/settings", NOTICES, "saved")


@router.post("/reset", dependencies=[Depends(require_csrf)])
def reset(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    return notify("/settings", NOTICES, "reset" if preferences.reset(conn) else "nothing")
