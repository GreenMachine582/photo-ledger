"""SQLite setup, migrations and queries. Standard library ``sqlite3`` only, and no FastAPI."""

import time
from datetime import UTC, datetime

from photo_ledger.db.connection import connect, migrate, open_db

__all__ = ["connect", "migrate", "now_iso", "now_ns", "open_db"]


def now_iso() -> str:
    """A UTC timestamp for display columns such as ``created_at``."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def now_ns() -> int:
    """Nanoseconds since the epoch, for ordering columns compared within a scan pass."""
    return time.time_ns()
