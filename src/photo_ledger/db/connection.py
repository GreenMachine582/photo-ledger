"""SQLite connection setup and numbered migrations.

Migrations are ``migrations/NNNN_description.sql`` files applied in order, each in its own
transaction, and tracked with ``PRAGMA user_version``. Never edit a migration that has shipped:
add a new one.
"""

import re
import sqlite3
from importlib.resources import files
from pathlib import Path

from photo_ledger.errors import PhotoLedgerError

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(PhotoLedgerError):
    """The migrations on disk or the database's schema version are not usable."""


def connect(path: Path) -> sqlite3.Connection:
    """Open the catalogue with WAL, foreign keys and named-column rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrations() -> list[tuple[int, str, str]]:
    """Every bundled migration as ``(number, filename, sql)``, numbered 1..N without gaps."""
    found = []
    for entry in (files("photo_ledger.db") / "migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    numbers = [number for number, _, _ in found]
    if numbers != list(range(1, len(found) + 1)):
        raise MigrationError(
            f"Migrations must be numbered 0001 upwards without gaps, found {numbers}"
        )
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any migrations the database hasn't seen yet and return the resulting schema version."""
    available = migrations()
    current = schema_version(conn)
    if current > len(available):
        raise MigrationError(
            f"The database is at schema version {current}, newer than this app's {len(available)}. "
            "Upgrade photo-ledger before opening it."
        )
    for number, _name, sql in available[current:]:
        # executescript commits any open transaction first, so each migration is atomic.
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    return schema_version(conn)


def open_db(path: Path) -> sqlite3.Connection:
    """Connect and bring the schema up to date."""
    conn = connect(path)
    migrate(conn)
    return conn
