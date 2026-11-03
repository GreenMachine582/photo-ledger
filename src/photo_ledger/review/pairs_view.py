"""What the comparison screen shows for one pair: each side's copy, its details and what differs."""

import json
import sqlite3
from dataclasses import dataclass, field

from photo_ledger.collections.folders import collections_by_content
from photo_ledger.formatting import file_date, human_size
from photo_ledger.matching.scoring import best_copy
from photo_ledger.matching.sides import Catalogue, label_path
from photo_ledger.review.decisions import active_decision

#: The details compared side by side, in display order.
FIELDS = (
    "Path",
    "Size",
    "Dimensions",
    "Format",
    "Captured",
    "Camera",
    "File date",
    "Collections",
)


@dataclass
class SideView:
    shown: sqlite3.Row
    others: list[str]
    details: dict[str, str]

    @property
    def file_id(self) -> int:
        return self.shown["id"]


@dataclass
class PairView:
    pair: sqlite3.Row
    left: SideView
    right: SideView
    differing: set[str] = field(default_factory=set)
    suggested: str | None = None
    reasons: list[str] = field(default_factory=list)
    against: list[str] = field(default_factory=list)
    decision: sqlite3.Row | None = None


def _details(row, collections: set[str]) -> dict[str, str]:
    captured = ""
    if row["captured_at"]:
        captured = row["captured_at"].replace("T", " ") + (row["capture_offset"] or "")
        captured += f" ({row['capture_date_source']})"
    camera = " ".join(part for part in (row["camera_make"], row["camera_model"]) if part)
    return {
        "Path": label_path(row),
        "Size": human_size(row["size_bytes"]),
        "Dimensions": f"{row['width']} x {row['height']}" if row["width"] else "",
        "Format": row["format"] or "",
        "Captured": captured,
        "Camera": camera,
        "File date": file_date(row["mtime_ns"]),
        "Collections": ", ".join(sorted(collections)),
    }


def _side(files, inherited) -> SideView:
    shown = best_copy(files)
    collections = set().union(*(inherited.get(f["content_id"], set()) for f in files))
    others = sorted(label_path(f) for f in files if f["id"] != shown["id"])
    return SideView(shown=shown, others=others, details=_details(shown, collections))


def pair_view(
    conn: sqlite3.Connection, pair_id: int, catalogue: Catalogue | None = None
) -> PairView | None:
    """The view of a pair, or ``None`` when it doesn't exist or its copies are gone."""
    pair = conn.execute("SELECT * FROM review_pairs WHERE id = ?", (pair_id,)).fetchone()
    if pair is None:
        return None
    catalogue = catalogue or Catalogue.load(conn)
    left_files, right_files = catalogue.sides(pair)
    if not left_files or not right_files:
        return None
    inherited = collections_by_content(conn)
    left, right = _side(left_files, inherited), _side(right_files, inherited)
    differing = {
        name for name in FIELDS if name != "Path" and left.details[name] != right.details[name]
    }
    score = json.loads(pair["score_reasons"]) if pair["score_reasons"] else {}
    return PairView(
        pair=pair,
        left=left,
        right=right,
        differing=differing,
        suggested=score.get("suggested"),
        reasons=score.get("reasons", []),
        against=score.get("against", []),
        decision=active_decision(conn, pair_id),
    )
