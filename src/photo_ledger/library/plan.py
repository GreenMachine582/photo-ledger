"""Plan and dry-run a library build. Only the catalogue is written; no file or folder is touched.

Planning adds a ``pending`` entry for each settled picture the library doesn't hold yet. Entries
already copied keep their place, so a rebuild only ever adds. A picture copied earlier that is no
longer settled, such as one rejected since, is reported but never removed.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from photo_ledger.actions import paths
from photo_ledger.actions.dryrun import Problem, free_bytes
from photo_ledger.db import library as queries
from photo_ledger.library import selection
from photo_ledger.library.layout import Layout, unique
from photo_ledger.library.settings import get_library, library_name, library_online
from photo_ledger.sources.service import is_online


@dataclass
class LibraryPlan:
    to_copy: int = 0
    to_copy_bytes: int = 0
    already: int = 0
    waiting: int = 0
    rejected: int = 0
    corrupt: int = 0
    #: Pictures in the library that are no longer settled. They stay; nothing is removed.
    no_longer_chosen: list[str] = field(default_factory=list)


def capture_date(row: sqlite3.Row) -> str | None:
    """The date a picture was taken, from EXIF. File dates never count: they may be restores."""
    return row["captured_at"]


def plan_library(conn: sqlite3.Connection) -> LibraryPlan:
    library = get_library(conn)
    picked = selection.settled_pictures(conn)
    layout = Layout(conn, library["layout"])
    result = LibraryPlan(
        waiting=len(picked.waiting), rejected=picked.rejected, corrupt=picked.corrupt
    )
    with conn:
        queries.forget_unbuilt(conn)
        kept = {row["content_id"]: row for row in queries.entries(conn)}
        used = {row["rel_path"].casefold() for row in kept.values()}
        for content_id, row in kept.items():
            if content_id not in picked.chosen:
                result.no_longer_chosen.append(row["rel_path"])
        new = [
            (layout.path_for(chosen, capture_date(chosen)), content_id, chosen)
            for content_id, chosen in picked.chosen.items()
            if content_id not in kept
        ]
        # A fixed order, so collision suffixes don't depend on the order rows came back in.
        for path, content_id, chosen in sorted(new, key=lambda item: (item[0].casefold(), item[1])):
            queries.insert_entry(
                conn,
                content_id=content_id,
                file_id=chosen["id"],
                rel_path=unique(path, used),
                expected_blake3=chosen["blake3"],
                size_bytes=chosen["size_bytes"],
            )
            result.to_copy += 1
            result.to_copy_bytes += chosen["size_bytes"]
        result.already = sum(1 for row in kept.values() if row["state"] == "done")
    return result


def endpoints(library: sqlite3.Row, entry: sqlite3.Row) -> tuple[Path, Path]:
    """``(the source copy, its place in the library)`` as absolute paths."""
    return (
        Path(entry["root_path"]) / entry["source_rel_path"],
        Path(library["root_path"]) / entry["rel_path"],
    )


def check_library(conn: sqlite3.Connection) -> list[Problem]:
    """A read-only dry run of every entry still to copy."""
    library = get_library(conn)
    if not library_online(library):
        return [Problem("library", f"The library is offline. Connect {library_name(library)}.")]
    problems, needed = [], 0
    for entry in queries.entries(conn, "pending", "failed", "started"):
        where = f"{entry['source_label']}/{entry['source_rel_path']}"
        origin, target = endpoints(library, entry)
        if not is_online(entry):
            problems.append(Problem(where, f"Source '{entry['source_label']}' is offline."))
            continue
        try:
            stat = origin.stat()
        except OSError:
            problems.append(
                Problem(where, "The file has gone. Rescan its source, then plan again.")
            )
            continue
        if stat.st_size != entry["size_bytes"] or stat.st_mtime_ns != entry["mtime_ns"]:
            problems.append(Problem(where, "The file has changed since it was scanned. Rescan it."))
        if target.exists() or paths.partial(target).exists():
            problems.append(
                Problem(
                    where, f"Something is already at {target}, and nothing is ever overwritten."
                )
            )
        needed += entry["size_bytes"]
    if needed:
        free = free_bytes(Path(library["root_path"]))
        if free < needed:
            problems.append(
                Problem("library", f"Needs {needed:,} bytes free, but only {free:,} are.")
            )
    return problems
