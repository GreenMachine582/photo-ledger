[← Back to README](../README.md)

# 👀 Review

The main screen shows one pair at a time, side by side with the differences highlighted, and it works from the keyboard.
Every decision saves immediately, so you can stop at any point and pick up where you left off.

```text
┌─ Pair 128 of 2,431 ─ Scope: All scans ─ Similar (distance 3) ──────────────┐
│ ┌──────── LEFT (suggested) ──────┐ ┌──────────── RIGHT ───────────────┐  │
│ │            [image]             │ │             [image]              │  │
│ └────────────────────────────────┘ └──────────────────────────────────┘  │
│ Backup-2019/Holiday/IMG_0412.jpg    Old-PC/Pictures/IMG_0412 (1).jpg     │
│ 4032 x 3024 · 3.2 MB                1600 x 1200 · 410 KB                 │
│ 2019-07-14 10:32                    2019-07-14 10:32                     │
│ Suggested: higher resolution, full EXIF, trusted source                  │
├──────────────────────────────────────────────────────────────────────────┤
│ [A] Keep left   [D] Keep right   [B] Keep both   [S] Skip   [Z] Undo     │
└──────────────────────────────────────────────────────────────────────────┘
```

## Keys

| Key | Action | Result |
|---|---|---|
| `A` | Keep left | The right copy is marked for the plan |
| `D` | Keep right | The left copy is marked for the plan |
| `B` | Keep both | The pair closes as not a duplicate and won't come back |
| `S` | Skip | The pair stays open and moves to the skipped list, to return to later |
| `Z` | Undo | Reverts the last review decision, without touching any files |

`Z` is not the same as `undo` on the command line, which reverses an applied plan. Reviewing never touches files:
decisions only build a plan.

## Starting a session

| Choice | Options |
|---|---|
| Scope | A saved scan, or all scans |
| Show | Open pairs, new since the scan last ran, skipped, or needs review |
| Kind | Exact, similar or name conflict |
| Matches | Any match, or only matches inside the scan's sources |

Decisions are stored per pair, not per scan or session. Resolving a pair in one scan resolves the same pair everywhere
else. See [rescans.md](rescans.md).

## Other pages

- **Sources:** Map, relabel and reconnect drives and folders, set quarantine paths, and see each source's storage type,
  online state and last scan. Scans can be created, paused and resumed here too.
- **Overview:** File counts by source, reclaimable space, and how many pairs are open, skipped and decided.
- **Mismatches:** The date, name and single-source reports. See [duplicate-detection.md](duplicate-detection.md).
- **Collections:** Rename, merge or hide collections. See [collections.md](collections.md).
- **Plan:** Every proposed move, its total size and a dry-run result, with an explicit confirm step. Bulk actions apply
  to exact duplicates only, and always go through this page.

## Building it

Pages use `gth-*` macros for the shell, tables, filters, modals and toasts. gth-ui has no image comparison component, so
that view is built in this repo. It moves upstream only if another service needs it. `web/static/` holds only the
comparison CSS and keyboard shortcuts.

The image route serves only files registered in the database, never a path taken from the URL. Originals stay untouched,
and the thumbnail cache can be deleted and rebuilt at any time. When a source is offline, reviews use its cached
thumbnails.
