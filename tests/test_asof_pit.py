"""Point-in-time (audit C-1) gating tests for the provider + as-of helpers.

Hermetic: no network. Verifies period-dropping with the reporting lag, the
indeterminate case, the screener-preferred deep source, and that live TTM
.info fields are stripped so they cannot leak into a historical score.
"""

from __future__ import annotations

import datetime as dt

from src.backtest.asof import as_of_financials, usable_period_count
from src.data.provider import (
    CompanySnapshot,
    DataProvider,
    enrich_snapshot_with_financials,
)


def _full_fin() -> dict:
    """A 6-year annual bundle (FY2015..FY2020, fiscal-year-end March)."""
    periods = [f"{y}-03-31" for y in range(2015, 2021)]
    return {
        "income": {
            "Total Revenue": [100, 120, 140, 160, 180, 200],
            "Operating Income": [20, 25, 30, 35, 40, 45],
            "EBIT": [22, 27, 32, 37, 42, 47],
            "Net Income": [12, 15, 18, 21, 24, 27],
            "Diluted EPS": [1.2, 1.5, 1.8, 2.1, 2.4, 2.7],
        },
        "balance": {
            "Total Assets": [200, 220, 240, 260, 280, 300],
            "Current Liabilities": [60, 62, 64, 66, 68, 70],
            "Stockholders Equity": [100, 115, 130, 145, 160, 175],
            "Total Debt": [40, 40, 40, 40, 40, 40],
        },
        "cashflow": {
            "Operating Cash Flow": [15, 18, 22, 26, 30, 34],
            "Capital Expenditure": [-5, -5, -6, -6, -7, -7],
        },
        "income_periods": periods,
        "balance_periods": periods,
        "cashflow_periods": periods,
        "status": "ok",
        "source": "screener_consolidated",
    }


def test_as_of_financials_drops_future_periods_with_lag():
    fin = _full_fin()
    # as_of 2019-01-01 => cutoff 2019-01-01 - 90d = 2018-10-03; keep periods
    # ending on/before that => FY2015..FY2018 (2018-03-31 <= cutoff), drop FY2019+.
    gated = as_of_financials(fin, dt.date(2019, 1, 1))
    assert gated["income_periods"] == [
        "2015-03-31", "2016-03-31", "2017-03-31", "2018-03-31",
    ]
    assert gated["income"]["Net Income"] == [12, 15, 18, 21]
    assert gated["status"] == "ok"


def test_as_of_reporting_lag_excludes_just_closed_year():
    fin = _full_fin()
    # as_of 2018-05-01 => cutoff 2018-01-31; FY2018 (ended 2018-03-31) is NOT yet
    # reportable, so the latest admissible year is FY2017.
    gated = as_of_financials(fin, dt.date(2018, 5, 1))
    assert gated["income_periods"][-1] == "2017-03-31"


def test_as_of_indeterminate_when_nothing_admissible():
    fin = _full_fin()
    gated = as_of_financials(fin, dt.date(2014, 1, 1))
    assert usable_period_count(gated) == 0
    assert gated["status"] == "failed"


def test_get_financials_prefers_screener_and_gates(monkeypatch):
    from src.data import screener

    monkeypatch.setattr(
        screener, "get_screener_financials", lambda *a, **k: _full_fin()
    )
    dp = DataProvider(use_stooq=False)
    gated = dp.get_financials("TITAN.NS", as_of=dt.date(2019, 1, 1))
    assert gated["source"] == "screener_consolidated"
    assert usable_period_count(gated) == 4  # FY2015..FY2018


def test_get_financials_falls_back_to_yfinance(monkeypatch):
    from src.data import screener

    monkeypatch.setattr(
        screener,
        "get_screener_financials",
        lambda *a, **k: {"status": "failed", "source": "screener_unreachable"},
    )
    dp = DataProvider(use_stooq=False)
    yf_bundle = _full_fin()
    yf_bundle["source"] = "yfinance"
    monkeypatch.setattr(dp, "_yfinance_financials", lambda ticker: yf_bundle)
    gated = dp.get_financials("TITAN.NS", as_of=dt.date(2020, 1, 1))
    assert gated["source"] == "yfinance"
    assert usable_period_count(gated) == 5  # FY2015..FY2019


def test_enrich_as_of_strips_lookahead_ttm_fields():
    snap = CompanySnapshot(ticker="X.NS", sector="Consumer")
    # Simulate live .info leakage on the snapshot.
    snap.roe = 0.25
    snap.gross_margin = 0.4
    snap.beta = 1.1
    snap.net_debt_to_ebitda = 2.0
    # PIT-safe caller-reconstructed values that must be preserved.
    snap.pe_trailing = 30.0
    snap.momentum_12_1 = 0.5
    enrich_snapshot_with_financials(snap, _full_fin(), as_of=dt.date(2020, 1, 1))
    # Leaky TTM fields nulled.
    assert snap.roe is None
    assert snap.gross_margin is None
    assert snap.beta is None
    assert snap.net_debt_to_ebitda is None
    # Reconstructed / caller-controlled fields kept.
    assert snap.pe_trailing == 30.0
    assert snap.momentum_12_1 == 0.5
    # Statement-derived fields populated from the gated bundle.
    assert len(snap.roce_series) == 5  # FY2015..FY2019 admissible at 2020-01-01


def test_enrich_as_of_indeterminate_leaves_series_empty():
    snap = CompanySnapshot(ticker="X.NS", sector="Consumer")
    enrich_snapshot_with_financials(snap, _full_fin(), as_of=dt.date(2014, 1, 1))
    assert snap.roce_series == []
    assert snap.financials_status == "failed"
