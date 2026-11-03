"""Generate a tree of synthetic test photos. This repo is public, so tests never use real ones.

    python scripts/make_fixtures.py <empty-directory>

The tree has two top-level folders, ``camera`` and ``backup``, which tests map as separate
sources. It holds exact copies, resized and re-encoded versions, reused filenames, an EXIF date
that disagrees with the file date, PNGs without EXIF, a truncated JPEG and unsupported files.
Everything is drawn from a seed and given fixed modification times, so the output is
deterministic. ``build`` returns a manifest describing which files play which role.
"""

import io
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = (320, 240)
#: 2021-03-04 05:06:07 UTC, used as the modification time of every generated file.
BASE_MTIME_NS = 1_614_834_367_000_000_000
#: 2024-01-01 00:00:00 UTC, a typical "restored from backup" file date.
RESTORE_MTIME_NS = 1_704_067_200_000_000_000

EXIF_IFD = 0x8769
TAG_MAKE, TAG_MODEL, TAG_DATETIME = 0x010F, 0x0110, 0x0132
TAG_DATETIME_ORIGINAL, TAG_OFFSET_TIME_ORIGINAL = 0x9003, 0x9011


def draw(seed: int, size: tuple[int, int] = SIZE) -> Image.Image:
    """A deterministic picture: a gradient with a few large shapes, so pHashes differ clearly."""
    rng = random.Random(seed)
    width, height = size
    image = Image.new("RGB", size)
    top = tuple(rng.randrange(256) for _ in range(3))
    bottom = tuple(rng.randrange(256) for _ in range(3))
    pen = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(height - 1, 1)
        pen.line(
            [(0, y), (width, y)], fill=tuple(round(a + (b - a) * mix) for a, b in zip(top, bottom))
        )
    for _ in range(4):
        x0, y0 = rng.randrange(width // 2), rng.randrange(height // 2)
        x1, y1 = (
            x0 + rng.randrange(width // 4, width // 2),
            y0 + rng.randrange(height // 4, height // 2),
        )
        colour = tuple(rng.randrange(256) for _ in range(3))
        shape = pen.ellipse if rng.random() < 0.5 else pen.rectangle
        shape([x0, y0, x1, y1], fill=colour)
    return image


def jpeg_bytes(image: Image.Image, *, quality: int = 90, taken: str | None = None) -> bytes:
    """Encode as JPEG, with camera EXIF and a ``DateTimeOriginal`` when ``taken`` is given."""
    buffer = io.BytesIO()
    exif = Image.Exif()
    if taken:
        exif[TAG_MAKE] = "FixtureCam"
        exif[TAG_MODEL] = "FC-1"
        exif[TAG_DATETIME] = taken
        exif_ifd = exif.get_ifd(EXIF_IFD)
        exif_ifd[TAG_DATETIME_ORIGINAL] = taken
        exif_ifd[TAG_OFFSET_TIME_ORIGINAL] = "+10:00"
    image.save(buffer, "JPEG", quality=quality, exif=exif.tobytes())
    return buffer.getvalue()


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _write(root: Path, rel: str, data: bytes, mtime_ns: int = BASE_MTIME_NS) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return rel


def build(root: Path, seed: int = 0) -> dict:
    """Write the fixture tree under ``root`` and return a manifest of the roles each file plays."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pics = {name: draw(seed * 100 + index) for index, name in enumerate("abcdef")}

    a = jpeg_bytes(pics["a"], taken="2019:06:01 10:00:00")
    b = jpeg_bytes(pics["b"], taken="2019:06:02 11:30:00")
    c = jpeg_bytes(pics["c"], taken="2020:01:15 09:00:00")
    d = png_bytes(pics["d"])
    e = jpeg_bytes(pics["e"], taken="2018:12:25 08:00:00")
    b_small = jpeg_bytes(pics["b"].resize((160, 120)), quality=70)
    d_as_jpeg = jpeg_bytes(pics["d"], quality=80)

    w = _write
    manifest = {
        "sources": ["camera", "backup"],
        "exact_copies": [
            (
                w(root, "camera/2019/IMG_0001.jpg", a),
                w(root, "backup/Holiday 2019/IMG_0001.jpg", a),
            ),
            (w(root, "camera/2019/IMG_0002.jpg", b), w(root, "backup/Holiday 2019/renamed.jpg", b)),
        ],
        "similar": [
            (
                "camera/2019/IMG_0002.jpg",
                w(root, "backup/Holiday 2019/IMG_0002_small.jpg", b_small),
            ),
            ("camera/screenshots/shot_01.png", w(root, "backup/shot_01.jpg", d_as_jpeg)),
        ],
        "name_conflicts": [("camera/2019/IMG_0001.jpg", w(root, "camera/2020/IMG_0001.jpg", c))],
        "pngs": [w(root, "camera/screenshots/shot_01.png", d)],
        "date_mismatch": [
            w(root, "backup/restored/IMG_0003.jpg", e, mtime_ns=RESTORE_MTIME_NS),
        ],
        "truncated": [w(root, "backup/broken/truncated.jpg", a[: len(a) // 2])],
        "unsupported": [
            w(root, "camera/notes.txt", b"not a photo\n"),
            w(root, "backup/clip.mp4", b"\x00\x00\x00\x18ftypmp42"),
        ],
        "distinct": ["a", "b", "c", "d", "e"],
        "taken": {
            "camera/2019/IMG_0001.jpg": "2019-06-01T10:00:00",
            "backup/restored/IMG_0003.jpg": "2018-12-25T08:00:00",
        },
    }
    manifest["files"] = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    )
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    root = Path(argv[1])
    if root.exists() and any(root.iterdir()):
        print(f"{root} isn't empty. Choose a new or empty directory.", file=sys.stderr)
        return 1
    manifest = build(root)
    print(f"Wrote {len(manifest['files'])} files to {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
