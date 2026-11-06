"""Scans in the browser: create, run, pause, resume, live progress, errors and offline sources."""

import asyncio
import threading
import time

import pytest
from greentechhub_core.background import InMemoryJobStore, JobRunner
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import now_ns, open_db
from photo_ledger.db import scans as scan_queries
from photo_ledger.scanner import engine
from photo_ledger.scanner import jobs as scan_jobs

HTMX = {"HX-Request": "true"}


@pytest.fixture
def conn(settings):
    connection = open_db(settings.db_path)
    yield connection
    connection.close()


def post(client, url, **data):
    return client.post(url, data={**data, "csrf_token": client.cookies["gth_csrf"]})


def scan_id(conn, name="all"):
    return scan_queries.by_name(conn, name)["id"]


def wait_until_stopped(client, sid, timeout=60):
    """Poll the card the way the page does, until the answer that stops the poll."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/scans/{sid}/progress", headers=HTMX)
        if response.status_code == 286:
            return response.text
        assert response.status_code == 200
        time.sleep(0.05)
    raise AssertionError("the scan never stopped")


def missing_count(conn):
    return conn.execute("SELECT COUNT(*) FROM files WHERE status = 'missing'").fetchone()[0]


def test_create_and_run_a_scan_to_the_end(app_client, conn, mapped):
    root, manifest = mapped
    before = snapshot(root)
    created = post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    assert created.status_code == 200 and "Scan saved" in created.text
    sid = scan_id(conn)

    started = post(app_client, f"/scans/{sid}/run")
    assert started.status_code == 200 and "Scan started" in started.text
    card = wait_until_stopped(app_client, sid)

    assert engine.get_scan(conn, "all")["status"] == "complete"
    assert "Run match on the Overview" in card
    assert 'hx-trigger="every 1s"' not in card  # the finished card doesn't poll
    files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert files > 0
    assert snapshot(root) == before  # scanning only reads
    assert "Find duplicates" in app_client.get("/").text  # the next step moves on to match


def test_a_running_scan_polls_and_pauses_without_marking_anything_missing(
    app_client, conn, mapped, monkeypatch
):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    real_run_scan = engine.run_scan
    waiting = threading.Event()

    def held_run_scan(conn, name, *, should_stop, **kwargs):
        # Hold the job open until Pause asks it to stop, then let the real engine stop at once.
        waiting.set()
        deadline = time.monotonic() + 30
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        return real_run_scan(conn, name, should_stop=should_stop, **kwargs)

    monkeypatch.setattr(scan_jobs.engine, "run_scan", held_run_scan)
    post(app_client, f"/scans/{sid}/run")
    assert waiting.wait(10)

    running = app_client.get(f"/scans/{sid}/progress", headers=HTMX)
    assert running.status_code == 200
    assert 'hx-trigger="every 1s"' in running.text and ">Pause<" in running.text
    again = post(app_client, f"/scans/{sid}/run")
    assert "already running" in again.text

    paused = post(app_client, f"/scans/{sid}/pause")
    assert "Pausing after the current file" in paused.text
    card = wait_until_stopped(app_client, sid)
    assert engine.get_scan(conn, "all")["status"] == "paused"
    assert ">Resume<" in card
    assert missing_count(conn) == 0

    monkeypatch.setattr(scan_jobs.engine, "run_scan", real_run_scan)
    post(app_client, f"/scans/{sid}/run")
    wait_until_stopped(app_client, sid)
    assert engine.get_scan(conn, "all")["status"] == "complete"
    assert missing_count(conn) == 0


def test_pausing_a_scan_that_isnt_running_says_so(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    response = post(app_client, f"/scans/{scan_id(conn)}/pause")
    assert "That scan isn&#39;t running" in response.text


def test_an_offline_source_pauses_and_marks_nothing_missing(app_client, conn, mapped):
    root, manifest = mapped
    label = next(iter(manifest["sources"]))
    post(app_client, "/scans", name="one", sources=[label])
    sid = scan_id(conn, "one")
    post(app_client, f"/scans/{sid}/run")
    wait_until_stopped(app_client, sid)
    catalogued = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    (root / label).rename(root / f"{label}-unplugged")
    post(app_client, f"/scans/{sid}/run")
    card = wait_until_stopped(app_client, sid)
    assert f"Offline: {label}" in card
    assert engine.get_scan(conn, "one")["status"] == "paused"
    assert missing_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == catalogued


def test_errors_show_on_the_card(app_client, conn, tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "IMG_0001.jpg").write_bytes(b"not really a jpeg")
    sources.add_source(conn, folder, "broken")
    post(app_client, "/scans", name="broken", sources=["broken"])
    sid = scan_id(conn, "broken")
    post(app_client, f"/scans/{sid}/run")
    card = wait_until_stopped(app_client, sid)
    assert "Recent errors" in card and "broken/IMG_0001.jpg" in card


def test_a_source_in_another_live_scan_is_refused(app_client, conn, mapped):
    _root, manifest = mapped
    labels = list(manifest["sources"])
    post(app_client, "/scans", name="first", sources=labels)
    post(app_client, "/scans", name="second", sources=labels[:1])
    first = scan_id(conn, "first")
    source_id = sources.get_source(conn, labels[0])["id"]
    with conn:  # as if the CLI were scanning it right now
        scan_queries.update_scan_source(
            conn, first, source_id, status="running", heartbeat_at=now_ns()
        )
    response = post(app_client, f"/scans/{scan_id(conn, 'second')}/run")
    assert response.status_code == 409
    assert "Already being scanned" in response.text


def test_a_scan_needs_a_source(app_client, conn, mapped):
    response = post(app_client, "/scans", name="empty")
    assert "Choose at least one source" in response.text
    assert scan_queries.by_name(conn, "empty") is None


def test_every_new_action_needs_a_csrf_token(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    for url in ("/scans", f"/scans/{sid}/run", f"/scans/{sid}/pause"):
        assert app_client.post(url, data={"name": "x", "sources": "a"}).status_code == 403
    assert engine.get_scan(conn, "all")["status"] == "new"


def test_the_page_without_sources_points_to_mapping(app_client):
    page = app_client.get("/scans").text
    assert "Map a folder or drive before scanning it." in page
    assert "No scans yet." in page


def test_the_job_function_runs_a_scan_on_its_own_connection(settings, conn, mapped):
    _root, manifest = mapped
    engine.create_scan(conn, "all", list(manifest["sources"]))
    sid = scan_id(conn)

    async def run():
        runner = JobRunner(InMemoryJobStore())
        job = await runner.start(
            scan_jobs.job_kind(sid), scan_jobs.scan_job(settings.db_path, "all"), unique=True
        )
        return await runner.wait(job.id, timeout=60)

    job = asyncio.run(run())
    assert job.state == "succeeded"
    assert job.result["status"] == "complete"
    assert {s["label"] for s in job.result["sources"]} == set(manifest["sources"])


def test_save_and_scan_starts_it_on_its_own_page(app_client, conn, mapped):
    _root, manifest = mapped
    response = post(app_client, "/scans", name="all", sources=list(manifest["sources"]), run="true")
    sid = scan_id(conn)
    assert str(response.url).endswith(f"/scans/{sid}")
    assert "Scan started" in response.text
    wait_until_stopped(app_client, sid)
    assert engine.get_scan(conn, "all")["status"] == "complete"
    page = app_client.get(f"/scans/{sid}").text
    assert "Done" in page and "Review this scan" in page and ">Scan again<" in page


def test_a_scan_not_run_yet_says_so_and_offers_to_run(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    page = app_client.get(f"/scans/{scan_id(conn)}").text
    assert "Not run yet." in page and ">Run scan<" in page
    assert "pending" not in page and ">walk<" not in page


def test_the_list_opens_each_scan_and_offers_its_actions(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    page = app_client.get("/scans").text
    assert f'href="/scans/{sid}" class="stretched-link' in page
    assert ">Open<" in page and ">Run scan<" in page and "not run yet" in page
    assert 'hx-trigger="every 1s"' not in page  # nothing running, so no polling
    assert app_client.get("/scans/rows", headers=HTMX).status_code == 286


def test_hashing_shows_how_far_it_has_got(app_client, conn, mapped):
    from photo_ledger.web.routes.scans import scan_card

    _root, manifest = mapped
    label = next(iter(manifest["sources"]))
    post(app_client, "/scans", name="one", sources=[label])
    sid = scan_id(conn, "one")
    post(app_client, f"/scans/{sid}/run")
    wait_until_stopped(app_client, sid)
    source_id = sources.get_source(conn, label)["id"]
    files = conn.execute("SELECT id FROM files WHERE source_id = ?", (source_id,)).fetchall()
    with conn:
        conn.execute("UPDATE files SET pending_hash = 1 WHERE id = ?", (files[0]["id"],))
        scan_queries.update_scan_source(conn, sid, source_id, status="running", stage="hash")
    [row] = scan_card(conn, scan_queries.by_id(conn, sid), None)["sources"]
    assert row["state_text"] == "Hashing"
    assert row["fraction"] == pytest.approx((len(files) - 1) / len(files))
    with conn:
        scan_queries.update_scan_source(conn, sid, source_id, stage="walk")
    [row] = scan_card(conn, scan_queries.by_id(conn, sid), None)["sources"]
    assert row["state_text"] == "Listing files" and row["fraction"] is None


def test_an_interrupted_scan_and_one_running_elsewhere_are_told_apart(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    source_id = sources.get_source(conn, next(iter(manifest["sources"])))["id"]
    with conn:
        scan_queries.set_status(conn, sid, "running")
        scan_queries.update_scan_source(conn, sid, source_id, status="running", heartbeat_at=1)
    assert "This scan was interrupted" in app_client.get(f"/scans/{sid}").text
    with conn:
        scan_queries.update_scan_source(conn, sid, source_id, heartbeat_at=now_ns())
    page = app_client.get(f"/scans/{sid}").text
    assert "running elsewhere" in page and "This scan was interrupted" not in page


def test_an_unknown_scan_is_a_notice(app_client):
    response = app_client.get("/scans/999")
    assert response.status_code == 409 and "There&#39;s no scan 999." in response.text


def test_actions_return_only_to_a_scans_page(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    listed = post(app_client, f"/scans/{sid}/pause", back="/scans")
    assert str(listed.url).endswith("/scans")
    offsite = post(app_client, f"/scans/{sid}/pause", back="https://example.com/")
    assert str(offsite.url).endswith(f"/scans/{sid}")


def test_removing_from_its_page_returns_to_the_list(app_client, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    response = post(app_client, f"/scans/{sid}/remove", back=f"/scans/{sid}")
    assert str(response.url).endswith("/scans") and "Scan removed" in response.text
    assert scan_queries.by_name(conn, "all") is None
