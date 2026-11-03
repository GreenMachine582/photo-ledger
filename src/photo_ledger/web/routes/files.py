"""Images for the review screen. Only files registered in the catalogue are served, by ID: no
route takes a path, so nothing outside the sources can be reached."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from photo_ledger import thumbnails
from photo_ledger.web.deps import get_db

router = APIRouter(prefix="/files")

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
PRIVATE = {"Cache-Control": "private, max-age=3600"}


@router.get("/{file_id}/original")
def original(file_id: int, conn: sqlite3.Connection = Depends(get_db)) -> FileResponse:
    row = thumbnails.registered_file(conn, file_id)
    if row is None or row["extension"] not in MEDIA_TYPES:
        raise HTTPException(404, "No such photo")
    path = thumbnails.source_path(conn, row)
    if path is None:
        raise HTTPException(404, f"'{row['label']}' is offline, or the file has gone")
    return FileResponse(path, media_type=MEDIA_TYPES[row["extension"]], headers=PRIVATE)


@router.get("/{file_id}/preview")
def preview(
    file_id: int, request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> FileResponse:
    cache_dir = request.app.state.settings.thumbnail_dir
    path = thumbnails.preview(conn, file_id, cache_dir)
    if path is None:
        raise HTTPException(404, "No preview for this photo")
    return FileResponse(path, media_type="image/jpeg", headers=PRIVATE)
