"""macOS AppleDouble sidecars (``._<name>.jpg``) are counted as unsupported, never decoded or
matched, and ones an older version read as corrupt photos are fixed by an ordinary rescan."""

import pytest
from PIL import Image
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import files as file_queries
from photo_ledger.db import scans as scan_queries
from photo_ledger.matching import reports
from photo_ledger.matching.pairs import match
from photo_ledger.scanner import metadata
from photo_ledger.scanner.engine import create_scan, run_scan

#: An AppleDouble header: magic 0x00051607, version 2, filler, then no entries. It holds no image.
APPLE_DOUBLE = bytes.fromhex("00051607 00020000") + b"Mac OS X        " + b"\x00\x00" + b"\x00" * 64


def phone_folder(root):
    root.mkdir()
    Image.new("RGB", (64, 48), (180, 90, 30)).save(root / "IMAG0041.jpg", "JPEG")
    (root / "._IMAG0041.jpg").write_bytes(APPLE_DOUBLE)
    return root


@pytest.fixture
def phones(db, tmp_path):
    """The same phone folder on two backups, each with the photo and its AppleDouble twin."""
    for label in ("backup-a", "backup-b"):
        sources.add_source(db, phone_folder(tmp_path / label), label)
    create_scan(db, "all", ["backup-a", "backup-b"])
    return tmp_path


def rows(db):
    return {
        (r["label"], r["rel_path"]): (r["status"], r["content_id"])
        for r in db.execute(
            "SELECT s.label, f.rel_path, f.status, f.content_id FROM files f "
            "JOIN sources s ON s.id = f.source_id"
        )
    }


@pytest.mark.parametrize(
    ("name", "photo"),
    [("._IMAG0041.jpg", False), ("._x.PNG", False), ("IMAG0041.jpg", True), (".holiday.jpg", True)],
)
def test_only_the_appledouble_prefix_is_left_out(name, photo):
    assert metadata.is_photo(name) is photo


def test_a_scan_counts_the_sidecar_and_decodes_only_the_photo(db, phones):
    before = {label: snapshot(phones / label) for label in ("backup-a", "backup-b")}
    assert run_scan(db, "all").status == "complete"
    found = rows(db)
    for label in ("backup-a", "backup-b"):
        assert found[(label, "IMAG0041.jpg")][0] == "present"
        assert found[(label, "._IMAG0041.jpg")] == ("unsupported", None)
        assert snapshot(phones / label) == before[label]
    assert scan_queries.errors(db, scan_queries.by_name(db, "all")["id"]) == []
    assert reports.corrupt_report(db).rows == []


def test_a_rescan_fixes_sidecars_an_older_version_read_as_corrupt(db, phones):
    run_scan(db, "all")
    scan_id = scan_queries.by_name(db, "all")["id"]
    with db:  # what an older version stored: both sidecars decoded, as one corrupt content
        content_id = file_queries.insert_content(
            db, "ad" * 32, len(APPLE_DOUBLE), {"decode_error": "UnidentifiedImageError: cannot"}
        )
        for label in ("backup-a", "backup-b"):
            source_id = sources.get_source(db, label)["id"]
            db.execute(
                "UPDATE files SET status = 'corrupt', content_id = ? "
                "WHERE source_id = ? AND rel_path = '._IMAG0041.jpg'",
                (content_id, source_id),
            )
            scan_queries.add_error(db, scan_id, source_id, "._IMAG0041.jpg", "decode", "cannot")
    match(db)
    pair = db.execute(
        "SELECT * FROM review_pairs WHERE left_id IN "
        "(SELECT id FROM files WHERE rel_path = '._IMAG0041.jpg')"
    ).fetchone()
    assert pair is not None and pair["status"] == "open"  # the old, meaningless exact pair

    result = run_scan(db, "all")  # an ordinary incremental rescan

    assert all(s.hashed == 0 for s in result.sources)  # nothing re-read: the photos are reused
    found = rows(db)
    for label in ("backup-a", "backup-b"):
        assert found[(label, "._IMAG0041.jpg")][0] == "unsupported"
        assert found[(label, "IMAG0041.jpg")][0] == "present"
    assert scan_queries.errors(db, scan_id) == []
    assert reports.corrupt_report(db).rows == []

    match(db)
    status = db.execute("SELECT status FROM review_pairs WHERE id = ?", (pair["id"],)).fetchone()
    assert status["status"] == "obsolete"
