"""Stable review pairs: exact duplicates, similar images and name conflicts.

Every run recomputes the candidate pairs from the catalogue and reconciles them with the stored
ones by a stable key, so rescanning unchanged files never creates a pair or reopens one.

| Kind            | Compares                          | Key                                |
|-----------------|-----------------------------------|------------------------------------|
| ``exact``         | two copies of the same content    | the two file IDs                   |
| ``similar``       | two contents with close pHashes   | the two BLAKE3 hashes              |
| ``name_conflict`` | one filename on two contents      | the two BLAKE3 hashes              |

Keys sort their members, so swapping left and right can't make a second pair. Similar pairs are
never resolved here or anywhere else automatically.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations

from photo_ledger.db import now_iso
from photo_ledger.db import pairs as queries
from photo_ledger.matching.similar import similar_pairs

DEFAULT_THRESHOLD = 8
#: Statuses that close when their pair stops matching. Resolved pairs keep their decision.
CLOSABLE_STATUSES = {"open", "skipped", "needs_review"}


@dataclass
class Candidate:
    key: str
    kind: str
    left_id: int
    right_id: int
    distance: int | None
    evidence: str | None
    scan_id: int | None
    score_reasons: str | None = None


@dataclass
class MatchResult:
    new: int = 0
    reopened: int = 0
    needs_review: int = 0
    obsolete: int = 0
    unchanged: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


def _latest(*scan_ids: int | None) -> int | None:
    present = [scan_id for scan_id in scan_ids if scan_id is not None]
    return max(present) if present else None


Scorer = Callable[[str, list[sqlite3.Row], list[sqlite3.Row]], dict | None]


def find_candidates(
    conn: sqlite3.Connection, threshold: int = DEFAULT_THRESHOLD, scorer: Scorer | None = None
) -> dict[str, Candidate]:
    """Every pair the catalogue supports right now, by key.

    ``scorer(kind, left_files, right_files)`` returns the keeper suggestion stored with each pair.
    """
    files = queries.eligible_files(conn)
    by_content: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in files:
        by_content[row["content_id"]].append(row)
    first = {content_id: rows[0] for content_id, rows in by_content.items()}

    def content_scan(content_id: int) -> int | None:
        return _latest(*(row["last_seen_scan_id"] for row in by_content[content_id]))

    def add(candidates, kind, left_files, right_files, **fields):
        reasons = scorer(kind, left_files, right_files) if scorer else None
        candidate = Candidate(
            kind=kind, score_reasons=json.dumps(reasons) if reasons else None, **fields
        )
        candidates[candidate.key] = candidate

    candidates: dict[str, Candidate] = {}

    for content_id, rows in by_content.items():
        for left, right in combinations(rows, 2):  # rows are in file ID order
            add(
                candidates,
                "exact",
                [left],
                [right],
                key=f"exact:{left['id']}:{right['id']}",
                left_id=left["id"],
                right_id=right["id"],
                distance=0,
                evidence=left["blake3"],
                scan_id=_latest(left["last_seen_scan_id"], right["last_seen_scan_id"]),
            )

    def add_content_pair(kind, content_a, content_b, distance):
        a, b = sorted((content_a, content_b), key=lambda cid: first[cid]["blake3"])
        add(
            candidates,
            kind,
            by_content[a],
            by_content[b],
            key=f"{kind}:{first[a]['blake3']}:{first[b]['blake3']}",
            left_id=a,
            right_id=b,
            distance=distance,
            evidence=None,
            scan_id=_latest(content_scan(a), content_scan(b)),
        )

    hashes = {cid: int(row["phash"], 16) for cid, row in first.items() if row["phash"]}
    for content_a, content_b, distance in similar_pairs(hashes, threshold):
        add_content_pair("similar", content_a, content_b, distance)

    by_name: dict[str, set[int]] = defaultdict(set)
    for row in files:
        by_name[row["filename"].casefold()].add(row["content_id"])
    for content_ids in by_name.values():
        for content_a, content_b in combinations(sorted(content_ids), 2):
            add_content_pair("name_conflict", content_a, content_b, None)

    return candidates


def match(
    conn: sqlite3.Connection, threshold: int = DEFAULT_THRESHOLD, scorer: Scorer | None = None
) -> MatchResult:
    """Bring the stored pairs in line with the catalogue, in one transaction."""
    candidates = find_candidates(conn, threshold, scorer)
    stored = queries.all_pairs(conn)
    result = MatchResult()
    now = now_iso()
    with conn:
        for key, candidate in candidates.items():
            result.by_kind[candidate.kind] = result.by_kind.get(candidate.kind, 0) + 1
            row = stored.get(key)
            if row is None:
                queries.insert(
                    conn,
                    pair_key=key,
                    kind=candidate.kind,
                    left_id=candidate.left_id,
                    right_id=candidate.right_id,
                    distance=candidate.distance,
                    evidence=candidate.evidence,
                    score_reasons=candidate.score_reasons,
                    status="open",
                    first_seen_scan_id=candidate.scan_id,
                    last_seen_scan_id=candidate.scan_id,
                    created_at=now,
                    updated_at=now,
                )
                result.new += 1
                continue
            status = row["status"]
            if status == "obsolete":
                status = "open"
                result.reopened += 1
            elif status == "resolved" and row["evidence"] != candidate.evidence:
                status = "needs_review"
                result.needs_review += 1
            else:
                result.unchanged += 1
            changes = {
                column: value
                for column, value in (
                    ("status", status),
                    ("distance", candidate.distance),
                    ("evidence", candidate.evidence),
                    ("score_reasons", candidate.score_reasons),
                    ("last_seen_scan_id", _latest(row["last_seen_scan_id"], candidate.scan_id)),
                )
                if row[column] != value
            }
            if changes:
                queries.update(conn, row["id"], updated_at=now, **changes)

        for key, row in stored.items():
            if key not in candidates and row["status"] in CLOSABLE_STATUSES:
                queries.update(conn, row["id"], status="obsolete", updated_at=now)
                result.obsolete += 1
    return result


def pair_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return queries.counts(conn)
