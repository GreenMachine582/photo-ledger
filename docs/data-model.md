[← Back to README](../README.md)

# 🗃️ Data Model

Content is separate from file locations, so one image with five copies is one `contents` row and five `files` rows.

| Table | Purpose |
|---|---|
| `sources` | A mapped drive or folder, its device details and its quarantine setting |
| `scans` | A saved scan you can pause, resume or leave behind |
| `scan_sources` | Each source's progress within a scan, including where to resume |
| `scan_errors` | Files that failed to read, decode or parse |
| `contents` | One row per unique file content: BLAKE3, pHash, dimensions, capture date and EXIF |
| `files` | One row per copy on disk, with a path relative to its source |
| `collections` | An album name, editable by you |
| `collection_folders` | Which folder maps to which collection |
| `review_pairs` | Two items to compare, shared by all scans |
| `decisions` | Append-only review history |
| `plans` | A batch of file operations |
| `plan_actions` | The operation journal, used for recovery and undo |

## Notes

- **File status:** `present`, `missing`, `unsupported`, `corrupt`, `unreadable` or `changed_during_scan`. An EXIF failure
  is recorded separately, as the image itself may be fine.
- **Capture date:** Keep the source of the chosen date, and never present a restore date as the capture date. PNG files
  often have no EXIF, so they can stay undated.
- **Timestamps:** Use `mtime_ns`. Use birth time only where the OS provides it, as `ctime` isn't a creation time on
  every system.
- **Device details:** Storage type, volume identifier, label, filesystem and capacity are best-effort.

Exact columns live in the migrations, which arrive in M1.
