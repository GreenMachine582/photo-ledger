[← Back to README](../README.md)

# 🏗️ Architecture

```
map sources ──► scan ──► detect ──► review ──► plan ──► dry run ──► apply ──► organise ──► export
                read-only ───────────────────────┘                  │
                                                                 journal
```

| Package | Responsibility | Milestone |
|---|---|---|
| `db/` | SQLite setup, numbered migrations, all queries | M1 |
| `sources/` | Mapped folders and their device details | M1 |
| `scanner/` | Resumable walk, metadata, hashes and verification | M1 |
| `matching/` | Exact, similar and mismatch checks, stable pairs, scores | M2 |
| `collections/` | Folder names to collections, and inheritance | M2 |
| `web/` | FastAPI app and pages, using the GTH packages | M0 onwards |
| `actions/` | Planner, executor, undo and recovery | M4 |
| `exports/` | CSV, JSON, XMP sidecars and the optional Immich export | M1, M5, M6 |

Scanning, matching and file actions don't import FastAPI, so the CLI works without the web layer.

## Key decisions

- **Browser UI, not Tkinter:** Browsers already render, zoom and cache images well.
- **SQLite, not CSV:** It handles indexes, safe partial updates and resumable scans. CSV is an export.
- **Stable pairs, not rebuilt groups:** A rescan can add pairs without disturbing earlier decisions.
- **Decisions build a plan:** Reviewing stays separate from touching files.
- **One database, many sources:** The database isn't portable between PCs, and the thumbnail cache is rebuildable.
