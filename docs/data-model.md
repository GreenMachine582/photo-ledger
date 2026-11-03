[← Back to README](../README.md)

# 🗃️ Data Model

Content is separate from file locations, so one image with five copies is one `contents` row and five `files` rows.
Every decision hangs on a stable pair, so a rescan can add work without undoing finished reviews.

| Table | Key columns | Purpose |
|---|---|---|
| `sources` | `id`, `label`, `root_path`, `source_type`, `volume_id`, `volume_root`, `device_label`, `filesystem`, `capacity_bytes`, `priority`, `state`, `quarantine_enabled`, `quarantine_path`, `quarantine_volume_id` | A mapped drive or folder, its device details and its quarantine setting |
| `scans` | `id`, `name`, `status`, `created_at`, `last_opened_at` | A saved scan you can pause, resume or leave behind |
| `scan_sources` | `scan_id`, `source_id`, `mode`, `status`, `stage`, `started_at`, `finished_at`, `file_count`, `total_bytes`, `resume_path`, `pass_started_at`, `heartbeat_at` | Each source's progress within a scan, including where to resume |
| `scan_errors` | `id`, `scan_id`, `source_id`, `rel_path`, `stage`, `message` | Files that failed to read, decode or parse |
| `contents` | `id`, `blake3`, `size_bytes`, `phash`, `width`, `height`, `format`, `captured_at`, `capture_offset`, `capture_date_source`, `camera_make`, `camera_model`, `gps_lat`, `gps_lon`, `exif_json`, `exif_error`, `decode_error` | One row per unique file content |
| `files` | `id`, `source_id`, `content_id`, `rel_path`, `filename`, `extension`, `size_bytes`, `mtime_ns`, `birthtime_ns`, `status`, `pending_hash`, `first_seen_scan_id`, `last_seen_scan_id`, `first_seen_at`, `last_seen_at`, `last_verified_at` | One row per copy on disk |
| `collections` | `id`, `name`, `parent_id`, `hidden` | An album name, editable by you |
| `collection_folders` | `source_id`, `folder_path`, `collection_id` | Which folder maps to which collection |
| `review_pairs` | `id`, `pair_key`, `kind`, `left_id`, `right_id`, `distance`, `evidence`, `score_reasons`, `status`, `first_seen_scan_id`, `last_seen_scan_id`, `created_at`, `updated_at` | Two items to compare, shared by all scans |
| `decisions` | `id`, `pair_id`, `action`, `rejected_kind`, `rejected_id`, `caused_by`, `previous_status`, `decided_at`, `superseded_at` | Append-only review history |
| `plans` | `id`, `status`, `undoes_plan_id`, `created_at`, `checked_at`, `applied_at` | A batch of file operations |
| `plan_actions` | `id`, `plan_id`, `file_id`, `op`, `from_path`, `to_path`, `quarantine_root`, `quarantine_volume_id`, `expected_blake3`, `size_bytes`, `state`, `started_at`, `finished_at`, `error` | The operation journal, used for recovery and undo |

## Notes

- **Paths:** Stored relative to `sources.root_path`, so a source can move to a new drive letter or mount path.
- **Indexes:** Unique on `files(source_id, rel_path)`, `contents(blake3)` and `review_pairs(pair_key)`, plus indexes on
  `size_bytes`, `filename` and `captured_at`.
- **File status:** `present`, `missing`, `unsupported`, `corrupt`, `unreadable` or `changed_during_scan`. An EXIF failure
  is recorded separately, as the image itself may be fine.
- **Capture date:** Keep the source of the chosen date, such as `DateTimeOriginal`, and never present a restore date as
  the capture date. PNG files often have no EXIF, so they can stay undated.
- **Timestamps:** Use `mtime_ns`. Use birth time only where the OS provides it, as `ctime` isn't a creation time on
  every system.
- **Device details:** Storage type, volume identifier, label, filesystem and capacity are best-effort.

- **Scan passes:** Each run of a source within a scan is a pass, starting at `pass_started_at`. A file whose
  `last_seen_at` is older than a finished pass has gone, and `heartbeat_at` shows whether a running pass is still alive.
- **Contents:** A file whose content failed to decode has a `decode_error` and the status `corrupt`. Its BLAKE3 is
  still recorded, so exact copies of a broken file are still found.

- **Collections:** Unique by name within their parent, ignoring case. `collection_folders` maps a source's folder to
  its deepest collection, and rows are only ever added, so renames and merges survive rescans.
- **Decisions:** `keep_left` and `keep_right` reject the other side: a file for an exact pair, a content (every copy)
  for the others. The rejected item's other open pairs close as `closed` rows pointing at the decision through
  `caused_by`. Undo and re-deciding supersede rows rather than editing them, and restore `previous_status`.
- **Plans:** There's at most one `draft`, rebuilt from the active decisions on resolved pairs whenever you plan. A plan
  is applied only after a clean dry run (`checked_at`) and while no decision is newer than it. Its `status` is `draft`,
  `applying`, `applied`, `incomplete` or `undone`. Undo is a plan of its own, with `restore` actions and
  `undoes_plan_id` pointing at the plan it reverses.
- **Plan actions:** `op` is `quarantine` or `restore`, and `state` is `pending`, `started`, `done` or `failed`.
  `from_path` and `to_path` are relative to the source root or to `quarantine_root`, which is copied from the source
  with its volume when the plan is built, so undo still finds a file after the quarantine setting changes. Quarantined
  copies go to `plan-<id>/<source label>/<rel_path>`.
- **Pairs:** `left_id` and `right_id` are file IDs for `exact` pairs and content IDs for `similar` and `name_conflict`.
  `status` is `open`, `skipped`, `resolved`, `needs_review` or `obsolete`, the last for a pair that stopped matching,
  such as when a copy went missing. An exact pair's `evidence` is its BLAKE3, so a resolved pair whose files changed
  content comes back as `needs_review`.

The migrations in `src/photo_ledger/db/migrations/` are the source of truth. `0001` creates the M1 tables, `0002`
adds `review_pairs`, `0003` adds `collections` and `collection_folders`, `0004` adds `decisions`, and `0005` adds
`plans` and `plan_actions`.
