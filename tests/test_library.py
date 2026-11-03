"""The destination library, checked against M5's "done when": a clean library builds from
approved keepers, with originals untouched by default and collections intact."""

import subprocess
import sys

import pytest
from plan_helpers import A_CAMERA, reject_backup_copy, reject_two_of_three
from review_helpers import exact_pair
from test_scanner import snapshot
from typer.testing import CliRunner

from photo_ledger import cli, sources
from photo_ledger.actions import executor, recovery
from photo_ledger.db import library as queries
from photo_ledger.library import LibraryError, plan, selection, settings
from photo_ledger.library.layout import unique
from photo_ledger.review.decisions import decide

#: The settled fixture pictures, with their library path and the copy they come from, checked
#: by hand against make_fixtures: a restore-dated photo files under its EXIF year, pictures
#: without EXIF are undated, and the IMG_0412 keeper takes a collection inherited from the
#: copies it replaced, as its own DCIM folder has none.
YEAR_LAYOUT = {
    "2018/restored/IMG_0003.jpg": "backup/restored/IMG_0003.jpg",
    "2019/IMG_0001.jpg": "camera/2019/IMG_0001.jpg",
    "2019/IMG_0002.jpg": "camera/2019/IMG_0002.jpg",
    "2019/Best of 2019/IMG_0412.jpg": "camera/DCIM/100CANON/IMG_0412.jpg",
    "2020/IMG_0001.jpg": "camera/2020/IMG_0001.jpg",
    "Undated/Holiday 2019/IMG_0002_small.jpg": "backup/Holiday 2019/IMG_0002_small.jpg",
    "Undated/screenshots/shot_01.png": "camera/screenshots/shot_01.png",
    "Undated/shot_01.jpg": "backup/shot_01.jpg",
}


class Crash(BaseException):
    """The process dying: nothing in the executor catches it."""


def settle_everything(conn):
    """Reject the duplicate copies, and call every other pair not a duplicate."""
    reject_backup_copy(conn)
    reject_two_of_three(conn)
    for (pair_id,) in conn.execute("SELECT id FROM review_pairs WHERE status = 'open'").fetchall():
        decide(conn, pair_id, "keep_both")


@pytest.fixture
def library(ledger):
    conn, root, manifest = ledger
    folder = root.parent / "library"
    folder.mkdir()
    return conn, root, folder


def build(conn):
    summary = plan.plan_library(conn)
    assert plan.check_library(conn) == []
    return summary, executor.build_library(conn)


def library_files(folder):
    return {path: values for path, values in snapshot(folder).items()}


# Done when ---------------------------------------------------------------------------------


def test_a_clean_library_builds_from_settled_keepers(library):
    conn, root, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder, "year")
    before = snapshot(root)

    summary, result = build(conn)
    assert (summary.to_copy, summary.waiting, summary.corrupt) == (8, 0, 1)
    assert (result.status, result.copied, result.failed) == ("complete", 8, [])

    built = library_files(folder)
    assert set(built) == set(YEAR_LAYOUT)
    for library_path, source_path in YEAR_LAYOUT.items():
        size, _mtime, blake3 = built[library_path]
        assert (size, blake3) == (before[source_path][0], before[source_path][2])
    assert snapshot(root) == before  # originals untouched

    again, rebuilt = build(conn)
    assert (again.to_copy, again.already, rebuilt.copied) == (0, 8, 0)
    assert library_files(folder) == built


def test_the_original_layout_keeps_source_paths(library):
    conn, _, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder, "original")
    build(conn)
    assert set(library_files(folder)) == set(YEAR_LAYOUT.values())


# Which pictures go in -------------------------------------------------------------------------


def test_a_picture_with_an_open_pair_waits_until_decided(library):
    conn, _, folder = library
    settings.set_library(conn, folder)
    picked = selection.settled_pictures(conn)
    assert picked.waiting  # nothing is decided yet
    pair = exact_pair(conn, A_CAMERA, "backup/Holiday 2019/IMG_0001.jpg")
    a_content = conn.execute(
        "SELECT content_id FROM files WHERE id = ?", (pair["left_id"],)
    ).fetchone()[0]
    assert a_content in picked.waiting

    summary, _ = build(conn)
    assert "2019/IMG_0001.jpg" not in library_files(folder)
    assert summary.waiting == len(picked.waiting)

    reject_backup_copy(conn)
    for (pair_id,) in conn.execute(
        "SELECT p.id FROM review_pairs p WHERE p.status = 'open' AND p.kind != 'exact'"
        " AND ? IN (p.left_id, p.right_id)",
        (a_content,),
    ).fetchall():
        decide(conn, pair_id, "keep_both")
    build(conn)
    assert "2019/IMG_0001.jpg" in library_files(folder)


def test_a_rejected_picture_never_goes_in(library):
    conn, _, folder = library
    settle_everything(conn)
    # Keep C over A in their name conflict, rejecting every copy of A.
    conflict = conn.execute("SELECT * FROM review_pairs WHERE kind = 'name_conflict'").fetchone()
    a_content = conn.execute(
        "SELECT content_id FROM files f JOIN sources s ON s.id = f.source_id"
        " WHERE s.label = 'camera' AND f.rel_path = '2019/IMG_0001.jpg'"
    ).fetchone()[0]
    decide(conn, conflict["id"], "keep_left" if conflict["right_id"] == a_content else "keep_right")
    settings.set_library(conn, folder)
    build(conn)
    assert "2019/IMG_0001.jpg" not in library_files(folder)
    assert "2020/IMG_0001.jpg" in library_files(folder)


def test_a_picture_rejected_after_building_stays_and_is_reported(library):
    conn, _, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder)
    build(conn)
    conflict = conn.execute("SELECT * FROM review_pairs WHERE kind = 'name_conflict'").fetchone()
    decide(conn, conflict["id"], "keep_left")
    summary = plan.plan_library(conn)
    assert len(summary.no_longer_chosen) == 1
    assert set(library_files(folder)) == set(YEAR_LAYOUT)  # nothing is ever removed


def test_names_that_collide_get_a_number():
    used = set()
    assert unique("2019/IMG_0001.jpg", used) == "2019/IMG_0001.jpg"
    assert unique("2019/img_0001.JPG", used) == "2019/img_0001 (2).JPG"
    assert unique("2019/IMG_0001.jpg", used) == "2019/IMG_0001 (3).jpg"


# Refusals -------------------------------------------------------------------------------------


def test_the_library_sits_outside_every_source_and_quarantine(library):
    conn, root, folder = library
    with pytest.raises(LibraryError, match="overlaps source 'camera'"):
        settings.set_library(conn, root / "camera" / "2019")
    (root.parent / "q").mkdir()
    sources.set_quarantine(conn, "camera", root.parent / "q")
    with pytest.raises(LibraryError, match="quarantine"):
        settings.set_library(conn, root.parent / "q")
    with pytest.raises(LibraryError, match="doesn't exist"):
        settings.set_library(conn, root.parent / "missing")
    with pytest.raises(LibraryError, match="Unknown layout"):
        settings.set_library(conn, folder, "by-camera")

    settings.set_library(conn, folder)
    (folder / "inner").mkdir()
    with pytest.raises(sources.SourceError, match="library"):
        sources.add_source(conn, folder / "inner", "inner")
    with pytest.raises(sources.SourceError, match="library"):
        sources.set_quarantine(conn, "camera", folder / "inner")


def test_an_existing_file_is_never_overwritten(library):
    conn, _, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder)
    plan.plan_library(conn)
    (folder / "2020").mkdir()
    (folder / "2020" / "IMG_0001.jpg").write_bytes(b"yours")
    assert any("nothing is ever overwritten" in p.message for p in plan.check_library(conn))
    result = executor.build_library(conn)
    assert result.status == "incomplete" and len(result.failed) == 1
    assert (folder / "2020" / "IMG_0001.jpg").read_bytes() == b"yours"


def test_an_offline_library_or_source_is_refused(library):
    conn, root, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder)
    plan.plan_library(conn)
    (root / "backup").rename(root / "backup-unplugged")
    assert any("Source 'backup' is offline" in p.message for p in plan.check_library(conn))
    result = executor.build_library(conn)
    assert result.status == "incomplete"
    assert not (folder / "2018").exists()  # backup's pictures waited; camera's were copied
    folder.rename(folder.with_name("unplugged"))
    assert "offline" in plan.check_library(conn)[0].message
    with pytest.raises(Exception, match="offline"):
        executor.build_library(conn)


def test_a_new_folder_starts_a_new_library_and_layouts_are_fixed_once_built(library):
    conn, root, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder, "year")
    build(conn)
    with pytest.raises(LibraryError, match="never moved"):
        settings.set_library(conn, folder, "original")
    other = root.parent / "library-2"
    other.mkdir()
    settings.set_library(conn, other, "original")
    assert queries.counts(conn) == {}
    summary, _ = build(conn)
    assert summary.to_copy == 8
    assert set(library_files(folder)) == set(YEAR_LAYOUT)  # the old library is left as it was


# Interruptions --------------------------------------------------------------------------------


def test_a_crash_between_copies_is_resumed(library, monkeypatch):
    conn, root, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder)
    plan.plan_library(conn)
    before = snapshot(root)
    real, calls = executor._copy_verified, []

    def crash_on_third(*args):
        calls.append(args)
        if len(calls) == 3:
            raise Crash
        return real(*args)

    monkeypatch.setattr(executor, "_copy_verified", crash_on_third)
    with pytest.raises(Crash):
        executor.build_library(conn)
    assert queries.counts(conn) == {"done": 2, "started": 1, "pending": 5}
    monkeypatch.setattr(executor, "_copy_verified", real)

    found = recovery.recover(conn)
    assert found.pending == 1
    assert executor.build_library(conn).status == "complete"
    assert set(library_files(folder)) == set(YEAR_LAYOUT)
    assert snapshot(root) == before


def test_a_crash_after_copying_is_marked_done_by_recovery(library, monkeypatch):
    conn, _, folder = library
    settle_everything(conn)
    settings.set_library(conn, folder)
    plan.plan_library(conn)
    real_state = queries.set_state

    def crash_when_done(conn_, entry_id, state, **kwargs):
        if state == "done":
            raise Crash
        return real_state(conn_, entry_id, state, **kwargs)

    monkeypatch.setattr(queries, "set_state", crash_when_done)
    with pytest.raises(Crash):
        executor.build_library(conn)
    monkeypatch.setattr(queries, "set_state", real_state)
    assert queries.counts(conn).get("started") == 1

    found = recovery.recover(conn)
    assert found.done == 1
    assert queries.counts(conn).get("done") == 1
    assert executor.build_library(conn).copied == 7


# The command line and imports -----------------------------------------------------------------


def test_cli_sets_plans_and_builds(library, settings, monkeypatch):
    conn, root, folder = library
    monkeypatch.setenv("PHOTO_LEDGER_DATA_DIR", str(settings.photo_ledger_data_dir))
    settle_everything(conn)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["library", "status"]).exit_code == 1  # none yet
    chosen = runner.invoke(cli.app, ["library", "set", str(folder)])
    assert chosen.exit_code == 0, chosen.output
    planned = runner.invoke(cli.app, ["library", "plan"])
    assert "To copy: 8 pictures" in planned.stdout
    assert "no problems" in planned.stdout
    assert library_files(folder) == {}
    built = runner.invoke(cli.app, ["library", "build", "--yes"])
    assert built.exit_code == 0, built.output
    assert "Copied 8 pictures, 0 failed" in built.stdout
    status = runner.invoke(cli.app, ["library", "status"])
    assert "8 done" in status.stdout
    assert "Nothing to copy" in runner.invoke(cli.app, ["library", "build", "--yes"]).stdout


def test_library_never_imports_fastapi():
    code = (
        "import sys; import photo_ledger.library.plan, photo_ledger.library.selection, "
        "photo_ledger.library.layout, photo_ledger.library.settings; "
        "sys.exit('fastapi' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
