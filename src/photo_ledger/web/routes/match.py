"""Matching from the browser: the same refresh and match as ``photo-ledger match``.

It only reads the catalogue's files and writes pairs and collections back to the catalogue.
Nothing on disk changes. With htmx, the response is the result panel alone, swapped in under
the button. Without htmx, it's the overview with the panel in place.
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.collections.folders import refresh_collections
from photo_ledger.matching import pairs as pair_matching
from photo_ledger.web.deps import get_db, render
from photo_ledger.web.routes.home import overview_context

router = APIRouter()


def match_summary(conn: sqlite3.Connection, threshold: int, generic: list[str]) -> dict:
    collections = refresh_collections(conn, generic)
    result = pair_matching.match(conn, threshold)
    found = [
        (f"{n:,} {kind.replace('_', ' ')}", "neutral") for kind, n in sorted(result.by_kind.items())
    ]
    changes = [
        (f"{result.new:,} new", "good" if result.new else "neutral"),
        (f"{result.reopened:,} reopened", "warn" if result.reopened else "neutral"),
        (f"{result.needs_review:,} need review", "warn" if result.needs_review else "neutral"),
        (f"{result.obsolete:,} closed", "neutral"),
        (f"{result.unchanged:,} unchanged", "neutral"),
    ]
    return {
        "threshold": threshold,
        "found": found,
        "changes": changes,
        "collections": collections,
        "to_review": result.new + result.reopened + result.needs_review,
    }


@router.post("/match", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def run_match(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    settings = request.app.state.settings
    summary = match_summary(
        conn, settings.photo_ledger_similar_threshold, settings.photo_ledger_generic_folders
    )
    if request.headers.get("HX-Request") == "true":
        return render(request, "match_result.html", {"match": summary})
    return render(request, "overview.html", {**overview_context(conn), "match": summary})
