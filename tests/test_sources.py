import sys

import pytest
from plan_helpers import F_BEST, F_CAMERA, F_JAPAN
from review_helpers import exact_pair, file_id, keep, status
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.review.decisions import decide
from photo_ledger.sources import device
from photo_ledger.sources.device import DeviceInfo
from photo_ledger.sources.service import overlaps


@pytest.fixture
def fake_volume(monkeypatch):
    """Pretend every path is on the volume named in ``state['id']``."""
    state = {"id": "AAAA-0001", "mounted": []}

    def describe(path):
        return DeviceInfo(
            source_type="removable",
            volume_id=state["id"],
            volume_root=str(path.anchor if hasattr(path, "anchor") else ""),
            device_label="USB",
            filesystem="exFAT",
            capacity_bytes=1000,
        )

    monkeypatch.setattr(device, "describe", describe)
    monkeypatch.setattr(device, "mounted_volumes", lambda: state["mounted"])
    return state


def test_add_records_device_details(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    source = sources.add_source(db, tmp_path / "usb", "usb-1")
    assert source["label"] == "usb-1"
    assert source["root_path"] == str((tmp_path / "usb").resolve())
    assert source["volume_id"] == "AAAA-0001"
    assert source["filesystem"] == "exFAT"
    assert source["state"] == "online"


def test_real_device_details_never_raise(tmp_path):
    info = device.describe(tmp_path)
    assert info.source_type in {"internal", "removable", "network", "optical", "unknown"}
    assert info.capacity_bytes is None or info.capacity_bytes > 0
    assert device.describe(tmp_path / "missing") is not None


@pytest.mark.parametrize("nested", ["inside", "containing", "same"])
def test_overlapping_sources_are_refused(db, tmp_path, nested):
    outer = tmp_path / "backup"
    inner = outer / "2019"
    inner.mkdir(parents=True)
    first, second = {
        "inside": (outer, inner),
        "containing": (inner, outer),
        "same": (outer, outer),
    }[nested]
    sources.add_source(db, first, "first")
    with pytest.raises(sources.SourceError, match="overlaps"):
        sources.add_source(db, second, "second")


def test_siblings_with_a_shared_prefix_do_not_overlap(tmp_path):
    assert not overlaps(tmp_path / "photos", tmp_path / "photos-old")


@pytest.mark.skipif(sys.platform != "win32", reason="paths are case-insensitive on Windows")
def test_overlap_ignores_case_on_windows(tmp_path):
    assert overlaps(tmp_path / "Photos", str(tmp_path / "PHOTOS" / "2019"))


def test_add_refuses_bad_input(db, tmp_path):
    with pytest.raises(sources.SourceError, match="doesn't exist"):
        sources.add_source(db, tmp_path / "nope", "nope")
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(sources.SourceError, match="isn't a folder"):
        sources.add_source(db, tmp_path / "file.txt", "file")
    with pytest.raises(sources.SourceError, match="Labels"):
        sources.add_source(db, tmp_path, "a,b")
    sources.add_source(db, tmp_path, "ok")
    with pytest.raises(sources.SourceError, match="already exists"):
        sources.add_source(db, tmp_path, "ok")


def test_offline_when_missing_or_on_another_volume(db, tmp_path, fake_volume):
    root = tmp_path / "usb"
    root.mkdir()
    source = sources.add_source(db, root, "usb")
    assert sources.is_online(source)
    fake_volume["id"] = "BBBB-0002"  # a different drive now sits at the same path
    assert not sources.is_online(source)
    assert not sources.refresh_state(db, source)
    assert sources.get_source(db, "usb")["state"] == "offline"
    fake_volume["id"] = "AAAA-0001"
    root.rename(tmp_path / "elsewhere")
    assert not sources.is_online(source)


def test_reconnect_to_the_same_volume(db, tmp_path, fake_volume):
    (tmp_path / "E" / "photos").mkdir(parents=True)
    source = sources.add_source(db, tmp_path / "E" / "photos", "usb")
    (tmp_path / "E").rename(tmp_path / "F")
    db.execute(
        "UPDATE sources SET volume_root = ? WHERE id = ?", (str(tmp_path / "E"), source["id"])
    )
    fake_volume["mounted"] = [(str(tmp_path / "F"), "AAAA-0001")]

    found = sources.find_new_root(sources.get_source(db, "usb"))
    assert found == tmp_path / "F" / "photos"
    updated = sources.reconnect(db, "usb", found)
    assert updated["root_path"] == str(found.resolve())
    assert updated["id"] == source["id"]


def test_reconnect_refuses_a_different_volume(db, tmp_path, fake_volume):
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    sources.add_source(db, tmp_path / "old", "usb")
    fake_volume["id"] = "BBBB-0002"
    with pytest.raises(sources.SourceError, match="different drive"):
        sources.reconnect(db, "usb", tmp_path / "new")


def test_reconnect_refuses_an_overlap(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b" / "inner").mkdir(parents=True)
    sources.add_source(db, tmp_path / "a", "a")
    sources.add_source(db, tmp_path / "b", "b")
    with pytest.raises(sources.SourceError, match="overlaps"):
        sources.reconnect(db, "a", tmp_path / "b" / "inner")


def test_quarantine_records_its_volume_and_turns_off(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "usb", "usb")
    source, same = sources.set_quarantine(db, "usb", tmp_path / "q")
    assert source["quarantine_enabled"] == 1
    assert source["quarantine_path"] == str((tmp_path / "q").resolve())
    assert source["quarantine_volume_id"] == "AAAA-0001"
    assert same is True
    assert sources.quarantine_online(source)

    fake_volume["id"] = "BBBB-0002"  # another drive now sits at the quarantine's path
    assert not sources.quarantine_online(source)
    assert "AAAA-0001" in sources.quarantine_device(source)

    source, same = sources.set_quarantine(db, "usb", None)
    assert source["quarantine_enabled"] == 0
    assert source["quarantine_path"] is None
    assert same is None
    assert not sources.quarantine_online(source)


def test_quarantine_on_another_volume_is_reported(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "usb", "usb")
    fake_volume["id"] = "BBBB-0002"
    _source, same = sources.set_quarantine(db, "usb", tmp_path / "q")
    assert same is False


def test_quarantine_must_exist_and_sit_outside_every_source(db, tmp_path):
    (tmp_path / "a" / "inner").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    sources.add_source(db, tmp_path / "a", "a")
    sources.add_source(db, tmp_path / "b", "b")
    with pytest.raises(sources.SourceError, match="doesn't exist"):
        sources.set_quarantine(db, "a", tmp_path / "missing")
    with pytest.raises(sources.SourceError, match="overlaps source 'a'"):
        sources.set_quarantine(db, "b", tmp_path / "a" / "inner")
    assert not (tmp_path / "missing").exists()


def test_a_source_inside_a_quarantine_is_refused(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "q" / "inner").mkdir(parents=True)
    sources.add_source(db, tmp_path / "a", "a")
    sources.set_quarantine(db, "a", tmp_path / "q")
    with pytest.raises(sources.SourceError, match="quarantine"):
        sources.add_source(db, tmp_path / "q" / "inner", "inner")


def test_quarantine_offline_when_its_folder_is_gone(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "a", "a")
    source, _ = sources.set_quarantine(db, "a", tmp_path / "q")
    (tmp_path / "q").rename(tmp_path / "q-moved")
    assert not sources.quarantine_online(source)


# Rename and forget ---------------------------------------------------------------------------


def _count(conn, query, *params):
    return conn.execute(query, params).fetchone()[0]


def test_rename_changes_only_the_label(db, tmp_path):
    (tmp_path / "usb").mkdir()
    (tmp_path / "pc").mkdir()
    sources.add_source(db, tmp_path / "usb", "usb")
    sources.add_source(db, tmp_path / "pc", "pc")
    renamed = sources.rename_source(db, "usb", "usb-2014")
    assert renamed["label"] == "usb-2014"
    assert renamed["root_path"] == str((tmp_path / "usb").resolve())
    assert sources.rename_source(db, "usb-2014", "usb-2014")["label"] == "usb-2014"
    with pytest.raises(sources.SourceError, match="already exists"):
        sources.rename_source(db, "usb-2014", "pc")
    with pytest.raises(sources.SourceError, match="Labels"):
        sources.rename_source(db, "usb-2014", "a/b")
    with pytest.raises(sources.SourceError, match="no source"):
        sources.rename_source(db, "usb", "other")


def test_forget_removes_the_source_and_reopens_what_it_closed(ledger):
    conn, root, _ = ledger
    before = snapshot(root / "camera")
    # Keeping the camera copy of F rejects the "Best of" backup copy, which closes the pair
    # between the two backup copies. That pair outlives the camera source, so it must reopen.
    best_vs_camera = exact_pair(conn, F_BEST, F_CAMERA)
    backups = exact_pair(conn, F_BEST, F_JAPAN)
    decide(conn, best_vs_camera["id"], keep(best_vs_camera, file_id(conn, F_CAMERA)))
    assert status(conn, backups["id"]) == "resolved"

    usage = sources.forget_usage(conn, "camera")
    assert usage["files"] > 0 and usage["pairs"] == 4 and usage["decisions"] == 1
    camera_id = sources.get_source(conn, "camera")["id"]
    sources.forget_source(conn, "camera")

    assert _count(conn, "SELECT COUNT(*) FROM sources WHERE label = 'camera'") == 0
    assert _count(conn, "SELECT COUNT(*) FROM files WHERE source_id = ?", camera_id) == 0
    assert status(conn, backups["id"]) == "open"
    assert _count(conn, "SELECT COUNT(*) FROM decisions") == 0
    assert _count(conn, "SELECT COUNT(*) FROM review_pairs WHERE kind = 'exact'") == 1
    # A content pair left with no copies on one side closes, as after any match.
    stranded = conn.execute(
        "SELECT p.status FROM review_pairs p WHERE p.kind != 'exact' AND NOT ("
        " EXISTS (SELECT 1 FROM files WHERE content_id = p.left_id)"
        " AND EXISTS (SELECT 1 FROM files WHERE content_id = p.right_id))"
    ).fetchall()
    assert stranded and {row[0] for row in stranded} == {"obsolete"}
    assert snapshot(root / "camera") == before
    sources.add_source(conn, root / "camera", "camera")  # the folder can be mapped again


def test_forget_is_refused_while_history_needs_the_files(ledger):
    conn, _, _ = ledger
    camera_file = file_id(conn, F_CAMERA)
    conn.execute("INSERT INTO plans (status, created_at) VALUES ('draft', 'now')")
    conn.execute("INSERT INTO plans (status, created_at) VALUES ('applied', 'now')")
    for plan_id in (1, 2):
        conn.execute(
            "INSERT INTO plan_actions (plan_id, file_id, op, from_path, to_path, quarantine_root,"
            " expected_blake3, size_bytes) VALUES (?, ?, 'quarantine', 'a', 'b', 'q', 'x', 1)",
            (plan_id, camera_file),
        )
    conn.commit()
    with pytest.raises(sources.SourceError, match="applied plan"):
        sources.forget_source(conn, "camera")

    conn.execute("DELETE FROM plans WHERE status = 'applied'")
    conn.execute(
        "INSERT INTO library_entries (content_id, file_id, rel_path, expected_blake3, size_bytes,"
        " state) SELECT content_id, id, 'x.jpg', 'x', 1, 'done' FROM files WHERE id = ?",
        (camera_file,),
    )
    conn.commit()
    with pytest.raises(sources.SourceError, match="library"):
        sources.forget_source(conn, "camera")

    conn.execute("UPDATE library_entries SET state = 'pending'")
    conn.execute("UPDATE scan_sources SET status = 'running'")
    conn.commit()
    with pytest.raises(sources.SourceError, match="being scanned"):
        sources.forget_source(conn, "camera")

    # A draft plan and an unbuilt library entry are rebuilt next time, so they don't stand in
    # the way.
    conn.execute("UPDATE scan_sources SET status = 'complete'")
    conn.commit()
    sources.forget_source(conn, "camera")
    assert _count(conn, "SELECT COUNT(*) FROM plans") == 0
    assert _count(conn, "SELECT COUNT(*) FROM library_entries") == 0


def test_forget_after_undo_drops_only_its_journal_rows(ledger):
    from plan_helpers import quarantine, reject_backup_copy, reject_two_of_three

    from photo_ledger.actions import dryrun, executor, planner

    conn, root, _ = ledger
    quarantine(conn, root, "backup")
    reject_backup_copy(conn)
    reject_two_of_three(conn)
    plan_id = planner.build_plan(conn).plan_id
    assert dryrun.dry_run(conn, plan_id).ok
    assert executor.apply(conn).status == "applied"
    with pytest.raises(sources.SourceError, match="until that plan is undone"):
        sources.forget_source(conn, "backup")

    assert executor.undo(conn).status == "applied"
    undo_row = conn.execute("SELECT id FROM plans WHERE undoes_plan_id = ?", (plan_id,))
    undo_id = undo_row.fetchone()[0]
    # Another source's row in the same undone journal must outlive the forgotten source.
    conn.execute(
        "INSERT INTO plan_actions (plan_id, file_id, op, from_path, to_path, quarantine_root,"
        " expected_blake3, size_bytes, state) VALUES (?, ?, 'quarantine', 'a', 'b', 'q', 'x', 1,"
        " 'done')",
        (plan_id, file_id(conn, F_CAMERA)),
    )
    conn.commit()
    backup_id = sources.get_source(conn, "backup")["id"]
    usage = sources.forget_usage(conn, "backup")
    assert usage["plan_actions"] == 0 and usage["undone_plan_actions"] == 6
    assert sources.forget_usage(conn, "camera")["plan_actions"] == 0

    before = snapshot(root)
    sources.forget_source(conn, "backup")
    assert _count(conn, "SELECT COUNT(*) FROM files WHERE source_id = ?", backup_id) == 0
    assert _count(conn, "SELECT COUNT(*) FROM plans WHERE id = ?", undo_id) == 0
    assert _count(conn, "SELECT COUNT(*) FROM plans WHERE id = ?", plan_id) == 1
    assert _count(conn, "SELECT COUNT(*) FROM plan_actions") == 1
    assert snapshot(root) == before


def test_forget_after_choosing_a_new_library_folder(ledger):
    from photo_ledger.library import settings as library_settings

    conn, root, _ = ledger
    for name in ("library", "library-2"):
        (root.parent / name).mkdir()
    library_settings.set_library(conn, root.parent / "library")
    conn.execute(
        "INSERT INTO library_entries (content_id, file_id, rel_path, expected_blake3, size_bytes,"
        " state) SELECT content_id, id, 'x.jpg', 'x', 1, 'done' FROM files WHERE id = ?",
        (file_id(conn, F_CAMERA),),
    )
    conn.commit()
    with pytest.raises(sources.SourceError, match="new library folder"):
        sources.forget_source(conn, "camera")
    library_settings.set_library(conn, root.parent / "library-2")
    sources.forget_source(conn, "camera")
    assert (root.parent / "library").is_dir()
