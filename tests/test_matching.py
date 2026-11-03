"""Stable pairs, checked against M2's "done when": a report matching a hand-checked sample, and
no new pairs from rescanning the same files."""

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.matching.pairs import match
from photo_ledger.scanner.engine import create_scan, run_scan

#: Worked out by hand from scripts/make_fixtures.py: picture a has 2 copies, b has 2 and f has 3,
#: b and d each have a re-encoded look-alike, and IMG_0001.jpg names both a and c. Exact pairs
#: name two files. Similar and name-conflict pairs compare contents, so each side lists every copy.
A = ("backup/Holiday 2019/IMG_0001.jpg", "camera/2019/IMG_0001.jpg")
B = ("backup/Holiday 2019/renamed.jpg", "camera/2019/IMG_0002.jpg")
F_CAMERA = "camera/DCIM/100CANON/IMG_0412.jpg"
F_BEST = "backup/Best of 2019/IMG_0412 (1).jpg"
F_JAPAN = "backup/Pictures/Holidays/2019/Japan/IMG_0412.jpg"
HAND_CHECKED = {
    ("exact", (A[0],), (A[1],)),
    ("exact", (B[0],), (B[1],)),
    ("exact", (F_CAMERA,), (F_BEST,)),
    ("exact", (F_CAMERA,), (F_JAPAN,)),
    ("exact", (F_BEST,), (F_JAPAN,)),
    ("similar", B, ("backup/Holiday 2019/IMG_0002_small.jpg",)),
    ("similar", ("camera/screenshots/shot_01.png",), ("backup/shot_01.jpg",)),
    ("name_conflict", A, ("camera/2020/IMG_0001.jpg",)),
}


def described(conn, statuses=("open",)):
    """Pairs as ``(kind, side, side)``, each side a sorted tuple of copies' paths."""

    def file_paths(file_id):
        rows = conn.execute(
            "SELECT s.label || '/' || f.rel_path FROM files f JOIN sources s ON s.id = f.source_id"
            " WHERE f.id = ?",
            (file_id,),
        )
        return tuple(sorted(row[0] for row in rows))

    def content_paths(content_id):
        rows = conn.execute(
            "SELECT s.label || '/' || f.rel_path FROM files f JOIN sources s ON s.id = f.source_id"
            " WHERE f.content_id = ? AND f.status != 'missing'",
            (content_id,),
        )
        return tuple(sorted(row[0] for row in rows))

    found = set()
    marks = ",".join("?" * len(statuses))
    for row in conn.execute(f"SELECT * FROM review_pairs WHERE status IN ({marks})", statuses):
        lookup = file_paths if row["kind"] == "exact" else content_paths
        found.add((row["kind"], lookup(row["left_id"]), lookup(row["right_id"])))
    return normalise(found)


def normalise(pairs):
    """Order inside a pair isn't meaningful here."""
    return {(kind, *sorted((a, b))) for kind, a, b in pairs}


def pair_rows(conn):
    return {
        row["pair_key"]: (row["id"], row["status"])
        for row in conn.execute("SELECT * FROM review_pairs")
    }


@pytest.fixture
def scanned(db, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(db, root / label, label)
    create_scan(db, "all", manifest["sources"])
    run_scan(db, "all")
    return root, manifest


def test_pairs_match_the_hand_checked_sample(db, scanned):
    root, _ = scanned
    before = snapshot(root)
    result = match(db)
    assert result.by_kind == {"exact": 5, "similar": 2, "name_conflict": 1}
    assert result.new == 8
    assert described(db) == normalise(HAND_CHECKED)
    assert snapshot(root) == before


def test_rescanning_the_same_files_creates_no_new_pairs(db, scanned):
    match(db)
    before = pair_rows(db)
    assert match(db).new == 0
    run_scan(db, "all")
    again = match(db)
    assert (again.new, again.reopened, again.obsolete, again.needs_review) == (0, 0, 0, 0)
    assert again.unchanged == 8
    assert pair_rows(db) == before


def test_keys_are_stable_and_ordered(db, scanned):
    match(db)
    for row in db.execute("SELECT * FROM review_pairs"):
        kind, left, right = row["pair_key"].split(":")
        assert kind == row["kind"]
        assert left < right if kind != "exact" else int(left) < int(right)


def test_a_new_file_queues_only_its_pairs(db, scanned):
    root, _ = scanned
    match(db)
    before = pair_rows(db)
    copy = root / "backup/extra/IMG_0003.jpg"
    copy.parent.mkdir()
    copy.write_bytes((root / "backup/restored/IMG_0003.jpg").read_bytes())
    run_scan(db, "all")
    result = match(db)
    assert result.new == 1 and result.unchanged == 8
    after = pair_rows(db)
    assert {key: after[key] for key in before} == before
    (new_key,) = set(after) - set(before)
    assert new_key.startswith("exact:")


def test_a_missing_file_closes_its_pairs(db, scanned):
    root, _ = scanned
    match(db)
    (root / "backup/Holiday 2019/renamed.jpg").unlink()
    run_scan(db, "all")
    result = match(db)
    assert result.obsolete == 1
    obsolete = described(db, statuses=("obsolete",))
    assert obsolete == normalise({("exact", (B[0],), (B[1],))})


def test_an_offline_source_changes_nothing(db, scanned):
    root, _ = scanned
    match(db)
    before = pair_rows(db)
    (root / "backup").rename(root / "unplugged")
    run_scan(db, "all")
    result = match(db)
    assert (result.new, result.obsolete) == (0, 0)
    assert pair_rows(db) == before


def test_changing_the_threshold_keeps_decided_pairs(db, scanned):
    match(db, threshold=8)
    similar = [
        row["id"] for row in db.execute("SELECT id FROM review_pairs WHERE kind = 'similar'")
    ]
    db.execute("UPDATE review_pairs SET status = 'resolved' WHERE id = ?", (similar[0],))
    db.commit()

    # Distance 0 still matches at 0, so close everything by pretending the pHashes moved apart.
    db.execute(
        "UPDATE contents SET phash = printf('%016x', id * 1311768467294899695 % 9007199254740881)"
    )
    db.commit()
    lowered = match(db, threshold=0)
    assert lowered.obsolete == 1
    statuses = dict(
        db.execute("SELECT id, status FROM review_pairs WHERE kind = 'similar'").fetchall()
    )
    assert statuses[similar[0]] == "resolved"
    assert statuses[similar[1]] == "obsolete"


def test_a_resolved_exact_pair_whose_content_changes_needs_review(db, scanned):
    root, _ = scanned
    match(db)
    low, high = db.execute(
        "SELECT MIN(id), MAX(id) FROM files WHERE rel_path IN (?, ?)",
        ("2019/IMG_0001.jpg", "Holiday 2019/IMG_0001.jpg"),
    ).fetchone()
    key = f"exact:{low}:{high}"
    db.execute("UPDATE review_pairs SET status = 'resolved' WHERE pair_key = ?", (key,))
    db.commit()
    replacement = (root / "camera/2020/IMG_0001.jpg").read_bytes()
    (root / "camera/2019/IMG_0001.jpg").write_bytes(replacement)
    (root / "backup/Holiday 2019/IMG_0001.jpg").write_bytes(replacement)
    run_scan(db, "all")
    result = match(db)
    assert result.needs_review == 1
    status = db.execute("SELECT status FROM review_pairs WHERE pair_key = ?", (key,)).fetchone()[0]
    assert status == "needs_review"


def test_an_obsolete_pair_reopens_when_it_matches_again(db, scanned):
    root, _ = scanned
    match(db)
    target = root / "backup/Holiday 2019/renamed.jpg"
    parked = root / "parked.jpg"
    target.rename(parked)
    run_scan(db, "all")
    assert match(db).obsolete == 1
    parked.rename(target)
    run_scan(db, "all")
    assert match(db).reopened == 1
    assert described(db) == normalise(HAND_CHECKED)
