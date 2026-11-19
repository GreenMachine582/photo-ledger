"""Rules that decide obvious pairs at match: tidier path, source priority, unlike name clashes."""

from plan_helpers import A_BACKUP, A_CAMERA, C_CAMERA, F_BEST, F_CAMERA, F_JAPAN
from review_helpers import content_pair, exact_pair, file_id, status
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.matching.pairs import match
from photo_ledger.matching.scoring import best_copy
from photo_ledger.review import automatic
from photo_ledger.review.decisions import (
    automatic_count,
    decide,
    rejected_items,
    reopen_automatic,
    undo_last,
)


def apply(conn, **switches):
    return automatic.apply(conn, **{"threshold": 8, **switches})


def active(conn, pair_id):
    return conn.execute(
        "SELECT * FROM decisions WHERE pair_id = ? AND superseded_at IS NULL", (pair_id,)
    ).fetchone()


def open_kinds(conn):
    rows = conn.execute("SELECT kind FROM review_pairs WHERE status = 'open' ORDER BY kind")
    return [row[0] for row in rows]


def test_exact_copies_told_apart_by_path_are_kept_by_the_tidier_path(ledger):
    conn, root, _ = ledger
    before = snapshot(root)
    result = apply(conn)
    assert (result.tidier_path, result.priority) == (4, 0)

    pair = exact_pair(conn, A_CAMERA, A_BACKUP)  # 2019/IMG_0001.jpg is shorter
    decision = active(conn, pair["id"])
    assert (decision["decided_by"], decision["rule"]) == ("auto", "tidier_path")
    assert ("file", file_id(conn, A_BACKUP)) in rejected_items(conn)
    assert snapshot(root) == before  # a rule only records a decision


def test_three_copies_keep_one(ledger):
    conn, _, _ = ledger
    apply(conn)
    rejected = rejected_items(conn)
    assert ("file", file_id(conn, F_BEST)) in rejected  # the copy marker
    assert ("file", file_id(conn, F_JAPAN)) in rejected  # the longer path
    assert ("file", file_id(conn, F_CAMERA)) not in rejected
    closed = active(conn, exact_pair(conn, F_BEST, F_JAPAN)["id"])
    assert (closed["action"], closed["decided_by"], closed["rule"]) == (
        "closed",
        "auto",
        "tidier_path",
    )


def test_similar_pairs_are_never_decided(ledger):
    conn, _, _ = ledger
    apply(conn, threshold=64)  # every name clash looks alike, so only exact pairs are decided
    assert open_kinds(conn) == ["name_conflict", "similar", "similar"]


def test_a_copy_marker_beats_a_shorter_path():
    tidy = {
        "id": 1,
        "source_priority": 0,
        "filename": "IMG_0412.jpg",
        "rel_path": "a/b/IMG_0412.jpg",
    }
    marked = {"id": 2, "source_priority": 0, "filename": "x (1).jpg", "rel_path": "x (1).jpg"}
    assert best_copy([marked, tidy]) is tidy
    assert automatic._rule(tidy, marked) == "tidier_path"


def test_a_tie_is_left_for_review():
    one = {"id": 1, "source_priority": 0, "filename": "a.jpg", "rel_path": "x/a.jpg"}
    two = {"id": 2, "source_priority": 0, "filename": "a.jpg", "rel_path": "y/a.jpg"}
    assert automatic._rule(best_copy([one, two]), two) is None


def test_a_higher_priority_source_needs_its_own_switch(ledger):
    conn, _, _ = ledger
    sources.set_priority(conn, "backup", 5)
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)

    assert apply(conn, priority=False).priority == 0
    assert status(conn, pair["id"]) == "open"  # the tidier path would keep camera: not enough

    result = apply(conn)
    assert result.priority == 3  # each group's backup copy wins
    assert active(conn, pair["id"])["rule"] == "priority"
    assert ("file", file_id(conn, A_CAMERA)) in rejected_items(conn)


def test_each_switch_turns_its_rule_off(ledger):
    conn, _, _ = ledger
    result = apply(conn, tidier_path=False, priority=False, unlike_names=False)
    assert result.total == 0
    assert automatic_count(conn) == 0


def test_a_pair_you_skipped_or_decided_is_never_touched(ledger):
    conn, _, _ = ledger
    skipped = exact_pair(conn, A_CAMERA, A_BACKUP)
    decide(conn, skipped["id"], "skip")
    kept = exact_pair(conn, F_CAMERA, F_JAPAN)
    decide(conn, kept["id"], "keep_both")
    undo_last(conn)  # taken back, but it was decided once

    result = apply(conn)
    assert result.tidier_path == 1  # only Holiday 2019/renamed.jpg's pair
    assert status(conn, skipped["id"]) == "skipped"
    assert status(conn, kept["id"]) == "open"


def test_reopened_decisions_go_back_for_review_and_stay_there(ledger):
    conn, _, _ = ledger
    apply(conn)
    assert automatic_count(conn) == 5
    assert reopen_automatic(conn) == 5
    assert rejected_items(conn) == []
    assert open_kinds(conn).count("exact") == 5

    match(conn)
    assert apply(conn).total == 0  # each has had a decision now
    assert automatic_count(conn) == 0


def test_undo_takes_back_only_your_decisions(ledger):
    conn, _, _ = ledger
    apply(conn)
    similar = content_pair(conn, "similar", "camera/screenshots/shot_01.png", "backup/shot_01.jpg")
    decide(conn, similar["id"], "keep_both")
    assert undo_last(conn) == similar["id"]
    assert undo_last(conn) is None  # the rules' decisions stay
    assert automatic_count(conn) == 5


def test_name_clashes_that_look_unlike_keep_both(ledger):
    conn, _, _ = ledger
    pair = content_pair(conn, "name_conflict", C_CAMERA, A_CAMERA)
    assert apply(conn, threshold=64).unlike_names == 0  # alike at this threshold: left open
    assert status(conn, pair["id"]) == "open"

    assert apply(conn).unlike_names == 1
    decision = active(conn, pair["id"])
    assert (decision["action"], decision["rule"]) == ("keep_both", "unlike_names")
    assert decision["rejected_id"] is None  # nothing is rejected
