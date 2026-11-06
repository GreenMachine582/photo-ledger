"""Notifications and the Activity page for scans, plans, builds and offline sources, no sign-in."""

import pytest
from pydantic import ValidationError
from test_executor import ready  # noqa: F401  (a fixture)
from test_library import settle_everything
from test_scanner import snapshot
from test_web_scans import scan_id, wait_until_stopped

from photo_ledger import sources
from photo_ledger.activity import LOCAL_USER
from photo_ledger.config import Settings
from photo_ledger.db import open_db
from photo_ledger.db.activity import SqliteAuditStore, SqliteNotificationStore
from photo_ledger.scanner import jobs as scan_jobs


def post(client, url, **data):
    return client.post(url, data={**data, "csrf_token": client.cookies["gth_csrf"]})


@pytest.fixture
def conn(settings):
    connection = open_db(settings.db_path)
    yield connection
    connection.close()


def actions(settings):
    return [e.action for e in SqliteAuditStore(settings.db_path).entries_sync()]


def notices(settings):
    return SqliteNotificationStore(settings.db_path).list_for_sync(LOCAL_USER)


def test_pages_work_without_signing_in(web):
    for url in ("/activity", "/notifications", "/notifications/panel"):
        response = web.get(url, follow_redirects=False)
        assert response.status_code == 200, url
    assert 'href="/activity"' in web.get("/").text
    assert 'href="/notifications"' in web.get("/").text


def test_the_app_only_runs_as_its_single_user(monkeypatch):
    monkeypatch.setenv("AUTH_ADAPTER", "local")
    with pytest.raises(ValidationError):
        Settings()


def test_a_finished_scan_is_logged_and_notified(app_client, settings, conn, mapped):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)
    post(app_client, f"/scans/{sid}/run")
    wait_until_stopped(app_client, sid)

    assert actions(settings) == ["scan.completed"]
    [note] = notices(settings)
    assert note.message.startswith("Scan 'all' complete:") and note.read_at is None
    assert note.action_url == "/"
    assert "Scan &#39;all&#39; complete" in app_client.get("/activity").text
    assert "1" in app_client.get("/notifications/badge").text


def test_a_scan_paused_by_an_offline_source_says_so(app_client, settings, conn, mapped):
    root, manifest = mapped
    label = next(iter(manifest["sources"]))
    post(app_client, "/scans", name="one", sources=[label])
    sid = scan_id(conn, "one")
    (root / label).rename(root / f"{label}-unplugged")
    post(app_client, f"/scans/{sid}/run")
    wait_until_stopped(app_client, sid)

    [entry] = SqliteAuditStore(settings.db_path).entries_sync()
    assert entry.action == "scan.paused"
    assert entry.details == {"offline": [label]}
    assert "Nothing was marked missing" in entry.summary
    assert notices(settings)[0].kind == "warning"


def test_a_failed_scan_is_logged(app_client, settings, conn, mapped, monkeypatch):
    _root, manifest = mapped
    post(app_client, "/scans", name="all", sources=list(manifest["sources"]))
    sid = scan_id(conn)

    def broken(*_args, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(scan_jobs.engine, "run_scan", broken)
    post(app_client, f"/scans/{sid}/run")
    card = wait_until_stopped(app_client, sid)
    assert "disk on fire" in card
    assert actions(settings) == ["scan.failed"]
    assert notices(settings)[0].kind == "danger"


def test_applying_and_undoing_a_plan_are_logged(ready, web, settings):  # noqa: F811
    post(web, "/plan/apply")
    post(web, "/plan/undo")
    assert actions(settings) == ["plan.undone", "plan.applied"]  # newest first
    applied = SqliteAuditStore(settings.db_path).entries_sync(action="plan.applied")[0]
    assert applied.details == {"done": 3, "failed": 0}
    assert [n.kind for n in notices(settings)] == ["success", "success"]


def test_building_the_library_is_logged(ledger, web, settings):
    conn, root, _ = ledger
    folder = root.parent / "library"
    folder.mkdir()
    post(web, "/library", path=str(folder), layout="year")
    settle_everything(conn)
    before = snapshot(root)
    post(web, "/library/build")
    [entry] = SqliteAuditStore(settings.db_path).entries_sync()
    assert entry.action == "library.built"
    assert entry.summary.startswith("Library built:")
    assert str(folder) not in entry.summary  # counts and labels, never paths
    assert snapshot(root) == before


def test_a_source_going_offline_is_logged_once(web, settings, conn, tmp_path):
    folder = tmp_path / "usb"
    folder.mkdir()
    sources.add_source(conn, folder, "usb")
    source_id = sources.get_source(conn, "usb")["id"]
    post(web, f"/sources/{source_id}/check")
    assert actions(settings) == []  # still online: nothing to say

    folder.rename(tmp_path / "usb-unplugged")
    post(web, f"/sources/{source_id}/check")
    post(web, "/sources/check")  # still offline: not logged again
    assert actions(settings) == ["source.offline"]
    assert notices(settings)[0].message == (
        "Source 'usb' is offline. Nothing in it was marked missing."
    )


def test_marking_notices_read_needs_the_csrf_token(web, settings):
    from photo_ledger import activity

    activity.record(settings.db_path, "scan.completed", "Scan 'x' complete: 1 files listed.")
    [note] = notices(settings)
    assert web.post(f"/notifications/{note.id}/read").status_code == 403
    assert web.post("/notifications/read-all").status_code == 403
    assert notices(settings)[0].read_at is None

    assert post(web, "/notifications/read-all").status_code < 400
    assert notices(settings)[0].read_at is not None


def test_recording_never_breaks_the_action(settings, monkeypatch):
    from photo_ledger import activity

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(activity.SqliteAuditStore, "record_sync", broken)
    activity.record(settings.db_path, "scan.completed", "Scan 'x' complete.")  # doesn't raise
    assert notices(settings) == []  # nothing half-recorded either
