[← Back to README](../README.md)

# 🔍 Duplicate Detection

Only JPEG and PNG are fully processed in the MVP. Other files are counted as unsupported, not hashed or matched.

## Pipeline

1. **Walk:** Record path, size and `mtime_ns` for each file, saving progress so an interrupted scan resumes.
2. **Exact:** Hash supported files, starting with those that share a size so likely duplicates appear early, then
   group by BLAKE3.
3. **Enrich:** Decode each new content once, reading EXIF and computing pHash. Failures go to `scan_errors`.
4. **Similar:** Pair images within a Hamming distance threshold, starting at 8 of 64 bits and tuned on real samples.
   Set it on the Settings page, set `PHOTO_LEDGER_SIMILAR_THRESHOLD`, or pass `match --threshold`. A saved setting wins
   over the variable, and `--threshold` wins over both. The search splits each hash into threshold + 1
   chunks: two hashes that close must share one chunk exactly, so only hashes sharing a chunk are compared, never
   every pair. Dimensions and capture time are used as supporting evidence.
5. **Mismatch:** Run the name, date and single-source checks below.
6. **Score:** Suggest a keeper and store the reasons.

## Pairs

| Kind | Compares | Stable key |
|---|---|---|
| `exact` | Two copies of the same content | The two file IDs |
| `similar` | Two different contents | The two BLAKE3 hashes |
| `name_conflict` | Same filename, different content | The two BLAKE3 hashes |

`photo-ledger match` recomputes the pairs from the catalogue and reconciles them with the stored ones by key:

| Found | Result |
|---|---|
| A new key | Queued as `open` |
| A known key | Kept as it is, so rescanning the same files queues nothing |
| An `obsolete` key matching again | Back to `open` |
| A `resolved` exact pair whose files changed content | `needs_review` |
| A stored key that no longer matches, such as a copy gone missing | `obsolete`, unless it was resolved |

Only `present` and `corrupt` files take part. Files on an offline source stay `present`, so their pairs are untouched.
Keys sort their two members, so swapping left and right can't create a second pair. Rejecting a copy closes its other
open pairs, so N copies take N − 1 reviews. Rejecting a similar image's content applies to all its copies, and the plan
lists each of them.

## Mismatches

- **Same filename, different content:** For example, `IMG_0001.jpg` reused after a camera counter reset.
- **Same content, different filename or folder.**
- **Dates disagree:** The filesystem date doesn't match the EXIF capture date, which is common after a restore.
- **Seen in only one source:** A neutral report, not a claim that anything is missing, since backups may cover
  different periods.
- **Corrupt or unreadable files:** Kept as a separate list for manual review.

## Keeper scores

Criteria are compared in this order, and the first that differs picks the suggested keeper:

1. Higher resolution
2. More complete EXIF: capture date, camera and GPS
3. Earlier capture date
4. Higher source priority, set with `source priority <label> <n>` (default 0)
5. Tidier path: no copy marker such as ` (1)`, ` - Copy` or `Copy of`, then a shorter path

File size only breaks ties, as larger doesn't always mean better. Every suggestion lists the criteria it wins and the
ones it loses, and only you make the decision. A similar or name-conflict pair compares the best copy of each content.

## Reports

`photo-ledger report <name>` prints a read-only report, or writes it with `--csv <path>` outside every source. With
`--scan <name>` it covers anything with a copy in that scan's sources.

| Report | Shows |
|---|---|
| `summary` | File, content and pair counts, and the size of each report below |
| `pairs` | Pairs with their suggested keeper and reasons. Filter with `--kind` and `--status` (default `open`, or `all`) |
| `renamed` | The same content under different filenames or in different folders |
| `dates` | Files whose file date and EXIF capture date are more than 24 hours apart |
| `single-source` | Content seen in only one source |
| `corrupt` | Corrupt and unreadable files |
| `collections` | Collections from folder names, with the folders, files and contents mapped to each |

Similar matches are never resolved automatically. Bulk actions apply to exact duplicates only and pass through the plan.
