"""Where each picture goes in the library. Pure: nothing here reads or writes a file.

| Layout     | Path                                                                        |
|------------|-----------------------------------------------------------------------------|
| ``year``     | ``YYYY/<main collection>/<filename>``, or ``Undated/...`` without a capture date |
| ``original`` | ``<source label>/<path in the source>`` of the chosen copy                   |

A picture's main collection is the collection of its chosen copy's own folder, or else the first
of the collections it inherits from its other copies. Hidden collections are skipped, and a
collection starting with the year itself isn't repeated, so ``2019`` gives ``2019/`` rather than
``2019/2019/``. The others it belongs to are kept in its sidecar and the CSV, never lost.
"""

import sqlite3
from pathlib import PurePosixPath

from photo_ledger.collections.folders import collections_by_content, folder_of
from photo_ledger.db import collections as collection_queries

UNDATED = "Undated"


def visible_paths(conn: sqlite3.Connection) -> dict[int, str]:
    """Each collection's path by ID, leaving out hidden ones and everything beneath them."""
    rows = {row["id"]: row for row in collection_queries.all_collections(conn)}
    paths: dict[int, str | None] = {}

    def path(collection_id: int) -> str | None:
        if collection_id not in paths:
            row = rows[collection_id]
            parent = path(row["parent_id"]) if row["parent_id"] is not None else ""
            hidden = row["hidden"] or parent is None
            paths[collection_id] = (
                None if hidden else "/".join(p for p in (parent, row["name"]) if p)
            )
        return paths[collection_id]

    for collection_id in rows:
        path(collection_id)
    return {cid: p for cid, p in paths.items() if p is not None}


class Layout:
    """Works out library paths for one build, given the catalogue's collections."""

    def __init__(self, conn: sqlite3.Connection, layout: str):
        self.layout = layout
        self.visible = visible_paths(conn)
        self.visible_set = set(self.visible.values())
        self.mapped = collection_queries.mapped_folders(conn)
        self.inherited = collections_by_content(conn)

    def collections(self, content_id: int) -> list[str]:
        """Every visible collection the picture belongs to, through any of its copies."""
        return sorted(c for c in self.inherited.get(content_id, ()) if c in self.visible_set)

    def main_collection(self, chosen: sqlite3.Row) -> str | None:
        own = self.mapped.get((chosen["source_id"], folder_of(chosen["rel_path"])))
        if own is not None and own in self.visible:
            return self.visible[own]
        others = self.collections(chosen["content_id"])
        return others[0] if others else None

    def path_for(self, chosen: sqlite3.Row, captured_at: str | None) -> str:
        if self.layout == "original":
            parts = [chosen["source_label"], *chosen["rel_path"].split("/")]
        else:
            year = captured_at[:4] if captured_at else UNDATED
            collection = self.main_collection(chosen)
            folders = collection.split("/") if collection else []
            if folders and folders[0] == year:
                folders = folders[1:]  # a "2019" collection inside 2019/ would only repeat it
            parts = [year, *folders, chosen["filename"]]
        return "/".join(_safe(part) for part in parts)


def _safe(part: str) -> str:
    """A path part that's valid on Windows too: no reserved characters or trailing dots."""
    cleaned = "".join("_" if ch in '<>:"\\|?*' or ord(ch) < 32 else ch for ch in part)
    return cleaned.rstrip(" .") or "_"


def unique(path: str, used: set[str]) -> str:
    """``path``, or ``name (2).ext`` and so on when it's taken, recorded in ``used``.

    ``used`` holds casefolded paths, so two names differing only in case never collide on
    Windows.
    """
    candidate, number = path, 2
    pure = PurePosixPath(path)
    while candidate.casefold() in used:
        candidate = str(pure.with_name(f"{pure.stem} ({number}){pure.suffix}"))
        number += 1
    used.add(candidate.casefold())
    return candidate
