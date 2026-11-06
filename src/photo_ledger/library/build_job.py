"""Building the library as a background job, for greentechhub-core's ``JobRunner``. No web imports.

The job does what ``POST /library/build`` used to do inside the request: finish any interrupted
copy, plan, dry-run and, only after a clean dry run, build through ``actions/executor.py``, which
is the only code that writes into the library. It runs in a worker thread on its own connection,
since a SQLite connection belongs to the thread that opened it, and reports each copy as progress.

There's no pause or cancel: a build already stops cleanly between verified copies if the app
closes, and the next build carries on from there.
"""

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

from photo_ledger import activity
from photo_ledger.actions import executor, recovery
from photo_ledger.db import open_db
from photo_ledger.library import plan as library_plan

#: One kind, started with ``unique=True``: there's one library, so one build at a time.
BUILD_KIND = "library-build"

PHASE_TEXT = {
    "copying": "Copying {done:,} of {total:,}",
    "finishing": "Updating sidecars {done:,} of {total:,}",
}


def build_job(db_path: Path) -> Callable[[Any], dict]:
    """A thread job function that builds the library after a clean dry run."""

    def run(ctx: Any) -> dict:
        def progress(done: int, total: int, phase: str) -> None:
            ctx.progress(done, total, message=PHASE_TEXT[phase].format(done=done, total=total))

        conn = open_db(db_path)
        try:
            ctx.progress(message="Checking the plan")
            recovery.recover(conn)
            library_plan.plan_library(conn)
            if library_plan.check_library(conn):
                return {"status": "problems"}
            result = executor.build_library(conn, progress=progress)
        finally:
            conn.close()
        complete = result.status == "complete"
        activity.record(
            db_path,
            "library.built" if complete else "library.incomplete",
            f"Library built: {activity.count(result.copied, 'picture')} copied and verified."
            if complete
            else f"Library build incomplete: {result.copied:,} copied, {len(result.failed):,} "
            "failed. Nothing was left half-written.",
            kind="success" if complete else "warning",
            target=("library", 1),
            link=("Library", "/library"),
            details={"copied": result.copied, "failed": len(result.failed)},
        )
        return dataclasses.asdict(result)

    return run
