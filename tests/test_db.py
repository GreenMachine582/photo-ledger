import sqlite3

import pytest

from photo_ledger.db import connect, migrate, open_db
from photo_ledger.db.connection import MigrationError, migrations, schema_version


def test_migrations_are_numbered_without_gaps():
    numbers = [number for number, _, _ in migrations()]
    assert numbers == list(range(1, len(numbers) + 1))


def test_migrate_is_idempotent(tmp_path):
    conn = open_db(tmp_path / "ledger.db")
    assert schema_version(conn) == len(migrations())
    assert migrate(conn) == len(migrations())
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"sources", "scans", "scan_sources", "scan_errors", "contents", "files"} <= tables


def test_connection_uses_wal_and_foreign_keys(tmp_path):
    conn = open_db(tmp_path / "nested" / "ledger.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO files (source_id, rel_path, filename, extension, size_bytes, mtime_ns,"
            " first_seen_at, last_seen_at) VALUES (999, 'a.jpg', 'a.jpg', '.jpg', 1, 1, 1, 1)"
        )


def test_refuses_a_newer_database(tmp_path):
    conn = connect(tmp_path / "ledger.db")
    conn.execute(f"PRAGMA user_version = {len(migrations()) + 1}")
    with pytest.raises(MigrationError):
        migrate(conn)


def test_unique_keys(db):
    db.execute("INSERT INTO contents (blake3, size_bytes) VALUES ('ab', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO contents (blake3, size_bytes) VALUES ('ab', 1)")
