"""Finding fixture pairs by path, for the review tests."""


def file_id(conn, path):
    label, rel_path = path.split("/", 1)
    return conn.execute(
        "SELECT f.id FROM files f JOIN sources s ON s.id = f.source_id"
        " WHERE s.label = ? AND f.rel_path = ?",
        (label, rel_path),
    ).fetchone()[0]


def content_id(conn, path):
    return conn.execute(
        "SELECT content_id FROM files WHERE id = ?", (file_id(conn, path),)
    ).fetchone()[0]


def exact_pair(conn, a, b):
    low, high = sorted((file_id(conn, a), file_id(conn, b)))
    return conn.execute(
        "SELECT * FROM review_pairs WHERE pair_key = ?", (f"exact:{low}:{high}",)
    ).fetchone()


def content_pair(conn, kind, a, b):
    ids = {content_id(conn, a), content_id(conn, b)}
    for row in conn.execute("SELECT * FROM review_pairs WHERE kind = ?", (kind,)):
        if {row["left_id"], row["right_id"]} == ids:
            return row
    raise LookupError((kind, a, b))


def keep(pair, keeper_id):
    """The action that keeps ``keeper_id`` (a file ID for exact pairs, else a content ID)."""
    return "keep_left" if pair["left_id"] == keeper_id else "keep_right"


def status(conn, pair_id):
    return conn.execute("SELECT status FROM review_pairs WHERE id = ?", (pair_id,)).fetchone()[0]
