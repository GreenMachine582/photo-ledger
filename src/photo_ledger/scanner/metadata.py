"""Decode an image once to read its size, EXIF, capture date and perceptual hash.

A decode failure means the file is corrupt. An EXIF failure is recorded separately, because the
image itself may be fine. The capture date only ever comes from the image's own metadata, never
from the filesystem, so a restore date can't pass for a capture date.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import imagehash
from PIL import ExifTags, Image, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_FORMATS = {"JPEG", "PNG"}
#: Formats read as another: an MPO (multi-picture JPEG, from many phones and 3D or burst cameras)
#: is a JPEG with extra frames after the first, and the first frame is the photo.
FORMAT_ALIASES = {"MPO": "JPEG"}

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_MAKE, TAG_MODEL, TAG_DATETIME, TAG_OFFSET_TIME = 0x010F, 0x0110, 0x0132, 0x9010

#: Capture-date tags in order of preference, with the offset tag that goes with each.
DATE_TAGS = (
    ("DateTimeOriginal", 0x9003, 0x9011, EXIF_IFD),
    ("DateTimeDigitized", 0x9004, 0x9012, EXIF_IFD),
    ("DateTime", TAG_DATETIME, TAG_OFFSET_TIME, None),
)
#: Values longer than this, such as maker notes and thumbnails, are left out of exif_json.
MAX_EXIF_VALUE_CHARS = 256


@dataclass
class ImageInfo:
    format: str | None = None
    width: int | None = None
    height: int | None = None
    phash: str | None = None
    captured_at: str | None = None
    capture_offset: str | None = None
    capture_date_source: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    exif_json: str | None = None
    exif_error: str | None = None
    decode_error: str | None = None


def is_supported(extension: str) -> bool:
    return extension.lower() in SUPPORTED_EXTENSIONS


def is_apple_double(name: str) -> bool:
    """A macOS AppleDouble sidecar, ``._<name>``: Finder metadata a Mac writes beside each file it
    copies to a drive or share that can't hold it. It keeps the photo's name but holds no image."""
    return name.startswith("._")


def is_photo(name: str) -> bool:
    """A file to hash and decode: a supported extension, and not an AppleDouble sidecar."""
    return is_supported(Path(name).suffix) and not is_apple_double(name)


def needs_redecode(content) -> bool:
    """A content stored as unsupported in a format that's now read, such as an older MPO row."""
    stored = content["format"]
    return stored not in SUPPORTED_FORMATS and FORMAT_ALIASES.get(stored) in SUPPORTED_FORMATS


def read_image(path: Path) -> ImageInfo:
    """Decode the image at ``path``. Never raises for a bad image: the error is in the result."""
    info = ImageInfo()
    try:
        with Image.open(path) as image:
            info.format = FORMAT_ALIASES.get(image.format, image.format)
            info.width, info.height = image.size
            if info.format not in SUPPORTED_FORMATS:
                info.decode_error = f"unsupported format {image.format}"
                return info
            image.load()  # decodes fully, so truncated files fail here
            try:
                _read_exif(image, info)
            except Exception as exc:  # any EXIF parsing failure is recorded, not fatal
                info.exif_error = f"{type(exc).__name__}: {exc}"
            info.phash = str(imagehash.phash(image))
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
        info.decode_error = f"{type(exc).__name__}: {exc}"
        info.phash = None
    return info


def parse_exif_datetime(value) -> str | None:
    """``YYYY:MM:DD HH:MM:SS`` to ISO 8601, or ``None`` for blank or impossible values."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip().rstrip("\x00")[:19], "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def _text(value) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if value is None:
        return None
    value = str(value).strip().rstrip("\x00").strip()
    return value or None


def _gps_coordinate(values, ref) -> float | None:
    if not values or len(values) != 3 or ref is None:
        return None
    degrees, minutes, seconds = (float(v) for v in values)
    result = degrees + minutes / 60 + seconds / 3600
    return -result if _text(ref) in ("S", "W") else result


def _read_exif(image: Image.Image, info: ImageInfo) -> None:
    exif = image.getexif()
    if not exif:
        return
    exif_ifd = exif.get_ifd(EXIF_IFD)
    for name, tag, offset_tag, ifd in DATE_TAGS:
        table = exif_ifd if ifd == EXIF_IFD else exif
        captured = parse_exif_datetime(table.get(tag))
        if captured:
            info.captured_at = captured
            info.capture_date_source = name
            info.capture_offset = _text(exif_ifd.get(offset_tag))
            break
    info.camera_make = _text(exif.get(TAG_MAKE))
    info.camera_model = _text(exif.get(TAG_MODEL))

    gps = exif.get_ifd(GPS_IFD)
    if gps:
        info.gps_lat = _gps_coordinate(gps.get(2), gps.get(1))
        info.gps_lon = _gps_coordinate(gps.get(4), gps.get(3))

    readable = {}
    for table in (exif, exif_ifd):
        for tag, value in table.items():
            if tag in (EXIF_IFD, GPS_IFD):
                continue
            text = _text(value) if isinstance(value, (str, bytes)) else str(value)
            if text and len(text) <= MAX_EXIF_VALUE_CHARS:
                readable[ExifTags.TAGS.get(tag, f"0x{tag:04X}")] = text
    info.exif_json = json.dumps(readable, sort_keys=True) if readable else None
