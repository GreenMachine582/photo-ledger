import random
from itertools import combinations

import pytest

from photo_ledger.matching.similar import _chunks, similar_pairs


def brute_force(hashes, threshold):
    found = []
    for (a, ha), (b, hb) in combinations(sorted(hashes.items()), 2):
        distance = (ha ^ hb).bit_count()
        if distance <= threshold:
            found.append((a, b, distance))
    return sorted(found)


def clustered_hashes(seed, count=300):
    """Random hashes, with some near copies so every threshold has matches."""
    rng = random.Random(seed)
    hashes = {}
    for index in range(count):
        if index and rng.random() < 0.4:
            base = hashes[rng.randrange(index)]
            for _ in range(rng.randrange(0, 14)):
                base ^= 1 << rng.randrange(64)
            hashes[index] = base
        else:
            hashes[index] = rng.getrandbits(64)
    return hashes


@pytest.mark.parametrize("threshold", [0, 1, 4, 8, 12, 20])
@pytest.mark.parametrize("seed", [1, 2])
def test_matches_brute_force(threshold, seed):
    hashes = clustered_hashes(seed)
    expected = brute_force(hashes, threshold)
    assert similar_pairs(hashes, threshold) == expected
    if threshold >= 4:
        assert expected  # the test means something


def test_chunks_cover_every_bit_once():
    for threshold in (0, 7, 8, 30):
        covered = 0
        for shift, mask in _chunks(threshold, 64):
            assert covered & (mask << shift) == 0
            covered |= mask << shift
        assert covered == (1 << 64) - 1


def test_large_thresholds_and_bad_input():
    hashes = {"a": 0, "b": (1 << 64) - 1}
    assert similar_pairs(hashes, 64) == [("a", "b", 64)]
    assert similar_pairs(hashes, 63) == []
    with pytest.raises(ValueError):
        similar_pairs(hashes, -1)
