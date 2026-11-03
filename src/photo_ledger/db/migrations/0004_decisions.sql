-- M3: append-only review history. A decision is never edited, only superseded by an undo or a new
-- decision on the same pair. Keeping a copy rejects the other side: a file for an exact pair, a
-- content (and so every copy of it) for a similar or name-conflict pair. A rejection also closes the
-- rejected item's other open pairs, recorded as 'closed' rows pointing at the decision through
-- caused_by, so undoing the decision reopens them too.

CREATE TABLE decisions (
    id              INTEGER PRIMARY KEY,
    pair_id         INTEGER NOT NULL REFERENCES review_pairs (id),
    action          TEXT    NOT NULL
                    CHECK (action IN ('keep_left', 'keep_right', 'keep_both', 'skip', 'closed')),
    rejected_kind   TEXT    CHECK (rejected_kind IN ('file', 'content')),
    rejected_id     INTEGER,
    caused_by       INTEGER REFERENCES decisions (id),
    previous_status TEXT    NOT NULL,
    decided_at      TEXT    NOT NULL,
    superseded_at   TEXT,
    CHECK ((rejected_kind IS NULL) = (rejected_id IS NULL)),
    CHECK ((action = 'closed') = (caused_by IS NOT NULL))
);

CREATE INDEX decisions_pair ON decisions (pair_id);
CREATE INDEX decisions_caused_by ON decisions (caused_by);
CREATE INDEX decisions_active ON decisions (superseded_at, id);
