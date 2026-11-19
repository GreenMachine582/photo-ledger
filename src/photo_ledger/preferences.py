"""Settings you edit in the browser: what a match finds, and which obvious pairs it decides.

They're stored in the catalogue's ``settings`` table. A stored value wins over the
``PHOTO_LEDGER_*`` environment variable, and resetting goes back to it. They only change what the
next match does: nothing on disk changes, and no FastAPI here.
"""

import json
import sqlite3
from dataclasses import dataclass

from photo_ledger.config import Settings
from photo_ledger.db import now_iso
from photo_ledger.errors import PhotoLedgerError

THRESHOLD_MIN, THRESHOLD_MAX = 0, 32
MIN_SIDE_MAX = 10000
#: Switches, in the order the Settings page shows them.
FLAGS = ("name_conflicts", "auto_tidier_path", "auto_priority", "dismiss_unlike_names")
KEYS = ("similar_threshold", "generic_folders", "min_similar_side", *FLAGS)


class PreferencesError(PhotoLedgerError):
    """A setting can't be saved as given."""


@dataclass(frozen=True)
class Preferences:
    similar_threshold: int
    generic_folders: list[str]
    name_conflicts: bool = True
    min_similar_side: int = 0
    auto_tidier_path: bool = True
    auto_priority: bool = True
    dismiss_unlike_names: bool = True
    #: The names of the settings that come from the catalogue, not the environment.
    saved: frozenset[str] = frozenset()

    def match_options(self) -> dict:
        """What ``matching.pairs.match`` takes, beside the threshold."""
        return {"name_conflicts": self.name_conflicts, "min_similar_side": self.min_similar_side}

    def rules(self) -> dict:
        """What ``review.automatic.apply`` takes."""
        return {
            "tidier_path": self.auto_tidier_path,
            "priority": self.auto_priority,
            "unlike_names": self.dismiss_unlike_names,
            "threshold": self.similar_threshold,
        }


def _stored(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: json.loads(row["value"]) for row in rows if row["key"] in KEYS}


def effective(conn: sqlite3.Connection, settings: Settings) -> Preferences:
    """The settings a match uses: the saved ones, else the environment's or the defaults."""
    stored = _stored(conn)
    env = {key: getattr(settings, f"photo_ledger_{key}") for key in KEYS}
    env["generic_folders"] = list(env["generic_folders"])
    return Preferences(**{**env, **stored}, saved=frozenset(stored))


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


def parse_min_side(value: str | int) -> int:
    text = str(value).strip()
    try:
        side = int(text) if text else 0
    except ValueError:
        raise PreferencesError("The smallest image size must be a whole number.") from None
    if not 0 <= side <= MIN_SIDE_MAX:
        raise PreferencesError(
            f"The smallest image size must be between 0 and {MIN_SIDE_MAX:,} pixels."
        )
    return side


def parse_flag(value: str | bool) -> bool:
    """A switch: ``true`` or ``false``, as a form sends them."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text not in ("true", "false"):
        raise PreferencesError(f"'{value}' isn't on or off.")
    return text == "true"


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
    conn: sqlite3.Connection,
    *,
    similar_threshold: str | int,
    generic_folders: str | list[str],
    min_similar_side: str | int | None = None,
    **flags: str | bool,
) -> None:
    """Check every value given, then store them together. Nothing is stored if one is wrong.

    ``flags`` are the switches in ``FLAGS``. A setting left out keeps what it had.
    """
    unknown = set(flags) - set(FLAGS)
    if unknown:
        raise PreferencesError(f"Unknown setting: {', '.join(sorted(unknown))}.")
    values = {
        "similar_threshold": parse_threshold(similar_threshold),
        "generic_folders": parse_folders(generic_folders),
    }
    if min_similar_side is not None:
        values["min_similar_side"] = parse_min_side(min_similar_side)
    values.update({key: parse_flag(value) for key, value in flags.items()})
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
