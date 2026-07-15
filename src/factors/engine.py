"""The deterministic factor engine.

Inputs:  list of CompanySnapshot, factor weights dict, optional config.
Outputs: list of FactorReport (per-ticker score breakdown), sorted desc.

LLMs reason over these scores; they never produce them.

Enhancements over v1:
- coverage-weighted composite: a ticker missing half its metrics has its
  composite shrunk toward the universe median.
- per-factor floor: configurable in the profile under
  `factor_config.per_factor_floor`. If any factor score is below this
  threshold the ticker is *flagged* (not auto-rejected) so users can choose
  to filter or just see the warning.
- factor std dev: report the standard deviation of factor scores; high
  std-dev = lopsided picks dominated by one factor.
- profile fit: cosine similarity between the pick's factor scores and the
  profile's weight vector. A profile that emphasises Quality should prefer
  picks whose factor profile *also* emphasises Quality.
- orthogonalization: optional simple residualisation of correlated factors
  (Earnings Quality vs Quality). Off by default; opt in via
  `factor_config.orthogonalize_eq`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..data.provider import CompanySnapshot
from . import metrics, scoring


@dataclass
class FactorReport:
    ticker: str
    name: str | None
    sector: str | None
    composite_score: float | None = None
    raw_composite: float | None = None      # composite before coverage-weighting
    factor_scores: dict[str, float | None] = field(default_factory=dict)
    metric_values: dict[str, float | None] = field(default_factory=dict)
    metric_percentiles: dict[str, float | None] = field(default_factory=dict)
    coverage: float = 0.0                   # fraction of metrics that were available
    coverage_weight: float = 1.0            # multiplier applied to raw_composite
    factor_std_dev: float | None = None     # spread across factor scores
    profile_fit: float | None = None        # cosine sim with profile weight vector
    floor_breaches: list[str] = field(default_factory=list)
    # Multibagger-variant extras (empty/None for the classic 5-factor mode).
    pillar_scores: dict[str, float | None] = field(default_factory=dict)
    consistency_stats: dict[str, float | None] = field(default_factory=dict)
    vetoes: list[str] = field(default_factory=list)          # hard red flags fired
    soft_flags: list[str] = field(default_factory=list)      # soft (penalty) flags
    # Optional macro/regime overlay annotation (advisory CONTEXT, never a veto).
    # Empty by default so the classic path and no-overlay multibagger path are
    # byte-for-byte unchanged.
    regime_context: dict = field(default_factory=dict)
    scoring_mode: str = "classic"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "composite_score": self.composite_score,
            "raw_composite": self.raw_composite,
            "factor_scores": self.factor_scores,
            "metric_values": self.metric_values,
            "metric_percentiles": self.metric_percentiles,
            "coverage": self.coverage,
            "coverage_weight": self.coverage_weight,
            "factor_std_dev": self.factor_std_dev,
            "profile_fit": self.profile_fit,
            "floor_breaches": list(self.floor_breaches),
            "pillar_scores": dict(self.pillar_scores),
            "consistency_stats": dict(self.consistency_stats),
            "vetoes": list(self.vetoes),
            "soft_flags": list(self.soft_flags),
            "regime_context": dict(self.regime_context),
            "scoring_mode": self.scoring_mode,
        }


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: max(0.0, float(v)) / total for k, v in weights.items()}


def _cosine_sim(a: dict[str, float | None], b: dict[str, float]) -> float | None:
    """Cosine similarity between factor score vector and weight vector.

    None entries on `a` are treated as universe-median 0.5 so a missing factor
    doesn't artificially zero out the similarity.
    """
    keys = list(b.keys())
    if not keys:
        return None
    av = [a.get(k) if a.get(k) is not None else 0.5 for k in keys]
    bv = [b[k] for k in keys]
    dot = sum(x * y for x, y in zip(av, bv))
    na = math.sqrt(sum(x * x for x in av))
    nb = math.sqrt(sum(y * y for y in bv))
    if na == 0 or nb == 0:
        return None
    return max(0.0, min(1.0, dot / (na * nb)))


def _stdev(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    mean = sum(nums) / len(nums)
    var = sum((v - mean) ** 2 for v in nums) / (len(nums) - 1)
    return var**0.5


def _orthogonalize_eq_against_quality(
    eq_pcts: list[float | None], q_pcts: list[float | None]
) -> list[float | None]:
    """Subtract the mean Quality score from each Earnings Quality score and
    re-rank. Cheap, OLS-free, but enough to demonstrate residualisation.
    """
    if not eq_pcts or not q_pcts or len(eq_pcts) != len(q_pcts):
        return eq_pcts
    residuals: list[float | None] = []
    pairs = [
        (eq, q) for eq, q in zip(eq_pcts, q_pcts) if eq is not None and q is not None
    ]
    if not pairs:
        return eq_pcts
    mean_q = sum(q for _, q in pairs) / len(pairs)
    for eq, q in zip(eq_pcts, q_pcts):
        if eq is None or q is None:
            residuals.append(eq)
        else:
            residuals.append(eq - (q - mean_q))
    # Re-percentile after residualisation so the result is back on [0, 1].
    return scoring.percentile_ranks(residuals)


def rank_universe(
    snapshots: Iterable[CompanySnapshot],
    weights: dict[str, float],
    *,
    coverage_fn: Callable[[CompanySnapshot], float] | None = None,
    coverage_weight_floor: float = 0.4,
    per_factor_floor: float | None = None,
    profile_weights_for_fit: dict[str, float] | None = None,
    orthogonalize_eq: bool = False,
) -> list[FactorReport]:
    """Rank a universe of snapshots, returning FactorReports sorted desc by score.

    Parameters
    ----------
    coverage_fn : optional callable returning per-snapshot data coverage in [0, 1].
        Used to compute a coverage_weight in [coverage_weight_floor, 1.0]. Picks
        with low coverage have their composite shrunk toward the universe median.
    coverage_weight_floor : minimum coverage_weight (caps the penalty).
    per_factor_floor : if set, any factor score below this threshold is
        recorded on `floor_breaches` (does NOT auto-reject - reporting only).
    profile_weights_for_fit : if provided, compute per-pick cosine similarity
        between factor scores and these weights. Defaults to `weights`.
    orthogonalize_eq : if True, residualise Earnings Quality against Quality
        before averaging into the composite (decorrelation).
    """
    snaps = list(snapshots)
    if not snaps:
        return []

    norm_weights = _normalize_weights(weights)
    fit_weights = profile_weights_for_fit or weights

    # 1. Extract raw metric values per factor for every ticker.
    factor_metric_grids: dict[str, dict[str, list[float | None]]] = {}
    for factor_name, extractor in metrics.FACTORS.items():
        per_ticker = [extractor(s) for s in snaps]
        metric_names = sorted({k for d in per_ticker for k in d.keys()})
        grid: dict[str, list[float | None]] = {m: [] for m in metric_names}
        for d in per_ticker:
            for m in metric_names:
                grid[m].append(d.get(m))
        factor_metric_grids[factor_name] = grid

    # 2. Percentile-rank each metric column across the universe.
    factor_metric_pct: dict[str, dict[str, list[float | None]]] = {}
    for factor_name, grid in factor_metric_grids.items():
        factor_metric_pct[factor_name] = {
            m: scoring.percentile_ranks(values) for m, values in grid.items()
        }

    # Optional: orthogonalise Earnings Quality against Quality.
    if orthogonalize_eq and "earnings_quality" in factor_metric_pct and "quality" in factor_metric_pct:
        # Build aggregated quality score column (mean of quality metric pcts per ticker).
        q_col: list[float | None] = []
        for i in range(len(snaps)):
            vals = [
                vals_list[i]
                for vals_list in factor_metric_pct["quality"].values()
            ]
            q_col.append(scoring.average(vals))
        # And EQ aggregated column.
        eq_col: list[float | None] = []
        for i in range(len(snaps)):
            vals = [
                vals_list[i]
                for vals_list in factor_metric_pct["earnings_quality"].values()
            ]
            eq_col.append(scoring.average(vals))
        eq_residual = _orthogonalize_eq_against_quality(eq_col, q_col)
        factor_metric_pct["earnings_quality"] = {"orthogonalized": eq_residual}
        factor_metric_grids["earnings_quality"] = {"orthogonalized": eq_col}

    # 3. Build per-ticker reports.
    reports: list[FactorReport] = []
    for i, snap in enumerate(snaps):
        report = FactorReport(
            ticker=snap.ticker,
            name=snap.name,
            sector=snap.sector,
        )
        all_metric_count = 0
        present_metric_count = 0
        weighted_sum = 0.0
        weight_used = 0.0

        for factor_name, grid in factor_metric_grids.items():
            metric_pcts: list[float | None] = []
            for metric_name, values in grid.items():
                v = values[i]
                p = factor_metric_pct[factor_name][metric_name][i]
                report.metric_values[f"{factor_name}.{metric_name}"] = v
                report.metric_percentiles[f"{factor_name}.{metric_name}"] = p
                all_metric_count += 1
                if v is not None:
                    present_metric_count += 1
                metric_pcts.append(p)

            factor_score = scoring.average(metric_pcts)
            report.factor_scores[factor_name] = factor_score

            if factor_score is not None:
                w = norm_weights.get(factor_name, 0.0)
                weighted_sum += factor_score * w
                weight_used += w

            if (
                per_factor_floor is not None
                and factor_score is not None
                and factor_score < per_factor_floor
            ):
                report.floor_breaches.append(
                    f"{factor_name} {factor_score:.2f} < floor {per_factor_floor:.2f}"
                )

        if weight_used > 0:
            raw_comp = weighted_sum / weight_used
        else:
            raw_comp = None
        report.raw_composite = raw_comp

        # Coverage and coverage-weighted composite.
        if coverage_fn is not None:
            report.coverage = float(coverage_fn(snap))
        elif all_metric_count:
            report.coverage = present_metric_count / all_metric_count

        # Map coverage [0..1] -> coverage_weight [floor..1.0]. A ticker with
        # zero coverage gets the floor (still scored, but with a penalty).
        report.coverage_weight = coverage_weight_floor + (
            1.0 - coverage_weight_floor
        ) * max(0.0, min(1.0, report.coverage))

        if raw_comp is not None:
            # Shrink toward universe-median 0.5 by (1 - coverage_weight).
            shrink = 1.0 - report.coverage_weight
            report.composite_score = (
                raw_comp * report.coverage_weight + 0.5 * shrink
            )
        else:
            report.composite_score = None

        # Per-factor std dev across the 5 factor scores.
        report.factor_std_dev = _stdev(list(report.factor_scores.values()))

        # Profile fit (cosine similarity).
        report.profile_fit = _cosine_sim(report.factor_scores, fit_weights)

        reports.append(report)

    # 4. Sort by composite_score desc (None last).
    reports.sort(
        key=lambda r: (r.composite_score is None, -(r.composite_score or 0.0))
    )
    return reports
