-- M5: manual capture dates and library sidecars. A date fix belongs to a content, so every copy
-- shares it and no rescan overwrites it. It never changes an original: it's applied only to the
-- library copy's file date and its XMP sidecar.
--
-- sidecar_blake3 is the hash of the sidecar the executor last wrote. A sidecar is replaced only
-- while it still has that hash, so a sidecar you've edited is never overwritten. applied_date is
-- the capture date last given to the library copy as its file date.

CREATE TABLE date_fixes (
    content_id  INTEGER PRIMARY KEY REFERENCES contents (id),
    captured_at TEXT    NOT NULL,
    set_at      TEXT    NOT NULL
);

ALTER TABLE library_entries ADD COLUMN sidecar_blake3 TEXT;
ALTER TABLE library_entries ADD COLUMN applied_date TEXT;
