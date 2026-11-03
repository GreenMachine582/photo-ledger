-- M2: collections named after folders, kept in the ledger because folders may disappear when
-- duplicates are consolidated. A folder maps to its deepest collection, and collections nest by parent_id.

CREATE TABLE collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    parent_id  INTEGER REFERENCES collections (id) ON DELETE CASCADE,
    hidden     INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    created_at TEXT    NOT NULL
);

CREATE UNIQUE INDEX collections_name ON collections (COALESCE(parent_id, 0), name COLLATE NOCASE);

CREATE TABLE collection_folders (
    source_id     INTEGER NOT NULL REFERENCES sources (id),
    folder_path   TEXT    NOT NULL,
    collection_id INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, folder_path)
);

CREATE INDEX collection_folders_collection ON collection_folders (collection_id);
