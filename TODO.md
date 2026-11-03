[← Back to README](README.md)

# ✅ TODO

Open work only: remove an item when it ships. Shipped work is in `CHANGELOG.md`. Each milestone is useful alone, and
nothing can change your files until M4.

## M1 Map and scan

Done when a paused scan resumes, a new overlapping scan reuses its hashes, changed files reconcile, an offline source
marks nothing missing, and source files are unchanged. Build it against generated fixtures before pointing it at a real
backup, and keep a separate copy of anything irreplaceable.

- [ ] Saved scans that pause, resume and overlap
- [ ] Walk, BLAKE3, EXIF, capture date and pHash for JPEG and PNG
- [ ] `scan --verify` and CSV export

## M2 Detect

Done when a read-only report matches a hand-checked sample, and rescanning the same files creates no new pairs.

- [ ] Stable pairs: exact, similar and name conflict
- [ ] Mismatch reports and explained keeper scores
- [ ] Collections from folder names

## M3 Review

Done when decisions survive a restart, a pair resolved in one scan is resolved in the others, and a rescan after adding
files queues only the new pairs.

- [ ] Side-by-side comparison view with keyboard actions
- [ ] Scan and all-scan sessions, skip list and decision undo
- [ ] Collections page and overview
- [ ] Check that the Secure CSRF cookie works on `127.0.0.1` in Firefox and Edge (confirmed in Chromium)

## M4 Apply safely

Done when a plan applied and undone restores the fixture set exactly, including across volumes, and a simulated crash
halfway never reports the plan as complete.

- [ ] Plan and dry run
- [ ] Opt-in quarantine on any device
- [ ] Journal, recovery and undo through the executor

## M5 Organise

Done when a clean library builds from approved keepers, with originals untouched by default and collections intact.

- [ ] Destination library you choose, with year-based or original folder layouts
- [ ] Date fixes and XMP sidecars

## M6 Immich export

Done when a test library shows the same albums and tags in Immich as in the ledger.

- [ ] Test sidecars and tags on a small sample
- [ ] Check whether an external library suits this better than uploading
- [ ] Optional album export through Immich's API
