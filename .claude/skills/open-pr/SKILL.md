---
name: open-pr
description: Open or update a pull request for photo-ledger the way CONTRIBUTING.md requires. Runs the checks, audits the diff against the CLAUDE.md hard rules, confirms TODO.md and the docs are updated, writes a Conventional Commit title and the PR template body, then pushes and creates or updates the PR. Use when asked to "open a PR", "raise a PR", "push this up" or "update the PR".
---

# Open or update a PR

## 1. Preconditions

- You're on a feature branch, never `main`.
- The work is committed. Commits are Conventional Commits with a first line of at most 100 characters and a body that
  explains why. They're signed (`git log --show-signature -1` should show a good signature), which is required on
  `main`.
- End every commit message with the attribution line from the current session's instructions.

## 2. Run the checks

Use the `check` skill. Don't continue until it passes.

## 3. Audit the diff against the hard rules

```bash
git diff origin/main...HEAD --stat
git diff origin/main...HEAD
```

Stop and fix anything that breaks these:

1. **No source writes outside `actions/executor.py`.** Look for `open(..., "w"|"a"|"r+")`, `write_bytes`,
   `write_text`, `os.utime`, `rename`, `replace`, `shutil.move` or `shutil.copy*` aimed at a source path anywhere
   else. Tests and `scripts/make_fixtures.py` may write, but only to `tmp_path` or a directory they were given.
2. **No delete operations on user files.** Look for `os.remove`, `os.unlink`, `Path.unlink`, `shutil.rmtree` and
   `send2trash`.
3. **Nothing private.** No staged images, `*.db` files or real paths:
   `git diff origin/main...HEAD --name-only | grep -Ei '\.(jpe?g|png|heic|db)$'` must print nothing.
4. The design rules: no FastAPI imports in `db/`, `sources/`, `scanner/`, `matching/` or `actions/`; every new
   state-changing route depends on `require_csrf`; nothing binds anywhere except `127.0.0.1`.

## 4. Docs and TODO

- Remove each TODO.md line this PR ships. Remove a whole milestone heading once it's empty.
- Code and the docs that describe it go in the same PR. Check `docs/` and README.md for anything now out of date,
  such as tables, CLI commands and columns.
- Don't touch CHANGELOG.md or the version. release-please owns them.

## 5. Title and body

- The title is a Conventional Commit of at most 100 characters, such as `feat: map sources and run resumable scans
  (M1)`. It becomes the changelog line when the PR is squash-merged, and the `pr-title` check enforces it. Add `!`
  for a breaking change.
- The body follows `.github/pull_request_template.md`:

```markdown
## Summary

<what changes and why, plus a bullet per commit or area>

## How it was verified

<checks run and their results, manual runs, and for anything touching files what happened to the fixtures>

## Breaking changes

<None, or what breaks and how to migrate>

<PR attribution line from the session instructions>
```

Write the body to a file in the scratchpad and pass it with `--body-file`. Don't inline it.

## 6. Push and create or update

```bash
git push -u origin HEAD
gh pr view --json url,state 2>/dev/null   # is there a PR already?
gh pr create --base main --title "<title>" --body-file <body.md>      # if none
gh pr edit --title "<title>" --body-file <body.md>                    # if one exists
```

To update an open PR, add commits or merge `main` into the branch. Never rebase, amend pushed commits or force-push.

## 7. Report

Give the user the PR URL and run `gh pr checks` (add `--watch` only if they want to wait). Report any failing check with
its log (`gh run view <id> --log-failed`).
