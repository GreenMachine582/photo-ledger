"""Read-only reports: mismatches, dates, corrupt files and more, as tables or CSV downloads."""

import csv
import io
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from photo_ledger.matching import reports
from photo_ledger.scanner.engine import list_scans
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/reports")


def _build(conn: sqlite3.Connection, name: str, scan: str | None) -> reports.Report:
    if name not in reports.REPORTS:
        raise HTTPException(404, "No such report")
    if name == "pairs":
        return reports.pairs_report(conn, scan or None, status=None)
    return reports.REPORTS[name](conn, scan or None)


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return render(request, "report.html", {"names": list(reports.REPORTS), "report": None})


@router.get("/{name}.csv")
def report_csv(
    name: str, scan: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> Response:
    """The same rows as a download, built in memory: nothing is written to disk."""
    result = _build(conn, name, scan)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("/{name}", response_class=HTMLResponse)
def report(
    request: Request,
    name: str,
    scan: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    return render(
        request,
        "report.html",
        {
            "names": list(reports.REPORTS),
            "name": name,
            "report": _build(conn, name, scan),
            "scan": scan or "",
            "scans": [row["name"] for row in list_scans(conn)],
        },
    )
