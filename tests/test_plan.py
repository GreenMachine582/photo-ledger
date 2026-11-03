"""Plans and dry runs. Building and checking a plan never touches a file."""

import os

import pytest
from plan_helpers import (
    A_BACKUP,
    A_CAMERA,
    quarantine,
    reject_backup_copy,
    reject_picture_a,
    reject_two_of_three,
)
from review_helpers import file_id
from test_scanner import snapshot

from photo_ledger.actions import PlanError, dryrun, paths, planner
from photo_ledger.db import plans as queries
from photo_ledger.review.decisions import undo_last


def csrf(client):
    return client.cookies["gth_csrf"]


def built(conn):
    summary = planner.build_plan(conn)
    return summary, queries.actions(conn, summary.plan_id)


def test_without_quarantine_rejected_copies_stay(ledger):
    conn, _, _ = ledger
    reject_backup_copy(conn)
    summary, actions = built(conn)
    assert (summary.moves, summary.stay) == (0, 1)
    assert actions == []


def test_an_exact_rejection_plans_one_move(ledger):
    conn, root, _ = ledger
    folder = quarantine(conn, root, "backup")
    reject_backup_copy(conn)
    summary, actions = built(conn)
    assert (summary.moves, summary.stay) == (1, 0)
    [action] = actions
    assert action["file_id"] == file_id(conn, A_BACKUP)
    assert action["op"] == "quarantine"
    assert action["from_path"] == "Holiday 2019/IMG_0001.jpg"
    assert action["to_path"] == f"plan-{summary.plan_id}/backup/Holiday 2019/IMG_0001.jpg"
    assert action["quarantine_root"] == str(folder.resolve())
    assert action["state"] == "pending"


def test_rejecting_a_picture_plans_every_copy(ledger):
    conn, root, _ = ledger
    quarantine(conn, root, "camera", "backup")
    reject_picture_a(conn)
    _summary, actions = built(conn)
    planned = {a["file_id"] for a in actions}
    assert planned == {file_id(conn, A_CAMERA), file_id(conn, A_BACKUP)}


def test_three_copies_plan_two_moves(ledger):
    conn, root, _ = ledger
    quarantine(conn, root, "camera", "backup")
    reject_two_of_three(conn)
    summary, _ = built(conn)
    assert summary.moves == 2


def test_undoing_a_decision_drops_its_move(ledger):
    conn, root, _ = ledger
    quarantine(conn, root, "backup")
    reject_backup_copy(conn)
    first, _ = built(conn)
    plan = queries.get(conn, first.plan_id)
    assert not planner.is_stale(conn, plan)
    undo_last(conn)
    assert planner.is_stale(conn, plan)
    second, actions = built(conn)
    assert actions == []
    # The old draft is replaced, not kept alongside.
    assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1
    assert planner.draft(conn)["id"] == second.plan_id


def test_a_copy_is_left_alone_when_no_kept_copy_remains(ledger):
    conn, root, _ = ledger
    quarantine(conn, root, "backup")
    reject_backup_copy(conn)
    # The kept camera copy has since gone, so moving the backup would leave picture A with none.
    conn.execute("UPDATE files SET status = 'missing' WHERE id = ?", (file_id(conn, A_CAMERA),))
    conn.commit()
    summary, actions = built(conn)
    assert actions == []
    assert summary.unsafe == [A_BACKUP]


def test_planning_waits_for_an_unfinished_plan(ledger):
    conn, _, _ = ledger
    summary = planner.build_plan(conn)
    queries.set_status(conn, summary.plan_id, "incomplete")
    conn.commit()
    with pytest.raises(PlanError, match="didn't finish"):
        planner.build_plan(conn)


# Dry runs ------------------------------------------------------------------------------------


def planned(ledger, *labels):
    conn, root, _ = ledger
    folder = quarantine(conn, root, *(labels or ("backup",)))
    reject_backup_copy(conn)
    summary, [action] = built(conn)
    return conn, root, folder, summary.plan_id, action


def problems(conn, plan_id, **options):
    return [p.message for p in dryrun.dry_run(conn, plan_id, **options).problems]


def test_a_clean_dry_run_allows_applying_and_writes_nothing(ledger):
    conn, root, folder, plan_id, _ = planned(ledger)
    before, quarantined = snapshot(root), snapshot(folder)
    result = dryrun.dry_run(conn, plan_id, verify=True)
    assert result.ok and result.actions == 1
    assert queries.get(conn, plan_id)["checked_at"] is not None
    assert snapshot(root) == before
    assert snapshot(folder) == quarantined == {}
    assert list(folder.iterdir()) == []  # not even a folder is created


def test_a_failed_dry_run_clears_the_check(ledger):
    conn, root, _, plan_id, action = planned(ledger)
    dryrun.dry_run(conn, plan_id)
    (root / A_BACKUP).rename(root / "backup" / "moved-away.jpg")
    assert any("has gone" in m for m in problems(conn, plan_id))
    assert queries.get(conn, plan_id)["checked_at"] is None


def test_a_record_free_dry_run_leaves_the_plan_alone(ledger):
    conn, _, _, plan_id, _ = planned(ledger)
    dryrun.dry_run(conn, plan_id, record=False)
    assert queries.get(conn, plan_id)["checked_at"] is None


def test_a_changed_size_is_found(ledger):
    conn, root, _, plan_id, _ = planned(ledger)
    with open(root / A_BACKUP, "ab") as handle:
        handle.write(b"x")
    assert any("changed since it was scanned" in m for m in problems(conn, plan_id))


def test_a_changed_content_is_found_with_verify(ledger):
    conn, root, _, plan_id, _ = planned(ledger)
    target = root / A_BACKUP
    stat = target.stat()
    data = bytearray(target.read_bytes())
    data[-3] ^= 0xFF  # same size, and the date is put back
    target.write_bytes(bytes(data))
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert problems(conn, plan_id) == []
    assert any("content has changed" in m for m in problems(conn, plan_id, verify=True))


def test_an_existing_destination_is_never_overwritten(ledger):
    conn, _, _, plan_id, action = planned(ledger)
    _origin, target = paths.endpoints(queries.action(conn, action["id"]))
    target.parent.mkdir(parents=True)
    target.write_bytes(b"already here")
    assert any("nothing is ever overwritten" in m for m in problems(conn, plan_id))


def test_an_offline_source_or_quarantine_is_found(ledger):
    conn, root, folder, plan_id, _ = planned(ledger)
    folder.rename(folder.with_name("unplugged"))
    assert any("quarantine is offline" in m for m in problems(conn, plan_id))
    folder.with_name("unplugged").rename(folder)
    (root / "backup").rename(root / "backup-unplugged")
    assert any("Source 'backup' is offline" in m for m in problems(conn, plan_id))


def test_too_little_space_across_volumes_is_found(ledger, monkeypatch):
    conn, _, _, plan_id, _ = planned(ledger)
    monkeypatch.setattr(paths, "same_volume", lambda a, b: False)
    monkeypatch.setattr(dryrun, "free_bytes", lambda path: 10)
    assert any("bytes free" in m for m in problems(conn, plan_id))


def test_same_volume_moves_need_no_space(ledger, monkeypatch):
    conn, _, _, plan_id, _ = planned(ledger)
    monkeypatch.setattr(paths, "same_volume", lambda a, b: True)
    monkeypatch.setattr(dryrun, "free_bytes", lambda path: 0)
    assert problems(conn, plan_id) == []


# Web -----------------------------------------------------------------------------------------


def test_plan_page_builds_and_checks(ledger, web):
    conn, root, _ = ledger
    before = snapshot(root)
    assert "No plan yet" in web.get("/plan").text
    quarantine(conn, root, "backup")
    reject_backup_copy(conn)

    assert web.post("/plan").status_code == 403
    assert web.post("/plan/check").status_code == 403
    rebuilt = web.post("/plan", data={"csrf_token": csrf(web)})
    assert rebuilt.status_code == 200
    assert "Plan rebuilt" in rebuilt.text
    assert "Holiday 2019/IMG_0001.jpg" in rebuilt.text
    assert "No problems" in rebuilt.text
    checked = web.post("/plan/check", data={"csrf_token": csrf(web)})
    assert "every file hashed" in checked.text
    assert planner.draft(conn)["checked_at"] is not None
    assert snapshot(root) == before


def test_plan_page_counts_copies_that_stay(ledger, web):
    conn, _, _ = ledger
    reject_backup_copy(conn)
    page = web.get("/plan").text
    assert "1 rejected copies" in page
    assert 'href="/plan"' in web.get("/").text
