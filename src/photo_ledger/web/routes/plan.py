"""The plan page: every proposed move, its size and a dry-run result.

Viewing the page only reads: the dry run it shows is recorded only when you ask for one.
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.actions import dryrun, executor, planner
from photo_ledger.activity import count
from photo_ledger.db import plans as queries
from photo_ledger.formatting import human_size
from photo_ledger.web.deps import get_db, notify, record, render

router = APIRouter(prefix="/plan")

#: Results are shown from this fixed list, never from text in the URL.
NOTICES = {
    "built": "Plan rebuilt from your decisions and dry-run. Nothing has changed on disk.",
    "checked": "Dry run finished, with every file hashed. Nothing has changed on disk.",
    "applied": "Applied. You can undo it here at any time: every move is in the journal.",
    "incomplete": "Some moves failed, and their files were left in place. See the problems below.",
    "undone": "Undone. Every moved file is back where it came from, verified by its hash.",
    "undo-incomplete": "Some files couldn't be put back, and both copies were left alone. "
    "Fix the problem, then undo again to finish.",
}


def undo_state(conn: sqlite3.Connection) -> dict:
    """What the page offers: finishing an interrupted plan or undo, or undoing the last plan.

    These mirror ``executor.apply`` and ``executor.undo``, which each finish an unfinished plan
    of their own kind before starting anything new.
    """
    unfinished = "status IN ('applying', 'incomplete')"
    unfinished_undo = conn.execute(
        f"SELECT * FROM plans WHERE {unfinished} AND undoes_plan_id IS NOT NULL"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    undoable = conn.execute(
        "SELECT * FROM plans WHERE status IN ('applied', 'incomplete')"
        " AND undoes_plan_id IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "unfinished": conn.execute(
            f"SELECT * FROM plans WHERE {unfinished} AND undoes_plan_id IS NULL"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone(),
        "unfinished_undo": unfinished_undo,
        # An interrupted undo is finished before another can start, so offer that instead.
        "undoable": None if unfinished_undo else undoable,
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
        **undo_state(conn),
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
def plan_page(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    return render(request, "plan.html", {**page_context(conn)})


@router.post("", dependencies=[Depends(require_csrf)])
def rebuild(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    summary = planner.build_plan(conn)
    dryrun.dry_run(conn, summary.plan_id)
    return notify("/plan", NOTICES, "built")


@router.post("/apply", dependencies=[Depends(require_csrf)])
def apply_plan(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    """Apply the dry-run plan through the executor, after the page's confirm step."""
    result = executor.apply(conn)
    notice = "applied" if result.status == "applied" else "incomplete"
    if notice == "applied":
        summary = (
            f"Plan applied: {count(result.done, 'copy', 'copies')} moved to quarantine. "
            "You can undo it."
        )
    else:
        summary = (
            f"Plan incomplete: {result.done:,} moved, {len(result.failed):,} failed and left "
            "in place."
        )
    record(
        request,
        "plan.applied" if notice == "applied" else "plan.incomplete",
        summary,
        kind="success" if notice == "applied" else "warning",
        target=("plan", result.plan_id),
        link=("Plan", "/plan"),
        details={"done": result.done, "failed": len(result.failed)},
    )
    return notify("/plan", NOTICES, notice)


@router.post("/undo", dependencies=[Depends(require_csrf)])
def undo_plan(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    """Put back the last applied plan's files through the executor, after the confirm step.

    An interrupted undo is finished first, as with ``photo-ledger undo``. A quarantine that's
    offline is refused with its name, through the app's expected-failure page.
    """
    result = executor.undo(conn)
    notice = "undone" if result.status == "applied" else "undo-incomplete"
    record(
        request,
        "plan.undone" if notice == "undone" else "plan.undo_incomplete",
        f"Plan undone: {count(result.done, 'file')} put back."
        if notice == "undone"
        else f"Undo incomplete: {count(len(result.failed), 'file')} couldn't be put back, and both "
        "copies were left alone.",
        kind="success" if notice == "undone" else "warning",
        target=("plan", result.plan_id),
        link=("Plan", "/plan"),
        details={"done": result.done, "failed": len(result.failed)},
    )
    return notify("/plan", NOTICES, notice)


@router.post("/check", dependencies=[Depends(require_csrf)])
def check(conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    current = planner.draft(conn)
    if current is not None:
        dryrun.dry_run(conn, current["id"], verify=True)
    return notify("/plan", NOTICES, "checked")
