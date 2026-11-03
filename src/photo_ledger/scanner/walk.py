"""A resumable, read-only walk of a source.

Entries are visited depth-first with each folder's entries sorted by name. That order is the
same as comparing paths as tuples of their parts, so a walk can resume after any path: folders
that sort entirely before it are skipped without being opened. Symlinks and junctions are never
followed, so a walk can't leave its source or loop.
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WalkEntry:
    rel_path: str  # POSIX-style, relative to the root
    size_bytes: int
    mtime_ns: int
    birthtime_ns: int | None


def parts(rel_path: str) -> tuple[str, ...]:
    return tuple(rel_path.split("/")) if rel_path else ()


def _is_link(entry: os.DirEntry) -> bool:
    return entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction())


def walk(
    root: Path,
    *,
    after: str | None = None,
    on_error: Callable[[str, OSError], None] | None = None,
) -> Iterator[WalkEntry]:
    """Yield every regular file under ``root`` whose path sorts after ``after``.

    A folder that can't be listed is reported to ``on_error`` with its relative path and
    skipped. If the root itself can't be listed, the ``OSError`` is raised instead.
    """
    resume = parts(after) if after else ()
    yield from _walk_dir(Path(root), (), resume, on_error, is_root=True)


def _walk_dir(directory, prefix, resume, on_error, *, is_root=False):
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        if is_root or on_error is None:
            raise
        on_error("/".join(prefix), exc)
        return
    for entry in entries:
        if _is_link(entry):
            continue
        path_parts = (*prefix, entry.name)
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
            is_file = not is_dir and entry.is_file(follow_symlinks=False)
        except OSError as exc:
            if on_error:
                on_error("/".join(path_parts), exc)
            continue
        if is_dir:
            if resume and path_parts < resume and resume[: len(path_parts)] != path_parts:
                continue  # everything inside sorts before the resume point
            child_resume = resume if resume[: len(path_parts)] == path_parts else ()
            yield from _walk_dir(entry.path, path_parts, child_resume, on_error)
        elif is_file:
            if resume and path_parts <= resume:
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                if on_error:
                    on_error("/".join(path_parts), exc)
                continue
            yield WalkEntry(
                rel_path="/".join(path_parts),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                birthtime_ns=getattr(stat, "st_birthtime_ns", None),
            )
