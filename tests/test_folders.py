"""The folder explorer's listing: names only, read-only, hidden and linked folders skipped."""

import os

import pytest
from test_scanner import snapshot

from photo_ledger import sources
from photo_ledger.library import settings as library_settings
from photo_ledger.sources import folders
from photo_ledger.sources.service import SourceError


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "drive"
    for name in ("Photos/2019", "Photos/2020", "backup", "Zed", ".cache/inner"):
        (root / name).mkdir(parents=True)
    (root / "Photos" / "IMG_0001.jpg").write_bytes(b"not really a jpeg")
    (root / "notes.txt").write_text("a file, never listed")
    return root


def names(listing):
    return [folder.name for folder in listing.folders]


def test_lists_subfolders_only_sorted_without_hidden(tree):
    listing = folders.children(str(tree))
    assert names(listing) == ["backup", "Photos", "Zed"]
    assert listing.more == 0
    by_name = {f.name: f for f in listing.folders}
    assert by_name["Photos"].has_children
    assert not by_name["Zed"].has_children
    assert by_name["Photos"].path == str(tree / "Photos")


def test_a_folder_of_files_has_no_subfolders(tree):
    assert names(folders.children(str(tree / "Photos" / "2019"))) == []
    assert names(folders.children(str(tree / "Photos"))) == ["2019", "2020"]


def test_listing_never_changes_anything(tree):
    before = snapshot(tree)
    dirs_before = sorted(p.as_posix() for p in tree.rglob("*"))
    folders.children(str(tree))
    folders.children(str(tree / "Photos"))
    folders.roots()
    assert snapshot(tree) == before
    assert sorted(p.as_posix() for p in tree.rglob("*")) == dirs_before


def test_links_are_left_out(tree):
    try:
        os.symlink(tree / "Photos", tree / "Shortcut", target_is_directory=True)
    except OSError:
        pytest.skip("Can't create symlinks here")
    assert "Shortcut" not in names(folders.children(str(tree)))


@pytest.mark.parametrize("path", ["", "relative/folder", "missing"])
def test_refuses_relative_and_missing_paths(tree, path):
    if path == "missing":
        path = str(tree / "missing")
    with pytest.raises(SourceError):
        folders.children(path)


def test_a_file_is_not_a_folder(tree):
    with pytest.raises(SourceError):
        folders.children(str(tree / "notes.txt"))


def test_caps_a_huge_folder(tree, monkeypatch):
    monkeypatch.setattr(folders, "LIMIT", 2)
    listing = folders.children(str(tree))
    assert names(listing) == ["backup", "Photos"]
    assert listing.more == 1


def test_roots_are_absolute_starting_places():
    found = folders.roots()
    assert found
    assert all(os.path.isabs(folder.path) and folder.has_children for folder in found)


def test_annotate_names_sources_quarantines_and_the_library(db, tree, tmp_path):
    (tmp_path / "q").mkdir()
    (tmp_path / "lib").mkdir()
    sources.add_source(db, tree / "Photos", "usb")
    sources.set_quarantine(db, "usb", tmp_path / "q")
    library_settings.set_library(db, tmp_path / "lib", "year")
    marked = {
        f.name: f.mapped_as for f in folders.annotate(db, folders.children(str(tmp_path)).folders)
    }
    assert marked["q"] == "quarantine"
    assert marked["lib"] == "library"
    photos = folders.annotate(db, folders.children(str(tree)).folders)
    assert {f.name: f.mapped_as for f in photos}["Photos"] == "source usb"
    assert {f.name: f.mapped_as for f in photos}["Zed"] is None
