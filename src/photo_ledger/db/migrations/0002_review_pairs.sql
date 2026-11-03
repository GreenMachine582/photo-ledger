-- M2: stable review pairs, shared by every scan.
-- For kind 'exact', left_id and right_id are files.id. For 'similar' and 'name_conflict' they are contents.id.
-- The status list already includes M3's decision states, as SQLite can't alter a CHECK constraint.

CREATE TABLE review_pairs (
    id                 INTEGER PRIMARY KEY,
    pair_key           TEXT    NOT NULL UNIQUE,
    kind               TEXT    NOT NULL CHECK (kind IN ('exact', 'similar', 'name_conflict')),
    left_id            INTEGER NOT NULL,
    right_id           INTEGER NOT NULL,
    distance           INTEGER,
    evidence           TEXT,
    score_reasons      TEXT,
    status             TEXT    NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'skipped', 'resolved', 'needs_review', 'obsolete')),
    first_seen_scan_id INTEGER REFERENCES scans (id) ON DELETE SET NULL,
    last_seen_scan_id  INTEGER REFERENCES scans (id) ON DELETE SET NULL,
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL,
    CHECK (left_id != right_id)
);

CREATE INDEX review_pairs_kind_status ON review_pairs (kind, status);
CREATE INDEX review_pairs_left ON review_pairs (left_id);
CREATE INDEX review_pairs_right ON review_pairs (right_id);
