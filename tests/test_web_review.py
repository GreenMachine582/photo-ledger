"""The comparison screen and the image routes."""

import re
import threading

from plan_helpers import A_BACKUP, A_CAMERA
from review_helpers import exact_pair, file_id, status
from test_scanner import snapshot

from photo_ledger import thumbnails
from photo_ledger.db import open_db
from photo_ledger.review.queue import queue


def csrf(client):
    return client.cookies["gth_csrf"]


def test_review_shows_the_first_pair_side_by_side(ledger, web):
    conn, _, _ = ledger
    page = web.get("/review")
    assert page.status_code == 200
    first = queue(conn)[0]
    assert "Pair 1 of 8" in page.text
    pair = conn.execute("SELECT * FROM review_pairs WHERE id = ?", (first,)).fetchone()
    for side in ("left_id", "right_id"):
        assert f"/files/{pair[side]}/preview" in page.text
        assert f"/files/{pair[side]}/original" in page.text
    assert f'action="/review/{first}/decide"' in page.text
    for key in "ADBS":
        assert f'data-key="{key}"' in page.text
    assert "/static/review.js" in page.text
    assert "suggested" in page.text.lower()


def test_differing_details_are_highlighted(ledger, web):
    conn, _, _ = ledger
    similar = conn.execute("SELECT id FROM review_pairs WHERE kind = 'similar'").fetchone()[0]
    page = web.get(f"/review?pair={similar}").text
    assert re.search(r'class="pl-diff">\s*320 x 240', page) or re.search(
        r'class="pl-diff">\s*160 x 120', page
    )
    assert "higher resolution" in page


def test_a_decision_needs_the_csrf_token(ledger, web):
    conn, root, _ = ledger
    before = snapshot(root)
    first = queue(conn)[0]
    refused = web.post(f"/review/{first}/decide", data={"action": "keep_left"})
    assert refused.status_code == 403
    assert status(conn, first) == "open"

    done = web.post(
        f"/review/{first}/decide",
        data={"action": "keep_left", "csrf_token": csrf(web)},
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"].startswith("/review")
    assert status(conn, first) == "resolved"
    assert first not in queue(conn)
    assert snapshot(root) == before


def test_a_refused_decision_explains_itself(ledger, web):
    conn, _, _ = ledger
    pair = queue(conn)[0]
    conn.execute("UPDATE review_pairs SET status = 'obsolete' WHERE id = ?", (pair,))
    conn.commit()
    response = web.post(f"/review/{pair}/decide", data={"action": "skip", "csrf_token": csrf(web)})
    assert response.status_code == 409
    assert "no longer matches" in response.text


def test_the_empty_state_when_everything_is_decided(ledger, web):
    conn, _, _ = ledger
    for pair in queue(conn):
        web.post(f"/review/{pair}/decide", data={"action": "keep_both", "csrf_token": csrf(web)})
    assert "Nothing left to review" in web.get("/review").text


def test_the_original_is_served_by_id_only(ledger, web):
    conn, root, _ = ledger
    path = "camera/2019/IMG_0001.jpg"
    response = web.get(f"/files/{file_id(conn, path)}/original")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == (root / path).read_bytes()
    assert web.get("/files/99999/original").status_code == 404
    assert web.get("/files/../../etc/passwd/original").status_code == 404
    routes = {getattr(route, "path", "") for route in web.app.routes}
    assert not any("{path" in route for route in routes)


def test_unsupported_files_are_not_served(ledger, web):
    conn, _, _ = ledger
    assert web.get(f"/files/{file_id(conn, 'camera/notes.txt')}/original").status_code == 404


def test_both_sides_of_an_exact_pair_get_their_shared_preview(ledger, settings, tmp_path):
    """Both copies have the same content, so the browser asks for the same cached preview twice
    at once. Neither request may lose the race."""
    conn, _, _ = ledger
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)
    for round_ in range(20):
        cache_dir = tmp_path / f"cache-{round_}"
        start = threading.Barrier(2)
        results = {}

        def load(side):
            own = open_db(settings.db_path)
            try:
                start.wait()
                results[side] = thumbnails.preview(own, pair[side], cache_dir)
            finally:
                own.close()

        threads = [threading.Thread(target=load, args=(side,)) for side in ("left_id", "right_id")]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        assert results["left_id"] is not None and results["right_id"] is not None, round_
        assert results["left_id"] == results["right_id"]
        assert [p.name for p in cache_dir.rglob("*") if p.is_file()] == [results["left_id"].name]


def test_a_preview_another_request_just_made_is_used(ledger, settings, monkeypatch):
    """On Windows, replacing a preview another request is still sending fails: use theirs."""
    conn, _, _ = ledger
    target = file_id(conn, "camera/2019/IMG_0001.jpg")
    cache_dir = settings.thumbnail_dir
    original_replace = type(cache_dir).replace

    def busy(self, target_path):
        original_replace(self, target_path)  # the other request's copy lands first
        raise PermissionError("in use")

    monkeypatch.setattr(type(cache_dir), "replace", busy)
    made = thumbnails.preview(conn, target, cache_dir)
    assert made is not None and made.is_file()
    assert [p for p in cache_dir.rglob("*") if p.is_file()] == [made]


def test_previews_are_cached_and_outlive_an_offline_source(ledger, web, settings):
    conn, root, _ = ledger
    before = snapshot(root)
    target = file_id(conn, "camera/2019/IMG_0001.jpg")
    response = web.get(f"/files/{target}/preview")
    assert response.status_code == 200
    assert response.content[:2] == b"\xff\xd8"
    cached = list(settings.thumbnail_dir.rglob("*.jpg"))
    assert len(cached) == 1
    assert snapshot(root) == before

    (root / "camera").rename(root / "unplugged")
    assert web.get(f"/files/{target}/original").status_code == 404
    assert web.get(f"/files/{target}/preview").status_code == 200
    other = file_id(conn, "camera/2020/IMG_0001.jpg")
    assert web.get(f"/files/{other}/preview").status_code == 404  # never cached


def test_previews_refuse_a_cache_inside_a_source(ledger):
    conn, root, _ = ledger
    target = file_id(conn, "camera/2019/IMG_0001.jpg")
    try:
        thumbnails.preview(conn, target, root / "camera" / ".cache")
    except Exception as exc:  # noqa: BLE001
        assert "never write to a source" in str(exc)
    else:
        raise AssertionError("expected a refusal")
    assert not (root / "camera" / ".cache").exists()


def test_review_links_from_the_nav(ledger, web):
    assert 'href="/review"' in web.get("/").text


def test_exact_pair_lookup_helper(ledger):
    conn, _, _ = ledger
    assert exact_pair(conn, "camera/2019/IMG_0001.jpg", "backup/Holiday 2019/IMG_0001.jpg")


def test_a_session_keeps_its_filters(ledger, web):
    conn, _, _ = ledger
    page = web.get("/review?scan=all&kind=similar")
    assert "Pair 1 of 2" in page.text
    first = queue(conn)[5]  # the first similar pair
    assert f'action="/review/{first}/decide?scan=all&amp;kind=similar"' in page.text
    done = web.post(
        f"/review/{first}/decide?scan=all&kind=similar",
        data={"action": "skip", "csrf_token": csrf(web)},
        follow_redirects=False,
    )
    assert done.headers["location"] == "/review?scan=all&kind=similar"
    skipped = web.get("/review?show=skipped").text
    assert "Pair 1 of 1" in skipped
    assert "Skipped (1)" in skipped


def test_undo_returns_to_the_pair(ledger, web):
    conn, _, _ = ledger
    first = queue(conn)[0]
    assert 'data-key="Z"' not in web.get("/review").text  # nothing to undo yet
    web.post(f"/review/{first}/decide", data={"action": "keep_left", "csrf_token": csrf(web)})
    assert 'data-key="Z"' in web.get("/review").text
    assert web.post("/review/undo").status_code == 403
    undone = web.post(
        "/review/undo?kind=exact", data={"csrf_token": csrf(web)}, follow_redirects=False
    )
    assert undone.headers["location"] == f"/review?kind=exact&pair={first}"
    assert status(conn, first) == "open"
    assert "Pair 1 of 5" in web.get(undone.headers["location"]).text


def test_an_unknown_scan_is_explained(ledger, web):
    response = web.get("/review?scan=nope")
    assert response.status_code == 409
    assert "no scan called" in response.text
