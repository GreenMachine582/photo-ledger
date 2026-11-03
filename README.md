# 🗂️ photo-ledger

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Status: Early Development](https://img.shields.io/badge/Status-Early%20Development-blue.svg)](TODO.md)
[![Python](https://img.shields.io/badge/Python-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![pytest](https://img.shields.io/badge/pytest-0A9EDC.svg?logo=pytest&logoColor=white)](https://docs.pytest.org/)

## 🎯 Objective

Turn several overlapping photo backups into one clean, trustworthy library, without ever risking a photo.
Map the drives and folders to scan, review duplicates side by side, and rescan without repeating finished reviews.

It runs on your own machine, on `127.0.0.1`. Scans are read-only, nothing is ever deleted, and originals stay
untouched unless you opt in to quarantine for a source.

> [!NOTE]
> **Status: M0 done.** The repo, app shell, health check and release automation are in place. Scanning arrives in M1. See [TODO.md](TODO.md).

## 🧩 Scope

| Area | MVP |
|---|---|
| Sources | Internal disks, USB drives, network folders and removable media, with device details recorded |
| Scans | Saved selections of sources that can be paused, resumed and overlapped without losing progress |
| Formats | JPEG and PNG. Other files are counted as unsupported |
| Detection | Exact duplicates, visually similar images and mismatches between copies |
| Review | One pair at a time, for a scan or all scans. Resolving a pair resolves it everywhere |
| Changes | A reversible plan with a dry run, a journal and crash recovery |
| Library | Folder names kept as collections, then exported as folders, XMP sidecars, CSV and JSON |

**Not in the MVP:** HEIC, WebP, RAW and video, cloud sync, face or object recognition, photo editing and multi-user
accounts.

> [!WARNING]
> Keep a separate copy of anything irreplaceable while testing. This tool shouldn't be your only safety net.

## 🚀 Quick start

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/photo-ledger serve
```

Then open <http://127.0.0.1:8765>. On Windows, use `.venv\Scripts\photo-ledger serve`.

The catalogue and thumbnails live in your OS application data folder, never in this repo. Set
`PHOTO_LEDGER_DATA_DIR` to move them, and `PHOTO_LEDGER_PORT` to change the port.

## 📚 Docs

| Doc | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 🏗️ Components and the scan → review → apply flow |
| [docs/data-model.md](docs/data-model.md) | 🗃️ Tables and what each one is for |
| [docs/duplicate-detection.md](docs/duplicate-detection.md) | 🔍 Pipeline, pair kinds and keeper scores |
| [docs/rescans.md](docs/rescans.md) | 🔁 Sources, saved scans, and how decisions survive a rescan |
| [docs/review.md](docs/review.md) | 👀 The comparison screen, keys, sessions and other pages |
| [docs/collections.md](docs/collections.md) | 🏷️ Folder names, tags and Immich |
| [docs/safety.md](docs/safety.md) | 🛡️ File safety and local-only protections |
| [docs/testing.md](docs/testing.md) | 🧪 Fixtures and test strategy |

## 🗺️ Status & Roadmap

Open work is in [TODO.md](TODO.md). Shipped versions are in `CHANGELOG.md` and on the
[Releases page](https://github.com/GreenMachine582/photo-ledger/releases). Branches, PRs and releases are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 Licence

[MIT](LICENSE) © 2026 Matthew Johnson
