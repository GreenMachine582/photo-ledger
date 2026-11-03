"""Read-only reports, checked against the hand-worked fixture roles."""

import csv
import json

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.exports.guard import ExportError, write_csv
from photo_ledger.matching import reports
from photo_ledger.matching.pairs import match
from photo_ledger.scanner.engine import create_scan, run_scan


@pytest.fixture
def matched(db, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(db, root / label, label)
    create_scan(db, "all", manifest["sources"])
    create_scan(db, "camera only", ["camera"])
    run_scan(db, "all")
    before = snapshot(root)
    match(db)
    yield root, manifest
    assert snapshot(root) == before


def column(report, name):
    index = report.columns.index(name)
    return [row[index] for row in report.rows]


def test_dates_lists_only_the_restored_file(db, matched):
    report = reports.dates_report(db)
    assert column(report, "path") == ["backup/restored/IMG_0003.jpg"]
    assert report.rows[0][1] == "2018-12-25T08:00:00+10:00"
    assert report.rows[0][4] > 1800


def test_corrupt_lists_the_truncated_file(db, matched):
    report = reports.corrupt_report(db)
    assert column(report, "path") == ["backup/broken/truncated.jpg"]
    assert "truncated" in report.rows[0][2]


def test_renamed_finds_copies_with_other_names_or_folders(db, matched):
    report = reports.renamed_report(db)
    names = column(report, "names")
    assert "IMG_0002.jpg; renamed.jpg" in names
    assert "IMG_0412 (1).jpg; IMG_0412.jpg" in names
    assert len(report.rows) == 3


def test_single_source_is_neutral_and_scoped(db, matched):
    report = reports.single_source_report(db)
    assert ("camera", "2020/IMG_0001.jpg") in {row[:2] for row in report.rows}
    assert "Not a claim" in report.note
    only_camera = reports.single_source_report(db, scan="camera only")
    assert {row[0] for row in only_camera.rows} == {"camera"}


def test_single_source_needs_two_sources(db, tmp_path):
    (tmp_path / "one").mkdir()
    sources.add_source(db, tmp_path / "one", "one")
    report = reports.single_source_report(db)
    assert report.rows == [] and "Only one source" in report.note


def test_pairs_show_the_keeper_and_why(db, matched):
    report = reports.pairs_report(db, kind="similar")
    by_left = {row[4]: row for row in report.rows}
    small = by_left["camera/2019/IMG_0002.jpg (+1 copy)"]
    assert small[6] == "camera/2019/IMG_0002.jpg"
    assert small[7].startswith("higher resolution (320x240 vs 160x120)")
    exact = reports.pairs_report(db, kind="exact")
    assert len(exact.rows) == 5
    stored = db.execute("SELECT score_reasons FROM review_pairs WHERE kind = 'exact'").fetchone()[0]
    assert set(json.loads(stored)) == {"suggested", "keep", "reasons", "against"}


def test_a_scan_includes_matches_in_other_sources(db, matched):
    report = reports.pairs_report(db, scan="camera only", kind="exact")
    # Every exact pair has a camera copy except Best of 2019 vs Japan, both on the backup.
    assert len(report.rows) == 4


def test_summary_counts(db, matched):
    summary = dict(reports.summary_report(db).rows)
    assert summary["exact pairs open"] == 5
    assert summary["similar pairs open"] == 2
    assert summary["name_conflict pairs open"] == 1
    assert summary["date disagreements"] == 1
    assert summary["corrupt or unreadable"] == 1
    assert summary["unique contents"] == 9


def test_csv_written_outside_sources_only(db, matched, tmp_path):
    root, _ = matched
    report = reports.pairs_report(db)
    out = tmp_path / "reports" / "pairs.csv"
    assert write_csv(db, out, report.columns, report.rows) == 8
    with open(out, newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 8
    with pytest.raises(ExportError):
        write_csv(db, root / "backup" / "pairs.csv", report.columns, report.rows)
