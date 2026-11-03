[← Back to README](../README.md)

# 🔁 Sources, Scans and Rescans

## Mapping sources

Add a source in the UI or with `source add <path> --label <name>`. A source can be an internal disk, an external USB
drive, a network folder or removable media. The same scanner handles all four.

- **Device details:** The storage type, volume identifier, label, filesystem and capacity are recorded on a best-effort
  basis. Nothing depends on knowing them in advance.
- **Reconnecting:** If a drive letter or mount path changes, `source reconnect <label>` looks for the volume it was
  mapped on and asks you to confirm the new root. You can also pass the new root yourself. A root on a different
  volume is refused, so map that drive as a new source instead.
- **Online:** A source is online when its root exists and, where both are known, is on the volume it was mapped on.
  A different drive at the same letter counts as offline. `source list` shows each source's state.
- **Offline sources:** A disconnected source shows as offline, and its files are never marked missing. Reviews use
  cached thumbnails until it comes back.
- **Overlaps:** A mapping nested inside another source is refused, because it would record every file twice.

## Saved scans

A scan is a saved selection of one or more sources, such as `scan create "Old drives" --sources old-pc,usb-1`.

- **Backing out:** Pause a scan at any point and start another with a subset of those sources, the same set or a
  different set. You can resume the paused scan later.
- **Progress:** Work is saved to the shared catalogue, not to the scan. A new scan reuses every file already hashed, as
  long as its size and `mtime_ns` still match.
- **Conflicts:** Only one scan can process a source at a time.
- **Reviews:** A scan's review includes any pair with at least one file in its sources, including matches in other
  sources. Resolving a pair resolves it in every scan.

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
