"""The library page: choose its folder and layout, plan it and build it.

Everything goes through ``library`` and the executor, the same as ``photo-ledger library``.
Viewing the page only reads: its dry run is the read-only ``check_library``. Planning writes only
to the catalogue, and building copies files through ``actions/executor.py``, never changing an
original.
"""

import asyncio
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from greentechhub_core.background import JobAlreadyRunning
from greentechhub_fastapi.auth.csrf import require_csrf
from greentechhub_fastapi.flash import flash
from greentechhub_fastapi.jobs import get_job_runner

from photo_ledger.actions import recovery
from photo_ledger.db import library as queries
from photo_ledger.db import open_db
from photo_ledger.formatting import human_size
from photo_ledger.library import plan as library_plan
from photo_ledger.library import settings as library_settings
from photo_ledger.library.build_job import BUILD_KIND, build_job
from photo_ledger.web.deps import get_db, notify, render

router = APIRouter(prefix="/library")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "set": "Library saved. Nothing is created until you build: plan it to see what it would copy.",
    "planned": "Planned. Only the catalogue changed: build to copy the pictures.",
    "built": "Built. Every copy was verified by its hash, and no original changed.",
    "incomplete": "Some copies failed, and nothing was left half-written. See the failures below.",
    "problems": "The dry run found problems, so nothing was copied. See them below.",
    "building": "Building. It carries on if you leave this page, and its result shows here.",
}
SAFE = "Nothing was left half-written, and no original changed."


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
    return notify("/library", NOTICES, notice)


@router.get("", response_class=HTMLResponse)
async def library_page(request: Request) -> HTMLResponse:
    state = await _build_state(request)
    building = state if state is not None and state["active"] else None
    conn = open_db(request.app.state.settings.db_path)  # async: its own connection, in this thread
    try:
        return render(request, "library.html", {**page_context(conn), "building": building})
    finally:
        conn.close()


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
async def build(request: Request) -> Response:
    """Build after the page's confirm step, as a background job. The popup's htmx form gets the
    progress partial back; a plain form goes back to the page, which shows the same progress.

    The dry run comes first, here, so one with problems (an offline library, say) is refused at
    once, as before. The job checks again before it copies anything."""
    if await asyncio.to_thread(_dry_run_problems, request.app.state.settings.db_path):
        return _done("problems")
    try:
        await get_job_runner(request).start(
            BUILD_KIND,
            build_job(request.app.state.settings.db_path),
            label="Build the library",
            unique=True,
        )
    except JobAlreadyRunning:
        pass  # already building: show that build
    if request.headers.get("HX-Request") != "true":
        return _done("building")
    return render(request, "build_progress.html", {"build": await _build_state(request)})


@router.get("/build/progress", response_class=HTMLResponse)
async def build_progress(request: Request) -> Response:
    """The popup's live part. Once the build ends, the page reloads with its result."""
    state = await _build_state(request)
    if state is not None and state["active"]:
        return render(request, "build_progress.html", {"build": state})
    if state is None:
        return RedirectResponse("/library", status_code=303)
    if state["error"]:
        response = RedirectResponse("/library", status_code=303)
        flash(response, f"The build stopped with an error: {state['error']}. {SAFE}", kind="danger")
        return response
    outcome = state["result"].get("status")
    return _done({"complete": "built", "problems": "problems"}.get(outcome, "incomplete"))


def _dry_run_problems(db_path) -> bool:
    """Finish any interrupted copy, plan, and dry-run, on a connection of this worker thread."""
    conn = open_db(db_path)
    try:
        recovery.recover(conn)
        library_plan.plan_library(conn)
        return bool(library_plan.check_library(conn))
    finally:
        conn.close()


async def _build_state(request: Request) -> dict | None:
    """The latest build job as the popup shows it, or None when none ran since the app started."""
    jobs = await get_job_runner(request).jobs(kind=BUILD_KIND, limit=1)
    if not jobs:
        return None
    job = jobs[0]
    return {
        "active": job.active,
        "percent": round(job.fraction * 100) if job.fraction is not None else None,
        "message": job.message or "Starting…",
        "result": dict(job.result),
        "error": job.error if job.state == "failed" else None,
    }
