import make_fixtures
from PIL import Image


def test_build_is_deterministic(tmp_path):
    first = make_fixtures.build(tmp_path / "one")
    second = make_fixtures.build(tmp_path / "two")
    assert first == second
    for rel in first["files"]:
        a, b = tmp_path / "one" / rel, tmp_path / "two" / rel
        assert a.read_bytes() == b.read_bytes()
        assert a.stat().st_mtime_ns == b.stat().st_mtime_ns


def test_roles(fixture_tree):
    root, manifest = fixture_tree
    for left, right in manifest["exact_copies"]:
        assert (root / left).read_bytes() == (root / right).read_bytes()
    for left, right in manifest["name_conflicts"]:
        assert (root / left).name == (root / right).name
        assert (root / left).read_bytes() != (root / right).read_bytes()
    exif = Image.open(root / "camera/2019/IMG_0001.jpg").getexif()
    assert exif.get_ifd(make_fixtures.EXIF_IFD)[make_fixtures.TAG_DATETIME_ORIGINAL].startswith(
        "2019:06:01"
    )
    restored = root / manifest["date_mismatch"][0]
    assert restored.stat().st_mtime_ns == make_fixtures.RESTORE_MTIME_NS


def test_main_refuses_a_non_empty_directory(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    assert make_fixtures.main(["make_fixtures.py", str(tmp_path)]) == 1
    assert make_fixtures.main(["make_fixtures.py", str(tmp_path / "new")]) == 0
