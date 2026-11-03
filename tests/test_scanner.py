"""Saved scans, checked against M1's "done when": a paused scan resumes, an overlapping scan
reuses hashes, changed files reconcile, an offline source marks nothing missing, and the
source files are never changed."""

import os
from types import SimpleNamespace

import pytest
from blake3 import blake3

from photo_ledger import sources
from photo_ledger.db import open_db
from photo_ledger.scanner import engine, hashing
from photo_ledger.scanner.engine import ScanConflict, ScanError, create_scan, run_scan


def supported(tree, source=None):
    """JPEG and PNG files in the fixture tree, or in one of its sources."""
    counts = tree[1]["supported"]
    return counts[source] if source else sum(counts.values())


def snapshot(root):
    """Everything that would show a source file had been touched."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
                blake3(path.read_bytes()).hexdigest(),
            )
    return found


def catalogue(conn):
    return {
        (row["label"], row["rel_path"], row["status"], row["blake3"])
        for row in conn.execute(
            """
            SELECT s.label, f.rel_path, f.status, c.blake3
            FROM files f JOIN sources s ON s.id = f.source_id
            LEFT JOIN contents c ON c.id = f.content_id
            """
        )
    }


def file_row(conn, rel_path):
    return conn.execute("SELECT * FROM files WHERE rel_path = ?", (rel_path,)).fetchone()


def in_source(manifest_path):
    """A manifest path is relative to the tree; the catalogue's are relative to each source."""
    return manifest_path.split("/", 1)[1]


def stop_after(calls):
    count = {"n": 0}

    def should_stop():
        count["n"] += 1
        return count["n"] > calls

    return should_stop


@pytest.fixture
def hashes(monkeypatch):
    """Count calls to the BLAKE3 hasher."""
    counter = {"n": 0}
    real = hashing.hash_file

    def counting(path):
        counter["n"] += 1
        return real(path)

    monkeypatch.setattr(hashing, "hash_file", counting)
    return counter


@pytest.fixture
def tree(db, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(db, root / label, label)
    create_scan(db, "all", manifest["sources"])
    return root, manifest


def map_tree(conn, root, labels):
    for label in labels:
        sources.add_source(conn, root / label, label)
    create_scan(conn, "all", labels)


def test_full_scan(db, tree, hashes):
    root, manifest = tree
    before = snapshot(root)
    result = run_scan(db, "all")

    assert result.status == "complete"
    assert [s.status for s in result.sources] == ["complete", "complete"]
    assert sum(s.seen for s in result.sources) == len(manifest["files"])
    assert hashes["n"] == supported(tree)
    assert db.execute("SELECT COUNT(*) FROM contents").fetchone()[0] == tree[1]["unique_contents"]
    for left, right in manifest["exact_copies"]:
        assert (
            file_row(db, in_source(left))["content_id"]
            == file_row(db, in_source(right))["content_id"]
        )
    assert file_row(db, in_source(manifest["truncated"][0]))["status"] == "corrupt"
    assert file_row(db, "notes.txt")["status"] == "unsupported"
    assert file_row(db, "clip.mp4")["content_id"] is None
    restored = db.execute(
        "SELECT c.* FROM files f JOIN contents c ON c.id = f.content_id WHERE f.rel_path = ?",
        ("restored/IMG_0003.jpg",),
    ).fetchone()
    assert restored["captured_at"] == "2018-12-25T08:00:00"
    assert restored["capture_date_source"] == "DateTimeOriginal"
    assert db.execute("SELECT status FROM scans").fetchone()[0] == "complete"
    stages = {row["stage"] for row in db.execute("SELECT stage FROM scan_errors")}
    assert stages == {"decode"}
    assert snapshot(root) == before


@pytest.mark.parametrize("pause_after", [1, 5, 12, 15])
def test_a_paused_scan_resumes_to_the_same_catalogue(db, tree, tmp_path, hashes, pause_after):
    """Pausing in either stage, as often as needed, ends with the uninterrupted result."""
    root, manifest = tree
    before = snapshot(root)
    runs = 0
    while True:
        runs += 1
        result = run_scan(db, "all", should_stop=stop_after(pause_after))
        if result.status == "complete":
            break
        assert result.status == "paused"
        assert runs < 100
    assert runs > 1
    assert hashes["n"] == supported(tree)  # nothing hashed twice across the pauses

    other = open_db(tmp_path / "uninterrupted.db")
    map_tree(other, root, manifest["sources"])
    run_scan(other, "all")
    assert catalogue(db) == catalogue(other)
    assert snapshot(root) == before


def test_an_overlapping_scan_reuses_hashes(db, tree, hashes):
    create_scan(db, "camera only", ["camera"])
    run_scan(db, "camera only")
    assert hashes["n"] == supported(tree, "camera")

    result = run_scan(db, "all")
    assert hashes["n"] == supported(tree)
    camera = next(s for s in result.sources if s.label == "camera")
    assert camera.reused == supported(tree, "camera") and camera.hashed == 0


def test_a_rescan_of_unchanged_files_hashes_nothing(db, tree, hashes):
    run_scan(db, "all")
    hashes["n"] = 0
    result = run_scan(db, "all")
    assert result.status == "complete"
    assert hashes["n"] == 0
    assert sum(s.reused for s in result.sources) == supported(tree)
    assert sum(s.missing + s.moved for s in result.sources) == 0


def test_a_changed_file_links_to_its_new_content(db, tree):
    root, _ = tree
    run_scan(db, "all")
    target = root / "camera/2019/IMG_0001.jpg"
    old = file_row(db, "2019/IMG_0001.jpg")
    target.write_bytes((root / "camera/2020/IMG_0001.jpg").read_bytes())

    result = run_scan(db, "all")
    camera = next(s for s in result.sources if s.label == "camera")
    assert camera.content_changes == ["2019/IMG_0001.jpg"]
    new = file_row(db, "2019/IMG_0001.jpg")
    assert new["id"] == old["id"]
    assert new["content_id"] == file_row(db, "2020/IMG_0001.jpg")["content_id"]


def test_verify_finds_a_change_that_size_and_mtime_hide(db, tree):
    root, _ = tree
    run_scan(db, "all")
    target = root / "camera/2019/IMG_0002.jpg"
    stat = target.stat()
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    old_content = file_row(db, "2019/IMG_0002.jpg")["content_id"]

    plain = run_scan(db, "all")
    assert all(not s.content_changes for s in plain.sources)
    assert file_row(db, "2019/IMG_0002.jpg")["content_id"] == old_content

    verified = run_scan(db, "all", verify=True)
    camera = next(s for s in verified.sources if s.label == "camera")
    assert camera.content_changes == ["2019/IMG_0002.jpg"]
    assert camera.hashed == supported(tree, "camera")
    assert file_row(db, "2019/IMG_0002.jpg")["content_id"] != old_content
    unverified = db.execute(
        "SELECT COUNT(*) FROM files WHERE status != 'unsupported' AND last_verified_at IS NULL"
    ).fetchone()[0]
    assert unverified == 0


def test_a_moved_file_keeps_its_id(db, tree):
    root, _ = tree
    run_scan(db, "all")
    old = file_row(db, "2019/IMG_0002.jpg")
    (root / "camera/moved").mkdir()
    (root / "camera/2019/IMG_0002.jpg").rename(root / "camera/moved/renamed.jpg")

    result = run_scan(db, "all")
    camera = next(s for s in result.sources if s.label == "camera")
    assert (camera.moved, camera.missing) == (1, 0)
    assert file_row(db, "2019/IMG_0002.jpg") is None
    moved = file_row(db, "moved/renamed.jpg")
    assert moved["id"] == old["id"]
    assert moved["filename"] == "renamed.jpg"
    assert moved["status"] == "present"


def test_a_deleted_file_is_missing_only_after_a_complete_scan(db, tree):
    root, _ = tree
    run_scan(db, "all")
    (root / "camera/2020/IMG_0001.jpg").unlink()

    paused = run_scan(db, "all", should_stop=stop_after(2))
    assert paused.status == "paused"
    assert file_row(db, "2020/IMG_0001.jpg")["status"] == "present"

    finished = run_scan(db, "all")
    assert finished.status == "complete"
    assert file_row(db, "2020/IMG_0001.jpg")["status"] == "missing"
    assert sum(s.missing for s in finished.sources) == 1


def test_a_missing_file_that_returns_is_present_again(db, tree):
    root, _ = tree
    run_scan(db, "all")
    target = root / "camera/2020/IMG_0001.jpg"
    parked = root / "parked.jpg"
    target.rename(parked)
    run_scan(db, "all")
    assert file_row(db, "2020/IMG_0001.jpg")["status"] == "missing"
    parked.rename(target)
    run_scan(db, "all")
    assert file_row(db, "2020/IMG_0001.jpg")["status"] == "present"


def test_an_offline_source_marks_nothing_missing(db, tree):
    root, _ = tree
    run_scan(db, "all")
    (root / "backup").rename(root / "unplugged")

    result = run_scan(db, "all")
    assert result.status == "paused"
    backup = next(s for s in result.sources if s.label == "backup")
    assert backup.status == "offline"
    assert sources.get_source(db, "backup")["state"] == "offline"
    statuses = {
        row[0]
        for row in db.execute(
            "SELECT f.status FROM files f JOIN sources s ON s.id = f.source_id"
            " WHERE s.label = 'backup'"
        )
    }
    assert "missing" not in statuses

    (root / "unplugged").rename(root / "backup")
    assert run_scan(db, "all").status == "complete"
    assert db.execute("SELECT COUNT(*) FROM files WHERE status = 'missing'").fetchone()[0] == 0


def test_a_source_unplugged_mid_walk_marks_nothing_missing(db, tree, monkeypatch):
    root, _ = tree
    run_scan(db, "all")
    real_record = engine._SourceRun._record

    def unplug_after_first(self, entry):
        real_record(self, entry)
        if self.source["label"] == "camera" and self.result.seen == 1:
            (root / "camera").rename(root / "gone")

    monkeypatch.setattr(engine._SourceRun, "_record", unplug_after_first)
    result = run_scan(db, "all")
    camera = next(s for s in result.sources if s.label == "camera")
    assert camera.status == "offline"
    assert db.execute("SELECT COUNT(*) FROM files WHERE status = 'missing'").fetchone()[0] == 0


def test_an_unreadable_folder_marks_nothing_missing(db, tree, monkeypatch):
    run_scan(db, "all")
    real_scandir = os.scandir

    def scandir(path):
        if str(path).endswith("2020"):
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    result = run_scan(db, "all")
    assert result.status == "complete"
    assert file_row(db, "2020/IMG_0001.jpg")["status"] == "present"
    assert sum(s.errors for s in result.sources) == 1


def test_a_file_changing_while_hashed_is_flagged(db, tree, monkeypatch):
    calls = {}
    real_stat = engine._stat

    def stat(path):
        result = real_stat(path)
        if path.name == "IMG_0003.jpg":
            calls[path] = calls.get(path, 0) + 1
            if calls[path] == 2:
                return SimpleNamespace(st_size=result.st_size, st_mtime_ns=result.st_mtime_ns + 1)
        return result

    monkeypatch.setattr(engine, "_stat", stat)
    run_scan(db, "all")
    row = file_row(db, "restored/IMG_0003.jpg")
    assert row["status"] == "changed_during_scan"
    assert row["content_id"] is None

    monkeypatch.setattr(engine, "_stat", real_stat)
    run_scan(db, "all")
    assert file_row(db, "restored/IMG_0003.jpg")["status"] == "present"


def test_only_one_scan_processes_a_source_at_a_time(db, tree):
    create_scan(db, "camera only", ["camera"])
    camera_id = sources.get_source(db, "camera")["id"]
    other = db.execute("SELECT id FROM scans WHERE name = 'all'").fetchone()[0]
    db.execute(
        "UPDATE scan_sources SET status = 'running', heartbeat_at = ?"
        " WHERE scan_id = ? AND source_id = ?",
        (engine.now_ns(), other, camera_id),
    )
    db.commit()
    with pytest.raises(ScanConflict, match="camera"):
        run_scan(db, "camera only")

    # A heartbeat older than the limit is a crashed run, and can be taken over.
    db.execute(
        "UPDATE scan_sources SET heartbeat_at = ? WHERE scan_id = ?",
        (engine.now_ns() - engine.STALE_AFTER_NS - 1, other),
    )
    db.commit()
    assert run_scan(db, "camera only").status == "complete"


def test_a_crashed_run_resumes(db, tree, monkeypatch, hashes):
    """An exception mid-hash keeps the work done so far, and the next run finishes it."""
    real = engine._SourceRun._hash_one
    calls = {"n": 0}

    def crash_on_third(self, row):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("power cut")
        real(self, row)

    monkeypatch.setattr(engine._SourceRun, "_hash_one", crash_on_third)
    with pytest.raises(RuntimeError):
        run_scan(db, "all")
    statuses = {row[0] for row in db.execute("SELECT status FROM scan_sources")}
    assert "running" not in statuses

    monkeypatch.setattr(engine._SourceRun, "_hash_one", real)
    assert run_scan(db, "all").status == "complete"
    assert hashes["n"] == supported(tree)


def test_create_scan_checks_its_input(db, tree):
    with pytest.raises(ScanError, match="already exists"):
        create_scan(db, "all", ["camera"])
    with pytest.raises(sources.SourceError, match="no source"):
        create_scan(db, "new", ["nope"])
    with pytest.raises(ScanError, match="at least one"):
        create_scan(db, "new", [" "])
    with pytest.raises(ScanError, match="no scan"):
        run_scan(db, "nope")
