[← Back to README](../README.md)

# 🏷️ Collections and Immich

Each folder name is a collection stored in the ledger, because the folder may disappear when duplicates are
consolidated. The keeper inherits the collections of every copy it replaces, and undoing a decision removes them.

- **Naming:** Use the deepest meaningful folder, keeping its parents as a hierarchy.
- **Generic folders:** Hide configurable names such as `DCIM`, `Camera` and `Pictures`, plus the source root.
- **Editing:** Rename, merge or hide collections. Mappings persist across rescans.

## Outputs

| Output | Gives you | Notes |
|---|---|---|
| Folders | A library people can browse | A photo in several collections gets one main folder |
| XMP sidecars | Filterable tags in Immich and other photo apps | Originals stay byte-identical |
| Immich albums | Real albums, including a photo in more than one | Optional export through Immich's API |
| CSV and JSON | Everything above, for your own scripts | Hash, path, collections and capture date |

## Tagging for Immich

Write `IMG_0412.jpg.xmp` beside each library file, with hierarchical tags in `digiKam:TagsList`, which Immich reads first:

- `Collections/Holidays/2019/Japan`
- `Sources/Old PC`

Immich uses the first tag field it finds and doesn't merge them, and sidecars take priority over embedded tags. Copy any
existing embedded keywords into the sidecar, or they'll stop showing.

`immich upload --album` names albums from each file's parent folder, so a photo in several collections lands in one album.
The CLI docs don't cover uploading sidecars, so test a small sample first.

See Immich's docs on [XMP sidecars](https://docs.immich.app/features/xmp-sidecars),
[tags](https://docs.immich.app/features/tags/) and the
[CLI](https://docs.immich.app/features/command-line-interface).
