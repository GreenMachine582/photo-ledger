import pytest

from photo_ledger.matching.scoring import has_copy_marker, suggest

BASE = {
    "id": 1,
    "source_label": "pc",
    "source_priority": 0,
    "rel_path": "2019/IMG_0001.jpg",
    "filename": "IMG_0001.jpg",
    "size_bytes": 1000,
    "width": 4032,
    "height": 3024,
    "captured_at": "2019-06-01T10:00:00",
    "camera_make": "Cam",
    "camera_model": "One",
    "gps_lat": 1.0,
}


def copy(**changes):
    return {**BASE, "id": BASE["id"] + 1, **changes}


@pytest.mark.parametrize(
    ("worse", "reason"),
    [
        ({"width": 1600, "height": 1200}, "higher resolution (4032x3024 vs 1600x1200)"),
        ({"gps_lat": None}, "more complete EXIF (3 of 3 fields vs 2)"),
        ({"captured_at": "2019-06-02T10:00:00"}, "earlier capture date (2019-06-01T10:00:00 vs"),
        ({"source_priority": -1, "source_label": "usb"}, "higher-priority source (pc 0 vs usb -1)"),
        (
            {"rel_path": "2019/IMG_0001 (1).jpg", "filename": "IMG_0001 (1).jpg"},
            "tidier path (no copy",
        ),
        ({"rel_path": "a/very/deep/2019/IMG_0001.jpg"}, "shorter path (17 vs 29 characters)"),
    ],
)
def test_each_criterion_decides_alone(worse, reason):
    good, bad = BASE, copy(**worse)
    left = suggest("exact", [good], [bad])
    assert left["suggested"] == "left"
    assert left["reasons"][0].startswith(reason)
    assert left["keep"] == "pc/2019/IMG_0001.jpg"
    right = suggest("exact", [bad], [good])
    assert right["suggested"] == "right"


def test_criteria_are_ordered_and_losses_are_explained():
    # Lower resolution but a higher-priority source: resolution decides, and the loss is listed.
    small_trusted = copy(width=1600, height=1200, source_priority=5, source_label="nas")
    result = suggest("similar", [small_trusted], [BASE])
    assert result["suggested"] == "right"
    assert result["reasons"] == ["higher resolution (4032x3024 vs 1600x1200)"]
    assert result["against"] == ["higher-priority source (nas 5 vs pc 0)"]


def test_size_only_breaks_ties():
    bigger = copy(size_bytes=5000)
    result = suggest("exact", [BASE], [bigger])
    assert result["suggested"] == "right"
    assert result["reasons"] == ["larger file, as a tie-break (5,000 vs 1,000 bytes)"]
    smaller_but_sharper = copy(size_bytes=10, width=8000, height=6000)
    assert suggest("similar", [BASE], [smaller_but_sharper])["suggested"] == "right"


def test_identical_copies_have_no_suggestion():
    result = suggest("exact", [BASE], [copy()])
    assert result["suggested"] is None
    assert result["reasons"] == ["no difference found"]


def test_unknown_values_never_decide():
    undated = copy(captured_at=None, camera_make=None, camera_model=None, gps_lat=None)
    result = suggest("similar", [BASE], [undated])
    assert result["reasons"] == ["more complete EXIF (3 of 3 fields vs 0)"]


def test_a_content_is_represented_by_its_best_copy():
    messy = copy(id=7, rel_path="dump/IMG_0001 - Copy.jpg", filename="IMG_0001 - Copy.jpg")
    tidy = copy(id=8)
    result = suggest("similar", [messy, tidy], [copy(id=9, width=10, height=10)])
    assert result["keep"] == "pc/2019/IMG_0001.jpg"


@pytest.mark.parametrize(
    ("name", "marked"),
    [
        ("IMG_0001 (1).jpg", True),
        ("IMG_0001 - Copy.jpg", True),
        ("IMG_0001_copy2.jpg", True),
        ("Copy of IMG_0001.jpg", True),
        ("IMG_0001.jpg", False),
        ("copyright.jpg", False),
        ("2019 (Japan).jpg", False),
    ],
)
def test_copy_markers(name, marked):
    assert has_copy_marker(name) is marked
