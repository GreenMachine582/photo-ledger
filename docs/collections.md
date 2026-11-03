[← Back to README](../README.md)

# 🏷️ Collections and Immich

Each folder name is a collection stored in the ledger, because the folder may disappear when duplicates are
consolidated. The keeper inherits the collections of every copy it replaces. For example, if `Japan 2019/IMG_0412.jpg`
and `Best of 2019/IMG_0412.jpg` are duplicates, the keeper stays in both collections.

- **Naming:** Use the deepest meaningful folder, keeping its parents as a hierarchy, so `Holidays/2019/Japan` stays nested.
- **Generic folders:** Hide configurable names such as `DCIM`, `Camera` and `Pictures`, plus the source root.
- **Editing:** Rename, merge or hide collections on the Collections page. Mappings persist across rescans.
- **Undo:** Inherited collections come from decisions, so undoing a decision removes them too.

## Outputs

| Output | Gives you | Notes |
|---|---|---|
| Folders | A library people can browse, such as `YYYY/Collection/` or the original structure | A photo in several collections gets one main folder. The others are in the tags and CSV |
| XMP sidecars | Filterable tags in Immich and other photo apps | Originals stay byte-identical, so their hashes still match |
| Immich albums | Real albums, including a photo in more than one | Needs the optional export through Immich's API (M6) |
| CSV and JSON | Everything above, for your own scripts | Includes hash, path, collections and capture date |

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
