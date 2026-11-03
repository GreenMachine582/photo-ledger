[← Back to README](../README.md)

# 🔁 Scans and Rescans

## Saved scans

A scan is a saved selection of one or more sources. Pause one at any point and start another with a subset of those
sources, the same set or a different set. Work is saved to the shared catalogue, so a new scan reuses every file already
hashed, as long as its size and `mtime_ns` still match. Only one scan can process a source at a time.

A scan's review includes any pair with at least one file in its sources, including matches in other sources. Resolving a
pair resolves it in every scan.

## What a rescan does

| Change found | Result |
|---|---|
| File unchanged | Decisions stand, and nothing is queued |
| New file | Only its new pairs are queued |
| File moved or renamed in the same source | Same file ID, and decisions stand |
| File content changed | The file links to its new content, and only its affected pairs return as `needs_review` |
| File gone after a complete scan | Marked `missing`, and its open pairs close |
| Scan paused or interrupted, or source offline | Nothing is marked missing |
| Pair previously skipped | Stays skipped and open |
| Threshold changed | New pairs are queued, and decided pairs are kept |

Size and `mtime_ns` don't prove content is unchanged, so `scan --verify` re-hashes every file and reconciles differences.
