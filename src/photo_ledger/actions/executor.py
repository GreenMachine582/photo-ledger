"""The executor: the only code that ever changes a source folder or a quarantine.

SQLite and the filesystem can't commit together, so every action is journalled as ``started``
before its file operation and as ``done`` or ``failed`` after it. ``recovery.py`` reads that
journal after an interruption. Nothing is deleted: a file leaves its folder only as the last
step of a verified move, once a copy with the same BLAKE3 hash exists at the destination.

| Move           | How                                                                   |
|----------------|-----------------------------------------------------------------------|
| Same volume    | A rename that never replaces an existing file                         |
| Across volumes | Copy to a ``.photo-ledger-partial`` file, fsync, verify the hash,     |
|                | rename it into place without replacing, then remove the original      |
"""

import errno
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from photo_ledger.actions import PlanError, paths, planner
from photo_ledger.db import now_iso
from photo_ledger.db import plans as queries
from photo_ledger.scanner.hashing import hash_file
from photo_ledger.sources.service import is_online

#: errno values meaning "this filesystem can't hard-link", which falls back to copying.
_NO_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK}


class Refused(Exception):
    """This action can't run safely. Its files are left as they are."""


@dataclass
class ApplyResult:
    plan_id: int
    status: str
    done: int = 0
    failed: list[str] = field(default_factory=list)


# File operations -----------------------------------------------------------------------------


def _verify(path: Path, expected: str) -> None:
    if not path.is_file():
        raise Refused(f"{path} isn't there.")
    if hash_file(path) != expected:
        raise Refused(f"{path} has changed since it was scanned, so it was left alone.")


def _link_into_place(origin: Path, target: Path) -> bool:
    """Give ``origin``'s file a second name at ``target`` without replacing anything.

    Returns ``False`` when the filesystem can't do it, so the caller falls back.
    """
    if sys.platform == "win32":
        return False
    try:
        os.link(origin, target)
    except FileExistsError:
        raise Refused(f"{target} already exists, and nothing is ever overwritten.") from None
    except OSError as exc:
        if exc.errno in _NO_LINKS:
            return False
        raise
    return True


def _rename_no_replace(origin: Path, target: Path) -> bool:
    """Rename without ever replacing a file. ``False`` when only a copy can do it."""
    if sys.platform == "win32":
        try:
            os.rename(origin, target)  # never replaces an existing file on Windows
        except FileExistsError:
            raise Refused(f"{target} already exists, and nothing is ever overwritten.") from None
        except OSError as exc:
            if exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17:
                return False
            raise
        return True
    if not _link_into_place(origin, target):
        return False
    _remove_original(origin)
    return True


def _remove_original(path: Path) -> None:
    """The last step of a verified move, once the destination holds a verified copy."""
    os.unlink(path)


def discard_partial(path: Path) -> None:
    """Remove an unfinished ``.photo-ledger-partial`` copy that only the executor made."""
    if not path.name.endswith(paths.PARTIAL_SUFFIX):
        raise ValueError(f"{path} isn't a partial copy.")
    if path.is_file():
        os.unlink(path)


def _copy_verified(origin: Path, target: Path, expected: str) -> None:
    """Copy, fsync and verify into a partial file, then move it into place without replacing."""
    partial = paths.partial(target)
    with open(origin, "rb") as source, open(partial, "xb") as copy:
        shutil.copyfileobj(source, copy, 1 << 20)
        copy.flush()
        os.fsync(copy.fileno())
    shutil.copystat(origin, partial)
    if hash_file(partial) != expected:
        discard_partial(partial)
        raise Refused(f"The copy at {target} didn't match, so the original was left in place.")
    if not _rename_no_replace(partial, target):
        if target.exists():
            raise Refused(f"{target} already exists, and nothing is ever overwritten.")
        os.rename(partial, target)


def _move(origin: Path, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if paths.same_volume(origin, target) and _rename_no_replace(origin, target):
        return
    _copy_verified(origin, target, expected)
    _remove_original(origin)


def finish_move(origin: Path, target: Path, expected: str) -> None:
    """Complete a move an interruption left with both copies. Only once the target verifies."""
    _verify(target, expected)
    _verify(origin, expected)
    _remove_original(origin)


# The journal ---------------------------------------------------------------------------------


def record_done(conn: sqlite3.Connection, action: sqlite3.Row) -> None:
    """Mark the action done and the catalogue to match: a quarantined copy has left its source."""
    status = "missing" if action["op"] == "quarantine" else "present"
    with conn:
        conn.execute("UPDATE files SET status = ? WHERE id = ?", (status, action["file_id"]))
        queries.set_action_state(conn, action["id"], "done")


def _run(conn: sqlite3.Connection, action: sqlite3.Row) -> str | None:
    """Carry out one action. Returns why it failed, or ``None`` when it's done."""
    origin, target = paths.endpoints(action)
    partial = paths.partial(target)
    had_partial = partial.exists()
    with conn:
        queries.set_action_state(conn, action["id"], "started")
    try:
        # Never create folders on a drive that isn't the one the source or quarantine is on.
        if not is_online(action):
            raise Refused(f"Source '{action['source_label']}' is offline.")
        if not paths.quarantine_reachable(action):
            raise Refused(f"The quarantine is offline. Connect {paths.quarantine_name(action)}.")
        if target.exists() or had_partial:
            raise Refused(f"{target} already exists, and nothing is ever overwritten.")
        _verify(origin, action["expected_blake3"])
        _move(origin, target, action["expected_blake3"])
    except (Refused, OSError) as exc:
        if not had_partial:
            discard_partial(partial)  # this attempt's own unfinished copy, if it made one
        with conn:
            queries.set_action_state(conn, action["id"], "failed", error=str(exc))
        return str(exc)
    record_done(conn, action)
    return None


def _execute(conn: sqlite3.Connection, plan_id: int) -> ApplyResult:
    with conn:
        queries.set_status(conn, plan_id, "applying")
    result = ApplyResult(plan_id, "applying")
    for action in queries.actions(conn, plan_id):
        if action["state"] == "done":
            result.done += 1
            continue
        error = _run(conn, action)
        if error is None:
            result.done += 1
        else:
            result.failed.append(f"{action['source_label']}/{action['rel_path']}: {error}")
    # Complete only when every action is done; anything less is reported as incomplete.
    result.status = "incomplete" if result.failed else "applied"
    plan = queries.get(conn, plan_id)
    with conn:
        queries.set_status(conn, plan_id, result.status, applied_at=now_iso())
        if result.status == "applied" and plan["undoes_plan_id"] is not None:
            queries.set_status(conn, plan["undoes_plan_id"], "undone")
    return result


# Applying and undoing ------------------------------------------------------------------------


def apply(conn: sqlite3.Connection) -> ApplyResult:
    """Finish an interrupted plan, or apply the draft after a clean dry run."""
    from photo_ledger.actions.recovery import recover

    recover(conn)
    unfinished = queries.latest(conn, "applying", "incomplete")
    if unfinished is not None:
        return _execute(conn, unfinished["id"])
    plan = planner.draft(conn)
    if plan is None:
        raise PlanError("There's no plan to apply. Build one with `photo-ledger plan`.")
    if planner.is_stale(conn, plan):
        raise PlanError("Decisions changed after this plan was built. Run `photo-ledger plan`.")
    if not plan["checked_at"]:
        raise PlanError("This plan hasn't passed a dry run. Run `photo-ledger plan` first.")
    return _execute(conn, plan["id"])


def undo(conn: sqlite3.Connection) -> ApplyResult:
    """Put back the files the most recent applied plan moved, through a plan of its own."""
    from photo_ledger.actions.recovery import recover

    recover(conn)
    unfinished = conn.execute(
        "SELECT * FROM plans WHERE status IN ('applying', 'incomplete')"
        " AND undoes_plan_id IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if unfinished is not None:
        return _execute(conn, unfinished["id"])
    original = conn.execute(
        "SELECT * FROM plans WHERE status IN ('applied', 'incomplete')"
        " AND undoes_plan_id IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if original is None:
        raise PlanError("There's no applied plan to undo.")
    moved = [a for a in queries.actions(conn, original["id"]) if a["state"] == "done"]
    for action in moved:
        if not paths.quarantine_reachable(action):
            raise PlanError(
                f"Undo needs the quarantine at {paths.quarantine_name(action)}. "
                "Connect it and try again."
            )
    with conn:
        plan_id = queries.insert_plan(conn, undoes=original["id"])
        queries.set_status(conn, plan_id, "applying")
        for action in reversed(moved):
            queries.insert_action(
                conn,
                plan_id,
                file_id=action["file_id"],
                op="restore",
                from_path=action["to_path"],
                to_path=action["from_path"],
                quarantine_root=action["quarantine_root"],
                quarantine_volume_id=action["quarantine_volume_id"],
                expected_blake3=action["expected_blake3"],
                size_bytes=action["size_bytes"],
            )
    return _execute(conn, plan_id)
