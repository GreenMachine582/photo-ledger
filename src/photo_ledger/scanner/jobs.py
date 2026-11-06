"""Scans as background jobs, for greentechhub-core's ``JobRunner``. No web imports.

A job runs ``engine.run_scan`` in a worker thread, on its own connection, since a SQLite
connection belongs to the thread that opened it. Pausing is cancelling the job: the engine
checks ``should_stop`` between files, commits its batch and ``resume_path``, and saves the scan
as ``paused``. So a pause survives a restart, and resuming is starting a new job, exactly like
``scan run`` after Ctrl+C. A job stopped by shutting the app down pauses the same way.
"""

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

from photo_ledger.db import open_db
from photo_ledger.scanner import engine


def job_kind(scan_id: int) -> str:
    """One kind per scan, so ``unique=True`` refuses a second run of the same scan."""
    return f"scan:{scan_id}"


def scan_job(db_path: Path, name: str, *, verify: bool = False) -> Callable[[Any], dict]:
    """A thread job function that starts or resumes the scan ``name``."""

    def run(ctx: Any) -> dict:
        def progress(label: str, stage: str, done: int) -> None:
            verb = "listed" if stage == "walk" else "hashed"
            ctx.progress(message=f"{label}: {done:,} {verb}")

        conn = open_db(db_path)
        try:
            result = engine.run_scan(
                conn,
                name,
                verify=verify,
                should_stop=lambda: ctx.cancelled,
                progress=progress,
            )
        finally:
            conn.close()
        return dataclasses.asdict(result)

    return run
