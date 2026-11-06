"""A missing or malformed form field or link reads like any other refusal, never as raw JSON."""

import pytest
from fastapi.exceptions import RequestValidationError

from photo_ledger import sources
from photo_ledger.db import open_db
from photo_ledger.web.errors import describe


@pytest.fixture
def conn(settings):
    connection = open_db(settings.db_path)
    yield connection
    connection.close()


def csrf(web):
    return {"csrf_token": web.cookies["gth_csrf"]}


def test_a_missing_field_is_named_on_the_notice_page(web, conn, tmp_path):
    response = web.post("/sources", data={"path": str(tmp_path), **csrf(web)})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "Fill in Label." in response.text
    assert '"detail"' not in response.text and "Field required" not in response.text
    assert sources.list_sources(conn) == []


def test_an_htmx_form_goes_back_with_the_reason_as_a_toast(web, tmp_path):
    response = web.post(
        "/sources",
        data={"path": str(tmp_path), **csrf(web)},
        headers={"HX-Request": "true", "Referer": "https://127.0.0.1/sources"},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/sources"
    assert "Fill in Label." in web.get("/sources").text  # the toast, on the next page


def test_a_number_field_says_it_needs_a_number(web, conn, tmp_path):
    sources.add_source(conn, tmp_path, "usb")
    source_id = sources.get_source(conn, "usb")["id"]
    response = web.post(
        f"/sources/{source_id}/priority", data={"priority": "<b>high</b>", **csrf(web)}
    )
    assert response.status_code == 422
    assert "Keeper priority must be a whole number." in response.text
    assert "<b>high</b>" not in response.text and "&lt;b&gt;high" not in response.text
    assert sources.get_source(conn, "usb")["priority"] == 0


def test_a_bad_link_id_is_a_bad_link(web):
    response = web.post("/sources/abc/check", data=csrf(web))
    assert response.status_code == 422
    assert "That link isn&#39;t valid." in response.text


def test_several_problems_are_each_named_once():
    exc = RequestValidationError(
        [
            {"type": "missing", "loc": ("body", "label")},
            {"type": "missing", "loc": ("body", "path")},
            {"type": "missing", "loc": ("body", "label")},
            {"type": "string_too_long", "loc": ("body", "generic_folders")},
        ]
    )
    assert describe(exc) == "Fill in Label. Fill in Folder. Generic folders isn't valid."


def test_required_fields_are_checked_by_the_browser_first(web):
    page = web.get("/sources").text
    assert 'id="map-path" name="path"' in page
    for field_id in ("map-path", "gth-field-label"):
        tag = page.split(f'id="{field_id}"', 1)[1].split(">", 1)[0]
        assert 'required="required"' in tag, field_id
    library = web.get("/library").text
    tag = library.split('id="library-path"', 1)[1].split(">", 1)[0]
    assert 'required="required"' in tag
