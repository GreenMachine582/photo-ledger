"""Scans in the browser: create, run, pause, resume, live progress, errors and offline sources."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from greentechhub_core.background import InMemoryJobStore, JobRunner
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.db import now_ns, open_db
from photo_ledger.db import scans as scan_queries
from photo_ledger.scanner import engine
from photo_ledger.scanner import jobs as scan_jobs
from photo_ledger.web.app import create_app

HTMX = {"HX-Request": "true"}


@pytest.fixture
def app_client(settings):
    """A client inside its lifespan, so its event loop (and the scan jobs on it) keeps running."""
    with TestClient(create_app(settings), base_url="https://127.0.0.1") as client:
        client.get("/")
        yield client


@pytest.fixture
def conn(settings):
    connection = open_db(settings.db_path)
    yield connection
    connection.close()


@pytest.fixture
def mapped(conn, fixture_tree):
    root, manifest = fixture_tree
    for label in manifest["sources"]:
        sources.add_source(conn, root / label, label)
    return root, manifest


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
