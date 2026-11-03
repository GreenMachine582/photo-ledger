# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A local-first photo catalogue: scan backups read-only, find duplicates and mismatches, review them side by side,
then organise safely. It runs on `127.0.0.1` for one person. Design details are in [docs/](docs/).

## Hard rules

1. **Never write to a source folder outside `actions/executor.py`.** Scanning, matching, reviewing and exporting are
   read-only with respect to sources. Undo goes through the executor too.
2. **Never add a delete operation.** Rejected copies stay where they are, or move to quarantine if the source opted in.
3. **Never commit real photos or a populated database.** This repo is public. Test images come from
   `scripts/make_fixtures.py`. Real paths don't belong in tests, docs or issues either.

## Design rules

- Scanning, matching and file actions must not import FastAPI, so the CLI works without the web layer.
- Decisions belong to stable pairs, not to scans or sessions. A rescan must never reopen a finished review
  unless the file's content changed. See [docs/rescans.md](docs/rescans.md).
- A paused or interrupted scan, or an offline source, must never mark a file as missing.
- Don't treat size and modified time as proof of identity. Only a BLAKE3 hash is.
- Similar matches are never resolved automatically. Bulk actions apply to exact duplicates only.
- The image route serves only files registered in the database, never a path from the URL.
- Every state-changing route depends on `require_csrf`.
- The app binds to `127.0.0.1` only. Don't add an option to change that.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
.venv/bin/photo-ledger serve
```

On Windows the tools are in `.venv/Scripts/`. The project skills in `.claude/skills/` cover the workflow:
`/next-task` picks up work, `/check` runs the checks CI runs and `/open-pr` opens or updates a PR.

## Conventions

- `src/` layout, numbered SQL migrations, standard library `sqlite3`.
- Pages use `gth-*` macros, not Bootstrap or HTMX directly. See greentechhub-ui's docs.
- Bump the three GTH pins together, to tags only. See [CONTRIBUTING.md](CONTRIBUTING.md).
- Commits and PR titles are Conventional Commits.
- [TODO.md](TODO.md) holds open work only. Remove an item when it ships.
