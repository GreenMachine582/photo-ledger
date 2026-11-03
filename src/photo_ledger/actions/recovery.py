"""Recovery after an interrupted plan. It decides; the executor makes any change to a file.

An action journalled as ``started`` but never finished could have stopped at any point, so both
paths are checked against the expected BLAKE3 hash:

| Found                                          | Then                                        |
|------------------------------------------------|---------------------------------------------|
| A ``.photo-ledger-partial`` copy               | Remove it (only the executor makes them)    |
| Original verified, no destination              | Back to ``pending``: the move never ran     |
| Destination verified, no original              | ``done``: the move finished                 |
| Both verified                                  | Finish the move by removing the original    |
| Anything else                                  | ``failed``, with both files left alone      |

A plan that was ``applying`` becomes ``incomplete``. It's only reported as applied once a later
``apply`` (or ``undo``) has finished every action.
"""

import sqlite3
from dataclasses import dataclass, field

from photo_ledger.actions import executor, paths
from photo_ledger.db import plans as queries
from photo_ledger.scanner.hashing import hash_file
from photo_ledger.sources.service import is_online


@dataclass
class Recovery:
    pending: int = 0
    done: int = 0
    finished: int = 0
    failed: list[str] = field(default_factory=list)
    #: Left ``started`` until both their source and quarantine are connected.
    waiting: list[str] = field(default_factory=list)
    plans: list[int] = field(default_factory=list)


def _matches(path, expected: str) -> bool:
    try:
        return path.is_file() and hash_file(path) == expected
    except OSError:
        return False


def _recover_action(conn: sqlite3.Connection, action: sqlite3.Row, result: Recovery) -> None:
    origin, target = paths.endpoints(action)
    expected = action["expected_blake3"]
    executor.discard_partial(paths.partial(target))
    origin_ok, target_ok = _matches(origin, expected), _matches(target, expected)
    if origin_ok and not target.exists():
        with conn:
            queries.set_action_state(conn, action["id"], "pending")
        result.pending += 1
    elif target_ok and not origin.exists():
        executor.record_done(conn, action)
        result.done += 1
    elif target_ok and origin_ok:
        executor.finish_move(origin, target, expected)
        executor.record_done(conn, action)
        result.finished += 1
    else:
        message = (
            f"Interrupted, and neither {origin} nor {target} could be confirmed. "
            "Both were left as they are: check them by hand."
        )
        with conn:
            queries.set_action_state(conn, action["id"], "failed", error=message)
        result.failed.append(message)


def recover(conn: sqlite3.Connection) -> Recovery:
    """Settle every action an interruption left ``started``, and mark its plan incomplete."""
    result = Recovery()
    started = conn.execute(f"{queries.ACTION_ROWS} WHERE a.state = 'started' ORDER BY a.id")
    for action in started.fetchall():
        where = f"{action['source_label']}/{action['rel_path']}"
        # A missing original on an unplugged drive isn't a finished move: wait for both ends.
        if not (is_online(action) and paths.quarantine_reachable(action)):
            result.waiting.append(where)
            continue
        try:
            _recover_action(conn, action, result)
        except OSError as exc:
            result.waiting.append(f"{where}: {exc}")
    for plan in conn.execute("SELECT id FROM plans WHERE status = 'applying'").fetchall():
        with conn:
            queries.set_status(conn, plan["id"], "incomplete")
        result.plans.append(plan["id"])
    return result
