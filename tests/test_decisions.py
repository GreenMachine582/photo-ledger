"""Review decisions, checked against M3's "done when": decisions survive a restart, and a rescan
after adding files queues only the new pairs. (Scan scopes are covered in test_queue.py.)"""

import pytest
from review_helpers import content_id, content_pair, exact_pair, file_id, keep, status
from test_scanner import snapshot

from photo_ledger.db import open_db
from photo_ledger.matching.pairs import match
from photo_ledger.review import decisions
from photo_ledger.review.decisions import DecisionError, decide, undo_last
from photo_ledger.review.queue import queue
from photo_ledger.scanner.engine import run_scan

F_CAMERA = "camera/DCIM/100CANON/IMG_0412.jpg"
F_BEST = "backup/Best of 2019/IMG_0412 (1).jpg"
F_JAPAN = "backup/Pictures/Holidays/2019/Japan/IMG_0412.jpg"
A_CAMERA = "camera/2019/IMG_0001.jpg"
A_BACKUP = "backup/Holiday 2019/IMG_0001.jpg"


def test_three_copies_take_two_reviews(ledger):
    conn, root, _ = ledger
    before = snapshot(root)
    camera = file_id(conn, F_CAMERA)
    first = exact_pair(conn, F_CAMERA, F_BEST)
    decide(conn, first["id"], keep(first, camera))
    # Rejecting "Best of" closes its pair with Japan, leaving only camera vs Japan.
    assert status(conn, exact_pair(conn, F_BEST, F_JAPAN)["id"]) == "resolved"
    second = exact_pair(conn, F_CAMERA, F_JAPAN)
    assert status(conn, second["id"]) == "open"
    decide(conn, second["id"], keep(second, camera))
    assert sorted(decisions.rejected_items(conn)) == sorted(
        [("file", file_id(conn, F_BEST)), ("file", file_id(conn, F_JAPAN))]
    )
    assert snapshot(root) == before  # deciding never touches files


def test_rejecting_a_content_rejects_every_copy(ledger):
    conn, _, _ = ledger
    conflict = content_pair(conn, "name_conflict", A_CAMERA, "camera/2020/IMG_0001.jpg")
    keeper = content_id(conn, "camera/2020/IMG_0001.jpg")
    decide(conn, conflict["id"], keep(conflict, keeper))
    assert decisions.rejected_items(conn) == [("content", content_id(conn, A_CAMERA))]
    # Both copies of the rejected picture are gone, so their exact pair closes too.
    assert status(conn, exact_pair(conn, A_CAMERA, A_BACKUP)["id"]) == "resolved"


def test_keep_both_and_skip(ledger):
    conn, _, _ = ledger
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)
    decide(conn, pair["id"], "skip")
    assert status(conn, pair["id"]) == "skipped"
    assert pair["id"] not in queue(conn)
    decide(conn, pair["id"], "keep_both")
    assert status(conn, pair["id"]) == "resolved"
    assert decisions.rejected_items(conn) == []


def test_undo_restores_the_pair_and_its_closures(ledger):
    conn, _, _ = ledger
    before = {row["id"]: row["status"] for row in conn.execute("SELECT * FROM review_pairs")}
    first = exact_pair(conn, F_CAMERA, F_BEST)
    decide(conn, first["id"], keep(first, file_id(conn, F_CAMERA)))
    assert undo_last(conn) == first["id"]
    after = {row["id"]: row["status"] for row in conn.execute("SELECT * FROM review_pairs")}
    assert after == before
    assert decisions.rejected_items(conn) == []
    assert undo_last(conn) is None


def test_deciding_again_replaces_the_earlier_decision(ledger):
    conn, _, _ = ledger
    pair = exact_pair(conn, F_CAMERA, F_BEST)
    decide(conn, pair["id"], keep(pair, file_id(conn, F_CAMERA)))
    decide(conn, pair["id"], keep(pair, file_id(conn, F_BEST)))
    assert decisions.rejected_items(conn) == [("file", file_id(conn, F_CAMERA))]
    # Camera rejected now: its pair with Japan closes, and Best of vs Japan reopened.
    assert status(conn, exact_pair(conn, F_CAMERA, F_JAPAN)["id"]) == "resolved"
    assert status(conn, exact_pair(conn, F_BEST, F_JAPAN)["id"]) == "open"


def test_deciding_a_closed_pair_drops_only_that_closure(ledger):
    conn, _, _ = ledger
    first = exact_pair(conn, F_CAMERA, F_BEST)
    decide(conn, first["id"], keep(first, file_id(conn, F_CAMERA)))
    closed = exact_pair(conn, F_BEST, F_JAPAN)
    decide(conn, closed["id"], "keep_both")
    assert status(conn, first["id"]) == "resolved"
    assert decisions.rejected_items(conn) == [("file", file_id(conn, F_BEST))]


def test_refusals(ledger):
    conn, _, _ = ledger
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)
    with pytest.raises(DecisionError, match="Unknown action"):
        decide(conn, pair["id"], "delete")
    with pytest.raises(DecisionError, match="no pair"):
        decide(conn, 9999, "skip")
    conn.execute("UPDATE review_pairs SET status = 'obsolete' WHERE id = ?", (pair["id"],))
    conn.commit()
    with pytest.raises(DecisionError, match="no longer matches"):
        decide(conn, pair["id"], "keep_left")


def test_decisions_survive_a_restart(ledger, settings):
    conn, _, _ = ledger
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)
    decide(conn, pair["id"], "keep_left")
    open_before = queue(conn)
    conn.close()

    reopened = open_db(settings.db_path)
    assert status(reopened, pair["id"]) == "resolved"
    assert queue(reopened) == open_before
    assert decisions.rejected_items(reopened) == [("file", pair["right_id"])]
    reopened.close()


def test_a_rescan_after_adding_files_queues_only_the_new_pairs(ledger):
    conn, root, _ = ledger
    while pending := queue(conn):
        decide(conn, pending[0], "keep_both")
    copy = root / "backup/extra/IMG_0003.jpg"
    copy.parent.mkdir()
    copy.write_bytes((root / "backup/restored/IMG_0003.jpg").read_bytes())

    run_scan(conn, "all")
    result = match(conn)
    assert result.new == 1
    (new_pair,) = queue(conn)
    row = conn.execute("SELECT * FROM review_pairs WHERE id = ?", (new_pair,)).fetchone()
    assert row["kind"] == "exact"
    assert file_id(conn, "backup/extra/IMG_0003.jpg") in (row["left_id"], row["right_id"])
    # Decisions made before the rescan all stand.
    resolved = conn.execute("SELECT COUNT(*) FROM review_pairs WHERE status = 'resolved'")
    assert resolved.fetchone()[0] == 8
