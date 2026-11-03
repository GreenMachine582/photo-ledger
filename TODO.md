[← Back to README](README.md)

# ✅ TODO

Open work only: remove an item when it ships. Shipped work is in `CHANGELOG.md`.

## M0 Repo setup

- [ ] Apply the rulesets with `scripts/apply-rulesets.sh`
- [ ] Decide whether to install the `gth-release-bot` app here, so release PRs trigger CI
- [ ] Enable Renovate for this repo

## M1 Map and scan

- [ ] Numbered SQL migrations and the SQLite connection setup
- [ ] `scripts/make_fixtures.py` for generated test images
- [ ] Source mapping with device details, reconnecting and overlap refusal
- [ ] Saved scans that pause, resume and overlap
- [ ] Walk, BLAKE3, EXIF, capture date and pHash for JPEG and PNG
- [ ] `scan --verify` and CSV export

## M2 Detect

- [ ] Stable pairs: exact, similar and name conflict
- [ ] Mismatch reports and explained keeper scores
- [ ] Collections from folder names

## M3 Review

- [ ] Side-by-side comparison view with keyboard actions
- [ ] Scan and all-scan sessions, skip list and decision undo
- [ ] Collections page and overview
- [ ] Check that the Secure CSRF cookie works on `127.0.0.1` in Firefox and Edge (confirmed in Chromium)

## M4 Apply safely

- [ ] Plan and dry run
- [ ] Opt-in quarantine on any device
- [ ] Journal, recovery and undo through the executor

## M5 Organise

- [ ] Destination library with year-based or original folder layouts
- [ ] Date fixes and XMP sidecars

## M6 Immich export

- [ ] Test sidecars and tags on a small sample
- [ ] Check whether an external library suits this better than uploading
- [ ] Optional album export through Immich's API
