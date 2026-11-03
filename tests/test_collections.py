"""Collections from folder names."""

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.collections.folders import (
    collection_path,
    collection_paths,
    collections_for_content,
    refresh_collections,
)
from photo_ledger.matching import reports
from photo_ledger.matching.pairs import match
from photo_ledger.scanner.engine import create_scan, run_scan

#: Worked out by hand from the folders holding photos in scripts/make_fixtures.py. The camera's
#: DCIM/100CANON and both source roots carry no meaningful name.
EXPECTED = {
    "2019",
    "2020",
    "screenshots",
    "Holiday 2019",
    "Holidays",
    "Holidays/2019",
    "Holidays/2019/Japan",
    "Best of 2019",
    "restored",
    "broken",
}


@pytest.mark.parametrize(
    ("folder", "path"),
    [
        ("Pictures/Holidays/2019/Japan", ("Holidays", "2019", "Japan")),
        ("DCIM/100CANON", ()),
        ("DCIM/101_PANA", ()),
        ("", ()),
        ("pictures/Camera Roll/Family", ("Family",)),
        ("Holidays/Camera/Japan", ("Holidays", "Japan")),
        ("2019", ("2019",)),
    ],
)
def test_collection_path(folder, path):
    assert collection_path(folder) == path


def test_generic_names_are_configurable():
    assert collection_path("DCIM/100CANON", generic=()) == ("DCIM",)
    assert collection_path("Trips/Japan", generic=("trips",)) == ("Japan",)


@pytest.fixture
def scanned(db, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(db, root / label, label)
    create_scan(db, "all", manifest["sources"])
    run_scan(db, "all")
    return root, manifest


def content_of(conn, rel_path):
    return conn.execute("SELECT content_id FROM files WHERE rel_path = ?", (rel_path,)).fetchone()[
        0
    ]


def test_collections_match_the_hand_checked_folders(db, scanned):
    root, _ = scanned
    before = snapshot(root)
    result = refresh_collections(db)
    assert set(collection_paths(db).values()) == EXPECTED
    assert result.new_collections == len(EXPECTED)
    assert snapshot(root) == before


def test_a_keeper_inherits_every_copys_collections(db, scanned):
    refresh_collections(db)
    content = content_of(db, "DCIM/100CANON/IMG_0412.jpg")
    assert collections_for_content(db, content) == ["Best of 2019", "Holidays/2019/Japan"]
    assert collections_for_content(db, content_of(db, "screenshots/shot_01.png")) == ["screenshots"]


def test_refreshing_again_adds_nothing(db, scanned):
    refresh_collections(db)
    again = refresh_collections(db)
    assert (again.new_collections, again.new_folders) == (0, 0)


def test_a_renamed_collection_survives_a_rescan(db, scanned):
    refresh_collections(db)
    db.execute("UPDATE collections SET name = 'Japan trip' WHERE name = 'Japan'")
    db.commit()
    run_scan(db, "all")
    result = refresh_collections(db)
    assert result.new_collections == 0
    paths = set(collection_paths(db).values())
    assert "Holidays/2019/Japan trip" in paths and "Holidays/2019/Japan" not in paths


def test_a_new_folder_with_a_known_name_joins_its_collection(db, scanned):
    root, _ = scanned
    refresh_collections(db)
    extra = root / "camera/Pictures/holidays/2019/japan/IMG_9999.jpg"
    extra.parent.mkdir(parents=True)
    extra.write_bytes((root / "backup/restored/IMG_0003.jpg").read_bytes())
    run_scan(db, "all")
    result = refresh_collections(db)
    assert (result.new_collections, result.new_folders) == (0, 1)
    content = content_of(db, "Pictures/holidays/2019/japan/IMG_9999.jpg")
    assert collections_for_content(db, content) == ["Holidays/2019/Japan", "restored"]


def test_reports_show_collections(db, scanned):
    refresh_collections(db)
    match(db)
    report = reports.collections_report(db)
    rows = {row[0]: row for row in report.rows}
    assert set(rows) == EXPECTED
    assert rows["Holidays/2019/Japan"][2:] == (1, 1, 1)
    assert rows["Holidays"][2:] == (0, 0, 0)
    exact = reports.pairs_report(db, kind="exact")
    japan = [row for row in exact.rows if "Japan" in row[4] + row[5]]
    assert {row[-1] for row in japan} == {"Best of 2019; Holidays/2019/Japan"}
