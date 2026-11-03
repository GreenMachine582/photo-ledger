"""The comparison screen and the image routes."""

import re

from review_helpers import exact_pair, file_id, status
from test_scanner import snapshot

from photo_ledger import thumbnails
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
