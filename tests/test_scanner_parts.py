"""The scanner's building blocks: the resumable walk, hashing and image metadata."""

import json
import os
import sys

import imagehash
import make_fixtures
import pytest
from blake3 import blake3

from photo_ledger.scanner import hashing, metadata
from photo_ledger.scanner.walk import walk


def test_walk_yields_every_file_in_sorted_order(fixture_tree):
    root, manifest = fixture_tree
    found = [entry.rel_path for entry in walk(root)]
    assert sorted(found) == manifest["files"]
    assert found == sorted(found, key=lambda rel: tuple(rel.split("/")))
    entry = next(e for e in walk(root) if e.rel_path == "camera/notes.txt")
    assert entry.size_bytes == len(b"not a photo\n")
    assert entry.mtime_ns == make_fixtures.BASE_MTIME_NS


@pytest.mark.parametrize("cut", range(1, 12))
def test_walk_resumes_after_any_path(fixture_tree, cut):
    root, _ = fixture_tree
    everything = [entry.rel_path for entry in walk(root)]
    resumed = [entry.rel_path for entry in walk(root, after=everything[cut - 1])]
    assert everything[:cut] + resumed == everything


def test_walk_resumes_after_a_path_that_has_gone(fixture_tree):
    root, _ = fixture_tree
    everything = [entry.rel_path for entry in walk(root)]
    resumed = [entry.rel_path for entry in walk(root, after="backup/Holiday 2019/IMG_0001.jpgz")]
    assert resumed == [rel for rel in everything if rel > "backup/Holiday 2019/IMG_0001.jpgz"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_walk_does_not_follow_symlinks(tmp_path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "a.jpg").write_bytes(b"x")
    (tmp_path / "root").mkdir()
    os.symlink(tmp_path / "outside", tmp_path / "root" / "link")
    assert list(walk(tmp_path / "root")) == []


def test_walk_reports_and_skips_unreadable_folders(tmp_path, monkeypatch):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "a.jpg").write_bytes(b"x")
    (tmp_path / "locked").mkdir()
    (tmp_path / "locked" / "b.jpg").write_bytes(b"x")
    real_scandir = os.scandir

    def scandir(path):
        if str(path).endswith("locked"):
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    errors = []
    found = [e.rel_path for e in walk(tmp_path, on_error=lambda rel, exc: errors.append(rel))]
    assert found == ["ok/a.jpg"]
    assert errors == ["locked"]


def test_walk_raises_when_the_root_is_gone(tmp_path):
    with pytest.raises(OSError):
        list(walk(tmp_path / "gone", on_error=lambda rel, exc: None))


def test_hash_matches_blake3(fixture_tree):
    root, manifest = fixture_tree
    path = root / manifest["exact_copies"][0][0]
    assert hashing.hash_file(path) == blake3(path.read_bytes()).hexdigest()
    left, right = manifest["exact_copies"][0]
    assert hashing.hash_file(root / left) == hashing.hash_file(root / right)


def test_jpeg_metadata(fixture_tree):
    root, _ = fixture_tree
    info = metadata.read_image(root / "camera/2019/IMG_0001.jpg")
    assert info.decode_error is None and info.exif_error is None
    assert (info.format, info.width, info.height) == ("JPEG", 320, 240)
    assert info.captured_at == "2019-06-01T10:00:00"
    assert info.capture_date_source == "DateTimeOriginal"
    assert info.capture_offset == "+10:00"
    assert (info.camera_make, info.camera_model) == ("FixtureCam", "FC-1")
    assert json.loads(info.exif_json)["Make"] == "FixtureCam"
    assert len(info.phash) == 16


def test_png_without_exif_stays_undated(fixture_tree):
    root, manifest = fixture_tree
    info = metadata.read_image(root / manifest["pngs"][0])
    assert info.format == "PNG"
    assert info.captured_at is None and info.capture_date_source is None
    assert info.decode_error is None and info.phash


def test_restored_file_keeps_its_exif_date(fixture_tree):
    root, manifest = fixture_tree
    info = metadata.read_image(root / manifest["date_mismatch"][0])
    assert info.captured_at == manifest["taken"][manifest["date_mismatch"][0]]


def test_phash_finds_similar_and_separates_distinct(fixture_tree):
    root, manifest = fixture_tree

    def distance(a, b):
        ha = imagehash.hex_to_hash(metadata.read_image(root / a).phash)
        hb = imagehash.hex_to_hash(metadata.read_image(root / b).phash)
        return ha - hb

    for left, right in manifest["similar"]:
        assert distance(left, right) <= 8
    left, right = manifest["name_conflicts"][0]
    assert distance(left, right) > 8


def test_truncated_and_unsupported_files(fixture_tree):
    root, manifest = fixture_tree
    truncated = metadata.read_image(root / manifest["truncated"][0])
    assert truncated.decode_error and truncated.phash is None
    text = metadata.read_image(root / "camera/notes.txt")
    assert text.decode_error


def test_wrong_format_behind_a_jpeg_extension(tmp_path):
    from PIL import Image

    Image.new("RGB", (8, 8)).save(tmp_path / "really.jpg", "GIF")
    info = metadata.read_image(tmp_path / "really.jpg")
    assert info.format == "GIF"
    assert info.decode_error == "unsupported format GIF"


def test_exif_dates(fixture_tree):
    assert metadata.parse_exif_datetime("2019:06:01 10:00:00") == "2019-06-01T10:00:00"
    assert metadata.parse_exif_datetime("0000:00:00 00:00:00") is None
    assert metadata.parse_exif_datetime("    ") is None
    assert metadata.parse_exif_datetime(None) is None
    assert metadata.is_supported(".JPG") and not metadata.is_supported(".heic")
