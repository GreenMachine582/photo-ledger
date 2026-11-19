"""Rules that decide obvious pairs at match, each switched on or off on the Settings page.

- ``tidier_path``: exact copies in sources of equal priority, told apart only by their paths. Keeps
  the copy without a copy marker such as `` (1)``, then the one with the shorter path.
- ``priority``: exact copies in sources of different priority. Keeps the copy in the
  higher-priority source.
- ``unlike_names``: a name conflict whose pictures don't look alike, as their pHashes are farther
  apart than the similar threshold. Keeps both, so nothing is rejected.

Exact copies are byte-for-byte the same and share their collections, so which one is kept loses
nothing but a path. The copy kept is the one ``scoring.best_copy`` picks, the same as the review
page suggests. A group of copies is only decided when the kept copy beats every other one under a
rule that's switched on. Any tie leaves the whole group for review.

A rule never touches a pair that has had a decision, even one since taken back, nor a skipped
pair or one that needs review. So a rule never overrules you, and a decision you undo or reopen
isn't made again at the next match. Similar pairs are never decided here.

Like any decision, these only build a plan: nothing on disk changes until a plan is applied. They
record ``decided_by = 'auto'`` and the rule, and ``decisions.reopen_automatic`` takes them back.
No FastAPI here.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from photo_ledger.db import pairs as pair_queries
from photo_ledger.matching.scoring import best_copy, has_copy_marker
from photo_ledger.review.decisions import record_decision

#: Rule names, as recorded in ``decisions.rule``.
RULES = ("tidier_path", "priority", "unlike_names")


@dataclass
class AutoResult:
    tidier_path: int = 0
    priority: int = 0
    unlike_names: int = 0

    @property
    def total(self) -> int:
        return self.tidier_path + self.priority + self.unlike_names


def apply(
    conn: sqlite3.Connection,
    *,
    tidier_path: bool = True,
    priority: bool = True,
    unlike_names: bool = True,
    threshold: int,
) -> AutoResult:
    """Decide the obvious pairs the switched-on rules cover, in one transaction.

    ``threshold`` is the similar threshold the match used: a name conflict farther apart than it
    is two different pictures.
    """
    result = AutoResult()
    with conn:
        decided = {row[0] for row in conn.execute("SELECT DISTINCT pair_id FROM decisions")}
        if tidier_path or priority:
            _exact(conn, decided, result, tidier_path=tidier_path, priority=priority)
        if unlike_names:
            _unlike_names(conn, decided, result, threshold)
    return result


def _rule(winner: sqlite3.Row, other: sqlite3.Row) -> str | None:
    """The rule that keeps ``winner`` over ``other``, or ``None`` when nothing tells them apart."""
    if winner["source_priority"] != other["source_priority"]:
        return "priority"  # best_copy puts the higher priority first
    marker = has_copy_marker(winner["filename"]), has_copy_marker(other["filename"])
    if marker == (False, True):
        return "tidier_path"
    if marker[0] == marker[1] and len(winner["rel_path"]) < len(other["rel_path"]):
        return "tidier_path"
    return None


def _exact(
    conn: sqlite3.Connection,
    decided: set[int],
    result: AutoResult,
    *,
    tidier_path: bool,
    priority: bool,
) -> None:
    enabled = {"tidier_path": tidier_path, "priority": priority}
    copies: dict[int, list[sqlite3.Row]] = defaultdict(list)
    files = {}
    for row in pair_queries.eligible_files(conn):
        copies[row["content_id"]].append(row)
        files[row["id"]] = row
    groups: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for pair in conn.execute("SELECT * FROM review_pairs WHERE kind = 'exact'"):
        left = files.get(pair["left_id"])
        if left is not None:
            groups[left["content_id"]].append(pair)

    for content_id, pairs in groups.items():
        group = copies[content_id]
        if len(pairs) != len(group) * (len(group) - 1) // 2:
            continue  # a copy without its pairs: leave it for a fresh match and review
        if any(pair["status"] != "open" or pair["id"] in decided for pair in pairs):
            continue
        winner = best_copy(group)
        rules = {other["id"]: _rule(winner, other) for other in group if other is not winner}
        if not all(rule is not None and enabled[rule] for rule in rules.values()):
            continue
        by_ids = {frozenset((pair["left_id"], pair["right_id"])): pair for pair in pairs}
        for other_id, rule in rules.items():
            pair = by_ids[frozenset((winner["id"], other_id))]
            action = "keep_left" if pair["left_id"] == winner["id"] else "keep_right"
            record_decision(conn, pair["id"], action, by="auto", rule=rule)
            setattr(result, rule, getattr(result, rule) + 1)


def _unlike_names(
    conn: sqlite3.Connection, decided: set[int], result: AutoResult, threshold: int
) -> None:
    phash = {row[0]: row[1] for row in conn.execute("SELECT id, phash FROM contents")}
    pairs = conn.execute(
        "SELECT * FROM review_pairs WHERE kind = 'name_conflict' AND status = 'open'"
    ).fetchall()
    for pair in pairs:
        left, right = phash.get(pair["left_id"]), phash.get(pair["right_id"])
        if pair["id"] in decided or not left or not right:
            continue
        if (int(left, 16) ^ int(right, 16)).bit_count() > threshold:
            record_decision(conn, pair["id"], "keep_both", by="auto", rule="unlike_names")
            result.unlike_names += 1
