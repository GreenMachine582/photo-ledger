[← Back to README](../README.md)

# 🏗️ Architecture

```
map sources ──► scan ──► detect ──► review ──► plan ──► dry run ──► apply ──► organise ──► export
                read-only ───────────────────────┘                  │
                                                                 journal
```

| Package | Responsibility | Milestone |
|---|---|---|
| `db/` | SQLite setup (WAL, foreign keys), numbered migrations, all queries | M1 |
| `sources/` | Mapped folders and their device details, and the folder names the browser's folder explorer lists (`folders.py`) | M1, v1 |
| `scanner/` | Resumable walk, metadata, hashes and verification | M1 |
| `matching/` | Exact, similar and mismatch checks, stable pairs, scores | M2 |
| `collections/` | Folder names to collections, and inheritance | M2 |
| `review/` | Decisions, review sessions and what the comparison view shows | M3 |
| `preferences.py` | The similar threshold and generic folder names saved on the Settings page, over the environment's | v1 |
| `activity.py` | What happened, for the Activity page and the notification bell, written through `db/activity.py` | v1 |
| `thumbnails.py` | Cached previews in the data folder, read from sources only | M3 |
| `web/` | FastAPI app and pages, using the GTH packages | M0 onwards |
| `actions/` | Planner, dry run, executor, undo and recovery. Only `executor.py` writes to sources, quarantines and the library | M4, M5 |
| `library/` | Which pictures are settled, the chosen copy of each, folder layouts, capture dates, keywords, what each sidecar holds, and the library's plan and dry run | M5 |
| `exports/` | CSV, JSON, XMP sidecars and the optional Immich export | M1, M5, M6 |

Scanning, matching and file actions don't import FastAPI, so the CLI works without the web layer. The CLI covers
`source`, `scan`, `match`, `report`, `serve`, `plan`, `apply`, `undo`, `library`, `date` and `export`. The browser
covers the same sources, match, review, plan, apply, undo, library and capture date steps, the CSV export, the match settings, and removing a saved scan. Every folder field (a source, its new location, a quarantine and the
library) can be typed or picked with a folder explorer that lists folder names one level at a time. Scans run as background
jobs on greentechhub-fastapi's `register_jobs` (`scanner/jobs.py`, `web/routes/scans.py`), each on its own connection,
with live progress. Pausing cancels the job, so the engine saves `paused` between files, as Ctrl+C does.

In the browser, the Overview names the next step, from mapping a source to a built library (`review/next_step.py`). The
navigation groups the pages under Catalogue (sources, photos, collections, reports), Review, Organise (plan,
library) and Settings. Each action redirects with its result as a toast, never as text in the URL. Long actions use busy buttons:
htmx posts the form, and `web/htmx.py` turns the redirect into a full page load. A refusal goes back to the page it
came from, as a toast, and a plain form gets a notice page. A form with a missing or malformed field is refused the
same way, with a sentence naming the field (`web/errors.py`) instead of FastAPI's JSON. Required fields are also
marked `required`, so the browser asks for them before anything is sent.

Runtime data lives outside the repo, in the OS application data folder from `platformdirs`: `photo-ledger.db`,
thumbnails and logs. Besides the GTH packages, the dependencies are `fastapi`, `uvicorn`, `typer` and `platformdirs`,
with `pillow`, `imagehash` and `blake3` added in M1, and `pytest`, `ruff` and `httpx` for development.

## Key decisions

| Decision | Choice | Why | Rejected |
|---|---|---|---|
| Review UI | FastAPI and greentechhub-ui, bound to `127.0.0.1` | Browsers already render, zoom and cache images well, and it matches hardware-ledger | Tkinter: manual image scaling and harder UI tests |
| Datastore | SQLite via the standard library `sqlite3` | Handles queries, indexes and resumable scans in one local file | CSV: no indexes or safe partial updates. `export --csv` is offered instead |
| Formats | JPEG (including MPO multi-picture JPEGs, read from their first frame) and PNG for the MVP | Keeps decoding, previews and tests small | HEIC, WebP, RAW and video, which can follow later |
| Storage | One scanner for all four storage types, with device details recorded per source | No storage assumptions are needed up front | A separate storage abstraction per type |
| Review unit | Stable pairs, not rebuilt groups | A rescan can add pairs without disturbing earlier decisions | Clustered groups, which change shape when a file is added |
| Review scope | One saved scan of any set of sources, or all scans | You can back out of a scan and start another without losing progress | Separate review data per scan |
| Rescans | Incremental by default, with a full verify mode | Fast repeat scans, plus a way to prove the catalogue is right | Trusting size and modified time forever |
| Skipping | `Skip` keeps a pair open to return to later | Nothing is lost or excluded | Permanent ignore rules |
| Deleting | Never delete. Moving a copy to quarantine is opt-in per source | Originals stay untouched by default, and a wrong decision stays recoverable | Direct delete or the recycle bin, which may not exist on external drives |
| Applying changes | Decisions build a plan, and `apply` runs it after a dry run | Reviewing stays separate from touching files | Moving files on a button click |
| Exact match | Size, then BLAKE3 | Size finds likely duplicates cheaply, and BLAKE3 is fast on large libraries | MD5 or SHA-1: slower or weaker, with no benefit here |
| Similar match | Perceptual hash, starting with pHash, always reviewed by hand | Catches resized and re-encoded copies, but can be wrong | Automatic resolution |
| Keeper suggestion | An explained score, shown with its reasons | You can see why a copy is suggested and overrule it | An unexplained score |
| Shared packages | greentechhub-fastapi, -ui and -core, each pinned to a tag | Reuses the shared logging, health, error pages, CSRF and app shell | Standalone FastAPI: fewer pins, but it rebuilds all of this |

## GTH packages

`web/app.py` calls `register_logging`, `register_core`, `register_health`, `register_csrf`,
`register_exception_handlers` and `register_error_pages`, plus `register_jobs` for scans and `register_audit` and
`register_notifications` for the Activity page and the notification bell. `register_auth` runs with
`AUTH_ADAPTER=single_user`, which `config.Settings` fixes: every request is the one local person, so notifications and
the activity log work with no sign-in, and there's no login page to fall back on. It skips `register_permissions`.
SQLite stays on `sqlite3`: `db/activity.py` implements core's notification and audit stores over it, and runs core's
contract suites in the tests. `activity.record` writes an entry and a notification for each scan outcome, applied or
undone plan, library build and source found offline. A scan records its own outcome, since a paused scan isn't a
finished job.

GTH's permissions are role-based and defined in code: `Permission("resource.action")` and `Role` in greentechhub-core,
and `require_permission` added to each route in greentechhub-fastapi. Only role membership is data (`ROLE_GROUPS`,
`ROLE_BOOTSTRAP` and the grants table). There's no rules file like Odoo's `ir.model.access.csv`, and no record rules
beyond `get_owned_or_404`. A rules file would protect nothing here, so the gate stays CSRF on every state-changing route,
the local-origin check and the trusted hosts. If the app ever had more than one user, it would use GTH's roles as they
are, not a rules file. Pins and upgrades are covered in [CONTRIBUTING.md](../CONTRIBUTING.md#-gth-pins).

## Settled questions

| Question | Decision |
|---|---|
| Should original backup folders ever be modified? | Only by opting in, with a configurable quarantine path per source that can be on another device |
| Should the database be portable between PCs? | No |
| Should thumbnails be regenerated? | Yes, the cache is rebuildable |
| Should decisions survive a database rebuild? | They can be exported as CSV and JSON |
| Should similar matches be resolved automatically? | No |
| Should exact duplicates be bulk-resolvable? | Yes, with explicit review and plan confirmation |
| Should original folder structures be preserved? | Yes, as an optional organisation mode |
| Should the app support multiple libraries? | No: one database with many sources |
| Should a scan's review include matches in other sources? | Yes, and resolving a pair resolves it in every scan |
| Should you be able to declare that sources are meant to hold the same files? | No |
| Should permissions come from a rules file, deny by default? | No: one local user. GTH's code-defined roles if that ever changes |
