"""Folder names become collections.

The deepest meaningful folder is the collection, with its meaningful parents kept as a hierarchy,
so ``Pictures/Holidays/2019/Japan`` becomes ``Holidays > 2019 > Japan``. The source root, generic
names such as ``DCIM`` and DCF camera folders such as ``100CANON`` carry no meaning and are left
out. Mappings are only ever added, so renaming or merging a collection survives every rescan.
"""

import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from photo_ledger.db import collections as queries
from photo_ledger.db import now_iso

DEFAULT_GENERIC_FOLDERS = ("DCIM", "Camera", "Pictures", "Photos", "My Pictures", "Camera Roll")
#: DCF folder names cameras create, such as 100CANON or 101_PANA.
DCF_FOLDER = re.compile(r"^\d{3}[A-Za-z0-9_]{5}$")


def folder_of(rel_path: str) -> str:
    return rel_path.rpartition("/")[0]


def collection_path(
    folder: str, generic: Iterable[str] = DEFAULT_GENERIC_FOLDERS
) -> tuple[str, ...]:
    """The collection hierarchy a folder belongs to, or ``()`` when it has no meaningful name."""
    skip = {name.casefold() for name in generic}
    return tuple(
        part
        for part in folder.split("/")
        if part and part.casefold() not in skip and not DCF_FOLDER.match(part)
    )


@dataclass
class RefreshResult:
    new_collections: int = 0
    new_folders: int = 0
    total_collections: int = 0


def refresh_collections(
    conn: sqlite3.Connection, generic: Iterable[str] = DEFAULT_GENERIC_FOLDERS
) -> RefreshResult:
    """Map every folder holding a catalogued photo that isn't mapped yet."""
    generic = tuple(generic)
    result = RefreshResult()
    mapped = queries.mapped_folders(conn)
    with conn:
        for source_id, folder in queries.photo_folders(conn):
            if (source_id, folder) in mapped:
                continue
            parts = collection_path(folder, generic)
            if not parts:
                continue
            parent_id = None
            for name in parts:
                existing = queries.find(conn, name, parent_id)
                if existing is None:
                    parent_id = queries.insert(conn, name, parent_id, now_iso())
                    result.new_collections += 1
                else:
                    parent_id = existing
            queries.map_folder(conn, source_id, folder, parent_id)
            result.new_folders += 1
    result.total_collections = queries.count(conn)
    return result


def collection_paths(conn: sqlite3.Connection) -> dict[int, str]:
    """Every collection's full path, such as ``Holidays/2019/Japan``, by ID."""
    rows = {row["id"]: (row["name"], row["parent_id"]) for row in queries.all_collections(conn)}
    paths: dict[int, str] = {}

    def path(collection_id: int) -> str:
        if collection_id not in paths:
            name, parent_id = rows[collection_id]
            paths[collection_id] = name if parent_id is None else f"{path(parent_id)}/{name}"
        return paths[collection_id]

    for collection_id in rows:
        path(collection_id)
    return paths


def collections_by_content(conn: sqlite3.Connection) -> dict[int, set[str]]:
    """The collections each content belongs to through any of its copies.

    This is what a keeper inherits from the copies it replaces.
    """
    paths = collection_paths(conn)
    mapped = queries.mapped_folders(conn)
    found: dict[int, set[str]] = defaultdict(set)
    for content_id, source_id, rel_path in queries.content_files(conn):
        collection_id = mapped.get((source_id, folder_of(rel_path)))
        if collection_id is not None:
            found[content_id].add(paths[collection_id])
    return found


def collections_for_content(conn: sqlite3.Connection, content_id: int) -> list[str]:
    return sorted(collections_by_content(conn).get(content_id, set()))
