"""Check a plan without changing anything: no file, folder or source is written.

The dry run only stats files, reads free space and, with ``verify``, hashes. A plan can only be
applied after a dry run that found no problems, and the executor checks each file again just
before moving it, so a dry run is a preview rather than a promise.
"""

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from photo_ledger.actions import PlanError, paths
from photo_ledger.db import now_iso
from photo_ledger.db import plans as queries
from photo_ledger.scanner.hashing import hash_file
from photo_ledger.sources.service import is_online


@dataclass
class Problem:
    where: str
    message: str


@dataclass
class DryRun:
    plan_id: int
    actions: int = 0
    bytes: int = 0
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _check_action(action: sqlite3.Row, verify: bool) -> list[str]:
    found = []
    origin, target = paths.endpoints(action)
    # Both ends must be connected, whichever way the file is going.
    if not is_online(action):
        return [f"Source '{action['source_label']}' is offline. Connect it first."]
    if not paths.quarantine_reachable(action):
        return [f"The quarantine is offline. Connect {paths.quarantine_name(action)}."]

    try:
        stat = origin.stat()
    except FileNotFoundError:
        return ["The file has gone. Rescan its source, then plan again."]
    except OSError as exc:
        return [f"The file can't be read: {exc}"]
    if verify:
        try:
            if hash_file(origin) != action["expected_blake3"]:
                found.append("The file's content has changed since it was scanned.")
        except OSError as exc:
            found.append(f"The file can't be read: {exc}")
    elif stat.st_size != action["size_bytes"] or (
        action["op"] == "quarantine" and stat.st_mtime_ns != action["mtime_ns"]
    ):
        found.append("The file has changed since it was scanned. Rescan its source.")
    if target.exists() or paths.partial(target).exists():
        found.append(f"Something is already at {target}, and nothing is ever overwritten.")
    return found


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _check_space(actions: list[sqlite3.Row]) -> list[Problem]:
    """Moves across volumes copy first, so each destination volume needs room for them."""
    needed: dict[Path, int] = {}
    for action in actions:
        origin, target = paths.endpoints(action)
        if paths.same_volume(origin, target):
            continue
        root = paths.existing_ancestor(target)
        if root is not None:
            needed[root] = needed.get(root, 0) + action["size_bytes"]
    problems = []
    for root, size in needed.items():
        try:
            free = free_bytes(root)
        except OSError:
            continue
        if free < size:
            problems.append(
                Problem(str(root), f"Needs {size:,} bytes free, but only {free:,} are.")
            )
    return problems


def dry_run(
    conn: sqlite3.Connection, plan_id: int, *, verify: bool = False, record: bool = True
) -> DryRun:
    """Check every action in a plan. With ``record``, a clean result allows the plan to apply."""
    plan = queries.get(conn, plan_id)
    if plan is None:
        raise PlanError(f"There's no plan {plan_id}.")
    actions = [a for a in queries.actions(conn, plan_id) if a["state"] != "done"]
    result = DryRun(plan_id, len(actions), sum(a["size_bytes"] for a in actions))
    targets: dict[Path, str] = {}
    for action in actions:
        where = f"{action['source_label']}/{action['rel_path']}"
        for message in _check_action(action, verify):
            result.problems.append(Problem(where, message))
        _origin, target = paths.endpoints(action)
        key = Path(str(target).casefold())
        if key in targets:
            result.problems.append(Problem(where, f"Goes to the same place as {targets[key]}."))
        targets[key] = where
    result.problems.extend(_check_space([a for a in actions if a["state"] == "pending"]))
    if record:
        with conn:
            queries.set_checked(conn, plan_id, now_iso() if result.ok else None)
    return result
