"""Tests for the DataHealthCard."""

from __future__ import annotations

from src.data.health import build_card, coverage_of
from src.data.provider import CompanySnapshot


def test_coverage_of_full_snapshot_is_high():
    s = CompanySnapshot(
        ticker="A",
        market_cap=1e9,
        price=100,
        pe_trailing=20,
        pb=3,
        ps=2,
        ev_to_ebitda=10,
        earnings_yield=0.05,
        fcf_yield=0.03,
        dividend_yield=0.02,
        roe=0.2,
        roic=0.18,
        gross_margin=0.5,
        operating_margin=0.2,
        profit_margin=0.15,
        debt_to_equity=0.3,
        net_debt_to_ebitda=1.0,
        current_ratio=2,
        cash_conversion=1.0,
        revenue_growth=0.1,
        earnings_growth=0.12,
        momentum_12_1=0.05,
        momentum_6_1=0.03,
        volatility_annualized=0.25,
    )
    assert coverage_of(s) > 0.9


def test_data_health_severity_critical_on_low_fetch_rate():
    requested = ["A", "B", "C", "D"]
    snaps = [CompanySnapshot(ticker="A", fetch_status="ok"),
             CompanySnapshot(ticker="B", fetch_status="failed")]
    card = build_card(requested, snaps)
    assert card.severity in {"warn", "critical"}
    assert card.failed >= 1


def test_data_health_records_agreement():
    s1 = CompanySnapshot(ticker="A", fetch_status="ok", data_agreement=0.99,
                         data_sources=["yfinance", "stooq"])
    s2 = CompanySnapshot(ticker="B", fetch_status="ok", data_agreement=0.80,
                         data_sources=["yfinance", "stooq"])
    card = build_card(["A", "B"], [s1, s2])
    assert card.avg_agreement is not None
    assert 0.85 <= card.avg_agreement <= 0.95
    assert ("stooq" in card.sources_used) and ("yfinance" in card.sources_used)


def test_data_health_serializes_round_trip():
    snaps = [CompanySnapshot(ticker="A", fetch_status="ok", data_agreement=0.97,
                             data_sources=["yfinance"])]
    card = build_card(["A"], snaps)
    d = card.to_dict()
    assert d["severity"] in {"ok", "warn", "critical"}
    assert isinstance(d["messages"], list)
