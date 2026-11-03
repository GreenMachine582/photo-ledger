"""The plan page: every proposed move, its size and a dry-run result.

Viewing the page only reads: the dry run it shows is recorded only when you ask for one.
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.actions import dryrun, planner
from photo_ledger.db import plans as queries
from photo_ledger.formatting import human_size
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/plan")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "built": "Plan rebuilt from your decisions and dry-run. Nothing has changed on disk.",
    "checked": "Dry run finished, with every file hashed. Nothing has changed on disk.",
}


def page_context(conn: sqlite3.Connection) -> dict:
    current = planner.draft(conn)
    preview, _moves = planner.classify(conn)
    context = {
        "plan": current,
        "stale": bool(current) and planner.is_stale(conn, current),
        "actions": [],
        "dry_run": None,
        "cards": [],
        "stay": preview.stay,
        "stay_size": human_size(preview.stay_bytes),
        "unsafe": preview.unsafe,
        "unfinished": queries.latest(conn, "applying", "incomplete"),
    }
    if current is None:
        return context
    actions = queries.actions(conn, current["id"])
    result = dryrun.dry_run(conn, current["id"], record=False)
    context.update(
        actions=[
            {
                "source": a["source_label"],
                "path": a["rel_path"],
                "to": f"{a['quarantine_root']}/{a['to_path']}",
                "size": human_size(a["size_bytes"]),
            }
            for a in actions
        ],
        dry_run=result,
        cards=[
            {"label": "Moves to quarantine", "value": f"{len(actions):,}"},
            {"label": "Size", "value": human_size(sum(a["size_bytes"] for a in actions))},
            {"label": "Staying in place", "value": f"{preview.stay:,}"},
            {"label": "Dry run", "value": "No problems" if result.ok else "Problems found"},
        ],
    )
    return context


@router.get("", response_class=HTMLResponse)
def plan_page(
    request: Request, notice: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> HTMLResponse:
    return render(request, "plan.html", {**page_context(conn), "notice": NOTICES.get(notice or "")})


@router.post("", dependencies=[Depends(require_csrf)])
def rebuild(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    summary = planner.build_plan(conn)
    dryrun.dry_run(conn, summary.plan_id)
    return RedirectResponse("/plan?notice=built", status_code=303)


@router.post("/check", dependencies=[Depends(require_csrf)])
def check(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    current = planner.draft(conn)
    if current is not None:
        dryrun.dry_run(conn, current["id"], verify=True)
    return RedirectResponse("/plan?notice=checked", status_code=303)
