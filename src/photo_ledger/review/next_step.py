"""The Overview's guided next step: the one thing to do next, from an empty catalogue to a built
library. Read-only. Each step names the page that does it, so the browser covers the whole path.
"""

import sqlite3
from dataclasses import dataclass

from photo_ledger.actions import planner
from photo_ledger.db import library as library_queries
from photo_ledger.library import plan as library_plan
from photo_ledger.review.overview import Overview


@dataclass(frozen=True)
class NextStep:
    key: str
    title: str
    text: str
    url: str | None = None
    label: str | None = None


def next_step(conn: sqlite3.Connection, data: Overview) -> NextStep:
    if not data.sources:
        return NextStep(
            "map",
            "Map a source",
            "Add the folder or drive that holds a backup. Mapping never changes it.",
            "/sources",
            "Map a source",
        )
    if not data.files:
        return NextStep(
            "scan",
            "Scan your sources",
            "Save a scan of your sources and run it. Scanning only reads, and you can pause it.",
            "/scans",
            "Scan sources",
        )
    matched = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM review_pairs) OR EXISTS (SELECT 1 FROM collection_folders)"
    ).fetchone()[0]
    if not matched:
        return NextStep(
            "match",
            "Find duplicates",
            "Run match below to find exact duplicates, similar images and name conflicts.",
        )
    to_review = data.pairs.get("open", 0) + data.pairs.get("needs_review", 0)
    if to_review:
        return NextStep(
            "review",
            "Review pairs",
            f"{to_review:,} pairs wait for a decision. Decide which copy to keep, side by side.",
            "/review",
            "Start reviewing",
        )
    _summary, moves = planner.classify(conn)
    if moves:
        return NextStep(
            "plan",
            "Move rejected copies to quarantine",
            f"{len(moves):,} rejected copies can move to quarantine. Build the plan and dry-run "
            "it. Nothing moves until you apply it, and you can undo it.",
            "/plan",
            "Open the plan",
        )
    if library_queries.get(conn) is None:
        return NextStep(
            "library",
            "Set up the library",
            "Choose a folder outside every source for a clean copy of each settled picture.",
            "/library",
            "Set up the library",
        )
    if library_plan.preview(conn).to_copy:
        return NextStep(
            "build",
            "Build the library",
            "Some settled pictures aren't in the library yet. Plan it, then build: originals "
            "never change.",
            "/library",
            "Open the library",
        )
    return NextStep(
        "done",
        "All caught up",
        "Every settled picture is in the library. Scan again after a new backup, then match.",
    )
