"""The Settings page: what a match finds, and which obvious pairs it decides by itself.

Saving writes only the catalogue's ``settings`` table, and a saved value wins over the
``PHOTO_LEDGER_*`` environment variable. Everything applies at the next match. Reopening the
automatic decisions only changes decisions. Nothing on disk changes here.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger import preferences
from photo_ledger.collections.folders import DEFAULT_GENERIC_FOLDERS
from photo_ledger.review import decisions
from photo_ledger.web.deps import get_db, notify, render

router = APIRouter(prefix="/settings")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "saved": "Settings saved. They apply at the next match: run it from the Overview.",
    "reset": "Back to the defaults. They apply at the next match.",
    "nothing": "Nothing was saved, so the defaults already apply.",
    "reopened": "The automatic decisions are back on the review page. No rule will make them "
    "again.",
    "none-automatic": "There were no automatic decisions to reopen.",
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
            "max_side": preferences.MIN_SIDE_MAX,
            "default_folders": ", ".join(DEFAULT_GENERIC_FOLDERS),
            "automatic": decisions.automatic_count(conn),
        },
    )


@router.post("", dependencies=[Depends(require_csrf)])
def save(
    similar_threshold: str = Form(...),
    generic_folders: str = Form(""),
    min_similar_side: str | None = Form(None),
    name_conflicts: str | None = Form(None),
    auto_tidier_path: str | None = Form(None),
    auto_priority: str | None = Form(None),
    dismiss_unlike_names: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    # Each switch sends "false", then "true" when it's on, and the last value wins. A field
    # that isn't sent at all keeps what was saved.
    switches = {
        "name_conflicts": name_conflicts,
        "auto_tidier_path": auto_tidier_path,
        "auto_priority": auto_priority,
        "dismiss_unlike_names": dismiss_unlike_names,
    }
    preferences.save(
        conn,
        similar_threshold=similar_threshold,
        generic_folders=generic_folders,
        min_similar_side=min_similar_side,
        **{key: value for key, value in switches.items() if value is not None},
    )
    return notify("/settings", NOTICES, "saved")


@router.post("/reset", dependencies=[Depends(require_csrf)])
def reset(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    return notify("/settings", NOTICES, "reset" if preferences.reset(conn) else "nothing")


@router.post("/reopen-automatic", dependencies=[Depends(require_csrf)])
def reopen_automatic(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    reopened = decisions.reopen_automatic(conn)
    return notify("/settings", NOTICES, "reopened" if reopened else "none-automatic")
