"""The sources page: map, check and reconnect sources, and set their priority and quarantine.

Everything goes through ``sources.service``, the same as the CLI. The page only stores paths you
type: it never browses folders, never serves a file and never writes to a source.
"""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.sources import service
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/sources")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "added": "Mapped. Mapping never changes the folder: create and run a scan to catalogue it.",
    "online": "Connected, and on the volume it was mapped on.",
    "offline": "Not connected, or a different drive is at that path. "
    "Nothing in it was marked missing.",
    "checked": "Checked every source.",
    "reconnected": "Reconnected at its new location.",
    "priority": "Priority saved. Keeper suggestions use it from the next `photo-ledger match`.",
    "quarantine-on": "Quarantine is on. Rejected copies can move there when you apply a plan.",
    "quarantine-far": "Quarantine is on, on another device. Moves will copy and verify each file, "
    "so a folder on the source's own drive would be faster.",
    "quarantine-off": "Quarantine is off. Rejected copies stay where they are.",
}


def _rows(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for source in conn.execute(
        """
        SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.source_id = s.id
                     AND f.status != 'missing') AS file_count,
               (SELECT MAX(finished_at) FROM scan_sources ss WHERE ss.source_id = s.id) AS last_scan
        FROM sources s ORDER BY s.label
        """
    ).fetchall():
        # The stored state, from the last check: looking at every drive on each page load can
        # take seconds when one is slow to answer, so the page itself never probes a drive.
        rows.append(
            {
                "id": source["id"],
                "label": source["label"],
                "online": source["state"] == "online",
                "type": source["source_type"],
                "device": source["device_label"] or source["volume_id"] or "",
                "root": source["root_path"],
                "files": source["file_count"],
                "last_scan": (source["last_scan"] or "")[:16].replace("T", " "),
                "priority": source["priority"],
                "quarantine": source["quarantine_path"] if source["quarantine_enabled"] else None,
            }
        )
    return rows


def _label(conn: sqlite3.Connection, source_id: int) -> str:
    row = conn.execute("SELECT label FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise service.SourceError(f"There's no source {source_id}.")
    return row["label"]


def _done(notice: str) -> RedirectResponse:
    return RedirectResponse(f"/sources?notice={notice}", status_code=303)


@router.get("", response_class=HTMLResponse)
def sources_page(
    request: Request, notice: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    return render(
        request, "sources.html", {"rows": _rows(conn), "notice": NOTICES.get(notice or "")}
    )


@router.post("", dependencies=[Depends(require_csrf)])
def add(
    path: str = Form(...), label: str = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    service.add_source(conn, Path(path.strip()), label.strip())
    return _done("added")


@router.post("/check", dependencies=[Depends(require_csrf)])
def check_all(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    for source in service.list_sources(conn):
        service.refresh_state(conn, source)
    return _done("checked")


@router.post("/{source_id}/check", dependencies=[Depends(require_csrf)])
def check(source_id: int, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    source = service.get_source(conn, _label(conn, source_id))
    return _done("online" if service.refresh_state(conn, source) else "offline")


@router.post("/{source_id}/reconnect", dependencies=[Depends(require_csrf)])
def reconnect(
    source_id: int, path: str = Form(""), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    label = _label(conn, source_id)
    new_root = (
        Path(path.strip())
        if path.strip()
        else service.find_new_root(service.get_source(conn, label))
    )
    if new_root is None:
        raise service.SourceError(
            f"Couldn't find the volume for '{label}'. Connect it, or type its new location."
        )
    service.reconnect(conn, label, new_root)
    return _done("reconnected")


@router.post("/{source_id}/priority", dependencies=[Depends(require_csrf)])
def priority(
    source_id: int, priority: int = Form(...), conn: sqlite3.Connection = Depends(get_db)
) -> RedirectResponse:
    service.set_priority(conn, _label(conn, source_id), priority)
    return _done("priority")


@router.post("/{source_id}/quarantine", dependencies=[Depends(require_csrf)])
def quarantine(
    source_id: int,
    path: str = Form(""),
    off: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    label = _label(conn, source_id)
    if off:
        service.set_quarantine(conn, label, None)
        return _done("quarantine-off")
    if not path.strip():
        raise service.SourceError("Type the quarantine folder, or turn quarantine off.")
    _source, same_volume = service.set_quarantine(conn, label, Path(path.strip()))
    return _done("quarantine-far" if same_volume is False else "quarantine-on")
