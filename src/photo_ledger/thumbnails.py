"""Preview images for the review screen, cached in the data folder.

Sources are only ever read. The cache can be deleted at any time and rebuilds itself, and it's how
an offline source's photos can still be reviewed.
"""

import sqlite3
from pathlib import Path

from PIL import Image, ImageOps

from photo_ledger.exports.guard import ensure_outside_sources
from photo_ledger.sources import service as source_service

PREVIEW_SIDE = 1600


def registered_file(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    """A catalogued file with its source and content, looked up by ID only."""
    return conn.execute(
        """
        SELECT f.id, f.rel_path, f.extension, f.status, f.source_id, c.blake3,
               s.root_path, s.volume_id, s.label
        FROM files f
        JOIN sources s ON s.id = f.source_id
        LEFT JOIN contents c ON c.id = f.content_id
        WHERE f.id = ?
        """,
        (file_id,),
    ).fetchone()


def source_path(conn: sqlite3.Connection, row: sqlite3.Row) -> Path | None:
    """The file on disk, when its source is online and the file is still there.

    The path is rebuilt from the database, and must stay inside the source's root.
    """
    source = conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
    if not source_service.is_online(source):
        return None
    root = Path(source["root_path"]).resolve()
    path = (root / row["rel_path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def cache_path(cache_dir: Path, blake3: str, max_side: int = PREVIEW_SIDE) -> Path:
    return cache_dir / blake3[:2] / f"{blake3}-{max_side}.jpg"


def preview(
    conn: sqlite3.Connection, file_id: int, cache_dir: Path, max_side: int = PREVIEW_SIDE
) -> Path | None:
    """A cached JPEG preview of a registered photo, made on first use."""
    row = registered_file(conn, file_id)
    if row is None or row["blake3"] is None:
        return None
    cached = cache_path(cache_dir, row["blake3"], max_side)
    if cached.is_file():
        return cached
    path = source_path(conn, row)
    if path is None:
        return None
    ensure_outside_sources(conn, cached)
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_side, max_side))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            cached.parent.mkdir(parents=True, exist_ok=True)
            partial = cached.with_suffix(".part")
            image.save(partial, "JPEG", quality=85)
            partial.replace(cached)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return cached
