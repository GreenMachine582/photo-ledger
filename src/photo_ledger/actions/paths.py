"""Where an action's file is and where it goes. Read-only: nothing here touches a file."""

import os
import sqlite3
from pathlib import Path

from photo_ledger.sources import device

#: The suffix of a copy in progress across volumes. Only the executor creates or removes one.
PARTIAL_SUFFIX = ".photo-ledger-partial"


def endpoints(action: sqlite3.Row) -> tuple[Path, Path]:
    """``(from, to)`` as absolute paths. ``action`` is a row from ``db.plans.ACTION_ROWS``."""
    source = Path(action["root_path"])
    quarantine = Path(action["quarantine_root"])
    if action["op"] == "quarantine":
        return source / action["from_path"], quarantine / action["to_path"]
    return quarantine / action["from_path"], source / action["to_path"]


def partial(path: Path) -> Path:
    return path.with_name(path.name + PARTIAL_SUFFIX)


def existing_ancestor(path: Path) -> Path | None:
    """The nearest folder above ``path`` that exists, which is where space and volume are read."""
    for parent in path.parents:
        if parent.is_dir():
            return parent
    return None


def same_volume(a: Path, b: Path) -> bool:
    """Whether a rename can move ``a`` to ``b``, judged by the folders that exist on each side."""
    left, right = existing_ancestor(a), existing_ancestor(b)
    if left is None or right is None:
        return False
    try:
        return os.stat(left).st_dev == os.stat(right).st_dev
    except OSError:
        return False


def quarantine_reachable(action: sqlite3.Row) -> bool:
    """The quarantine folder the action was planned with is there, on the volume it was set on."""
    root = Path(action["quarantine_root"])
    if not root.is_dir():
        return False
    if action["quarantine_volume_id"]:
        current = device.describe(root).volume_id
        if current and current != action["quarantine_volume_id"]:
            return False
    return True


def quarantine_name(action: sqlite3.Row) -> str:
    """The device to ask for when the quarantine is offline."""
    volume = action["quarantine_volume_id"]
    root = action["quarantine_root"]
    return f"volume {volume} ({root})" if volume else root
