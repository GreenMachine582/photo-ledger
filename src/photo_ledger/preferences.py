"""Settings you edit in the browser: the similar threshold and the generic folder names.

They're stored in the catalogue's ``settings`` table. A stored value wins over the
``PHOTO_LEDGER_*`` environment variable, and resetting goes back to it. They only change what the
next match finds: nothing on disk changes, and no FastAPI here.
"""

import json
import sqlite3
from dataclasses import dataclass

from photo_ledger.config import Settings
from photo_ledger.db import now_iso
from photo_ledger.errors import PhotoLedgerError

THRESHOLD_MIN, THRESHOLD_MAX = 0, 32
KEYS = ("similar_threshold", "generic_folders")


class PreferencesError(PhotoLedgerError):
    """A setting can't be saved as given."""


@dataclass(frozen=True)
class Preferences:
    similar_threshold: int
    generic_folders: list[str]
    #: The names of the settings that come from the catalogue, not the environment.
    saved: frozenset[str] = frozenset()


def _stored(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: json.loads(row["value"]) for row in rows if row["key"] in KEYS}


def effective(conn: sqlite3.Connection, settings: Settings) -> Preferences:
    """The settings a match uses: the saved ones, else the environment's or the defaults."""
    stored = _stored(conn)
    return Preferences(
        similar_threshold=stored.get("similar_threshold", settings.photo_ledger_similar_threshold),
        generic_folders=stored.get("generic_folders", list(settings.photo_ledger_generic_folders)),
        saved=frozenset(stored),
    )


def parse_threshold(value: str | int) -> int:
    try:
        threshold = int(str(value).strip())
    except ValueError:
        raise PreferencesError("The similar threshold must be a whole number.") from None
    if not THRESHOLD_MIN <= threshold <= THRESHOLD_MAX:
        raise PreferencesError(
            f"The similar threshold must be between {THRESHOLD_MIN} and {THRESHOLD_MAX}."
        )
    return threshold


def parse_folders(value: str | list[str]) -> list[str]:
    """Folder names, one per line, stripped and without repeats (ignoring case)."""
    names = value.splitlines() if isinstance(value, str) else value
    folders, seen = [], set()
    for name in (name.strip() for name in names):
        if not name:
            continue
        if "/" in name or "\\" in name:
            raise PreferencesError(f"'{name}' isn't a folder name: leave out slashes.")
        if name.casefold() not in seen:
            seen.add(name.casefold())
            folders.append(name)
    return folders


def save(
    conn: sqlite3.Connection, *, similar_threshold: str | int, generic_folders: str | list[str]
) -> None:
    """Check both values, then store them together. Nothing is stored if either is wrong."""
    values = {
        "similar_threshold": parse_threshold(similar_threshold),
        "generic_folders": parse_folders(generic_folders),
    }
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value, set_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, set_at = excluded.set_at",
            [(key, json.dumps(value), now_iso()) for key, value in values.items()],
        )


def reset(conn: sqlite3.Connection) -> bool:
    """Forget the saved settings. Returns whether there were any."""
    with conn:
        cursor = conn.execute("DELETE FROM settings")
    return cursor.rowcount > 0
