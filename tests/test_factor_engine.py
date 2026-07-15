"""Tests for the deterministic factor engine."""

from __future__ import annotations

from src.data.provider import CompanySnapshot
from src.factors import scoring
from src.factors.engine import rank_universe


def test_percentile_ranks_basic():
    out = scoring.percentile_ranks([1.0, 2.0, 3.0, 4.0])
    # Best (highest) gets 1.0, worst gets 0.0.
    assert out == [0.0, 1 / 3, 2 / 3, 1.0]


def test_percentile_ranks_with_none():
    out = scoring.percentile_ranks([1.0, None, 3.0, None])
    assert out[1] is None and out[3] is None
    # Two non-None values -> ranks 0.0 and 1.0
    assert out[0] == 0.0 and out[2] == 1.0


def test_percentile_ranks_ties_get_average():
    out = scoring.percentile_ranks([5.0, 5.0, 5.0])
    assert all(abs(v - 0.5) < 1e-9 for v in out)


def test_rank_universe_orders_by_composite():
    snaps = []
    # Company A: dominant on every factor.
    snaps.append(
        CompanySnapshot(
            ticker="A",
            name="A",
            roe=0.30,
            roic=0.30,
            gross_margin=0.50,
            operating_margin=0.30,
            profit_margin=0.20,
            earnings_yield=0.10,
            fcf_yield=0.08,
            pb=2.0,
            ps=3.0,
            ev_to_ebitda=8.0,
            momentum_12_1=0.30,
            momentum_6_1=0.15,
            debt_to_equity=0.1,
            net_debt_to_ebitda=0.5,
            current_ratio=3.0,
            cash_conversion=1.2,
        )
    )
    # Company B: middling.
    snaps.append(
        CompanySnapshot(
            ticker="B",
            name="B",
            roe=0.15,
            roic=0.10,
            gross_margin=0.30,
            operating_margin=0.15,
            profit_margin=0.10,
            earnings_yield=0.05,
            fcf_yield=0.04,
            pb=4.0,
            ps=5.0,
            ev_to_ebitda=12.0,
            momentum_12_1=0.05,
            momentum_6_1=0.02,
            debt_to_equity=0.5,
            net_debt_to_ebitda=2.0,
            current_ratio=1.5,
            cash_conversion=0.9,
        )
    )
    # Company C: weakest.
    snaps.append(
        CompanySnapshot(
            ticker="C",
            name="C",
            roe=0.05,
            roic=0.04,
            gross_margin=0.20,
            operating_margin=0.05,
            profit_margin=0.03,
            earnings_yield=0.02,
            fcf_yield=0.01,
            pb=8.0,
            ps=10.0,
            ev_to_ebitda=20.0,
            momentum_12_1=-0.10,
            momentum_6_1=-0.05,
            debt_to_equity=2.0,
            net_debt_to_ebitda=5.0,
            current_ratio=0.8,
            cash_conversion=0.5,
        )
    )

    weights = {
        "quality": 0.3,
        "value": 0.25,
        "momentum": 0.2,
        "financial_health": 0.15,
        "earnings_quality": 0.1,
    }
    reports = rank_universe(snaps, weights)
    assert [r.ticker for r in reports] == ["A", "B", "C"]
    assert reports[0].composite_score is not None
    assert reports[0].composite_score > reports[1].composite_score > reports[2].composite_score
