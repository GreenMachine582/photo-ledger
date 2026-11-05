"""Read-only catalogue lookups for the Photos page: find a picture and list its copies."""

import sqlite3

#: The date a picture shows: the one you set, else EXIF, else none.
_DATE = (
    "COALESCE(d.captured_at, c.captured_at) AS taken,"
    " CASE WHEN d.captured_at IS NOT NULL THEN 'manual'"
    " WHEN c.captured_at IS NOT NULL THEN 'exif' ELSE 'undated' END AS date_source"
)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search(
    conn: sqlite3.Connection, q: str = "", undated: bool = False, limit: int = 50
) -> list[sqlite3.Row]:
    """Pictures with a copy whose name or path holds ``q``, one row per picture, by path."""
    where = ["f.content_id IS NOT NULL", "f.status != 'missing'"]
    params: list = []
    if q.strip():
        where.append(
            "(f.filename LIKE ? ESCAPE '\\' OR s.label || '/' || f.rel_path LIKE ? ESCAPE '\\')"
        )
        params += [_like(q.strip())] * 2
    if undated:
        where.append("d.captured_at IS NULL AND c.captured_at IS NULL")
    return conn.execute(
        f"""
        SELECT c.id AS content_id, MIN(f.id) AS file_id,
               MIN(s.label || '/' || f.rel_path) AS first_path, COUNT(*) AS copies, {_DATE}
        FROM files f
        JOIN sources s ON s.id = f.source_id
        JOIN contents c ON c.id = f.content_id
        LEFT JOIN date_fixes d ON d.content_id = c.id
        WHERE {" AND ".join(where)}
        GROUP BY c.id
        ORDER BY first_path
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()


def photo(conn: sqlite3.Connection, content_id: int) -> sqlite3.Row | None:
    """One picture with its date, or None if the catalogue has no such content."""
    return conn.execute(
        f"""
        SELECT c.id AS content_id, c.width, c.height, c.format, c.camera_make, c.camera_model,
               c.capture_offset, {_DATE}
        FROM contents c LEFT JOIN date_fixes d ON d.content_id = c.id
        WHERE c.id = ?
        """,
        (content_id,),
    ).fetchone()


def copies(conn: sqlite3.Connection, content_id: int) -> list[sqlite3.Row]:
    """Every catalogued copy of a picture, by source and path."""
    return conn.execute(
        "SELECT f.id AS file_id, s.label, f.rel_path, f.status"
        " FROM files f JOIN sources s ON s.id = f.source_id"
        " WHERE f.content_id = ? ORDER BY s.label, f.rel_path",
        (content_id,),
    ).fetchall()
