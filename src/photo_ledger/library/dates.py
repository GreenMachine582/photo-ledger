"""Capture dates for the library: a date you set wins, then EXIF. A file date never counts.

A file's modified time may only be the day it was restored from a backup, so it's never shown
or used as a capture date. A photo without EXIF, such as most PNGs, stays undated until you give
it a date on the Photos page or with ``photo-ledger date set``. Dates belong to a picture, not
one copy, and only ever change the library copy's file date and sidecar. Originals are never
touched.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from photo_ledger.db import now_iso
from photo_ledger.library import LibraryError

_ACCEPTED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?$")
_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


@dataclass(frozen=True)
class CaptureDate:
    #: ``YYYY-MM-DDTHH:MM:SS`` as the camera's clock showed it.
    taken: str
    #: Its UTC offset, such as ``+10:00``, when the camera recorded one.
    offset: str | None
    source: str  # "manual" or "exif"

    def timestamp_ns(self) -> int:
        """The moment as nanoseconds since the epoch, for a file date. Without an offset, the
        time is read as this computer's local time, as it's the best guess there is."""
        moment = datetime.fromisoformat(self.taken)
        match = _OFFSET.match(self.offset or "")
        if match:
            sign = 1 if match.group(1) == "+" else -1
            delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
            moment = moment.replace(tzinfo=timezone(sign * delta))
        elif moment.tzinfo is None:
            moment = moment.astimezone()  # local time
        return int(moment.astimezone(UTC).timestamp()) * 1_000_000_000


def parse_date(value: str) -> str:
    """``YYYY-MM-DD``, optionally with ``THH:MM`` or ``THH:MM:SS``, as ``YYYY-MM-DDTHH:MM:SS``."""
    match = _ACCEPTED.match(value.strip())
    if not match:
        raise LibraryError(f"'{value}' isn't a date. Use YYYY-MM-DD, or YYYY-MM-DDTHH:MM[:SS].")
    year, month, day, hour, minute, second = (int(part or 0) for part in match.groups())
    try:
        moment = datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise LibraryError(f"'{value}' isn't a real date: {exc}.") from exc
    return moment.isoformat(timespec="seconds")


def capture_dates(conn: sqlite3.Connection) -> dict[int, CaptureDate]:
    """Every dated picture's capture date, by content ID."""
    found = {}
    for content_id, fixed, exif, offset in conn.execute(
        "SELECT c.id, d.captured_at, c.captured_at, c.capture_offset"
        " FROM contents c LEFT JOIN date_fixes d ON d.content_id = c.id"
        " WHERE d.captured_at IS NOT NULL OR c.captured_at IS NOT NULL"
    ):
        if fixed:
            found[content_id] = CaptureDate(fixed, None, "manual")
        else:
            found[content_id] = CaptureDate(exif, offset, "exif")
    return found


def _content_of(conn: sqlite3.Connection, where: str) -> int:
    """The content of a catalogued file named as ``<source label>/<path in the source>``."""
    label, _, rel_path = where.replace("\\", "/").partition("/")
    row = conn.execute(
        "SELECT f.content_id FROM files f JOIN sources s ON s.id = f.source_id"
        " WHERE s.label = ? AND f.rel_path = ?",
        (label, rel_path),
    ).fetchone()
    if row is None:
        raise LibraryError(
            f"There's no catalogued file '{where}'. Name it as <source label>/<path in the source>."
        )
    if row[0] is None:
        raise LibraryError(f"'{where}' isn't a photo the catalogue has read, so it can't be dated.")
    return row[0]


def date_of(conn: sqlite3.Connection, content_id: int) -> CaptureDate | None:
    """One picture's capture date: the one you set, else its EXIF date, else none."""
    row = conn.execute(
        "SELECT d.captured_at, c.captured_at, c.capture_offset"
        " FROM contents c LEFT JOIN date_fixes d ON d.content_id = c.id WHERE c.id = ?",
        (content_id,),
    ).fetchone()
    if row is None:
        return None
    fixed, exif, offset = row
    if fixed:
        return CaptureDate(fixed, None, "manual")
    return CaptureDate(exif, offset, "exif") if exif else None


def _known_content(conn: sqlite3.Connection, content_id: int) -> int:
    if conn.execute("SELECT 1 FROM contents WHERE id = ?", (content_id,)).fetchone() is None:
        raise LibraryError(f"There's no catalogued photo {content_id}.")
    return content_id


def set_date(conn: sqlite3.Connection, where: str, value: str) -> str:
    """Give a picture a capture date. Every copy shares it, and no rescan overwrites it."""
    taken = parse_date(value)
    return set_content_date(conn, _content_of(conn, where), taken)


def set_content_date(conn: sqlite3.Connection, content_id: int, value: str) -> str:
    """``set_date`` for a picture named by its content ID, as the Photos page does."""
    taken = parse_date(value)
    content_id = _known_content(conn, content_id)
    with conn:
        conn.execute(
            "INSERT INTO date_fixes (content_id, captured_at, set_at) VALUES (?, ?, ?)"
            " ON CONFLICT (content_id) DO UPDATE SET captured_at = excluded.captured_at,"
            " set_at = excluded.set_at",
            (content_id, taken, now_iso()),
        )
    return taken


def clear_date(conn: sqlite3.Connection, where: str) -> bool:
    """Forget a date you set, going back to EXIF or undated. Returns whether there was one."""
    return clear_content_date(conn, _content_of(conn, where))


def clear_content_date(conn: sqlite3.Connection, content_id: int) -> bool:
    """``clear_date`` for a picture named by its content ID."""
    content_id = _known_content(conn, content_id)
    with conn:
        cursor = conn.execute("DELETE FROM date_fixes WHERE content_id = ?", (content_id,))
    return cursor.rowcount > 0
