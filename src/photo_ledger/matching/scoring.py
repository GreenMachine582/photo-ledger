"""Explained keeper suggestions.

Criteria are compared in order, and the first that differs picks the suggested side:

1. higher resolution
2. more complete EXIF (capture date, camera, GPS)
3. earlier capture date
4. higher source priority
5. tidier path (no copy marker such as `` (1)`` or ``copy``, then shorter)

File size breaks ties only, as larger doesn't always mean better. Every suggestion lists the
criteria its side wins, and those it loses, so it can be checked and overruled. Nothing is
ever decided here.
"""

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

COPY_MARKER = re.compile(r"(\s\(\d+\)$|[\s_-]copy(\s?\(?\d+\)?)?$|^copy of\s)", re.IGNORECASE)


def has_copy_marker(filename: str) -> bool:
    stem = filename.rsplit(".", 1)[0]
    return bool(COPY_MARKER.search(stem))


def exif_fields(row) -> int:
    return sum(
        (
            row["captured_at"] is not None,
            row["camera_make"] is not None or row["camera_model"] is not None,
            row["gps_lat"] is not None,
        )
    )


def best_copy(files: Sequence[sqlite3.Row]):
    """The copy that represents a content: highest source priority, then tidiest path."""
    return min(
        files,
        key=lambda f: (
            -f["source_priority"],
            has_copy_marker(f["filename"]),
            len(f["rel_path"]),
            f["rel_path"],
            f["id"],
        ),
    )


@dataclass(frozen=True)
class Criterion:
    name: str
    value: Callable  # row -> comparable, where bigger is better, or None when unknown
    describe: Callable  # (winner, loser) -> str


def _pixels(row):
    return (row["width"] or 0) * (row["height"] or 0) or None


def _capture(row):
    # Earlier is better, so compare on a negated ordinal: ISO strings sort chronologically.
    return None if row["captured_at"] is None else _Earlier(row["captured_at"])


class _Earlier:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value > other.value


def _tidiness(row):
    return (not has_copy_marker(row["filename"]), -len(row["rel_path"]))


def _path(row):
    return f"{row['source_label']}/{row['rel_path']}"


def _describe_tidier(winner, loser):
    if has_copy_marker(loser["filename"]) and not has_copy_marker(winner["filename"]):
        return f"tidier path (no copy marker, unlike {loser['filename']})"
    return f"shorter path ({len(winner['rel_path'])} vs {len(loser['rel_path'])} characters)"


CRITERIA = (
    Criterion(
        "resolution",
        _pixels,
        lambda w, lo: (
            f"higher resolution ({w['width']}x{w['height']} vs {lo['width']}x{lo['height']})"
        ),
    ),
    Criterion(
        "exif",
        exif_fields,
        lambda w, lo: f"more complete EXIF ({exif_fields(w)} of 3 fields vs {exif_fields(lo)})",
    ),
    Criterion(
        "capture_date",
        _capture,
        lambda w, lo: f"earlier capture date ({w['captured_at']} vs {lo['captured_at']})",
    ),
    Criterion(
        "source_priority",
        lambda row: row["source_priority"],
        lambda w, lo: (
            f"higher-priority source ({w['source_label']} {w['source_priority']}"
            f" vs {lo['source_label']} {lo['source_priority']})"
        ),
    ),
    Criterion("tidier_path", _tidiness, _describe_tidier),
)
TIE_BREAK = Criterion(
    "size",
    lambda row: row["size_bytes"],
    lambda w, lo: (
        f"larger file, as a tie-break ({w['size_bytes']:,} vs {lo['size_bytes']:,} bytes)"
    ),
)


def _compare(criterion, left, right) -> int:
    """1 when left wins, -1 when right wins, 0 when equal or unknown on either side."""
    a, b = criterion.value(left), criterion.value(right)
    if a is None or b is None or a == b:
        return 0
    return 1 if b < a else -1


def suggest(kind: str, left_files: Sequence, right_files: Sequence) -> dict:
    """``{"suggested": "left"|"right"|None, "keep": path, "reasons": [...], "against": [...]}``."""
    left, right = best_copy(left_files), best_copy(right_files)
    outcomes = [(criterion, _compare(criterion, left, right)) for criterion in CRITERIA]
    deciding = next((outcome for _, outcome in outcomes if outcome), 0)
    if deciding == 0:
        deciding = _compare(TIE_BREAK, left, right)
        if deciding == 0:
            return {
                "suggested": None,
                "keep": None,
                "reasons": ["no difference found"],
                "against": [],
            }
        winner, loser = (left, right) if deciding > 0 else (right, left)
        side = "left" if deciding > 0 else "right"
        return {
            "suggested": side,
            "keep": _path(winner),
            "reasons": [TIE_BREAK.describe(winner, loser)],
            "against": [],
        }
    winner, loser = (left, right) if deciding > 0 else (right, left)
    return {
        "suggested": "left" if deciding > 0 else "right",
        "keep": _path(winner),
        "reasons": [c.describe(winner, loser) for c, outcome in outcomes if outcome == deciding],
        "against": [c.describe(loser, winner) for c, outcome in outcomes if outcome == -deciding],
    }
