"""Saved scans from the browser: create, run, pause, resume, watch, and remove.

The list (``/scans``) shows every scan as a row you can open, with its actions and progress. Each
scan has its own page (``/scans/<id>``) with each source's progress and its recent errors. Both
refresh themselves every second while a scan runs.

A run is a background job (``scanner.jobs``) on the app's ``JobRunner``. Pausing cancels the job,
which makes the engine stop between files and save the scan as ``paused``, so a pause outlasts a
restart. Scanning only reads sources. Removing a scan only drops its progress and errors, and an
interrupted or offline scan never marks a file missing.

The routes that touch the job runner are ``async``, so they open their own connection in the
event loop's thread: a SQLite connection can't cross threads.
"""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from greentechhub_core.background import Job, JobAlreadyRunning
from greentechhub_fastapi.auth.csrf import require_csrf
from greentechhub_fastapi.jobs import STOP_POLLING, get_job_runner

from photo_ledger.db import files as file_queries
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

#: What a source's row says, from its status and stage.
STATE_TEXT = {
    ("running", "walk"): "Listing files",
    ("running", "hash"): "Hashing",
    ("running", "done"): "Finishing",
    "pending": "Waiting",
    "paused": "Paused",
    "offline": "Offline",
    "complete": "Done",
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


def _back(back: str, default: str) -> str:
    """Where an action returns to: a scans page it was sent from, never anywhere else."""
    return back if back == "/scans" or back.startswith("/scans/") else default


async def _active_job(request: Request, scan_id: int) -> Job | None:
    jobs = await get_job_runner(request).jobs(kind=job_kind(scan_id), active=True, limit=1)
    return jobs[0] if jobs else None


async def _last_job(request: Request, scan_id: int) -> Job | None:
    jobs = await get_job_runner(request).jobs(kind=job_kind(scan_id), limit=1)
    return jobs[0] if jobs else None


def _elapsed(job: Job) -> str | None:
    if job.started_at is None:
        return None
    seconds = int((datetime.now(UTC) - job.started_at).total_seconds())
    minutes, seconds = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def _source(conn: sqlite3.Connection, row: sqlite3.Row, scan_status: str) -> dict:
    status, stage, files = row["status"], row["stage"], row["file_count"] or 0
    fraction = None
    if status == "running" and stage == "hash":
        waiting = file_queries.pending_hash_count(conn, row["source_id"])
        fraction = (files - waiting) / files if files else None
    if scan_status == "new":
        text = "Not started"
    else:
        text = STATE_TEXT.get((status, stage)) or STATE_TEXT.get(status, status.capitalize())
    return {
        "label": row["label"],
        "status": status,
        "stage": stage,
        "state_text": text,
        "mode": row["mode"],
        "files": files,
        "errors": row["error_count"],
        "fraction": fraction,
        "finished": (row["finished_at"] or "")[:16].replace("T", " "),
    }


def scan_card(
    conn: sqlite3.Connection, scan: sqlite3.Row, job: Job | None, *, errors: int = 10
) -> dict:
    """What a scan's row and page show: its sources' progress, recent errors and the job."""
    active = job is not None and job.active
    rows = engine.scan_progress(conn, scan["id"])
    sources = [_source(conn, row, scan["status"]) for row in rows]
    hashing = [s for s in sources if s["fraction"] is not None]
    # Running with no job here: another process (the CLI) holds it, or it was interrupted.
    elsewhere = bool(
        not active
        and scan["status"] == "running"
        and queries.live_claims(
            conn, [row["source_id"] for row in rows], now_ns() - engine.STALE_AFTER_NS
        )
    )
    hashed = sum(s["fraction"] * s["files"] for s in hashing)
    to_hash = sum(s["files"] for s in hashing)
    return {
        "id": scan["id"],
        "name": scan["name"],
        "status": scan["status"],
        "started": scan["status"] != "new",
        "active": active,
        "elsewhere": elsewhere,
        "interrupted": not active and not elsewhere and scan["status"] == "running",
        "message": job.message if active else None,
        "elapsed": _elapsed(job) if active else None,
        "percent": round(hashed * 100 / to_hash) if active and to_hash else None,
        "failed": job.error if job is not None and job.state == "failed" else None,
        "labels": ", ".join(s["label"] for s in sources),
        "files": sum(s["files"] for s in sources),
        "sources": sources,
        "offline": [s["label"] for s in sources if s["status"] == "offline"],
        "errors": [
            {"where": f"{e['label']}/{e['rel_path']}", "stage": e["stage"], "message": e["message"]}
            for e in engine.recent_errors(conn, scan["id"], limit=errors)
        ],
    }


async def _cards(request: Request, conn: sqlite3.Connection) -> list[dict]:
    return [
        scan_card(conn, scan, await _last_job(request, scan["id"]), errors=0)
        for scan in engine.list_scans(conn)
    ]


def _stop_when_idle(request: Request, response: Response, active: bool) -> Response:
    """While nothing runs, answer an htmx poll with 286 so it stops asking."""
    if not active and request.headers.get("HX-Request") == "true":
        response.status_code = STOP_POLLING
    return response


@router.get("", response_class=HTMLResponse)
async def scans_page(request: Request) -> HTMLResponse:
    with _connection(request) as conn:
        cards = await _cards(request, conn)
        labels = [source["label"] for source in source_service.list_sources(conn)]
        return render(request, "scans.html", {"cards": cards, "labels": labels})


@router.get("/rows", response_class=HTMLResponse)
async def rows(request: Request) -> Response:
    """The list's rows. They poll while any scan runs; the last answer stops the poll."""
    with _connection(request) as conn:
        cards = await _cards(request, conn)
        response = render(request, "scan_rows.html", {"cards": cards})
    return _stop_when_idle(request, response, any(card["active"] for card in cards))


@router.get("/{scan_id}", response_class=HTMLResponse)
async def scan_page(request: Request, scan_id: int) -> HTMLResponse:
    with _connection(request) as conn:
        card = scan_card(conn, _scan(conn, scan_id), await _last_job(request, scan_id), errors=100)
        return render(request, "scan.html", {"card": card})


@router.get("/{scan_id}/progress", response_class=HTMLResponse)
async def progress(request: Request, scan_id: int) -> Response:
    """The scan page's live part. While it runs, it polls itself; the last answer stops it."""
    with _connection(request) as conn:
        card = scan_card(conn, _scan(conn, scan_id), await _last_job(request, scan_id), errors=100)
        response = render(request, "scan_card.html", {"card": card})
    return _stop_when_idle(request, response, card["active"])


async def _start(request: Request, scan_id: int, *, verify: bool = False) -> None:
    """Start or resume a scan as a background job, refusing a source another scan holds."""
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


@router.post("", dependencies=[Depends(require_csrf)])
async def create(
    request: Request,
    name: str = Form(...),
    sources: list[str] = Form([]),
    run: bool = Form(False),
) -> RedirectResponse:
    """Save a scan. With ``run`` (Save and scan) it starts at once, on its own page."""
    if not sources:
        raise engine.ScanError("Choose at least one source to scan.")
    with _connection(request) as conn:
        scan_id = engine.create_scan(conn, name.strip(), sources)["id"]
    if not run:
        return notify("/scans", NOTICES, "created")
    await _start(request, scan_id)
    return notify(f"/scans/{scan_id}", NOTICES, "started")


@router.post("/{scan_id}/run", dependencies=[Depends(require_csrf)])
async def run(
    request: Request, scan_id: int, verify: bool = Form(False), back: str = Form("")
) -> RedirectResponse:
    await _start(request, scan_id, verify=verify)
    return notify(_back(back, f"/scans/{scan_id}"), NOTICES, "started")


@router.post("/{scan_id}/pause", dependencies=[Depends(require_csrf)])
async def pause(request: Request, scan_id: int, back: str = Form("")) -> RedirectResponse:
    to = _back(back, f"/scans/{scan_id}")
    job = await _active_job(request, scan_id)
    if job is None:
        return notify(to, NOTICES, "not-running")
    get_job_runner(request).cancel(job.id)
    return notify(to, NOTICES, "pausing")


@router.post("/{scan_id}/remove", dependencies=[Depends(require_csrf)])
def remove(
    scan_id: int, back: str = Form(""), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    scan = _scan(conn, scan_id)
    engine.remove_scan(conn, scan["name"])
    # From the Overview, back to it; from a scan's page, to the list, as that page is gone.
    return notify("/scans" if _back(back, "/") != "/" else "/", NOTICES, "scan-removed")
