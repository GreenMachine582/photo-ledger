"""The folder explorer: folder names on this computer, one level at a time, for the folder fields.

Read-only and names only, through ``sources.folders``. It never lists or serves a file. Any site
can make the browser send a GET here but can't read the answer, as CORS stays closed. To be sure,
it also answers only htmx requests from this app's own pages: ``HX-Request`` is a custom header a
cross-site page can't send without a preflight, and ``Sec-Fetch-Site`` must not name another site.
"""

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from photo_ledger.errors import PhotoLedgerError
from photo_ledger.sources import folders
from photo_ledger.web.deps import get_db

router = APIRouter(prefix="/folders")

TREE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
LOCAL_FETCH_SITES = {"same-origin", "none"}


def local_page_only(request: Request) -> None:
    """Refuse anything but this app's own pages asking through htmx."""
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if request.headers.get("HX-Request") != "true" or (
        fetch_site is not None and fetch_site not in LOCAL_FETCH_SITES
    ):
        raise HTTPException(403, "Folders are listed only for this app's own pages")


def _node(folder: folders.Folder, root: bool) -> dict:
    node = {
        "id": folder.path,
        "label": folder.name,
        "icon": "device-hdd" if root else "folder",
        "has_children": folder.has_children,
    }
    if folder.mapped_as:
        node["badge"] = {"label": folder.mapped_as, "tone": "info"}
    return node


@router.get("", response_class=HTMLResponse, dependencies=[Depends(local_page_only)])
def list_folders(
    request: Request,
    tree: str = Query(...),
    parent: str | None = Query(None),
    level: int = Query(1, ge=1, le=64),
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    if not TREE_ID.match(tree):
        raise HTTPException(400, "Unknown folder tree")
    error, more = None, 0
    try:
        if parent is None:
            found = folders.roots()
        else:
            listing = folders.children(parent)
            found, more = listing.folders, listing.more
    except PhotoLedgerError as exc:
        found, error = [], str(exc)
    nodes = [_node(folder, parent is None) for folder in folders.annotate(conn, found)]
    return request.app.state.templates.TemplateResponse(
        request,
        "folder_nodes.html",
        {
            "nodes": nodes,
            "level": level,
            "tree_id": tree,
            "lazy_url": f"/folders?tree={tree}",
            "error": error,
            "more": more,
            "empty": parent is not None and not found and error is None,
        },
    )
