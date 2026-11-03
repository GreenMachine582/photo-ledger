[← Back to README](../README.md)

# 🔍 Duplicate Detection

## Pipeline

1. **Walk:** Record path, size and `mtime_ns`, saving progress so an interrupted scan resumes.
2. **Exact:** Hash supported files, starting with those that share a size, then group by BLAKE3.
3. **Enrich:** Decode each new content once, reading EXIF and computing pHash.
4. **Similar:** Pair images within a Hamming distance threshold, starting at 8 of 64 bits and tuned on real samples.
5. **Mismatch:** Check names, dates and files seen in only one source. That last report is neutral, not a claim
   that anything is missing.
6. **Score:** Suggest a keeper and store the reasons.

## Pairs

| Kind | Compares | Stable key |
|---|---|---|
| `exact` | Two copies of the same content | The two file IDs |
| `similar` | Two different contents | The two BLAKE3 hashes |
| `name_conflict` | Same filename, different content | The two BLAKE3 hashes |

Keys sort their two members, so left and right can't create a second pair. Rejecting a copy closes its other open
pairs, so N copies take N − 1 reviews. Rejecting a similar image's content applies to all its copies.

## Keeper scores

Scores use resolution, EXIF completeness, earliest capture date, source priority and tidier path. File size only
breaks ties. Every suggestion shows its reasons, and only you make the decision.

Similar matches are never resolved automatically. Bulk actions apply to exact duplicates only and pass through the plan.
