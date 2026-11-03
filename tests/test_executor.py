"""Applying, undoing and recovering plans, checked against M4's "done when": a plan applied and
undone restores the fixture set exactly, including across volumes, and a simulated crash halfway
never reports the plan as complete."""

import subprocess
import sys

import pytest
from plan_helpers import (
    A_BACKUP,
    F_BEST,
    F_JAPAN,
    quarantine,
    reject_backup_copy,
    reject_two_of_three,
)
from review_helpers import file_id
from test_scanner import snapshot
from typer.testing import CliRunner

from photo_ledger import cli
from photo_ledger.actions import PlanError, dryrun, executor, paths, planner, recovery
from photo_ledger.db import plans as queries
from photo_ledger.matching.pairs import match
from photo_ledger.scanner.engine import run_scan

MOVED = (A_BACKUP, F_BEST, F_JAPAN)


class Crash(BaseException):
    """The process dying: nothing in the executor catches it."""


def pair_counts(conn):
    return dict(conn.execute("SELECT status, COUNT(*) FROM review_pairs GROUP BY status"))


@pytest.fixture
def ready(ledger):
    """Three rejected backup copies in a plan that has passed its dry run."""
    conn, root, _ = ledger
    folder = quarantine(conn, root, "camera", "backup")
    reject_backup_copy(conn)
    reject_two_of_three(conn)
    summary = planner.build_plan(conn)
    assert summary.moves == 3
    assert dryrun.dry_run(conn, summary.plan_id, verify=True).ok
    return conn, root, folder, summary.plan_id


def across_volumes(monkeypatch):
    monkeypatch.setattr(paths, "same_volume", lambda a, b: False)


def status(conn, plan_id):
    return queries.get(conn, plan_id)["status"]


def file_status(conn, path):
    return conn.execute("SELECT status FROM files WHERE id = ?", (file_id(conn, path),)).fetchone()[
        0
    ]


# Done when: applied and undone restores the fixtures exactly ---------------------------------


@pytest.mark.parametrize("volumes", ["same", "across"])
def test_apply_then_undo_restores_the_fixtures_exactly(ready, monkeypatch, volumes):
    conn, root, folder, plan_id = ready
    if volumes == "across":
        across_volumes(monkeypatch)
    before, pairs_before = snapshot(root), pair_counts(conn)

    result = executor.apply(conn)
    assert (result.status, result.done, result.failed) == ("applied", 3, [])
    assert status(conn, plan_id) == "applied"
    after = snapshot(root)
    for path in MOVED:
        assert path not in after
        assert file_status(conn, path) == "missing"
        assert (folder / f"plan-{plan_id}" / path).is_file()
    assert set(before) - set(after) == set(MOVED)  # nothing else moved
    assert {k: v for k, v in before.items() if k not in MOVED} == after
    quarantined = snapshot(folder)
    for path in MOVED:
        assert quarantined[f"plan-{plan_id}/{path}"] == before[path]  # same bytes and date

    undone = executor.undo(conn)
    assert (undone.status, undone.done, undone.failed) == ("applied", 3, [])
    assert status(conn, plan_id) == "undone"
    assert snapshot(root) == before
    assert snapshot(folder) == {}  # no copies left in quarantine, only empty folders
    for path in MOVED:
        assert file_status(conn, path) == "present"

    # A rescan and match find the same files and queue no new review work.
    run_scan(conn, "all")
    result = match(conn)
    assert (result.new, result.reopened, result.needs_review) == (0, 0, 0)
    assert pair_counts(conn) == pairs_before


# Done when: a crash halfway never reports the plan as complete --------------------------------


def test_a_crash_between_actions_is_never_complete(ready, monkeypatch):
    conn, root, _, plan_id = ready
    before = snapshot(root)
    real_move, calls = executor._move, []

    def crash_on_second(*args):
        calls.append(args)
        if len(calls) == 2:
            raise Crash
        return real_move(*args)

    monkeypatch.setattr(executor, "_move", crash_on_second)
    with pytest.raises(Crash):
        executor.apply(conn)
    assert status(conn, plan_id) == "applying"
    states = [a["state"] for a in queries.actions(conn, plan_id)]
    assert states == ["done", "started", "pending"]
    monkeypatch.setattr(executor, "_move", real_move)

    found = recovery.recover(conn)
    assert (found.pending, found.plans) == (1, [plan_id])
    assert status(conn, plan_id) == "incomplete"
    with pytest.raises(PlanError, match="didn't finish"):
        planner.build_plan(conn)

    assert executor.apply(conn).status == "applied"
    executor.undo(conn)
    assert snapshot(root) == before


def test_a_crash_after_copying_across_volumes_is_finished_by_recovery(ready, monkeypatch):
    conn, root, folder, plan_id = ready
    across_volumes(monkeypatch)
    before = snapshot(root)
    real_remove = executor._remove_original

    def crash(path):
        raise Crash

    monkeypatch.setattr(executor, "_remove_original", crash)
    with pytest.raises(Crash):
        executor.apply(conn)
    assert status(conn, plan_id) != "applied"
    [first, *_] = queries.actions(conn, plan_id)
    assert first["state"] == "started"
    assert (root / first["source_label"] / first["from_path"]).is_file()  # original still there

    monkeypatch.setattr(executor, "_remove_original", real_remove)
    found = recovery.recover(conn)
    assert found.finished + found.done == 1
    assert queries.action(conn, first["id"])["state"] == "done"
    assert not (root / first["source_label"] / first["from_path"]).exists()
    assert not any(p.name.endswith(paths.PARTIAL_SUFFIX) for p in folder.rglob("*"))

    assert executor.apply(conn).status == "applied"
    executor.undo(conn)
    assert snapshot(root) == before


def test_a_crash_mid_copy_leaves_a_partial_that_recovery_removes(ready, monkeypatch):
    conn, root, folder, plan_id = ready
    across_volumes(monkeypatch)
    before = snapshot(root)
    real_hash, calls = executor.hash_file, []

    def crash_when_hashing_the_copy(path):
        calls.append(path)
        if str(path).endswith(paths.PARTIAL_SUFFIX):
            raise Crash
        return real_hash(path)

    monkeypatch.setattr(executor, "hash_file", crash_when_hashing_the_copy)
    with pytest.raises(Crash):
        executor.apply(conn)
    assert any(p.name.endswith(paths.PARTIAL_SUFFIX) for p in folder.rglob("*"))
    assert status(conn, plan_id) == "applying"

    monkeypatch.setattr(executor, "hash_file", real_hash)
    found = recovery.recover(conn)
    assert found.pending == 1
    assert not any(p.name.endswith(paths.PARTIAL_SUFFIX) for p in folder.rglob("*"))
    assert snapshot(root) == before  # nothing had moved yet

    assert executor.apply(conn).status == "applied"
    executor.undo(conn)
    assert snapshot(root) == before


def test_recovery_waits_for_an_unplugged_source(ready, monkeypatch):
    conn, root, _, plan_id = ready

    def crash(*args):
        raise Crash

    monkeypatch.setattr(executor, "_move", crash)
    with pytest.raises(Crash):
        executor.apply(conn)
    (root / "backup").rename(root / "backup-unplugged")
    found = recovery.recover(conn)
    assert len(found.waiting) == 1
    assert queries.actions(conn, plan_id)[0]["state"] == "started"
    assert status(conn, plan_id) == "incomplete"


# Refusals -------------------------------------------------------------------------------------


def test_a_file_changed_since_the_dry_run_is_left_alone(ready):
    conn, root, _, plan_id = ready
    changed = root / A_BACKUP
    changed.write_bytes(changed.read_bytes() + b"edited")
    result = executor.apply(conn)
    assert result.status == "incomplete"
    assert len(result.failed) == 1 and "changed since it was scanned" in result.failed[0]
    assert changed.is_file()
    assert file_status(conn, A_BACKUP) == "present"
    assert status(conn, plan_id) == "incomplete"


def test_an_existing_destination_is_never_overwritten(ready):
    conn, _, _, plan_id = ready
    first = queries.actions(conn, plan_id)[0]
    _origin, target = paths.endpoints(first)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"someone else's file")
    result = executor.apply(conn)
    assert result.status == "incomplete"
    assert target.read_bytes() == b"someone else's file"


def test_apply_needs_a_clean_current_dry_run(ledger):
    conn, root, _ = ledger
    quarantine(conn, root, "backup")
    with pytest.raises(PlanError, match="no plan"):
        executor.apply(conn)
    reject_backup_copy(conn)
    planner.build_plan(conn)
    with pytest.raises(PlanError, match="dry run"):
        executor.apply(conn)
    dryrun.dry_run(conn, planner.draft(conn)["id"])
    reject_two_of_three(conn)  # a decision made after the plan was built
    with pytest.raises(PlanError, match="Decisions changed"):
        executor.apply(conn)


def test_undo_names_the_offline_quarantine(ready):
    conn, _, folder, _ = ready
    executor.apply(conn)
    folder.rename(folder.with_name("unplugged"))
    with pytest.raises(PlanError, match="Undo needs the quarantine at") as raised:
        executor.undo(conn)
    assert str(folder.resolve()) in str(raised.value)


def test_undo_never_overwrites_a_file_created_since(ready):
    conn, root, folder, plan_id = ready
    executor.apply(conn)
    (root / A_BACKUP).write_bytes(b"a new file in the old place")
    result = executor.undo(conn)
    assert result.status == "incomplete"
    assert (root / A_BACKUP).read_bytes() == b"a new file in the old place"
    assert (folder / f"plan-{plan_id}" / A_BACKUP).is_file()  # the quarantined copy is kept
    assert status(conn, plan_id) == "applied"


def test_nothing_to_undo(ledger):
    conn, _, _ = ledger
    with pytest.raises(PlanError, match="no applied plan"):
        executor.undo(conn)


def test_actions_never_import_fastapi():
    code = (
        "import sys; import photo_ledger.actions.executor, photo_ledger.actions.recovery, "
        "photo_ledger.actions.planner, photo_ledger.actions.dryrun; "
        "sys.exit('fastapi' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


# The command line and the page ----------------------------------------------------------------


def test_cli_plans_applies_and_undoes(ledger, settings, monkeypatch):
    conn, root, _ = ledger
    monkeypatch.setenv("PHOTO_LEDGER_DATA_DIR", str(settings.photo_ledger_data_dir))
    quarantine(conn, root, "backup")
    reject_backup_copy(conn)
    before = snapshot(root)
    runner = CliRunner()

    planned = runner.invoke(cli.app, ["plan", "--verify"])
    assert planned.exit_code == 0, planned.output
    assert "move 1 rejected copies" in planned.stdout
    assert "no problems" in planned.stdout

    declined = runner.invoke(cli.app, ["apply"], input="n\n")
    assert declined.exit_code == 1
    assert snapshot(root) == before

    applied = runner.invoke(cli.app, ["apply"], input="y\n")
    assert applied.exit_code == 0, applied.output
    assert "1 moved, 0 failed" in applied.stdout
    assert A_BACKUP not in snapshot(root)

    undone = runner.invoke(cli.app, ["undo", "--yes"])
    assert undone.exit_code == 0, undone.output
    assert "1 restored" in undone.stdout
    assert snapshot(root) == before


def csrf(client):
    return client.cookies["gth_csrf"]


def test_plan_page_applies_after_confirming(ready, web):
    conn, root, _, plan_id = ready
    page = web.get("/plan").text
    assert "Apply plan" in page and 'id="apply-plan"' in page
    assert web.post("/plan/apply").status_code == 403
    assert A_BACKUP in snapshot(root)
    applied = web.post("/plan/apply", data={"csrf_token": csrf(web)})
    assert "Applied." in applied.text
    assert status(conn, plan_id) == "applied"
    assert A_BACKUP not in snapshot(root)
    assert "photo-ledger undo" in applied.text
