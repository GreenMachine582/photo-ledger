import csv

import pytest

from photo_ledger import sources
from photo_ledger.exports.csv_export import COLUMNS, ExportError, export_files
from photo_ledger.scanner.engine import create_scan, run_scan


@pytest.fixture
def scanned(db, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(db, root / label, label)
    create_scan(db, "all", manifest["sources"])
    create_scan(db, "camera only", ["camera"])
    run_scan(db, "all")
    return root, manifest


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_exports_every_file(db, scanned, tmp_path):
    root, manifest = scanned
    out = tmp_path / "exports" / "catalogue.csv"
    assert export_files(db, out) == len(manifest["files"])
    rows = read(out)
    assert tuple(rows[0]) == COLUMNS
    by_path = {(r["source"], r["rel_path"]): r for r in rows}
    first = by_path[("camera", "2019/IMG_0001.jpg")]
    assert first["status"] == "present"
    assert first["captured_at"] == "2019-06-01T10:00:00"
    assert first["capture_date_source"] == "DateTimeOriginal"
    assert len(first["blake3"]) == 64
    assert by_path[("camera", "notes.txt")]["blake3"] == ""
    assert by_path[("backup", "broken/truncated.jpg")]["status"] == "corrupt"


def test_exports_one_scan(db, scanned, tmp_path):
    out = tmp_path / "camera.csv"
    export_files(db, out, scan_name="camera only")
    assert {row["source"] for row in read(out)} == {"camera"}


def test_refuses_to_write_inside_a_source(db, scanned):
    root, _ = scanned
    with pytest.raises(ExportError, match="never write to a source"):
        export_files(db, root / "camera" / "export.csv")
    assert not (root / "camera" / "export.csv").exists()
