"""Notifications and the activity log in the catalogue, over the standard library ``sqlite3``.

These implement greentechhub-core's ``NotificationStore`` and ``AuditStore`` protocols, and
``tests/test_activity_stores.py`` runs core's contract suites against them. Each call opens its own
short connection, since the web app calls them from its event loop and scan jobs call them from
worker threads, and a SQLite connection belongs to one thread.
"""

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from greentechhub_core.audit import AuditEntry
from greentechhub_core.notifications import Notification

from photo_ledger.db.connection import open_db


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class _Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = open_db(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()


class SqliteNotificationStore(_Store):
    """Notifications for the notification centre, one row each."""

    def add_sync(self, notification: Notification) -> None:
        n = notification
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO notifications (id, recipient, message, kind, title, icon, action_label,
                                           action_url, category, created_at, read_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    n.id,
                    n.recipient,
                    n.message,
                    n.kind,
                    n.title,
                    n.icon,
                    n.action_label,
                    n.action_url,
                    n.category,
                    _iso(n.created_at),
                    _iso(n.read_at) if n.read_at else None,
                ),
            )

    def list_for_sync(
        self, recipient: str, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        unread = " AND read_at IS NULL" if unread_only else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM notifications WHERE recipient = ?{unread} "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (recipient, limit),
            ).fetchall()
        return [
            Notification(
                id=r["id"],
                recipient=r["recipient"],
                message=r["message"],
                kind=r["kind"],
                title=r["title"],
                icon=r["icon"],
                action_label=r["action_label"],
                action_url=r["action_url"],
                category=r["category"],
                created_at=_time(r["created_at"]),
                read_at=_time(r["read_at"]),
            )
            for r in rows
        ]

    def unread_count_sync(self, recipient: str) -> int:
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE recipient = ? AND read_at IS NULL",
                (recipient,),
            ).fetchone()[0]

    def mark_read_sync(self, recipient: str, ids: Iterable[str], *, at: datetime) -> int:
        ids = list(ids)
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        with self._conn() as conn:
            return conn.execute(
                f"UPDATE notifications SET read_at = ? WHERE recipient = ? AND read_at IS NULL "
                f"AND id IN ({marks})",
                (_iso(at), recipient, *ids),
            ).rowcount

    def mark_all_read_sync(self, recipient: str, *, at: datetime) -> int:
        with self._conn() as conn:
            return conn.execute(
                "UPDATE notifications SET read_at = ? WHERE recipient = ? AND read_at IS NULL",
                (_iso(at), recipient),
            ).rowcount

    def prune_sync(self, before: datetime) -> int:
        with self._conn() as conn:
            return conn.execute(
                "DELETE FROM notifications WHERE read_at IS NOT NULL AND created_at < ?",
                (_iso(before),),
            ).rowcount

    async def add(self, notification: Notification) -> None:
        self.add_sync(notification)

    async def list_for(
        self, recipient: str, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        return self.list_for_sync(recipient, unread_only=unread_only, limit=limit)

    async def unread_count(self, recipient: str) -> int:
        return self.unread_count_sync(recipient)

    async def mark_read(self, recipient: str, ids: Iterable[str], *, at: datetime) -> int:
        return self.mark_read_sync(recipient, ids, at=at)

    async def mark_all_read(self, recipient: str, *, at: datetime) -> int:
        return self.mark_all_read_sync(recipient, at=at)

    async def prune(self, before: datetime) -> int:
        return self.prune_sync(before)


class SqliteAuditStore(_Store):
    """The activity log: what was scanned, applied, undone and built, newest first."""

    def record_sync(self, entry: AuditEntry) -> None:
        e = entry
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (id, at, action, actor, target_type, target_id, summary,
                                       details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e.id,
                    _iso(e.at),
                    e.action,
                    e.actor,
                    e.target_type,
                    e.target_id,
                    e.summary,
                    json.dumps(dict(e.details)),
                ),
            )

    def entries_sync(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        target: tuple[str, str | None] | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        where, params = [], []
        if actor is not None:
            where.append("actor = ?")
            params.append(actor)
        if action is not None:
            if action.endswith("."):
                where.append("substr(action, 1, ?) = ?")
                params += [len(action), action]
            else:
                where.append("action = ?")
                params.append(action)
        if target is not None:
            where.append("target_type = ?")
            params.append(target[0])
            if target[1] is not None:
                where.append("target_id = ?")
                params.append(str(target[1]))
        if before is not None:
            where.append("at < ?")
            params.append(_iso(before))
        clause = f"WHERE {' AND '.join(where)} " if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log {clause}ORDER BY at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [
            AuditEntry(
                id=r["id"],
                at=_time(r["at"]),
                action=r["action"],
                actor=r["actor"],
                target_type=r["target_type"],
                target_id=r["target_id"],
                summary=r["summary"],
                details=json.loads(r["details"]),
            )
            for r in rows
        ]

    def prune_sync(self, before: datetime) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM audit_log WHERE at < ?", (_iso(before),)).rowcount

    async def record(self, entry: AuditEntry) -> None:
        self.record_sync(entry)

    async def entries(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        target: tuple[str, str | None] | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        return self.entries_sync(
            actor=actor, action=action, target=target, before=before, limit=limit
        )

    async def prune(self, before: datetime) -> int:
        return self.prune_sync(before)
