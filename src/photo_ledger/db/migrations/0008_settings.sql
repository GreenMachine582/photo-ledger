-- v1: settings edited on the Settings page. Each value is JSON, keyed by name. A stored value wins
-- over the PHOTO_LEDGER_* environment variable; deleting the row goes back to it.

CREATE TABLE settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL,
    set_at TEXT NOT NULL
);
