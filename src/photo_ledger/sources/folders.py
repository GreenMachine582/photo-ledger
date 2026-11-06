"""Folder names for the browser's folder explorer: drives and mount points, then each folder's
subfolders on request.

Read-only and names only: this lists directories with ``os.scandir`` and never opens, stats for
content or lists a file. Hidden and system folders, and links, are left out, so a junction can't
loop and nothing is shown that Explorer or a file manager would hide by default.
"""

import os
import sqlite3
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from photo_ledger.db import library as library_queries
from photo_ledger.db import sources as source_queries
from photo_ledger.sources import device
from photo_ledger.sources.service import SourceError, _normalised

#: Most subfolders shown under one folder. A folder with more is better typed than scrolled.
LIMIT = 500

#: POSIX mount points worth offering as starting places, besides ``/`` and the home folder.
_MOUNT_PARENTS = ("/media/", "/mnt/", "/run/media/", "/Volumes/")

_HIDDEN_ATTRIBUTES = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(
    stat, "FILE_ATTRIBUTE_SYSTEM", 4
)


@dataclass(frozen=True)
class Folder:
    name: str
    path: str
    has_children: bool
    mapped_as: str | None = None


@dataclass(frozen=True)
class Listing:
    folders: list[Folder]
    more: int = 0  # how many were left out over LIMIT


def _visible_folder(entry: os.DirEntry) -> bool:
    """A real, non-hidden directory: not a file, link or junction, not a dot or system folder."""
    try:
        if entry.name.startswith(".") or entry.is_symlink() or entry.is_junction():
            return False
        if not entry.is_dir(follow_symlinks=False):
            return False
        if sys.platform == "win32":
            attributes = entry.stat(follow_symlinks=False).st_file_attributes
            return not attributes & _HIDDEN_ATTRIBUTES
    except OSError:
        return False
    return True


def _has_subfolder(path: str) -> bool:
    """Stops at the first visible subfolder, so a large folder costs one entry, not all of them."""
    try:
        with os.scandir(path) as entries:
            return any(_visible_folder(entry) for entry in entries)
    except OSError:
        return False


def roots() -> list[Folder]:
    """Where browsing starts: drive letters on Windows, otherwise ``/``, home and removable mounts.

    A root isn't probed for subfolders, so a slow or empty drive never holds up the list.
    """
    if sys.platform == "win32":
        return [Folder(name=drive, path=drive, has_children=True) for drive in os.listdrives()]
    places = ["/", str(Path.home())]
    try:
        places += sorted(
            point for _dev, point, _fs in device._mounts() if point.startswith(_MOUNT_PARENTS)
        )
    except OSError:
        pass
    return [Folder(name=p, path=p, has_children=True) for p in dict.fromkeys(places)]


def children(path: str) -> Listing:
    """The visible subfolders of an existing folder, by name, case-insensitively sorted."""
    if not path or not os.path.isabs(path):
        raise SourceError("Pick a folder from the list.")
    if not os.path.isdir(path):
        raise SourceError(f"{path} isn't connected, or isn't a folder.")
    try:
        with os.scandir(path) as entries:
            found = sorted(
                ((entry.name, entry.path) for entry in entries if _visible_folder(entry)),
                key=lambda pair: pair[0].casefold(),
            )
    except OSError as exc:
        raise SourceError(f"{path} can't be read.") from exc
    shown = [
        Folder(name=name, path=full, has_children=_has_subfolder(full))
        for name, full in found[:LIMIT]
    ]
    return Listing(folders=shown, more=max(0, len(found) - LIMIT))


def annotate(conn: sqlite3.Connection, folders: list[Folder]) -> list[Folder]:
    """Name the folders already in use, since mapping inside or over them is refused."""
    used: dict[object, str] = {}
    for source in source_queries.all_sources(conn):
        used[_normalised(source["root_path"])] = f"source {source['label']}"
        if source["quarantine_path"]:
            used.setdefault(_normalised(source["quarantine_path"]), "quarantine")
    library = library_queries.get(conn)
    if library is not None:
        used.setdefault(_normalised(library["root_path"]), "library")
    return [Folder(f.name, f.path, f.has_children, used.get(_normalised(f.path))) for f in folders]
