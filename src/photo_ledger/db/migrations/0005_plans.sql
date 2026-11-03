-- M4: plans and their operation journal. A plan is built from the active decisions, dry-run, then
-- applied by actions/executor.py, the only code that changes a source folder. Each action is
-- journalled as 'started' before its file operation and 'done' or 'failed' after it, so
-- recovery can tell what an interruption left behind. Undo is a plan of its own: 'restore'
-- actions pointing back at the plan they undo through undoes_plan_id.
--
-- from_path and to_path are relative: to the source root for a source file, and to
-- quarantine_root for a quarantined one. quarantine_root and quarantine_volume_id are copied
-- from the source when the plan is built, so undo still finds a file after the source's
-- quarantine setting changes.

CREATE TABLE plans (
    id             INTEGER PRIMARY KEY,
    status         TEXT    NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'applying', 'applied', 'incomplete', 'undone')),
    undoes_plan_id INTEGER REFERENCES plans (id),
    created_at     TEXT    NOT NULL,
    checked_at     TEXT,
    applied_at     TEXT
);

CREATE TABLE plan_actions (
    id                   INTEGER PRIMARY KEY,
    plan_id              INTEGER NOT NULL REFERENCES plans (id) ON DELETE CASCADE,
    file_id              INTEGER NOT NULL REFERENCES files (id),
    op                   TEXT    NOT NULL CHECK (op IN ('quarantine', 'restore')),
    from_path            TEXT    NOT NULL,
    to_path              TEXT    NOT NULL,
    quarantine_root      TEXT    NOT NULL,
    quarantine_volume_id TEXT,
    expected_blake3      TEXT    NOT NULL,
    size_bytes           INTEGER NOT NULL,
    state                TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (state IN ('pending', 'started', 'done', 'failed')),
    started_at           TEXT,
    finished_at          TEXT,
    error                TEXT
);

CREATE INDEX plan_actions_plan ON plan_actions (plan_id, id);
CREATE INDEX plan_actions_state ON plan_actions (state);
