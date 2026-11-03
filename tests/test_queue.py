"""Review sessions: scope, show, kind and matches. Includes M3's "a pair resolved in one scan is
resolved in the others"."""

import pytest
from review_helpers import exact_pair

from photo_ledger.matching.pairs import match
from photo_ledger.review.decisions import decide
from photo_ledger.review.queue import Filters, counts, queue
from photo_ledger.scanner.engine import ScanError, create_scan, run_scan


@pytest.fixture
def scoped(ledger):
    conn, root, manifest = ledger
    create_scan(conn, "camera only", ["camera"])
    create_scan(conn, "backup only", ["backup"])
    return conn, root, manifest


def kinds(conn, ids):
    rows = conn.execute(
        f"SELECT kind FROM review_pairs WHERE id IN ({','.join('?' * len(ids))})", ids
    )
    return sorted(row[0] for row in rows)


def test_all_scans_shows_every_open_pair_exact_first(scoped):
    conn, _, _ = scoped
    ids = queue(conn)
    assert len(ids) == 8
    order = [
        conn.execute("SELECT kind FROM review_pairs WHERE id = ?", (i,)).fetchone()[0] for i in ids
    ]
    assert order == ["exact"] * 5 + ["similar"] * 2 + ["name_conflict"]


@pytest.mark.parametrize(
    ("scan", "matches", "expected"),
    [
        # Worked out from the fixtures: only Best of 2019 vs Japan has no camera copy.
        ("camera only", "any", 7),
        # Inside the camera: only IMG_0001.jpg's name conflict has every side there.
        ("camera only", "inside", 1),
        ("backup only", "any", 8),
        # Inside the backup: Best of 2019 vs Japan, and the resized look-alike of IMG_0002.
        ("backup only", "inside", 2),
        ("all", "inside", 8),
    ],
)
def test_scan_scopes(scoped, scan, matches, expected):
    conn, _, _ = scoped
    assert len(queue(conn, Filters(scan=scan, matches=matches))) == expected


def test_kind_filter(scoped):
    conn, _, _ = scoped
    similar = queue(conn, Filters(kind="similar"))
    assert kinds(conn, similar) == ["similar", "similar"]


def test_a_pair_resolved_in_one_scan_is_resolved_in_the_others(scoped):
    conn, _, _ = scoped
    first = queue(conn, Filters(scan="camera only"))[0]
    assert first in queue(conn, Filters(scan="backup only"))
    decide(conn, first, "keep_left")
    for scan in ("camera only", "backup only", "all", None):
        assert first not in queue(conn, Filters(scan=scan))


def test_skip_list_and_needs_review(scoped):
    conn, _, _ = scoped
    first = queue(conn)[0]
    decide(conn, first, "skip")
    assert queue(conn, Filters(show="skipped")) == [first]
    assert first not in queue(conn)
    conn.execute("UPDATE review_pairs SET status = 'needs_review' WHERE id = ?", (first,))
    conn.commit()
    assert queue(conn, Filters(show="needs_review")) == [first]
    assert counts(conn, Filters()) == {"open": 7, "new": 7, "skipped": 0, "needs_review": 1}


def test_new_since_the_scan_last_ran(scoped):
    conn, root, _ = scoped
    assert len(queue(conn, Filters(scan="all", show="new"))) == 8
    run_scan(conn, "all")
    match(conn)
    assert queue(conn, Filters(scan="all", show="new")) == []

    copy = root / "backup/extra/IMG_0003.jpg"
    copy.parent.mkdir()
    copy.write_bytes((root / "backup/restored/IMG_0003.jpg").read_bytes())
    run_scan(conn, "all")
    match(conn)
    (new,) = queue(conn, Filters(scan="all", show="new"))
    assert kinds(conn, [new]) == ["exact"]
    # A scan that has never run has nothing new.
    assert queue(conn, Filters(scan="camera only", show="new")) == []


def test_filters_round_trip_through_the_query_string(scoped):
    assert Filters().query() == ""
    filters = Filters.parse(scan="all", show="skipped", kind="nope", matches="inside")
    assert filters == Filters(scan="all", show="skipped", kind=None, matches="inside")
    assert filters.query() == "?scan=all&show=skipped&matches=inside"
    assert filters.query(pair=3).endswith("&pair=3")


def test_an_unknown_scan_is_refused(scoped):
    conn, _, _ = scoped
    with pytest.raises(ScanError):
        queue(conn, Filters(scan="nope"))


def test_helper_lookup(scoped):
    conn, _, _ = scoped
    assert exact_pair(conn, "camera/2019/IMG_0002.jpg", "backup/Holiday 2019/renamed.jpg")
