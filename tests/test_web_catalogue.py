"""The Catalogue page: find a photo and its copies, and set or clear its capture date."""

import pytest
from test_scanner import snapshot

from photo_ledger.db import catalogue
from photo_ledger.library import LibraryError, dates

PNG = "camera/screenshots/shot_01.png"
COPIED = "IMG_0001.jpg"


def post(web, url, **data):
    return web.post(url, data={**data, "csrf_token": web.cookies["gth_csrf"]})


def content_of(conn, where):
    label, _, rel_path = where.partition("/")
    return conn.execute(
        "SELECT f.content_id FROM files f JOIN sources s ON s.id = f.source_id"
        " WHERE s.label = ? AND f.rel_path = ?",
        (label, rel_path),
    ).fetchone()[0]


def fixes(conn):
    return conn.execute("SELECT COUNT(*) FROM date_fixes").fetchone()[0]


def test_every_date_action_needs_a_csrf_token(ledger, web):
    conn, _, _ = ledger
    content = content_of(conn, PNG)
    assert web.post(f"/catalogue/{content}/date", data={"value": "2020-01-01"}).status_code == 403
    dates.set_content_date(conn, content, "2020-01-01")
    assert web.post(f"/catalogue/{content}/date/clear").status_code == 403
    assert fixes(conn) == 1


def test_search_finds_a_photo_with_all_its_copies(ledger, web):
    conn, _, _ = ledger
    assert 'href="/catalogue"' in web.get("/").text
    assert "Search for a photo" in web.get("/catalogue").text

    rows = catalogue.search(conn, COPIED)
    by_content = {}
    for row in rows:
        by_content.setdefault(row["content_id"], row)
    content = content_of(conn, f"camera/2019/{COPIED}")
    assert by_content[content]["copies"] > 1
    page = web.get("/catalogue", params={"q": COPIED}).text
    assert f'href="/catalogue/{content}"' in page

    detail = web.get(f"/catalogue/{content}").text
    for copy in catalogue.copies(conn, content):
        assert copy["rel_path"] in detail
    assert web.get("/catalogue/999999").status_code == 404


def test_wildcards_in_a_search_are_literal(ledger):
    conn, _, _ = ledger
    assert catalogue.search(conn, "%") == []
    assert all("_" in row["first_path"] for row in catalogue.search(conn, "_"))


def test_undated_lists_only_photos_without_a_date(ledger, web):
    conn, _, _ = ledger
    undated = catalogue.search(conn, undated=True)
    assert undated and all(row["date_source"] == "undated" for row in undated)
    content = content_of(conn, PNG)
    assert content in {row["content_id"] for row in undated}
    assert "undated" in web.get("/catalogue", params={"undated": "1"}).text


def test_set_and_clear_a_date_from_the_browser(ledger, web):
    conn, root, _ = ledger
    before = snapshot(root)
    content = content_of(conn, PNG)

    saved = post(web, f"/catalogue/{content}/date", value="2020-02-03 04:05")
    assert saved.status_code == 200 and "Date saved for every copy" in saved.text
    assert "2020-02-03 04:05:00" in saved.text and "set by you" in saved.text
    assert dates.capture_dates(conn)[content] == dates.CaptureDate(
        "2020-02-03T04:05:00", None, "manual"
    )
    assert fixes(conn) == 1
    assert content not in {row["content_id"] for row in catalogue.search(conn, undated=True)}
    assert 'data-bs-target="#clear-date"' in saved.text

    bad = post(web, f"/catalogue/{content}/date", value="03/02/2020")
    assert bad.status_code == 409 and "Use YYYY-MM-DD" in bad.text
    assert dates.date_of(conn, content).taken == "2020-02-03T04:05:00"

    cleared = post(web, f"/catalogue/{content}/date/clear")
    assert "Forgot the date you set" in cleared.text
    assert dates.date_of(conn, content) is None and fixes(conn) == 0
    assert "had no date set by hand" in post(web, f"/catalogue/{content}/date/clear").text
    assert snapshot(root) == before


def test_content_dates_match_the_path_ones(ledger):
    conn, _, _ = ledger
    content = content_of(conn, PNG)
    assert dates.set_content_date(conn, content, "2017-07-07") == "2017-07-07T00:00:00"
    assert dates.date_of(conn, content).source == "manual"
    assert dates.clear_date(conn, PNG)
    assert not dates.clear_content_date(conn, content)
    with pytest.raises(LibraryError, match="no catalogued photo"):
        dates.set_content_date(conn, 999999, "2017-07-07")


def test_clearing_goes_back_to_the_exif_date(ledger):
    conn, _, _ = ledger
    exif = next(row for row in catalogue.search(conn, ".jpg") if row["date_source"] == "exif")
    content = exif["content_id"]
    dates.set_content_date(conn, content, "2001-01-01")
    assert dates.date_of(conn, content).source == "manual"
    dates.clear_content_date(conn, content)
    assert dates.date_of(conn, content) == dates.CaptureDate(
        exif["taken"], dates.date_of(conn, content).offset, "exif"
    )
