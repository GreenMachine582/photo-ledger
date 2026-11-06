"""The folder explorer in the browser: names only, read-only, and only for this app's own pages."""

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import open_db

HTMX = {"HX-Request": "true", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def drive(tmp_path):
    root = tmp_path / "drive"
    for name in ("Photos/2019", "Archive"):
        (root / name).mkdir(parents=True)
    (root / "Photos" / "IMG_0001.jpg").write_bytes(b"not really a jpeg")
    (root / "secret-plans.txt").write_text("never listed")
    return root


def listing(web, **params):
    return web.get("/folders", params={"tree": "map-path-tree", **params}, headers=HTMX)


def test_lists_folder_names_and_never_files(web, drive):
    before = snapshot(drive)
    response = listing(web, parent=str(drive), level=2)
    assert response.status_code == 200
    page = response.text
    assert 'data-label="Photos"' in page and 'data-label="Archive"' in page
    assert 'aria-level="2"' in page
    assert "secret-plans" not in page and "IMG_0001" not in page
    # Photos has a subfolder, so it expands lazily from the same tree.
    assert "/folders?tree=map-path-tree&amp;parent=" in page
    assert snapshot(drive) == before


def test_roots_load_when_browsing_starts(web):
    response = listing(web)
    assert response.status_code == 200
    assert 'role="treeitem"' in response.text


def test_an_empty_or_unreadable_folder_says_so(web, drive, tmp_path):
    assert "No folders inside." in listing(web, parent=str(drive / "Archive")).text
    missing = listing(web, parent=str(tmp_path / "unplugged")).text
    assert "connected, or" in missing and 'role="treeitem"' not in missing
    relative = listing(web, parent="Photos").text
    assert "Pick a folder from the list." in relative


def test_mapped_folders_are_marked(web, settings, drive):
    conn = open_db(settings.db_path)
    try:
        sources.add_source(conn, drive / "Photos", "usb")
    finally:
        conn.close()
    assert "source usb" in listing(web, parent=str(drive)).text


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin"},
        {"HX-Request": "true", "Sec-Fetch-Site": "cross-site"},
        {"HX-Request": "true", "Sec-Fetch-Site": "same-site"},
    ],
)
def test_only_this_apps_pages_can_list_folders(web, drive, headers):
    response = web.get("/folders", params={"tree": "t", "parent": str(drive)}, headers=headers)
    assert response.status_code == 403
    assert "Photos" not in response.text


def test_a_foreign_host_is_refused(web, drive):
    response = web.get(
        "/folders",
        params={"tree": "t", "parent": str(drive)},
        headers={**HTMX, "Host": "attacker.example"},
    )
    assert response.status_code == 400
    assert "Photos" not in response.text


def test_a_bad_tree_id_is_refused(web, drive):
    response = web.get(
        "/folders", params={"tree": '"><script>', "parent": str(drive)}, headers=HTMX
    )
    assert response.status_code == 400


def test_folder_fields_offer_the_explorer(web):
    sources_page = web.get("/sources").text
    assert "Browse folders" in sources_page
    assert 'hx-get="/folders?tree=map-path-tree"' in sources_page
    assert "/static/folder-picker.js" in sources_page
    library_page = web.get("/library").text
    assert 'hx-get="/folders?tree=library-path-tree"' in library_page
    assert web.get("/static/folder-picker.js").status_code == 200


def test_a_picked_folder_maps_as_a_source(web, settings, drive):
    # The tree hands the field the folder's path, and the extra "-picked" field is ignored.
    picked = str(drive / "Photos")
    response = web.post(
        "/sources",
        data={
            "path": picked,
            "map-path-picked": picked,
            "label": "usb",
            "csrf_token": web.cookies["gth_csrf"],
        },
    )
    assert response.status_code in (200, 303)
    conn = open_db(settings.db_path)
    try:
        assert sources.get_source(conn, "usb")["root_path"] == str(drive.resolve() / "Photos")
    finally:
        conn.close()
