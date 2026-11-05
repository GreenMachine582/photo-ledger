"""Download the catalogue as CSV: the same rows as ``photo-ledger export csv``.

The file is built in memory and sent to the browser, so nothing is written to disk here.
"""

import csv
import io
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from photo_ledger.exports import csv_export
from photo_ledger.web.deps import get_db

router = APIRouter(prefix="/export")


@router.get("/catalogue.csv")
def catalogue_csv(scan: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(csv_export.COLUMNS)
    writer.writerows(csv_export.catalogue_rows(conn, scan or None))
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="photo-ledger-catalogue.csv"'},
    )
