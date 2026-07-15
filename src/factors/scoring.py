"""Cross-sectional percentile scoring.

We compute, per metric, a percentile rank across the universe (0..1 where 1.0
is best). Per-metric ranks are averaged within a factor to produce a factor
score, then factor scores are blended via profile-driven weights into a
composite score. None values are skipped.
"""

from __future__ import annotations


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Return percentile rank (0..1) for each value. None stays None.

    Ties get the average rank. Empty/all-None input => list of Nones.
    """
    indexed = [(i, v) for i, v in enumerate(values) if v is not None]
    if not indexed:
        return [None] * len(values)

    sorted_vals = sorted(indexed, key=lambda x: x[1])
    n = len(sorted_vals)

    # Build a map idx -> rank, averaging ties.
    rank_map: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            rank_map[sorted_vals[k][0]] = avg_rank
        i = j + 1

    out: list[float | None] = []
    denom = max(n - 1, 1)
    for idx, v in enumerate(values):
        if v is None:
            out.append(None)
        else:
            out.append(rank_map[idx] / denom)
    return out


def average(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def sector_percentile_ranks(
    values: list[float | None],
    sectors: list[str | None],
    min_peers: int = 6,
) -> list[float | None]:
    """Percentile-rank each value *within its sector* peer group.

    Fallback ladder (spec section 5): if a value's sector has fewer than
    `min_peers` members with a non-None value, that value is ranked against the
    whole universe instead. This keeps thin-sector stats from being unstable
    while still normalising within sector wherever there is enough data.
    None values stay None.
    """
    n = len(values)
    if n != len(sectors):
        return percentile_ranks(values)

    global_ranks = percentile_ranks(values)

    # Group indices by sector (only those with a value present).
    groups: dict[str | None, list[int]] = {}
    for i, (v, sec) in enumerate(zip(values, sectors)):
        if v is None:
            continue
        groups.setdefault(sec, []).append(i)

    out: list[float | None] = [None] * n
    for sec, idxs in groups.items():
        if len(idxs) >= min_peers:
            sub_vals = [values[i] for i in idxs]
            sub_ranks = percentile_ranks(sub_vals)
            for local, i in enumerate(idxs):
                out[i] = sub_ranks[local]
        else:
            # Thin sector -> fall back to whole-universe rank.
            for i in idxs:
                out[i] = global_ranks[i]
    return out
