"""The catalogue's notification and activity stores pass greentechhub-core's contract suites."""

import pytest
from greentechhub_core.contracts.audit import AuditStoreContract
from greentechhub_core.contracts.notifications import NotificationStoreContract

from photo_ledger.db.activity import SqliteAuditStore, SqliteNotificationStore


class TestNotificationStore(NotificationStoreContract):
    @pytest.fixture
    def store(self, tmp_path):
        return SqliteNotificationStore(tmp_path / "photo-ledger.db")


class TestAuditStore(AuditStoreContract):
    @pytest.fixture
    def store(self, tmp_path):
        return SqliteAuditStore(tmp_path / "photo-ledger.db")
