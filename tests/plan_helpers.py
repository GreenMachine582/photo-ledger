"""Shared set-up for the plan and executor tests."""

from review_helpers import content_id, content_pair, exact_pair, file_id, keep

from photo_ledger import sources
from photo_ledger.review.decisions import decide

A_CAMERA = "camera/2019/IMG_0001.jpg"
A_BACKUP = "backup/Holiday 2019/IMG_0001.jpg"
C_CAMERA = "camera/2020/IMG_0001.jpg"
F_CAMERA = "camera/DCIM/100CANON/IMG_0412.jpg"
F_BEST = "backup/Best of 2019/IMG_0412 (1).jpg"
F_JAPAN = "backup/Pictures/Holidays/2019/Japan/IMG_0412.jpg"


def quarantine(conn, root, *labels):
    """Turn quarantine on for ``labels``, in a folder beside the fixture sources."""
    folder = root.parent / "quarantine"
    folder.mkdir(exist_ok=True)
    for label in labels:
        sources.set_quarantine(conn, label, folder)
    return folder


def reject_backup_copy(conn):
    """Keep the camera copy of picture A, rejecting the backup copy."""
    pair = exact_pair(conn, A_CAMERA, A_BACKUP)
    return decide(conn, pair["id"], keep(pair, file_id(conn, A_CAMERA)))


def reject_picture_a(conn):
    """Keep picture C over A in their name conflict, rejecting both copies of A."""
    pair = content_pair(conn, "name_conflict", A_CAMERA, C_CAMERA)
    return decide(conn, pair["id"], keep(pair, content_id(conn, C_CAMERA)))


def reject_two_of_three(conn):
    """Keep the camera copy of picture F, rejecting both backup copies."""
    camera = file_id(conn, F_CAMERA)
    first = exact_pair(conn, F_CAMERA, F_BEST)
    decide(conn, first["id"], keep(first, camera))
    second = exact_pair(conn, F_CAMERA, F_JAPAN)
    decide(conn, second["id"], keep(second, camera))
