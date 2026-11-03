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
> **Status: M5 done.** Manage sources in the browser and scan from the CLI. Then review pairs side by side at <http://127.0.0.1:8765/review> with keyboard actions, sessions per scan, a skip list and undo, plus the overview, collections and reports pages. Decisions build a plan that's dry-run, then applied with a journal, crash recovery and undo, moving rejected copies into an opt-in quarantine. Settled pictures are copied into a clean library by year or original path, with XMP sidecars that keep every collection, and with capture dates from EXIF or set by you. Immich export arrives in M6. See [TODO.md](TODO.md).

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

Scanning works from the command line. It only ever reads your files:

```bash
photo-ledger source add /media/usb-1/Photos --label usb-1
photo-ledger scan create "Old drives" --sources usb-1
photo-ledger scan run "Old drives"            # Ctrl+C pauses; run it again to resume
photo-ledger scan run "Old drives" --verify   # re-hash everything instead of trusting size and date
photo-ledger match                            # find duplicates, similar images and name conflicts
photo-ledger report pairs                     # also: summary, renamed, dates, single-source, corrupt, collections
photo-ledger export csv catalogue.csv
```

After reviewing, only an applied plan moves anything, and only for sources that opted in to quarantine:

```bash
photo-ledger source quarantine usb-1 /media/usb-1/Quarantine   # an existing folder outside every source
photo-ledger plan --verify    # build the plan from your decisions and dry-run it; changes nothing
photo-ledger apply            # move the rejected copies, verified by hash, after you confirm
photo-ledger undo             # put them back
```

Then build a clean library from the settled pictures. It only copies, so originals are never changed:

```bash
photo-ledger library set /media/library --layout year   # or --layout original
photo-ledger date set usb-1/Screenshots/shot_01.png 2020-02-03   # date a photo with no EXIF
photo-ledger library plan     # preview and dry-run the build
photo-ledger library build    # copy, verified by hash, with an XMP sidecar beside each file
```

Sources can also be mapped, checked and reconnected on the Sources page at <http://127.0.0.1:8765/sources>.

To try it without real photos, `python scripts/make_fixtures.py <empty-folder>` generates a test tree.

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
