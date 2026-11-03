"""Find perceptual hashes within a Hamming distance, without comparing every pair.

Split each 64-bit hash into ``threshold + 1`` chunks. Two hashes that differ in at most
``threshold`` bits can't differ in every chunk, so they share at least one chunk exactly
(the pigeonhole principle). Bucketing by each chunk finds every candidate, and only candidates
are compared bit by bit.
"""

from collections import defaultdict
from collections.abc import Hashable
from itertools import combinations

HASH_BITS = 64


def _chunks(threshold: int, bits: int) -> list[tuple[int, int]]:
    """``(shift, mask)`` for ``threshold + 1`` chunks of near-equal width covering ``bits``."""
    count = threshold + 1
    widths = [bits // count + (1 if index < bits % count else 0) for index in range(count)]
    chunks, shift = [], 0
    for width in widths:
        chunks.append((shift, (1 << width) - 1))
        shift += width
    return chunks


def similar_pairs(
    hashes: dict[Hashable, int], threshold: int, bits: int = HASH_BITS
) -> list[tuple[Hashable, Hashable, int]]:
    """Every ``(a, b, distance)`` with ``a < b`` and a Hamming distance of at most ``threshold``."""
    if threshold < 0:
        raise ValueError("The threshold can't be negative.")
    items = sorted(hashes.items())
    if threshold >= bits - 1:
        candidates = combinations(items, 2)
    else:
        candidates = _bucketed(items, _chunks(threshold, bits))
    found = []
    for (key_a, hash_a), (key_b, hash_b) in candidates:
        distance = (hash_a ^ hash_b).bit_count()
        if distance <= threshold:
            found.append((key_a, key_b, distance))
    return sorted(found)


def _bucketed(items, chunks):
    seen = set()
    for shift, mask in chunks:
        buckets = defaultdict(list)
        for item in items:
            buckets[(item[1] >> shift) & mask].append(item)
        for bucket in buckets.values():
            for left, right in combinations(bucket, 2):
                if (left[0], right[0]) not in seen:
                    seen.add((left[0], right[0]))
                    yield left, right
