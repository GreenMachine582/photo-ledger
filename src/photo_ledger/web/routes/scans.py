"""Saved scans from the browser: create, run, pause, resume, watch, and remove.

A run is a background job (``scanner.jobs``) on the app's ``JobRunner``. Pausing cancels the job,
which makes the engine stop between files and save the scan as ``paused``, so a pause outlasts a
restart. Scanning only reads sources. Removing a scan only drops its progress and errors, and an
interrupted or offline scan never marks a file missing.

The routes that touch the job runner are ``async``, so they open their own connection in the
event loop's thread: a SQLite connection can't cross threads.
"""

import sqlite3
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from greentechhub_core.background import Job, JobAlreadyRunning
from greentechhub_fastapi.auth.csrf import require_csrf
from greentechhub_fastapi.jobs import STOP_POLLING, get_job_runner

from photo_ledger.db import now_ns, open_db
from photo_ledger.db import scans as queries
from photo_ledger.scanner import engine
from photo_ledger.scanner.jobs import job_kind, scan_job
from photo_ledger.sources import service as source_service
from photo_ledger.web.deps import get_db, notify, render

router = APIRouter(prefix="/scans")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "created": "Scan saved. Run it to catalogue its sources. Scanning only reads them.",
    "started": "Scan started. It carries on if you leave this page.",
    "pausing": "Pausing after the current file. Its progress is saved, and nothing is marked "
    "missing.",
    "not-running": "That scan isn't running.",
    "scan-removed": "Scan removed. Its sources, catalogued files and decisions stay, and nothing "
    "on disk changed.",
}


@contextmanager
def _connection(request: Request):
    conn = open_db(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _scan(conn: sqlite3.Connection, scan_id: int) -> sqlite3.Row:
    scan = queries.by_id(conn, scan_id)
    if scan is None:
        raise engine.ScanError(f"There's no scan {scan_id}.")
    return scan


async def _active_job(request: Request, scan_id: int) -> Job | None:
    jobs = await get_job_runner(request).jobs(kind=job_kind(scan_id), active=True, limit=1)
    return jobs[0] if jobs else None


async def _last_job(request: Request, scan_id: int) -> Job | None:
    jobs = await get_job_runner(request).jobs(kind=job_kind(scan_id), limit=1)
    return jobs[0] if jobs else None


def scan_card(conn: sqlite3.Connection, scan: sqlite3.Row, job: Job | None) -> dict:
    """What a scan's card shows: its sources' progress, recent errors and the job's state."""
    active = job is not None and job.active
    rows = engine.scan_progress(conn, scan["id"])
    return {
        "id": scan["id"],
        "name": scan["name"],
        "status": scan["status"],
        "active": active,
        "message": job.message if active else None,
        "failed": job.error if job is not None and job.state == "failed" else None,
        "sources": [
            {
                "label": row["label"],
                "status": row["status"],
                "stage": row["stage"],
                "mode": row["mode"],
                "files": row["file_count"],
                "errors": row["error_count"],
                "finished": (row["finished_at"] or "")[:16].replace("T", " "),
            }
            for row in rows
        ],
        "offline": [row["label"] for row in rows if row["status"] == "offline"],
        "errors": [
            {"where": f"{e['label']}/{e['rel_path']}", "stage": e["stage"], "message": e["message"]}
            for e in engine.recent_errors(conn, scan["id"], limit=10)
        ],
    }


@router.get("", response_class=HTMLResponse)
async def scans_page(request: Request) -> HTMLResponse:
    with _connection(request) as conn:
        cards = [
            scan_card(conn, scan, await _last_job(request, scan["id"]))
            for scan in engine.list_scans(conn)
        ]
        labels = [source["label"] for source in source_service.list_sources(conn)]
        return render(request, "scans.html", {"cards": cards, "labels": labels})


@router.get("/{scan_id}/progress", response_class=HTMLResponse)
async def progress(request: Request, scan_id: int) -> Response:
    """The card for one scan. While it runs, it polls itself; the last answer stops the poll."""
    with _connection(request) as conn:
        card = scan_card(conn, _scan(conn, scan_id), await _last_job(request, scan_id))
        response = render(request, "scan_card.html", {"card": card})
    if not card["active"] and request.headers.get("HX-Request") == "true":
        response.status_code = STOP_POLLING
    return response


@router.post("", dependencies=[Depends(require_csrf)])
def create(
    name: str = Form(...),
    sources: list[str] = Form([]),
    conn: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    if not sources:
        raise engine.ScanError("Choose at least one source to scan.")
    engine.create_scan(conn, name.strip(), sources)
    return notify("/scans", NOTICES, "created")


@router.post("/{scan_id}/run", dependencies=[Depends(require_csrf)])
async def run(request: Request, scan_id: int, verify: bool = Form(False)) -> RedirectResponse:
    with _connection(request) as conn:
        scan = _scan(conn, scan_id)
        source_ids = [row["source_id"] for row in engine.scan_progress(conn, scan_id)]
        live = queries.live_claims(conn, source_ids, now_ns() - engine.STALE_AFTER_NS)
    if live:
        busy = ", ".join(f"'{c['label']}' (scan '{c['scan_name']}')" for c in live)
        raise engine.ScanConflict(
            f"Already being scanned: {busy}. Only one scan can process a source at a time."
        )
    settings = request.app.state.settings
    try:
        await get_job_runner(request).start(
            job_kind(scan_id),
            scan_job(settings.db_path, scan["name"], verify=verify),
            label=f"Scan {scan['name']}",
            unique=True,
        )
    except JobAlreadyRunning as exc:
        raise engine.ScanError(f"Scan '{scan['name']}' is already running.") from exc
    return notify("/scans", NOTICES, "started")


@router.post("/{scan_id}/pause", dependencies=[Depends(require_csrf)])
async def pause(request: Request, scan_id: int) -> RedirectResponse:
    job = await _active_job(request, scan_id)
    if job is None:
        return notify("/scans", NOTICES, "not-running")
    get_job_runner(request).cancel(job.id)
    return notify("/scans", NOTICES, "pausing")


@router.post("/{scan_id}/remove", dependencies=[Depends(require_csrf)])
def remove(scan_id: int, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    scan = _scan(conn, scan_id)
    engine.remove_scan(conn, scan["name"])
    return notify("/", NOTICES, "scan-removed")
