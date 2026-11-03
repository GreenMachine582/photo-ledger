"""Mapping, checking and reconnecting sources.

A source is identified by its label. Its root may move to a new drive letter or mount path, in
which case the volume identifier recorded when it was mapped is used to find and confirm it.
"""

import dataclasses
import os
import re
import sqlite3
from pathlib import Path, PurePath

from photo_ledger.db import sources as queries
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.sources import device

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


class SourceError(PhotoLedgerError):
    """A source can't be mapped, found or reconnected."""


def _normalised(path: Path | str) -> PurePath:
    return PurePath(os.path.normcase(os.path.normpath(str(path))))


def overlaps(a: Path | str, b: Path | str) -> bool:
    """True when either path is the other or inside it. Case-insensitive where the OS is."""
    na, nb = _normalised(a), _normalised(b)
    return na == nb or na.is_relative_to(nb) or nb.is_relative_to(na)


def _resolve_root(path: Path | str) -> Path:
    try:
        root = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SourceError(f"{path} doesn't exist or can't be read.") from exc
    if not root.is_dir():
        raise SourceError(f"{root} isn't a folder.")
    return root


def _refuse_overlap(conn: sqlite3.Connection, root: Path, *, ignore_id: int | None = None) -> None:
    for other in queries.all_sources(conn):
        if other["id"] != ignore_id and overlaps(root, other["root_path"]):
            raise SourceError(
                f"{root} overlaps source '{other['label']}' at {other['root_path']}. "
                "Nested sources would record every file twice."
            )


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return queries.all_sources(conn)


def get_source(conn: sqlite3.Connection, label: str) -> sqlite3.Row:
    row = queries.by_label(conn, label)
    if row is None:
        raise SourceError(f"There's no source called '{label}'. See `photo-ledger source list`.")
    return row


def add_source(conn: sqlite3.Connection, path: Path | str, label: str) -> sqlite3.Row:
    """Map a folder or drive as a source, refusing one that overlaps an existing source."""
    if not LABEL_PATTERN.match(label):
        raise SourceError(
            "Labels are 1-64 letters, digits, spaces, dots, dashes or underscores, "
            "starting with a letter or digit."
        )
    if queries.by_label(conn, label):
        raise SourceError(f"A source called '{label}' already exists.")
    root = _resolve_root(path)
    _refuse_overlap(conn, root)
    details = dataclasses.asdict(device.describe(root))
    with conn:
        source_id = queries.insert(conn, label=label, root_path=str(root), device=details)
    return queries.by_id(conn, source_id)


def is_online(source: sqlite3.Row) -> bool:
    """The root is reachable and, where both are known, on the volume it was mapped on.

    A different drive mounted at the same letter must not count as online, or a scan of it
    would mark every catalogued file missing.
    """
    root = Path(source["root_path"])
    if not root.is_dir():
        return False
    if source["volume_id"]:
        current = device.describe(root).volume_id
        if current and current != source["volume_id"]:
            return False
    return True


def refresh_state(conn: sqlite3.Connection, source: sqlite3.Row) -> bool:
    """Record whether the source is online now, and return it."""
    online = is_online(source)
    with conn:
        queries.set_state(conn, source["id"], "online" if online else "offline")
    return online


def find_new_root(source: sqlite3.Row) -> Path | None:
    """Look for the source's volume at another drive letter or mount path."""
    volume_id, volume_root = source["volume_id"], source["volume_root"]
    if not volume_id or not volume_root:
        return None
    old_root = Path(source["root_path"])
    try:
        tail = old_root.relative_to(volume_root)
    except ValueError:
        return None
    for mounted_root, mounted_id in device.mounted_volumes():
        if mounted_id == volume_id:
            candidate = Path(mounted_root) / tail
            if candidate.is_dir() and _normalised(candidate) != _normalised(old_root):
                return candidate
    return None


def reconnect(conn: sqlite3.Connection, label: str, new_root: Path | str) -> sqlite3.Row:
    """Point a source at a new root, refusing one on a different volume or overlapping another."""
    source = get_source(conn, label)
    root = _resolve_root(new_root)
    _refuse_overlap(conn, root, ignore_id=source["id"])
    details = dataclasses.asdict(device.describe(root))
    if source["volume_id"] and details["volume_id"] and details["volume_id"] != source["volume_id"]:
        raise SourceError(
            f"{root} is on volume {details['volume_id']}, but '{label}' was mapped on volume "
            f"{source['volume_id']}. Map it as a new source if it's a different drive."
        )
    with conn:
        queries.update_root(conn, source["id"], root_path=str(root), device=details)
    return queries.by_id(conn, source["id"])


def set_priority(conn: sqlite3.Connection, label: str, priority: int) -> sqlite3.Row:
    """Set how strongly keeper suggestions prefer this source's copies. Higher wins."""
    source = get_source(conn, label)
    with conn:
        queries.set_priority(conn, source["id"], priority)
    return queries.by_id(conn, source["id"])
