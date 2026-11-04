"""The library page: choose its folder and layout, plan it and build it.

Everything goes through ``library`` and the executor, the same as ``photo-ledger library``.
Viewing the page only reads: its dry run is the read-only ``check_library``. Planning writes only
to the catalogue, and building copies files through ``actions/executor.py``, never changing an
original.
"""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.actions import executor, recovery
from photo_ledger.db import library as queries
from photo_ledger.formatting import human_size
from photo_ledger.library import plan as library_plan
from photo_ledger.library import settings as library_settings
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/library")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "set": "Library saved. Nothing is created until you build: plan it to see what it would copy.",
    "planned": "Planned. Only the catalogue changed: build to copy the pictures.",
    "built": "Built. Every copy was verified by its hash, and no original changed.",
    "incomplete": "Some copies failed, and nothing was left half-written. See the failures below.",
    "problems": "The dry run found problems, so nothing was copied. See them below.",
}


def page_context(conn: sqlite3.Connection) -> dict:
    library = queries.get(conn)
    context = {"library": None, "layouts": library_settings.LAYOUTS}
    if library is None:
        return context
    online = library_settings.library_online(library)
    counts = queries.counts(conn)
    to_build = counts.get("pending", 0) + counts.get("failed", 0)
    summary = library_plan.preview(conn)
    problems = library_plan.check_library(conn) if to_build else []
    context.update(
        library=library,
        online=online,
        summary=summary,
        to_copy_size=human_size(summary.to_copy_bytes),
        to_build=to_build,
        problems=problems,
        failed=[
            {"where": f"{e['source_label']}/{e['source_rel_path']}", "error": e["error"] or ""}
            for e in queries.entries(conn, "failed")
        ],
        can_build=bool(to_build and online and not problems),
        cards=[
            {"label": "Built", "value": f"{counts.get('done', 0):,}"},
            {"label": "Planned to copy", "value": f"{to_build:,}"},
            {"label": "Not planned yet", "value": f"{max(summary.to_copy - to_build, 0):,}"},
            {"label": "Waiting for review", "value": f"{summary.waiting:,}"},
        ],
    )
    return context


def _done(notice: str) -> RedirectResponse:
    return RedirectResponse(f"/library?notice={notice}", status_code=303)


@router.get("", response_class=HTMLResponse)
def library_page(
    request: Request, notice: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    return render(
        request, "library.html", {**page_context(conn), "notice": NOTICES.get(notice or "")}
    )


@router.post("", dependencies=[Depends(require_csrf)])
def set_library(
    path: str = Form(...), layout: str = Form("year"), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    library_settings.set_library(conn, Path(path.strip()), layout)
    return _done("set")


@router.post("/plan", dependencies=[Depends(require_csrf)])
def plan(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    library_plan.plan_library(conn)
    return _done("planned")


@router.post("/build", dependencies=[Depends(require_csrf)])
def build(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    """Build after the page's confirm step, and only after a clean dry run, as the CLI does."""
    recovery.recover(conn)
    library_plan.plan_library(conn)
    if library_plan.check_library(conn):
        return _done("problems")
    result = executor.build_library(conn)
    return _done("built" if result.status == "complete" else "incomplete")
