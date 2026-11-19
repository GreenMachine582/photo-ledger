"""Matching from the browser: the same run as ``photo-ledger match`` (``matching/run.py``).

It only reads the catalogue's files and writes pairs, collections and the rules' decisions back to
the catalogue. Nothing on disk changes. With htmx, the response is the result panel alone,
swapped in under the button. Without htmx, it's the overview with the panel in place.
"""

import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger import preferences
from photo_ledger.matching.run import automatic_lines, run_match
from photo_ledger.preferences import Preferences
from photo_ledger.web.deps import get_db, record, render
from photo_ledger.web.routes.home import overview_context

router = APIRouter()


def match_summary(request: Request, conn: sqlite3.Connection, prefs: Preferences) -> dict:
    run = run_match(conn, prefs)
    result = run.pairs
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
    decided = automatic_lines(run.automatic)
    if decided:
        record(
            request,
            "match.automatic",
            "Decided automatically: " + ", ".join(decided) + ". Nothing moves until a plan is "
            "applied.",
            link=("Settings", "/settings"),
            details=asdict(run.automatic),
        )
    return {
        "threshold": prefs.similar_threshold,
        "found": found,
        "changes": changes,
        "automatic": [(line, "good") for line in decided],
        "collections": run.collections,
        "to_review": result.new + result.reopened + result.needs_review,
    }


@router.post("/match", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def run_match_route(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    prefs = preferences.effective(conn, request.app.state.settings)
    summary = match_summary(request, conn, prefs)
    if request.headers.get("HX-Request") == "true":
        return render(request, "match_result.html", {"match": summary})
    return render(request, "overview.html", {**overview_context(conn), "match": summary})
