"""The sources page: mapping, checking, reconnecting, priority and quarantine from the browser."""

import pytest
from test_scanner import snapshot
from test_sources import fake_volume  # noqa: F401  (a fixture)

from photo_ledger import sources
from photo_ledger.db import open_db


def csrf(client):
    return client.cookies["gth_csrf"]


@pytest.fixture
def conn(settings):
    connection = open_db(settings.db_path)
    yield connection
    connection.close()


@pytest.fixture
def folders(tmp_path):
    for name in ("usb", "usb-moved", "q", "other"):
        (tmp_path / name).mkdir()
    (tmp_path / "usb" / "IMG_0001.jpg").write_bytes(b"not really a jpeg")
    return tmp_path


def post(web, url, **data):
    return web.post(url, data={**data, "csrf_token": csrf(web)})


def source(conn, label="usb"):
    return sources.get_source(conn, label)


def test_every_action_needs_a_csrf_token(web, conn, folders):
    sources.add_source(conn, folders / "usb", "usb")
    source_id = source(conn)["id"]
    for url in (
        "/sources",
        "/sources/check",
        f"/sources/{source_id}/check",
        f"/sources/{source_id}/reconnect",
        f"/sources/{source_id}/priority",
        f"/sources/{source_id}/quarantine",
        f"/sources/{source_id}/rename",
        f"/sources/{source_id}/forget",
    ):
        data = {"path": str(folders), "label": "x", "priority": 1, "confirm": "usb"}
        assert web.post(url, data=data).status_code == 403
    assert [row["label"] for row in sources.list_sources(conn)] == ["usb"]


def test_map_list_and_refuse_an_overlap(web, conn, folders):
    before = snapshot(folders / "usb")
    page = web.get("/sources").text
    assert "No sources yet" in page
    added = post(web, "/sources", path=str(folders / "usb"), label="usb")
    assert "Mapped." in added.text
    assert "usb" in added.text and str((folders / "usb").resolve()) in added.text
    assert "Sources" in web.get("/").text and 'href="/sources"' in web.get("/").text

    refused = post(web, "/sources", path=str(folders), label="everything")
    assert refused.status_code == 409
    assert "overlaps" in refused.text
    bad_label = post(web, "/sources", path=str(folders / "other"), label="a,b")
    assert bad_label.status_code == 409
    assert snapshot(folders / "usb") == before


def test_check_marks_a_moved_folder_offline_and_reconnect_finds_it(
    web,
    conn,
    folders,
    fake_volume,  # noqa: F811
):
    sources.add_source(conn, folders / "usb", "usb")
    source_id = source(conn)["id"]
    assert "Connected" in post(web, f"/sources/{source_id}/check").text

    (folders / "usb").rename(folders / "usb-gone")
    checked = post(web, f"/sources/{source_id}/check")
    assert "Not connected" in checked.text
    assert source(conn)["state"] == "offline"

    # The drive comes back at another letter: an empty Reconnect finds it by its volume.
    conn.execute("UPDATE sources SET volume_root = ? WHERE id = ?", (str(folders), source_id))
    conn.commit()
    (folders / "moved").mkdir()
    (folders / "usb-gone").rename(folders / "moved" / "usb")
    fake_volume["mounted"] = [(str(folders / "moved"), "AAAA-0001")]
    assert "offline" in web.get("/sources").text

    reconnected = post(web, f"/sources/{source_id}/reconnect", path="")
    assert "Reconnected" in reconnected.text
    assert source(conn)["root_path"] == str((folders / "moved" / "usb").resolve())
    assert source(conn)["state"] == "online"


def test_reconnect_to_a_typed_path_and_refuse_another_drive(
    web,
    conn,
    folders,
    fake_volume,  # noqa: F811
):
    sources.add_source(conn, folders / "usb", "usb")
    source_id = source(conn)["id"]
    moved = post(web, f"/sources/{source_id}/reconnect", path=str(folders / "usb-moved"))
    assert "Reconnected" in moved.text
    fake_volume["id"] = "BBBB-0002"
    refused = post(web, f"/sources/{source_id}/reconnect", path=str(folders / "other"))
    assert refused.status_code == 409
    assert "different drive" in refused.text


def test_check_all(web, conn, folders):
    sources.add_source(conn, folders / "usb", "usb")
    sources.add_source(conn, folders / "other", "other")
    (folders / "other").rename(folders / "other-gone")
    assert "Checked every source" in post(web, "/sources/check").text
    assert source(conn, "usb")["state"] == "online"
    assert source(conn, "other")["state"] == "offline"


def test_priority_and_quarantine(web, conn, folders):
    before = snapshot(folders / "usb")
    sources.add_source(conn, folders / "usb", "usb")
    source_id = source(conn)["id"]
    assert "Priority saved" in post(web, f"/sources/{source_id}/priority", priority=5).text
    assert source(conn)["priority"] == 5

    on = post(web, f"/sources/{source_id}/quarantine", path=str(folders / "q"))
    assert "Quarantine is on" in on.text
    assert source(conn)["quarantine_path"] == str((folders / "q").resolve())
    inside = post(web, f"/sources/{source_id}/quarantine", path=str(folders / "usb"))
    assert inside.status_code == 409
    empty = post(web, f"/sources/{source_id}/quarantine", path="")
    assert empty.status_code == 409

    off = post(web, f"/sources/{source_id}/quarantine", off="true")
    assert "Quarantine is off" in off.text
    assert source(conn)["quarantine_enabled"] == 0
    assert list((folders / "q").iterdir()) == []
    assert snapshot(folders / "usb") == before


def test_an_unknown_source_is_refused(web):
    assert post(web, "/sources/999/check").status_code == 409


def test_rename_and_forget(web, conn, folders):
    before = snapshot(folders / "usb")
    sources.add_source(conn, folders / "usb", "usb")
    sources.add_source(conn, folders / "other", "other")
    source_id = source(conn)["id"]

    renamed = post(web, f"/sources/{source_id}/rename", label=" usb-2014 ")
    assert "Renamed" in renamed.text and "usb-2014" in renamed.text
    assert post(web, f"/sources/{source_id}/rename", label="other").status_code == 409
    assert post(web, f"/sources/{source_id}/rename", label="a,b").status_code == 409

    wrong = post(web, f"/sources/{source_id}/forget", confirm="usb")
    assert wrong.status_code == 409
    assert "to confirm" in wrong.text
    forgot = post(web, f"/sources/{source_id}/forget", confirm="usb-2014")
    assert "Forgotten" in forgot.text
    assert [row["label"] for row in sources.list_sources(conn)] == ["other"]
    assert snapshot(folders / "usb") == before
