"""One match, the same from the CLI and the browser: collections, then pairs, then the rules.

Only the catalogue changes. The rules (``review/automatic.py``) record decisions, and those only
build a plan. No FastAPI here.
"""

import sqlite3
from dataclasses import dataclass

from photo_ledger.collections.folders import RefreshResult, refresh_collections
from photo_ledger.matching.pairs import MatchResult, match
from photo_ledger.preferences import Preferences
from photo_ledger.review import automatic


@dataclass(frozen=True)
class RunResult:
    collections: RefreshResult
    pairs: MatchResult
    automatic: automatic.AutoResult


def run_match(conn: sqlite3.Connection, prefs: Preferences) -> RunResult:
    collections = refresh_collections(conn, prefs.generic_folders)
    pairs = match(conn, prefs.similar_threshold, **prefs.match_options())
    decided = automatic.apply(conn, **prefs.rules())
    return RunResult(collections=collections, pairs=pairs, automatic=decided)


def automatic_lines(result: automatic.AutoResult) -> list[str]:
    """What the rules did, for the CLI and the result panel. Empty when they did nothing."""
    lines = []
    if result.tidier_path:
        lines.append(f"{result.tidier_path:,} exact kept by tidier path")
    if result.priority:
        lines.append(f"{result.priority:,} exact kept by source priority")
    if result.unlike_names:
        lines.append(f"{result.unlike_names:,} unlike name clashes kept both")
    return lines
