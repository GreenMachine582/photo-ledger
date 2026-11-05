"""Saved scans from the browser: removing one you no longer need.

Removing a scan only drops its progress and errors from the catalogue. Its sources, catalogued
files, pairs and decisions stay, and nothing on disk changes. Creating and running scans stays on
the command line.
"""

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.db import scans as queries
from photo_ledger.scanner import engine
from photo_ledger.web.deps import get_db, notify

router = APIRouter(prefix="/scans")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "scan-removed": "Scan removed. Its sources, catalogued files and decisions stay, and nothing "
    "on disk changed.",
}


@router.post("/{scan_id}/remove", dependencies=[Depends(require_csrf)])
def remove(scan_id: int, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    scan = queries.by_id(conn, scan_id)
    if scan is None:
        raise engine.ScanError(f"There's no scan {scan_id}.")
    engine.remove_scan(conn, scan["name"])
    return notify("/", NOTICES, "scan-removed")
