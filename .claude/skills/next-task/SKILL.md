---
name: next-task
description: Pick up the next piece of work in photo-ledger. Syncs main, reads TODO.md, checks nothing is already in flight, reads the docs the item touches and creates a correctly named branch. Use when asked to "pick up work", "start the next milestone", "what's next" or to start a named TODO item.
---

# Pick up the next task

Work through these steps in order and report briefly as you go.

## 1. Sync

```bash
git status --short          # stop and ask if the tree is dirty
git fetch --prune
git switch main && git pull --ff-only
```

Never rebase or force-push anything (see CONTRIBUTING.md).

## 2. Choose the item

- Read `TODO.md`. It holds open work only, grouped by milestone (`## M<n> <name>`), each with a **Done when** line.
- If the user named an item or milestone, use that. Otherwise take the earliest milestone with unchecked items.
- A milestone can go in one `feat` PR with one commit per TODO line when the user asks for that. Otherwise, use one
  PR per item.

## 3. Check it isn't already in flight

```bash
gh pr list --state open
git branch -r
```

If an open PR or remote branch already covers the item, stop and tell the user instead of starting over.

## 4. Load the context

- Read `CLAUDE.md`, both hard rules and design rules, and follow them throughout.
- Read the docs the item touches. `docs/architecture.md` maps packages to milestones. `docs/data-model.md`,
  `docs/rescans.md`, `docs/duplicate-detection.md`, `docs/review.md`, `docs/safety.md`, `docs/collections.md` and
  `docs/testing.md` cover the rest.
- Look at the existing code in `src/photo_ledger/` and `tests/` before you design anything new.

## 5. Branch

Name it `<area>/<short-description>`, where the area is the package or topic, such as `scanner/resumable-walk`,
`db/migrations` or `docs/rescans`.

```bash
git switch -c <area>/<short-description>
```

## 6. Report

Give the user:
- the item(s) picked and the milestone's **Done when** criteria, which become the acceptance tests
- the branch name
- a short plan: the files to add or change, the tests that prove each **Done when** clause, and the docs to update

Then start the work. Use the `check` skill before each commit and the `open-pr` skill when the work is ready.
