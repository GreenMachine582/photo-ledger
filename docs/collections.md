[← Back to README](../README.md)

# 🏷️ Collections and Immich

Each folder name is a collection stored in the ledger, because the folder may disappear when duplicates are
consolidated. The keeper inherits the collections of every copy it replaces. For example, if `Japan 2019/IMG_0412.jpg`
and `Best of 2019/IMG_0412.jpg` are duplicates, the keeper stays in both collections.

- **Naming:** Use the deepest meaningful folder, keeping its parents as a hierarchy, so `Pictures/Holidays/2019/Japan`
  becomes `Holidays > 2019 > Japan`. Names match case-insensitively, so `holidays/2019/japan` on another drive joins
  the same collection.
- **Generic folders:** Leave out the source root, DCF camera folders such as `100CANON`, and generic names: `DCIM`,
  `Camera`, `Pictures`, `Photos`, `My Pictures` and `Camera Roll` by default. Change the list with
  `PHOTO_LEDGER_GENERIC_FOLDERS`, as JSON such as `["DCIM", "Pictures"]`. A folder with no meaningful name left has
  no collection.
- **Building:** `photo-ledger match` maps any new folder before matching, and `photo-ledger report collections` lists
  them. Mappings are only ever added, never rewritten.
- **Editing:** Rename, merge or hide collections on the Collections page. A rename that would clash with a sibling is
  refused, so merge instead. Merging moves the folders and sub-collections across, combining sub-collections with the
  same name. Only the ledger changes: no folder is renamed or moved. Mappings persist across rescans.
- **Undo:** Inherited collections come from decisions, so undoing a decision removes them too.

## Outputs

| Output | Gives you | Notes |
|---|---|---|
| Folders | A library people can browse, such as `YYYY/Collection/` or the original structure | A photo in several collections gets one main folder. The others are in the tags and CSV |
| XMP sidecars | Filterable tags in Immich and other photo apps | Originals stay byte-identical, so their hashes still match |
| Immich albums | Real albums, including a photo in more than one | Needs the optional export through Immich's API (M6) |
| CSV and JSON | Everything above, for your own scripts | Includes hash, path, collections and capture date |

## Building the library

`photo-ledger library set <folder> [--layout year|original]` chooses an existing folder outside every source and
quarantine. `library plan` previews the build and dry-runs it, and `library build` copies each picture in, verified
by its hash. Originals are never changed.

- **Which pictures:** Every picture that no decision rejects and that has no pair still open, skipped or needing
  review. The rest wait for review and are counted, so the library never holds an undecided duplicate. A picture
  whose copies can't be decoded is left out.
- **Which copy:** The best of its present copies that no decision rejects: the higher source priority, then the
  tidiest path. This is the same rule the reports use.
- **`year` layout:** `YYYY/<main collection>/<filename>`, using the EXIF capture date. A picture without one goes in
  `Undated/`, as a file date may only be the date it was restored. A collection that starts with the year itself
  isn't repeated, so a `2019` folder gives `2019/IMG_0001.jpg`.
- **`original` layout:** `<source label>/<path in the source>`.
- **Main collection:** The collection of the chosen copy's own folder, or else the first, alphabetically, of the
  collections it inherits from the copies it replaced. Hidden collections, and everything beneath them, are skipped.
- **Names:** A name already used, ignoring case, gets ` (2)`, ` (3)` and so on. Characters that Windows doesn't allow
  become `_`.
- **Rebuilding:** Only adds. Files already copied keep their place. A picture rejected since stays where it is and
  is reported. A layout can't change once files are copied, so a new layout needs a new folder.

## Tagging for Immich

Write `IMG_0412.jpg.xmp` beside each library file, with hierarchical tags in `digiKam:TagsList`, which Immich reads first:

- `Collections/Holidays/2019/Japan`
- `Sources/Old PC`

Immich uses the first tag field it finds and doesn't merge them, and sidecars take priority over embedded tags. Copy any
existing embedded keywords into the sidecar, or they'll stop showing.

## Getting photos into Immich

`immich upload --album` names albums from each file's parent folder. That suits simple libraries, but a photo in several
collections would land in only one album. The CLI docs don't cover uploading sidecars either, so test a small sample
first, including whether the tags arrive. A separate milestone (M6) adds the API export for full albums.

Immich's docs, checked on 3 November 2026:
[XMP sidecars](https://docs.immich.app/features/xmp-sidecars),
[tags](https://docs.immich.app/features/tags/),
the [CLI](https://docs.immich.app/features/command-line-interface) and the
[EXIF tags reference](https://docs.pr-30460.preview.immich.app/reference/exif-tags) (a preview build of the docs).
