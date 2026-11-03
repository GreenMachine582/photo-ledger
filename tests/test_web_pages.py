"""The overview, collections and reports pages."""

import pytest
from review_helpers import exact_pair, file_id, keep
from test_scanner import snapshot

from photo_ledger.collections import editing
from photo_ledger.collections.folders import (
    collection_paths,
    collections_for_content,
    refresh_collections,
)
from photo_ledger.review.decisions import decide
from photo_ledger.review.overview import overview


def csrf(client):
    return client.cookies["gth_csrf"]


def collection_id(conn, path):
    return {p: i for i, p in collection_paths(conn).items()}[path]


def test_overview_without_sources(settings, web):
    page = web.get("/")
    assert page.status_code == 200
    assert "No sources mapped yet" in page.text


def test_overview_numbers(ledger, web):
    conn, _, _ = ledger
    page = web.get("/").text
    for label in ("Files", "Unique photos", "Duplicated space", "Open pairs", "Decided"):
        assert label in page
    assert "camera" in page and "backup" in page
    assert 'href="/review?scan=all"' in page
    pair = exact_pair(conn, "camera/2019/IMG_0001.jpg", "backup/Holiday 2019/IMG_0001.jpg")
    decide(conn, pair["id"], keep(pair, file_id(conn, "camera/2019/IMG_0001.jpg")))
    data = overview(conn)
    assert data.pairs["resolved"] == 1
    size = conn.execute("SELECT size_bytes FROM files WHERE id = ?", (pair["right_id"],))
    assert data.marked_bytes == size.fetchone()[0]
    assert data.reclaimable_bytes > data.marked_bytes


def test_collections_page_lists_and_edits(ledger, web):
    conn, root, _ = ledger
    before = snapshot(root)
    page = web.get("/collections").text
    assert "Holidays/2019/Japan" in page
    japan = collection_id(conn, "Holidays/2019/Japan")

    assert (
        web.post(
            "/collections/rename", data={"collection": japan, "name": "Japan trip"}
        ).status_code
        == 403
    )
    renamed = web.post(
        "/collections/rename",
        data={"collection": japan, "name": "Japan trip", "csrf_token": csrf(web)},
    )
    assert "Renamed." in renamed.text
    assert "Holidays/2019/Japan trip" in renamed.text

    hidden = web.post(
        f"/collections/{japan}/hidden", data={"hidden": "true", "csrf_token": csrf(web)}
    )
    assert "Hidden." in hidden.text
    assert conn.execute("SELECT hidden FROM collections WHERE id = ?", (japan,)).fetchone()[0] == 1
    assert snapshot(root) == before  # no folder was renamed


def test_rename_refuses_a_clash(ledger, web):
    conn, _, _ = ledger
    response = web.post(
        "/collections/rename",
        data={"collection": collection_id(conn, "2019"), "name": "2020", "csrf_token": csrf(web)},
    )
    assert response.status_code == 409
    assert "Merge into it instead" in response.text


def test_merge_moves_folders_and_children(ledger, web):
    conn, _, _ = ledger
    content = conn.execute(
        "SELECT content_id FROM files WHERE rel_path = 'Best of 2019/IMG_0412 (1).jpg'"
    ).fetchone()[0]
    response = web.post(
        "/collections/merge",
        data={
            "source": collection_id(conn, "Best of 2019"),
            "target": collection_id(conn, "Holidays/2019/Japan"),
            "csrf_token": csrf(web),
        },
    )
    assert "Merged" in response.text
    assert "Best of 2019" not in set(collection_paths(conn).values())
    assert collections_for_content(conn, content) == ["Holidays/2019/Japan"]
    # A rescan's refresh doesn't bring the merged collection back.
    assert refresh_collections(conn).new_collections == 0


def test_merge_combines_same_named_children(ledger):
    conn, _, _ = ledger
    conn.execute("INSERT INTO collections (name, created_at) VALUES ('Trips', 'now')")
    trips = conn.execute("SELECT id FROM collections WHERE name = 'Trips'").fetchone()[0]
    conn.execute(
        "INSERT INTO collections (name, parent_id, created_at) VALUES ('2019', ?, 'now')", (trips,)
    )
    conn.commit()
    editing.merge(conn, collection_id(conn, "Holidays"), trips)
    paths = set(collection_paths(conn).values())
    assert "Trips/2019/Japan" in paths and "Holidays" not in paths


@pytest.mark.parametrize(
    ("source", "target", "message"),
    [("Holidays", "Holidays", "into itself"), ("Holidays", "Holidays/2019", "own sub")],
)
def test_merge_refusals(ledger, source, target, message):
    conn, _, _ = ledger
    with pytest.raises(editing.CollectionError, match=message):
        editing.merge(conn, collection_id(conn, source), collection_id(conn, target))


def test_report_pages_and_csv(ledger, web):
    index = web.get("/reports")
    assert index.status_code == 200
    for name in ("summary", "pairs", "renamed", "dates", "single-source", "corrupt", "collections"):
        page = web.get(f"/reports/{name}?scan=all")
        assert page.status_code == 200, name
        download = web.get(f"/reports/{name}.csv")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
    assert "restored/IMG_0003.jpg" in web.get("/reports/dates").text
    assert web.get("/reports/nope").status_code == 404


def test_nav_links(ledger, web):
    page = web.get("/").text
    for url in ("/review", "/collections", "/reports"):
        assert f'href="{url}"' in page
