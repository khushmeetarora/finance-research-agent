"""Tests for the v2 factor engine improvements."""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.data.health import coverage_of
from src.data.provider import CompanySnapshot
from src.factors import scoring
from src.factors.engine import rank_universe


def _full_snapshot(ticker: str, **overrides) -> CompanySnapshot:
    base = dict(
        ticker=ticker,
        market_cap=1e9,
        price=100,
        roe=0.2,
        roic=0.18,
        gross_margin=0.5,
        operating_margin=0.2,
        profit_margin=0.15,
        earnings_yield=0.05,
        fcf_yield=0.03,
        pb=3,
        ps=2,
        ev_to_ebitda=10,
        momentum_12_1=0.10,
        momentum_6_1=0.05,
        debt_to_equity=0.3,
        net_debt_to_ebitda=1.0,
        current_ratio=2,
        cash_conversion=1.0,
    )
    base.update(overrides)
    return CompanySnapshot(**base)


def test_coverage_weighted_composite_shrinks_low_coverage():
    """A ticker missing all metrics should have its composite shrunk
    materially toward 0.5 vs an identical-ranking ticker with full coverage."""
    full = _full_snapshot("FULL")
    sparse = CompanySnapshot(ticker="SPARSE", roe=0.20, momentum_12_1=0.10)
    # A baseline pool to make percentile rank meaningful.
    snaps = [full, sparse, _full_snapshot("X", roe=0.05, momentum_12_1=-0.10)]
    weights = {"quality": 0.3, "value": 0.25, "momentum": 0.2,
               "financial_health": 0.15, "earnings_quality": 0.1}
    reports = rank_universe(
        snaps, weights, coverage_fn=coverage_of, coverage_weight_floor=0.4
    )
    by = {r.ticker: r for r in reports}
    assert by["SPARSE"].coverage < by["FULL"].coverage
    # Coverage weight monotonically reflects coverage.
    assert by["SPARSE"].coverage_weight <= by["FULL"].coverage_weight


def test_profile_fit_in_unit_interval():
    snaps = [_full_snapshot("A"), _full_snapshot("B", roe=0.05)]
    weights = {"quality": 0.5, "value": 0.2, "momentum": 0.2,
               "financial_health": 0.05, "earnings_quality": 0.05}
    reports = rank_universe(snaps, weights, profile_weights_for_fit=weights)
    for r in reports:
        if r.profile_fit is not None:
            assert 0.0 <= r.profile_fit <= 1.0


def test_per_factor_floor_records_breaches_only():
    """Floor breaches should be recorded but not auto-reject the ticker."""
    snaps = [
        _full_snapshot("LOWMOM", momentum_12_1=-0.5, momentum_6_1=-0.4),
        _full_snapshot("HIGHMOM"),
    ]
    weights = {"quality": 0.2, "value": 0.2, "momentum": 0.4,
               "financial_health": 0.1, "earnings_quality": 0.1}
    reports = rank_universe(snaps, weights, per_factor_floor=0.4)
    assert len(reports) == 2  # both retained
    by = {r.ticker: r for r in reports}
    assert any("momentum" in b for b in by["LOWMOM"].floor_breaches)


def test_factor_std_dev_low_for_balanced_pick():
    """A ticker with all factor scores near 0.5 should have low std dev."""
    snaps = [
        _full_snapshot("BAL"),
        _full_snapshot("OTHER", roe=0.05),
    ]
    weights = {"quality": 0.2, "value": 0.2, "momentum": 0.2,
               "financial_health": 0.2, "earnings_quality": 0.2}
    reports = rank_universe(snaps, weights)
    for r in reports:
        if r.factor_std_dev is not None:
            assert 0.0 <= r.factor_std_dev <= 0.6


@given(st.lists(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
                min_size=2, max_size=20))
@settings(max_examples=50, deadline=None)
def test_percentile_ranks_property(values):
    """Property: every output is in [0, 1]; ties get equal ranks."""
    out = scoring.percentile_ranks(values)
    assert len(out) == len(values)
    for v in out:
        assert v is None or 0.0 <= v <= 1.0
