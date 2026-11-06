"""What happened, for the Activity page and the notification bell. No web imports.

``record`` writes one activity-log entry and one notification for the app's single user, through
the catalogue's stores (``db/activity.py``). It is synchronous, so a scan job's worker thread and
the web routes call it the same way. A failure to record is logged and never raised: the scan,
apply or build it describes has already happened.

Summaries name scans and sources by label and give counts. They never hold file paths.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from greentechhub_core.audit import new_entry
from greentechhub_core.notifications import new_notification

from photo_ledger.db.activity import SqliteAuditStore, SqliteNotificationStore

logger = logging.getLogger(__name__)

#: The app's one person under AUTH_ADAPTER=single_user (see ``config.Settings``).
LOCAL_USER = "local"


def count(n: int, noun: str, plural: str | None = None) -> str:
    """``1 file``, ``2 files``, ``1 copy``, ``2 copies``: the counts in a summary."""
    return f"{n:,} {noun if n == 1 else plural or noun + 's'}"


def record(
    db_path: Path,
    action: str,
    summary: str,
    *,
    kind: str = "success",
    target: tuple[str, Any] | None = None,
    link: tuple[str, str] | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Log ``action`` (such as ``scan.completed``) and notify the user with ``summary``.

    ``link`` is the notification's ``(label, url)`` button, to a page in this app.
    """
    try:
        SqliteAuditStore(db_path).record_sync(
            new_entry(action, actor=LOCAL_USER, target=target, summary=summary, details=details)
        )
        action_link = {"label": link[0], "url": link[1]} if link else None
        SqliteNotificationStore(db_path).add_sync(
            new_notification(
                LOCAL_USER, summary, kind=kind, action=action_link, category=action.split(".")[0]
            )
        )
    except Exception:
        logger.exception("activity: recording %s failed", action)
