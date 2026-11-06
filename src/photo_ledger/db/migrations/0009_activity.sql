-- v1: notifications and the activity log, for greentechhub-core's NotificationStore and AuditStore
-- (db/activity.py). Times are UTC ISO 8601 with microseconds, so text order is time order.

CREATE TABLE notifications (
    id           TEXT PRIMARY KEY,
    recipient    TEXT NOT NULL,
    message      TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'info',
    title        TEXT,
    icon         TEXT,
    action_label TEXT,
    action_url   TEXT,
    category     TEXT NOT NULL DEFAULT 'general',
    created_at   TEXT NOT NULL,
    read_at      TEXT
);
CREATE INDEX notifications_recipient ON notifications (recipient, created_at);

CREATE TABLE audit_log (
    id          TEXT PRIMARY KEY,
    at          TEXT NOT NULL,
    action      TEXT NOT NULL,
    actor       TEXT,
    target_type TEXT,
    target_id   TEXT,
    summary     TEXT NOT NULL DEFAULT '',
    details     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_at ON audit_log (at);
