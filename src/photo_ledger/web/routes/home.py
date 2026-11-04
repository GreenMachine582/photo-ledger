"""The overview: what's catalogued, how much is duplicated, and how far the review has got."""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from photo_ledger.formatting import human_size
from photo_ledger.review.overview import overview
from photo_ledger.web.deps import get_db, render

router = APIRouter()

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "scan-removed": "Scan removed. Its sources, catalogued files and decisions stay, and nothing "
    "on disk changed.",
}


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request, notice: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    data = overview(conn)
    cards = [
        {"label": "Files", "value": f"{data.files:,}"},
        {"label": "Unique photos", "value": f"{data.contents:,}"},
        {"label": "Duplicated space", "value": human_size(data.reclaimable_bytes)},
        {
            "label": "Marked for the plan",
            "value": human_size(data.marked_bytes),
            "delta": '<a href="/plan">See the plan</a>',
        },
        {"label": "Open pairs", "value": f"{data.pairs.get('open', 0):,}"},
        {"label": "Skipped", "value": f"{data.pairs.get('skipped', 0):,}"},
        {"label": "Needs review", "value": f"{data.pairs.get('needs_review', 0):,}"},
        {"label": "Decided", "value": f"{data.pairs.get('resolved', 0):,}"},
    ]
    return render(
        request,
        "overview.html",
        {"data": data, "cards": cards, "notice": NOTICES.get(notice or "")},
    )
