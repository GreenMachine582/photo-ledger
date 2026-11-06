"""MPO (multi-picture) JPEGs, from many phones and 3D or burst cameras, are read as JPEGs, and
ones an older version stored as unsupported are read again at the next ordinary rescan."""

import pytest
from PIL import Image
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import scans as scan_queries
from photo_ledger.scanner import metadata
from photo_ledger.scanner.engine import create_scan, run_scan

TAKEN = "2019:07:14 10:30:00"


def write_mpo(path, colour=(200, 40, 40)):
    """A two-frame MPO saved as .jpg, the way cameras name them, with an EXIF date."""
    first = Image.new("RGB", (96, 64), colour)
    for x in range(0, 96, 8):  # some structure, so the pHash isn't flat
        first.paste((x * 2, 255 - x * 2, 90), (x, 0, x + 4, 64))
    second = Image.new("RGB", (96, 64), (20, 20, 200))
    exif = Image.Exif()
    exif.get_ifd(metadata.EXIF_IFD)[0x9003] = TAKEN
    first.save(path, "MPO", save_all=True, append_images=[second], exif=exif.tobytes())
    with Image.open(path) as check:
        assert check.format == "MPO"  # really an MPO, not a plain JPEG
    return path


def test_an_mpo_reads_as_a_jpeg_from_its_first_frame(tmp_path):
    info = metadata.read_image(write_mpo(tmp_path / "IMG_0001.jpg"))
    assert info.decode_error is None
    assert info.format == "JPEG"
    assert (info.width, info.height) == (96, 64)
    assert info.phash is not None
    assert info.captured_at == "2019-07-14T10:30:00"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("MPO", True), ("JPEG", False), ("PNG", False), ("GIF", False), (None, False)],
)
def test_only_an_aliased_format_is_read_again(stored, expected):
    assert metadata.needs_redecode({"format": stored}) is expected


@pytest.fixture
def mpo_source(db, tmp_path):
    folder = tmp_path / "phone"
    folder.mkdir()
    write_mpo(folder / "IMG_0001.jpg")
    write_mpo(folder / "IMG_0002.jpg", colour=(40, 200, 40))
    # A second copy of the first: one content, so only one copy is decoded again on a rescan.
    (folder / "copy").mkdir()
    (folder / "copy" / "IMG_0001.jpg").write_bytes((folder / "IMG_0001.jpg").read_bytes())
    sources.add_source(db, folder, "phone")
    create_scan(db, "phone", ["phone"])
    return folder


def statuses(db):
    return dict(db.execute("SELECT rel_path, status FROM files ORDER BY rel_path").fetchall())


def test_a_scan_catalogues_mpo_files_as_present(db, mpo_source):
    before = snapshot(mpo_source)
    result = run_scan(db, "phone")
    assert result.status == "complete"
    assert set(statuses(db).values()) == {"present"} and len(statuses(db)) == 3
    assert db.execute("SELECT COUNT(*) FROM contents WHERE phash IS NULL").fetchone()[0] == 0
    assert snapshot(mpo_source) == before


def test_a_rescan_repairs_files_an_older_version_marked_unsupported(db, mpo_source):
    run_scan(db, "phone")
    scan_id = scan_queries.by_name(db, "phone")["id"]
    source_id = sources.get_source(db, "phone")["id"]
    with db:  # what the catalogue held before MPO was read: unsupported, with a decode error
        db.execute(
            "UPDATE contents SET format = 'MPO', decode_error = 'unsupported format MPO', "
            "phash = NULL, captured_at = NULL"
        )
        db.execute("UPDATE files SET status = 'unsupported'")
        for name in ("IMG_0001.jpg", "IMG_0002.jpg", "copy/IMG_0001.jpg"):
            scan_queries.add_error(db, scan_id, source_id, name, "decode", "unsupported format MPO")
    before = snapshot(mpo_source)

    result = run_scan(db, "phone")  # an ordinary incremental rescan, not --verify

    [source] = result.sources
    assert source.hashed == 3 and source.reused == 0 and source.new_contents == 0
    assert set(statuses(db).values()) == {"present"}
    rows = db.execute("SELECT format, decode_error, phash, captured_at FROM contents").fetchall()
    assert all(r["format"] == "JPEG" and r["decode_error"] is None and r["phash"] for r in rows)
    assert all(r["captured_at"] == "2019-07-14T10:30:00" for r in rows)
    assert scan_queries.errors(db, scan_id) == []  # the old MPO errors are gone
    assert snapshot(mpo_source) == before

    again = run_scan(db, "phone")  # and after that, they're simply reused
    assert again.sources[0].reused == 3 and again.sources[0].hashed == 0
