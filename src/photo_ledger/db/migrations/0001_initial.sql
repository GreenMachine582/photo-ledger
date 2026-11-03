-- M1: sources, saved scans and the file catalogue.
-- Paths in files and scan_errors are POSIX-style and relative to sources.root_path.
-- Columns ending _ns or _at holding integers are nanoseconds since the epoch; text _at columns are ISO 8601 UTC.

CREATE TABLE sources (
    id                   INTEGER PRIMARY KEY,
    label                TEXT    NOT NULL UNIQUE,
    root_path            TEXT    NOT NULL,
    source_type          TEXT    NOT NULL DEFAULT 'unknown'
                         CHECK (source_type IN ('internal', 'removable', 'network', 'optical', 'unknown')),
    volume_id            TEXT,
    volume_root          TEXT,
    device_label         TEXT,
    filesystem           TEXT,
    capacity_bytes       INTEGER,
    priority             INTEGER NOT NULL DEFAULT 0,
    state                TEXT    NOT NULL DEFAULT 'online' CHECK (state IN ('online', 'offline')),
    quarantine_enabled   INTEGER NOT NULL DEFAULT 0 CHECK (quarantine_enabled IN (0, 1)),
    quarantine_path      TEXT,
    quarantine_volume_id TEXT,
    created_at           TEXT    NOT NULL
);

CREATE TABLE scans (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'running', 'paused', 'complete')),
    created_at     TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE scan_sources (
    scan_id         INTEGER NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
    source_id       INTEGER NOT NULL REFERENCES sources (id),
    mode            TEXT    NOT NULL DEFAULT 'incremental' CHECK (mode IN ('incremental', 'verify')),
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'paused', 'offline', 'complete')),
    stage           TEXT    NOT NULL DEFAULT 'walk' CHECK (stage IN ('walk', 'hash', 'done')),
    started_at      TEXT,
    finished_at     TEXT,
    file_count      INTEGER NOT NULL DEFAULT 0,
    total_bytes     INTEGER NOT NULL DEFAULT 0,
    resume_path     TEXT,
    pass_started_at INTEGER,
    heartbeat_at    INTEGER,
    PRIMARY KEY (scan_id, source_id)
);

CREATE TABLE scan_errors (
    id         INTEGER PRIMARY KEY,
    scan_id    INTEGER NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
    source_id  INTEGER NOT NULL REFERENCES sources (id),
    rel_path   TEXT    NOT NULL,
    stage      TEXT    NOT NULL CHECK (stage IN ('walk', 'hash', 'decode', 'exif')),
    message    TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX scan_errors_scan ON scan_errors (scan_id, source_id, stage);

CREATE TABLE contents (
    id                  INTEGER PRIMARY KEY,
    blake3              TEXT    NOT NULL UNIQUE,
    size_bytes          INTEGER NOT NULL,
    phash               TEXT,
    width               INTEGER,
    height              INTEGER,
    format              TEXT,
    captured_at         TEXT,
    capture_offset      TEXT,
    capture_date_source TEXT,
    camera_make         TEXT,
    camera_model        TEXT,
    gps_lat             REAL,
    gps_lon             REAL,
    exif_json           TEXT,
    exif_error          TEXT,
    decode_error        TEXT
);

CREATE INDEX contents_size ON contents (size_bytes);
CREATE INDEX contents_captured_at ON contents (captured_at);

CREATE TABLE files (
    id                 INTEGER PRIMARY KEY,
    source_id          INTEGER NOT NULL REFERENCES sources (id),
    content_id         INTEGER REFERENCES contents (id),
    rel_path           TEXT    NOT NULL,
    filename           TEXT    NOT NULL,
    extension          TEXT    NOT NULL,
    size_bytes         INTEGER NOT NULL,
    mtime_ns           INTEGER NOT NULL,
    birthtime_ns       INTEGER,
    status             TEXT    NOT NULL DEFAULT 'present'
                       CHECK (status IN ('present', 'missing', 'unsupported', 'corrupt', 'unreadable',
                                         'changed_during_scan')),
    pending_hash       INTEGER NOT NULL DEFAULT 0 CHECK (pending_hash IN (0, 1)),
    first_seen_scan_id INTEGER REFERENCES scans (id) ON DELETE SET NULL,
    last_seen_scan_id  INTEGER REFERENCES scans (id) ON DELETE SET NULL,
    first_seen_at      INTEGER NOT NULL,
    last_seen_at       INTEGER NOT NULL,
    last_verified_at   TEXT,
    UNIQUE (source_id, rel_path)
);

CREATE INDEX files_content ON files (content_id);
CREATE INDEX files_size ON files (size_bytes);
CREATE INDEX files_filename ON files (filename);
CREATE INDEX files_pending ON files (source_id, pending_hash);
