"""The plan page: every proposed move, its size and a dry-run result.

Viewing the page only reads: the dry run it shows is recorded only when you ask for one.
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.actions import dryrun, executor, planner
from photo_ledger.db import plans as queries
from photo_ledger.formatting import human_size
from photo_ledger.web.deps import get_db, render

router = APIRouter(prefix="/plan")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "built": "Plan rebuilt from your decisions and dry-run. Nothing has changed on disk.",
    "checked": "Dry run finished, with every file hashed. Nothing has changed on disk.",
    "applied": "Applied. Undo it with `photo-ledger undo`.",
    "incomplete": "Some moves failed, and their files were left in place. See the problems below.",
}


def page_context(conn: sqlite3.Connection) -> dict:
    current = planner.draft(conn)
    preview, _moves = planner.classify(conn)
    context = {
        "plan": current,
        "stale": bool(current) and planner.is_stale(conn, current),
        "actions": [],
        "dry_run": None,
        "can_apply": False,
        "cards": [],
        "stay": preview.stay,
        "stay_size": human_size(preview.stay_bytes),
        "unsafe": preview.unsafe,
        "unfinished": queries.latest(conn, "applying", "incomplete"),
        "last_applied": conn.execute(
            "SELECT * FROM plans WHERE status = 'applied' AND undoes_plan_id IS NULL"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone(),
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
        # Only a recorded clean dry run, on a plan no decision has overtaken, can be applied.
        can_apply=bool(actions and current["checked_at"] and result.ok and not context["stale"]),
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


@router.post("/apply", dependencies=[Depends(require_csrf)])
def apply_plan(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    """Apply the dry-run plan through the executor, after the page's confirm step."""
    result = executor.apply(conn)
    notice = "applied" if result.status == "applied" else "incomplete"
    return RedirectResponse(f"/plan?notice={notice}", status_code=303)


@router.post("/check", dependencies=[Depends(require_csrf)])
def check(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    current = planner.draft(conn)
    if current is not None:
        dryrun.dry_run(conn, current["id"], verify=True)
    return RedirectResponse("/plan?notice=checked", status_code=303)
