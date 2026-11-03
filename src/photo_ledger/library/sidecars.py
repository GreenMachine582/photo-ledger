"""What each library file's sidecar and file date should be. Read-only: the executor writes them.

A picture keeps every collection it belongs to through any copy, including the copies it
replaced, so consolidating duplicates never loses an album. Its sidecar lists them all, with
the sources that held a copy, the keywords the photo carried and its capture date.
"""

import sqlite3
from pathlib import Path

from photo_ledger.db.pairs import ELIGIBLE_STATUSES
from photo_ledger.exports.xmp import sidecar
from photo_ledger.library.dates import CaptureDate, capture_dates
from photo_ledger.library.keywords import embedded_keywords
from photo_ledger.library.layout import Layout

SIDECAR_SUFFIX = ".xmp"


def sidecar_path(library_file: Path) -> Path:
    """``IMG_0412.jpg.xmp`` beside ``IMG_0412.jpg``, the name Immich looks for first."""
    return library_file.with_name(library_file.name + SIDECAR_SUFFIX)


class Extras:
    """Collections, sources and dates for one build, loaded once."""

    def __init__(self, conn: sqlite3.Connection, layout: str):
        self.layout = Layout(conn, layout)
        self.dates = capture_dates(conn)
        marks = ",".join("?" * len(ELIGIBLE_STATUSES))
        self.sources: dict[int, set[str]] = {}
        for content_id, label in conn.execute(
            f"SELECT f.content_id, s.label FROM files f JOIN sources s ON s.id = f.source_id"
            f" WHERE f.content_id IS NOT NULL AND f.status IN ({marks})",
            ELIGIBLE_STATUSES,
        ):
            self.sources.setdefault(content_id, set()).add(label)

    def date(self, content_id: int) -> CaptureDate | None:
        return self.dates.get(content_id)

    def sidecar_text(self, content_id: int, library_file: Path) -> str:
        date = self.date(content_id)
        return sidecar(
            collections=self.layout.collections(content_id),
            sources=self.sources.get(content_id, ()),
            keywords=embedded_keywords(library_file),
            taken=date.taken if date else None,
            offset=date.offset if date else None,
        )
