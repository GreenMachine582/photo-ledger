"""Running match from the Overview."""

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import open_db
from photo_ledger.scanner.engine import create_scan, run_scan

HX = {"HX-Request": "true"}


@pytest.fixture
def scanned(settings, fixture_tree):
    """The fixtures mapped and scanned, but never matched."""
    root, manifest = fixture_tree
    conn = open_db(settings.db_path)
    for label in manifest["sources"]:
        sources.add_source(conn, root / label, label)
    create_scan(conn, "all", manifest["sources"])
    run_scan(conn, "all")
    yield conn, root
    conn.close()


def test_overview_offers_match(scanned, web):
    page = web.get("/").text
    assert 'hx-post="/match"' in page and 'id="match-result"' in page


def test_match_needs_a_csrf_token(scanned, web):
    conn, _ = scanned
    assert web.post("/match", headers=HX).status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM review_pairs").fetchone()[0] == 0


def test_match_from_the_browser(scanned, web):
    conn, root = scanned
    before = snapshot(root)
    token = {"X-CSRF-Token": web.cookies["gth_csrf"]}

    first = web.post("/match", headers={**HX, **token})
    assert first.status_code == 200
    assert "<html" not in first.text  # just the panel, for htmx to swap in
    assert "Matched with a similarity threshold of 8" in first.text
    assert " exact<" in first.text and 'href="/review"' in first.text
    found = conn.execute("SELECT COUNT(*) FROM review_pairs").fetchone()[0]
    assert found > 0
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0] > 0

    again = web.post("/match", headers={**HX, **token})
    assert f"{found:,} unchanged" in again.text and "0 new" in again.text
    assert conn.execute("SELECT COUNT(*) FROM review_pairs").fetchone()[0] == found
    assert snapshot(root) == before


def test_match_without_htmx_shows_the_overview(scanned, web):
    page = web.post("/match", data={"csrf_token": web.cookies["gth_csrf"]})
    assert page.status_code == 200
    assert "<html" in page.text and "Matched with a similarity threshold" in page.text
