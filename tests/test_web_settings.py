"""The Settings page: the similar threshold and generic folder names the next match uses."""

from test_web_match import scanned  # noqa: F401  (a fixture)

from photo_ledger import preferences


def token(web):
    return web.cookies["gth_csrf"]


def stored(conn):
    return conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]


def test_changes_need_a_csrf_token(ledger, web):
    conn, _, _ = ledger
    data = {"similar_threshold": "4", "generic_folders": "DCIM"}
    assert web.post("/settings", data=data).status_code == 403
    assert web.post("/settings/reset").status_code == 403
    assert stored(conn) == 0


def test_the_page_shows_the_defaults(ledger, web):
    page = web.get("/settings").text
    assert 'name="similar_threshold"' in page and 'value="8"' in page
    assert "Camera Roll" in page and "Reset to defaults" not in page
    assert 'href="/settings"' in web.get("/").text  # in the navigation


def test_save_then_reset(ledger, web, settings):
    conn, _, _ = ledger
    saved = web.post(
        "/settings",
        data={"similar_threshold": "5", "generic_folders": "DCIM\nScans", "csrf_token": token(web)},
    )
    assert saved.url.path == "/settings"
    assert "gth-toast-success" in saved.text and "Settings saved." in saved.text
    assert 'value="5"' in saved.text and "Scans" in saved.text and "saved here" in saved.text
    assert preferences.effective(conn, settings).generic_folders == ["DCIM", "Scans"]

    reset = web.post("/settings/reset", data={"csrf_token": token(web)})
    assert "Back to the defaults." in reset.text and 'value="8"' in reset.text
    assert stored(conn) == 0


def test_a_bad_value_is_refused_and_stores_nothing(ledger, web):
    conn, _, _ = ledger
    refused = web.post(
        "/settings",
        data={"similar_threshold": "40", "generic_folders": "", "csrf_token": token(web)},
    )
    assert refused.status_code == 409 and "between 0 and 32" in refused.text
    assert stored(conn) == 0


def test_the_next_match_uses_the_saved_settings(scanned, web):  # noqa: F811
    conn, _ = scanned
    web.post(
        "/settings",
        data={"similar_threshold": "3", "generic_folders": "Holidays", "csrf_token": token(web)},
    )
    matched = web.post("/match", data={"csrf_token": token(web)})
    assert "Matched with a similarity threshold of 3" in matched.text
    names = {row[0] for row in conn.execute("SELECT name FROM collections")}
    assert "Holidays" not in names and "Pictures" in names  # only the saved names are generic
