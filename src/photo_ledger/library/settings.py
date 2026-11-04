"""Where the library is and how it's laid out. Setting it up creates nothing on disk."""

import os
import sqlite3
from pathlib import Path

from photo_ledger.db import library as queries
from photo_ledger.db import sources as source_queries
from photo_ledger.library import LibraryError
from photo_ledger.sources import device
from photo_ledger.sources.service import overlaps

LAYOUTS = ("year", "original")


def get_library(conn: sqlite3.Connection) -> sqlite3.Row:
    library = queries.get(conn)
    if library is None:
        raise LibraryError(
            "There's no library yet. Choose its folder with `photo-ledger library set <folder>`."
        )
    return library


def set_library(conn: sqlite3.Connection, folder: Path | str, layout: str = "year") -> sqlite3.Row:
    """Choose the library's folder and layout.

    The folder must exist and sit outside every source and quarantine. Choosing a different
    folder starts a new, empty library and leaves the old folder as it is. The layout of a library
    that already holds files can't change, as files are never moved once copied.
    """
    if layout not in LAYOUTS:
        raise LibraryError(f"Unknown layout '{layout}'. Use one of: {', '.join(LAYOUTS)}.")
    try:
        root = Path(folder).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LibraryError(f"{folder} doesn't exist or can't be read.") from exc
    if not root.is_dir():
        raise LibraryError(f"{root} isn't a folder.")
    for source in source_queries.all_sources(conn):
        if overlaps(root, source["root_path"]):
            raise LibraryError(
                f"{root} overlaps source '{source['label']}'. The library must sit outside every "
                "source, so building it never writes to one."
            )
        if source["quarantine_path"] and overlaps(root, source["quarantine_path"]):
            raise LibraryError(
                f"{root} overlaps the quarantine for '{source['label']}'. Choose another folder."
            )
    current = queries.get(conn)
    same_folder = current is not None and os.path.normcase(str(root)) == os.path.normcase(
        current["root_path"]
    )
    with conn:
        if current is not None and not same_folder:
            queries.forget_all(conn)
        elif current is not None and layout != current["layout"]:
            if queries.counts(conn).get("done"):
                raise LibraryError(
                    f"The library at {root} already holds files in the '{current['layout']}' "
                    "layout, and copied files are never moved. Choose a new folder for another "
                    "layout."
                )
            queries.forget_unbuilt(conn)
        queries.save(
            conn, root_path=str(root), volume_id=device.describe(root).volume_id, layout=layout
        )
    return queries.get(conn)


def library_online(library: sqlite3.Row) -> bool:
    """The library folder is reachable and, where known, on the volume it was set on."""
    root = Path(library["root_path"])
    if not root.is_dir():
        return False
    if library["volume_id"]:
        current = device.describe(root).volume_id
        if current and current != library["volume_id"]:
            return False
    return True


def library_name(library: sqlite3.Row) -> str:
    volume = library["volume_id"]
    return f"volume {volume} ({library['root_path']})" if volume else library["root_path"]
