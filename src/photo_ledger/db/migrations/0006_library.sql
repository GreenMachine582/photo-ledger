-- M5: the destination library. One folder, outside every source and quarantine, that receives a
-- verified copy of each settled picture. library_entries is both the library's manifest (which
-- picture is where) and its journal: an entry is 'started' before its copy and 'done' or
-- 'failed' after it, so recovery can tell what an interruption left behind. Building only ever
-- adds files, so nothing in the library is removed or overwritten.

CREATE TABLE library (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    root_path  TEXT    NOT NULL,
    volume_id  TEXT,
    layout     TEXT    NOT NULL DEFAULT 'year' CHECK (layout IN ('year', 'original')),
    created_at TEXT    NOT NULL
);

CREATE TABLE library_entries (
    id              INTEGER PRIMARY KEY,
    content_id      INTEGER NOT NULL UNIQUE REFERENCES contents (id),
    file_id         INTEGER NOT NULL REFERENCES files (id),
    rel_path        TEXT    NOT NULL,
    expected_blake3 TEXT    NOT NULL,
    size_bytes      INTEGER NOT NULL,
    state           TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'started', 'done', 'failed')),
    started_at      TEXT,
    finished_at     TEXT,
    error           TEXT
);

CREATE UNIQUE INDEX library_entries_path ON library_entries (rel_path COLLATE NOCASE);
CREATE INDEX library_entries_state ON library_entries (state);
