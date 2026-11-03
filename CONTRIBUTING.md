[← Back to README](README.md)

# 🤝 Contributing

## 🔀 Flow

```
branch ──► commits ──► PR to main ──► checks pass ──► squash merge ──► release PR ──► tag vX.Y.Z
```

- `main` is protected. Changes go through a PR, and every commit on it must be signed. Commit and push from Windows,
  where the signing key is.
- One change per PR. Code and the docs that describe it go in the same PR.
- Update an open PR by adding commits, or by merging `main` into the branch. Never rebase and force-push.
- There's no `dev` branch, as nothing else pins this project's releases.

**Branch names:** `<area>/<short-description>`, such as `scanner/resumable-walk` or `docs/rescans`.

## ✍️ Commit messages

[Conventional Commits](https://www.conventionalcommits.org), with a first line of at most 100 characters and a body
explaining why. The PR title follows the same format and becomes the changelog line, checked by `pr-title`.

| type | for |
|---|---|
| `feat` | new behaviour |
| `fix` | something that was broken |
| `docs` | documentation only |
| `chore` | housekeeping that changes no behaviour |
| `refactor` | restructuring with the same behaviour |
| `test` | tests only |
| `ci` | GitHub Actions workflows |
| `build` | tooling and dependencies |
| `perf` | faster or lighter, same behaviour |
| `revert` | undoing an earlier commit |

## 🚢 Releasing

release-please keeps a `chore(main): release X.Y.Z` PR open on `main`, with the version bump and changelog worked out
from the commits. Merging it tags `vX.Y.Z` and publishes the GitHub Release. Never bump versions or edit released
changelog sections by hand, and never move a `v*` tag.

## 📌 GTH pins

`pyproject.toml` pins greentechhub-core, -fastapi and -ui to tags. Bump them together, and only to tags. The core pin
must match the one gth-fastapi declares, and `tests/test_app.py` exercises the parts this app uses.

With the GTH repos checked out next to this one, `./scripts/use-local-gth.sh` runs the venv against those checkouts.
`--status` shows which is in use and `--undo` goes back to the pins. It changes only the venv, so CI still tests the pins.

## 🔒 Rules

Rulesets live in [`.github/rulesets/`](.github/rulesets/) and are applied with `scripts/apply-rulesets.sh`, which needs
an authenticated `gh` with admin rights. `main` needs a PR, green `test` and `pr-title` checks and signed commits, with
no force-pushes or deletion. `v*` tags can't be moved or deleted.
