[← Back to README](../README.md)

# 🔍 Duplicate Detection

Only JPEG and PNG are fully processed in the MVP. Other files are counted as unsupported, not hashed or matched.

## Pipeline

1. **Walk:** Record path, size and `mtime_ns` for each file, saving progress so an interrupted scan resumes.
2. **Exact:** Hash supported files, starting with those that share a size so likely duplicates appear early, then
   group by BLAKE3.
3. **Enrich:** Decode each new content once, reading EXIF and computing pHash. Failures go to `scan_errors`.
4. **Similar:** Pair images within a Hamming distance threshold, starting at 8 of 64 bits and tuned on real samples.
   Dimensions and capture time are used as supporting evidence.
5. **Mismatch:** Run the name, date and single-source checks below.
6. **Score:** Suggest a keeper and store the reasons.

## Pairs

| Kind | Compares | Stable key |
|---|---|---|
| `exact` | Two copies of the same content | The two file IDs |
| `similar` | Two different contents | The two BLAKE3 hashes |
| `name_conflict` | Same filename, different content | The two BLAKE3 hashes |

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

Scores use resolution, EXIF completeness, earliest capture date, source priority and tidier path. File size only
breaks ties, as larger doesn't always mean better. Every suggestion shows its reasons, and only you make the decision.

Similar matches are never resolved automatically. Bulk actions apply to exact duplicates only and pass through the plan.
