"""The Settings page: the similar threshold and generic folder names the next match uses."""

from test_web_match import scanned  # noqa: F401  (a fixture)

from photo_ledger import preferences
from photo_ledger.review import automatic


def token(web):
    return web.cookies["gth_csrf"]


def stored(conn):
    return conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]


def test_changes_need_a_csrf_token(ledger, web):
    conn, _, _ = ledger
    data = {"similar_threshold": "4", "generic_folders": "DCIM"}
    assert web.post("/settings", data=data).status_code == 403
    assert web.post("/settings/reset").status_code == 403
    assert web.post("/settings/reopen-automatic").status_code == 403
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


def test_switches_save_off_and_on(ledger, web, settings):
    conn, _, _ = ledger
    page = web.get("/settings").text
    assert 'name="auto_tidier_path"' in page and 'name="min_similar_side"' in page
    # A switch always sends "false", then "true" after it when it's on.
    saved = web.post(
        "/settings",
        data={
            "similar_threshold": "8",
            "generic_folders": "",
            "min_similar_side": "64",
            "auto_tidier_path": ["false"],
            "name_conflicts": ["false", "true"],
            "csrf_token": token(web),
        },
    )
    assert "Settings saved." in saved.text
    prefs = preferences.effective(conn, settings)
    assert prefs.auto_tidier_path is False and prefs.name_conflicts is True
    assert prefs.min_similar_side == 64


def test_reopen_the_automatic_decisions(ledger, web):
    conn, _, _ = ledger
    assert "Reopen them for review" not in web.get("/settings").text
    automatic.apply(conn, threshold=8)
    page = web.get("/settings").text
    assert "5 decided automatically" in page and "Reopen them for review" in page

    reopened = web.post("/settings/reopen-automatic", data={"csrf_token": token(web)})
    assert "back on the review page" in reopened.text
    assert (
        conn.execute("SELECT COUNT(*) FROM review_pairs WHERE status = 'open'").fetchone()[0] == 8
    )
    again = web.post("/settings/reopen-automatic", data={"csrf_token": token(web)})
    assert "no automatic decisions to reopen" in again.text
