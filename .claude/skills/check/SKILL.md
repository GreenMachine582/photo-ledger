---
name: check
description: Run photo-ledger's lint, format check and tests from the project venv, the same checks CI runs. Use before committing, before opening a PR, or when asked to "run the checks", "lint" or "run tests". Pass "fix" to apply ruff's formatting and safe fixes first.
---

# Run the checks

CI (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on Ubuntu with Python 3.12. Run the same checks
locally, plus the format check.

## 1. Find or create the venv

The tools live in `.venv/Scripts/` on Windows and in `.venv/bin/` elsewhere.

```bash
if [ -d .venv/Scripts ]; then BIN=.venv/Scripts; else BIN=.venv/bin; fi
```

If `.venv` is missing, create it. Prefer `uv` when it's installed:

```bash
uv venv && uv pip install -e ".[dev]"
# or, without uv:
python -m venv .venv && $BIN/python -m pip install -e ".[dev]"
```

If `pyproject.toml` changed since the venv was built, for example by a new dependency, re-run the install line.

## 2. Fix first (only when asked with `fix`)

```bash
$BIN/ruff format . && $BIN/ruff check --fix .
```

## 3. Check

```bash
$BIN/ruff check . && $BIN/ruff format --check . && $BIN/pytest -q
```

## 4. Report

Report pass or fail for each step. On a failure, show the relevant output and fix the cause. Never skip, `xfail` or
delete a test to make it pass, and never weaken an assertion. Tests only ever touch `tmp_path`, and no real photos or
paths go in them.
