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

Keeping one side rejects the other: the file in an exact pair, or every copy of the image in a similar or
name-conflict pair. The rejected item's other open pairs close with it, so N copies of a photo take N − 1 reviews.
Deciding a pair again replaces the earlier decision.

`Z` is not the same as `undo` on the command line, which reverses an applied plan. Reviewing never touches files:
decisions only build a plan.

## Starting a session

| Choice | Options |
|---|---|
| Scope | A saved scan, or all scans |
| Show | Open pairs, new since the scan last ran, skipped, or needs review |
| Kind | Exact, similar or name conflict |
| Matches | Any match, or only matches inside the scan's sources |

A session is just these choices, kept in the page's address, such as `/review?scan=Old%20drives&show=skipped`, so you
can bookmark one or switch at any time. "Any match" includes a pair when at least one copy is in the scan's sources;
"only inside" needs a copy of both sides there. "New since the scan last ran" lists open pairs created since the scan's
latest round started. Pairs are shown exact duplicates first, then similar images, then name conflicts.

`Z` undoes the most recent decision anywhere, along with the pairs it closed, and goes back to that pair. Press it
again to step further back.

Decisions are stored per pair, not per scan or session. Resolving a pair in one scan resolves the same pair everywhere
else. See [rescans.md](rescans.md).

## Other pages

- **Overview** (`/`): File and photo counts, duplicated space, space marked for the plan by your decisions, and how
  many pairs are open, skipped, needing review and decided. It lists each source with its online state and last scan,
  and each scan with a link to review it, or to remove it once you no longer need it. Removing a scan keeps its
  sources, catalogued files, pairs and decisions, and asks you to confirm.
- **Sources** (`/sources`): Map a folder or drive by typing its path and a label. Check whether each source is
  connected, on the volume it was mapped on, one at a time or all at once. Reconnect a source at its new drive letter
  or mount path: leave the path empty to find it by its volume, or type it. The page shows the state from the last
check and never probes a drive itself, as some drives are slow to answer. Set its keeper priority, and turn its
  quarantine on or off. Rename a source, or forget it: forgetting removes its catalogued files, its exact pairs and
  the decisions on them from the ledger, and leaves the folder as it is. Type its label to confirm. A source with files
  in an applied plan can be forgotten only once that plan is undone, and its rows in the undone journals go with it. A
  source with files copied into the library can't be forgotten while that library is current. It's
  the same as `photo-ledger source`, with the same refusals: overlapping folders, a different drive, or a quarantine
  inside a source. The page stores the paths you type or pick in its folder explorer, which lists
  folder names only, and never serves or changes a folder.
- **Scans** (`/scans`): Save a scan of some sources, then run, pause and resume it with live progress, offline
  sources and recent errors. The same as `photo-ledger scan`, and only ever reading.
- **Reports** (`/reports`): Every report from `photo-ledger report`, including the date, name and single-source
  mismatches, scoped to a scan and downloadable as CSV. See [duplicate-detection.md](duplicate-detection.md).
- **Collections** (`/collections`): Rename, merge or hide collections. See [collections.md](collections.md).
- **Plan** (`/plan`): Every proposed move, its total size and a dry-run result, with an explicit confirm step. Copies
  in sources without a quarantine are counted as staying where they are, and a copy whose picture would be left with
  no kept copy is left alone. Viewing the page runs a quick dry run without recording it. **Rebuild plan** rebuilds the
  plan from your decisions, and **Dry run with hashes** hashes every file. Both write only to the catalogue. **Apply
  plan** appears only after a clean recorded dry run, and asks you to confirm. **Undo plan** puts back every file the
  last applied plan moved, after you confirm, through the executor as `photo-ledger undo` does. A plan or undo that
  was interrupted shows **Finish plan** or **Finish the undo** instead, which retries what's left after recovery has
  checked it. Bulk actions apply to exact duplicates only, and always go through this page. `photo-ledger plan`,
  `apply` and `undo` do the same from the command line.
- **Library** (`/library`): Choose the library's folder and its `year` or `original` layout, then **Plan** and
  **Build**, the same as `photo-ledger library`. The page shows whether the folder is connected, how many pictures are
  built, planned and waiting for review, the read-only dry-run problems, failed copies and pictures no longer chosen.
  **Build** appears only when something is planned and the dry run is clean, and asks you to confirm. Choosing a new
  folder starts a new, empty library and leaves the old folder as it is.

## Building it

Run `photo-ledger serve` and open <http://127.0.0.1:8765/review>. Each side shows a cached preview, which opens the
original when clicked, and the differences between the two are highlighted. Images come from `/files/<id>/preview` and
`/files/<id>/original`, looked up by ID in the catalogue. Previews are cached in the data folder's `thumbnails`, so an
offline source can still be reviewed.

Pages use `gth-*` macros for the shell, tables, filters, modals and toasts. gth-ui has no image comparison component, so
that view is built in this repo. It moves upstream only if another service needs it. `web/static/` holds only the
comparison CSS and keyboard shortcuts.

The image route serves only files registered in the database, never a path taken from the URL. Originals stay untouched,
and the thumbnail cache can be deleted and rebuilt at any time. When a source is offline, reviews use its cached
thumbnails.
