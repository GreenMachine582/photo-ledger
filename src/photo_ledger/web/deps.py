"""Request dependencies: one catalogue connection per request, page rendering and results.

A state-changing route answers with ``notify``: a redirect that carries its result as a flash, so
it shows as a toast on the next page and never as text in the URL.
"""

import sqlite3
from collections.abc import Iterator

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from greentechhub_fastapi.flash import FLASH_COOKIE_NAME, flash, get_flashes

from photo_ledger.db import open_db


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = open_db(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


#: Results that went wrong, shown as warnings rather than successes.
WARNINGS = {"incomplete", "problems", "undo-incomplete", "offline", "nothing"}


def notify(url: str, notices: dict[str, str], key: str) -> RedirectResponse:
    """Redirect to ``url`` with the fixed message ``notices[key]`` as a toast."""
    response = RedirectResponse(url, status_code=303)
    flash(response, notices[key], kind="warning" if key in WARNINGS else "success")
    return response


def render(request: Request, template: str, context: dict, status_code: int = 200):
    """A page, with any waiting flashes as toasts. An htmx partial leaves them for the next page."""
    partial = request.headers.get("HX-Request") == "true" and not request.headers.get("HX-Boosted")
    waiting = FLASH_COOKIE_NAME in request.cookies and not partial
    flashes = get_flashes(request, Response()) if waiting else []
    response = request.app.state.templates.TemplateResponse(
        request,
        template,
        {**context, "flashes": [{"message": f.message, "kind": f.kind} for f in flashes]},
        status_code=status_code,
    )
    if waiting:
        response.delete_cookie(
            FLASH_COOKIE_NAME, httponly=True, secure=True, samesite="lax", path="/"
        )
    return response
