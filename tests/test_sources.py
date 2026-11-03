import sys

import pytest

from photo_ledger import sources
from photo_ledger.sources import device
from photo_ledger.sources.device import DeviceInfo
from photo_ledger.sources.service import overlaps


@pytest.fixture
def fake_volume(monkeypatch):
    """Pretend every path is on the volume named in ``state['id']``."""
    state = {"id": "AAAA-0001", "mounted": []}

    def describe(path):
        return DeviceInfo(
            source_type="removable",
            volume_id=state["id"],
            volume_root=str(path.anchor if hasattr(path, "anchor") else ""),
            device_label="USB",
            filesystem="exFAT",
            capacity_bytes=1000,
        )

    monkeypatch.setattr(device, "describe", describe)
    monkeypatch.setattr(device, "mounted_volumes", lambda: state["mounted"])
    return state


def test_add_records_device_details(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    source = sources.add_source(db, tmp_path / "usb", "usb-1")
    assert source["label"] == "usb-1"
    assert source["root_path"] == str((tmp_path / "usb").resolve())
    assert source["volume_id"] == "AAAA-0001"
    assert source["filesystem"] == "exFAT"
    assert source["state"] == "online"


def test_real_device_details_never_raise(tmp_path):
    info = device.describe(tmp_path)
    assert info.source_type in {"internal", "removable", "network", "optical", "unknown"}
    assert info.capacity_bytes is None or info.capacity_bytes > 0
    assert device.describe(tmp_path / "missing") is not None


@pytest.mark.parametrize("nested", ["inside", "containing", "same"])
def test_overlapping_sources_are_refused(db, tmp_path, nested):
    outer = tmp_path / "backup"
    inner = outer / "2019"
    inner.mkdir(parents=True)
    first, second = {
        "inside": (outer, inner),
        "containing": (inner, outer),
        "same": (outer, outer),
    }[nested]
    sources.add_source(db, first, "first")
    with pytest.raises(sources.SourceError, match="overlaps"):
        sources.add_source(db, second, "second")


def test_siblings_with_a_shared_prefix_do_not_overlap(tmp_path):
    assert not overlaps(tmp_path / "photos", tmp_path / "photos-old")


@pytest.mark.skipif(sys.platform != "win32", reason="paths are case-insensitive on Windows")
def test_overlap_ignores_case_on_windows(tmp_path):
    assert overlaps(tmp_path / "Photos", str(tmp_path / "PHOTOS" / "2019"))


def test_add_refuses_bad_input(db, tmp_path):
    with pytest.raises(sources.SourceError, match="doesn't exist"):
        sources.add_source(db, tmp_path / "nope", "nope")
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(sources.SourceError, match="isn't a folder"):
        sources.add_source(db, tmp_path / "file.txt", "file")
    with pytest.raises(sources.SourceError, match="Labels"):
        sources.add_source(db, tmp_path, "a,b")
    sources.add_source(db, tmp_path, "ok")
    with pytest.raises(sources.SourceError, match="already exists"):
        sources.add_source(db, tmp_path, "ok")


def test_offline_when_missing_or_on_another_volume(db, tmp_path, fake_volume):
    root = tmp_path / "usb"
    root.mkdir()
    source = sources.add_source(db, root, "usb")
    assert sources.is_online(source)
    fake_volume["id"] = "BBBB-0002"  # a different drive now sits at the same path
    assert not sources.is_online(source)
    assert not sources.refresh_state(db, source)
    assert sources.get_source(db, "usb")["state"] == "offline"
    fake_volume["id"] = "AAAA-0001"
    root.rename(tmp_path / "elsewhere")
    assert not sources.is_online(source)


def test_reconnect_to_the_same_volume(db, tmp_path, fake_volume):
    (tmp_path / "E" / "photos").mkdir(parents=True)
    source = sources.add_source(db, tmp_path / "E" / "photos", "usb")
    (tmp_path / "E").rename(tmp_path / "F")
    db.execute(
        "UPDATE sources SET volume_root = ? WHERE id = ?", (str(tmp_path / "E"), source["id"])
    )
    fake_volume["mounted"] = [(str(tmp_path / "F"), "AAAA-0001")]

    found = sources.find_new_root(sources.get_source(db, "usb"))
    assert found == tmp_path / "F" / "photos"
    updated = sources.reconnect(db, "usb", found)
    assert updated["root_path"] == str(found.resolve())
    assert updated["id"] == source["id"]


def test_reconnect_refuses_a_different_volume(db, tmp_path, fake_volume):
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    sources.add_source(db, tmp_path / "old", "usb")
    fake_volume["id"] = "BBBB-0002"
    with pytest.raises(sources.SourceError, match="different drive"):
        sources.reconnect(db, "usb", tmp_path / "new")


def test_reconnect_refuses_an_overlap(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b" / "inner").mkdir(parents=True)
    sources.add_source(db, tmp_path / "a", "a")
    sources.add_source(db, tmp_path / "b", "b")
    with pytest.raises(sources.SourceError, match="overlaps"):
        sources.reconnect(db, "a", tmp_path / "b" / "inner")


def test_quarantine_records_its_volume_and_turns_off(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "usb", "usb")
    source, same = sources.set_quarantine(db, "usb", tmp_path / "q")
    assert source["quarantine_enabled"] == 1
    assert source["quarantine_path"] == str((tmp_path / "q").resolve())
    assert source["quarantine_volume_id"] == "AAAA-0001"
    assert same is True
    assert sources.quarantine_online(source)

    fake_volume["id"] = "BBBB-0002"  # another drive now sits at the quarantine's path
    assert not sources.quarantine_online(source)
    assert "AAAA-0001" in sources.quarantine_device(source)

    source, same = sources.set_quarantine(db, "usb", None)
    assert source["quarantine_enabled"] == 0
    assert source["quarantine_path"] is None
    assert same is None
    assert not sources.quarantine_online(source)


def test_quarantine_on_another_volume_is_reported(db, tmp_path, fake_volume):
    (tmp_path / "usb").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "usb", "usb")
    fake_volume["id"] = "BBBB-0002"
    _source, same = sources.set_quarantine(db, "usb", tmp_path / "q")
    assert same is False


def test_quarantine_must_exist_and_sit_outside_every_source(db, tmp_path):
    (tmp_path / "a" / "inner").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    sources.add_source(db, tmp_path / "a", "a")
    sources.add_source(db, tmp_path / "b", "b")
    with pytest.raises(sources.SourceError, match="doesn't exist"):
        sources.set_quarantine(db, "a", tmp_path / "missing")
    with pytest.raises(sources.SourceError, match="overlaps source 'a'"):
        sources.set_quarantine(db, "b", tmp_path / "a" / "inner")
    assert not (tmp_path / "missing").exists()


def test_a_source_inside_a_quarantine_is_refused(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "q" / "inner").mkdir(parents=True)
    sources.add_source(db, tmp_path / "a", "a")
    sources.set_quarantine(db, "a", tmp_path / "q")
    with pytest.raises(sources.SourceError, match="quarantine"):
        sources.add_source(db, tmp_path / "q" / "inner", "inner")


def test_quarantine_offline_when_its_folder_is_gone(db, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "q").mkdir()
    sources.add_source(db, tmp_path / "a", "a")
    source, _ = sources.set_quarantine(db, "a", tmp_path / "q")
    (tmp_path / "q").rename(tmp_path / "q-moved")
    assert not sources.quarantine_online(source)
