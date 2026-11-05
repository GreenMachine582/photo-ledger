"""The Overview's next step, grouped navigation, toasts for results and busy-button forms."""

from test_library import settle_everything
from test_web_match import scanned  # noqa: F401  (a fixture)

from photo_ledger import sources
from photo_ledger.actions import executor
from photo_ledger.db import open_db
from photo_ledger.library import plan as library_plan
from photo_ledger.library import settings as library_settings
from photo_ledger.review.next_step import next_step
from photo_ledger.review.overview import overview

TOASTS = "gth-flash-toasts"


def token(web):
    return web.cookies["gth_csrf"]


def htmx(web, referer="https://127.0.0.1/sources"):
    return {"HX-Request": "true", "X-CSRF-Token": token(web), "Referer": referer}


def step(conn):
    return next_step(conn, overview(conn)).key


# Toasts ----------------------------------------------------------------------------------------


def test_a_result_is_a_toast_not_a_query_string(ledger, web):
    done = web.post("/sources/check", data={"csrf_token": token(web)})
    assert done.url.path == "/sources" and not done.url.query
    assert TOASTS in done.text and "Checked every source." in done.text
    again = web.get("/sources").text
    assert TOASTS not in again and "Checked every source." not in again  # shown once


def test_a_warning_result_is_a_warning_toast(ledger, web):
    conn, root, _ = ledger
    folder = root.parent / "library"
    folder.mkdir()
    web.post("/library", data={"path": str(folder), "layout": "year", "csrf_token": token(web)})
    folder.rmdir()
    refused = web.post("/library/build", data={"csrf_token": token(web)})
    assert "found problems" in refused.text and "gth-toast-warning" in refused.text
    done = web.post("/sources/check", data={"csrf_token": token(web)})
    assert "gth-toast-success" in done.text


# Busy buttons over htmx ------------------------------------------------------------------------


def test_long_actions_are_busy_button_forms(ledger, web):
    page = web.get("/plan").text
    assert 'hx-post="/plan"' in page and "gth-busy-button" in page
    assert 'hx-post="/sources/check"' in web.get("/sources").text


def test_an_htmx_form_gets_a_full_page_load_with_its_toast(ledger, web):
    done = web.post("/sources/check", headers=htmx(web), follow_redirects=False)
    assert done.status_code == 200 and done.headers["HX-Redirect"] == "/sources"
    assert "location" not in done.headers
    assert "Checked every source." in web.get("/sources").text


def test_an_htmx_refusal_goes_back_with_the_reason(ledger, web):
    _, root, _ = ledger
    refused = web.post(
        "/library",
        data={"path": str(root / "camera"), "layout": "year"},
        headers=htmx(web, "https://127.0.0.1/library"),
        follow_redirects=False,
    )
    assert refused.status_code == 200 and refused.headers["HX-Redirect"] == "/library"
    page = web.get("/library").text
    assert TOASTS in page and "overlaps source" in page


def test_an_htmx_refusal_never_goes_back_off_site(ledger, web):
    _, root, _ = ledger
    refused = web.post(
        "/library",
        data={"path": str(root / "camera"), "layout": "year"},
        headers=htmx(web, "https://elsewhere.example/library"),
        follow_redirects=False,
    )
    assert refused.headers["HX-Redirect"] == "/"


# Navigation ------------------------------------------------------------------------------------


def test_navigation_is_grouped(ledger, web):
    page = web.get("/").text
    assert "Catalogue" in page and "Organise" in page
    for url in (
        "/sources",
        "/catalogue",
        "/collections",
        "/reports",
        "/review",
        "/plan",
        "/library",
    ):
        assert f'href="{url}"' in page


# Next step -------------------------------------------------------------------------------------


def test_next_step_from_an_empty_catalogue(settings, fixture_tree, web):
    root, manifest = fixture_tree
    conn = open_db(settings.db_path)
    try:
        assert step(conn) == "map"
        sources.add_source(conn, root / "camera", "camera")
        assert step(conn) == "scan"
        page = web.get("/").text
        assert "Next step: Scan your sources" in page
    finally:
        conn.close()


def test_next_step_after_a_scan_is_match(scanned, web):  # noqa: F811
    conn, _ = scanned
    assert step(conn) == "match"
    assert "Next step: Find duplicates" in web.get("/").text


def test_next_step_walks_to_a_built_library(ledger, web):
    conn, root, _ = ledger
    assert step(conn) == "review"
    assert 'href="/review">Start reviewing' in web.get("/").text

    settle_everything(conn)
    assert step(conn) == "library"  # no quarantine, so nothing for a plan to move

    folder = root.parent / "library"
    folder.mkdir()
    library_settings.set_library(conn, folder, "year")
    assert step(conn) == "build"

    library_plan.plan_library(conn)
    executor.build_library(conn)
    assert step(conn) == "done"
    assert "Next step: All caught up" in web.get("/").text


def test_next_step_offers_the_plan_when_copies_can_move(ledger):
    conn, root, _ = ledger
    quarantine = root.parent / "quarantine"
    quarantine.mkdir()
    sources.set_quarantine(conn, "backup", quarantine)
    settle_everything(conn)
    assert step(conn) == "plan"
