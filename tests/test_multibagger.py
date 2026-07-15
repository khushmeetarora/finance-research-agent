"""Unit tests for the multibagger scoring variant.

Covers the consistency operator, Beneish M-score, Altman Z"-EM, ROCE / accruals
/ FCF enrichment from statements, sector-relative ranking, the 7-pillar
composite, and the hard red-flag veto pass. All fixtures are tiny and
hand-computed so the expected numbers are auditable.
"""

from __future__ import annotations

import math

import pytest

from src.data.provider import CompanySnapshot, enrich_snapshot_with_financials
from src.factors import forensic, multibagger, scoring
from src.factors.multibagger import (
    is_early_stage_growth_exception,
    rank_multibagger,
    run_veto_pass,
)
from src.factors.engine import FactorReport


# ---------------------------------------------------------------------------
# Consistency operator (spec 3.1)
# ---------------------------------------------------------------------------


def test_consistency_mean_min_cv_slope():
    xs = [0.20, 0.22, 0.24]  # steadily rising ROCE
    assert multibagger.series_mean(xs) == pytest.approx(0.22)
    assert multibagger.series_min(xs) == pytest.approx(0.20)
    # cv = stdev/|mean|; sample stdev of [.2,.22,.24] = 0.02
    assert multibagger.series_cv(xs) == pytest.approx(0.02 / 0.22, rel=1e-6)
    # stability is negated cv
    assert multibagger.series_stability(xs) == pytest.approx(-(0.02 / 0.22), rel=1e-6)
    # positive slope for a rising series
    assert multibagger.series_slope(xs) > 0


def test_consistency_insufficient_data():
    assert multibagger.series_mean([0.2]) is None       # needs >= 2
    assert multibagger.series_cv([0.2]) is None
    assert multibagger.series_slope([0.2, 0.3]) is None  # slope needs >= 3
    assert multibagger.series_mean([]) is None


def test_stable_beats_spiky_stability():
    stable = [0.20, 0.20, 0.21, 0.20]
    spiky = [0.05, 0.35, 0.02, 0.40]
    # same-ish mean, but stable has much higher (less negative) stability
    assert multibagger.series_stability(stable) > multibagger.series_stability(spiky)


# ---------------------------------------------------------------------------
# Beneish M-score (spec 3.6)
# ---------------------------------------------------------------------------


def _clean_beneish_kwargs(ni_t=100.0, cfo_t=120.0):
    # Two aligned years (t-1, t). Designed so every index ~= 1 and TATA small.
    return dict(
        revenue=[1000.0, 1100.0],
        cogs=[600.0, 660.0],
        sga=None,
        net_income=[90.0, ni_t],
        cfo=[110.0, cfo_t],
        receivables=[100.0, 110.0],
        current_assets=[300.0, 330.0],
        ppe=[400.0, 440.0],
        total_assets=[1000.0, 1100.0],
        depreciation=None,
        current_liabilities=[200.0, 220.0],
        long_term_debt=[100.0, 110.0],
    )


def test_beneish_clean_company_below_threshold():
    m = forensic.beneish_m_score(**_clean_beneish_kwargs(ni_t=100.0, cfo_t=120.0))
    assert m is not None
    assert m == pytest.approx(-2.476, abs=0.02)
    assert m < -1.78  # not a manipulator


def test_beneish_high_accruals_flags_manipulator():
    # Large positive accruals (NI >> CFO) pushes TATA up and M above -1.78.
    m = forensic.beneish_m_score(**_clean_beneish_kwargs(ni_t=300.0, cfo_t=-100.0))
    assert m is not None
    assert m > -1.78  # manipulation-likely


def test_beneish_returns_none_without_cogs():
    kw = _clean_beneish_kwargs()
    kw["cogs"] = None  # COGS not split -> not computable (spec caveat)
    assert forensic.beneish_m_score(**kw) is None


# ---------------------------------------------------------------------------
# Altman Z"-EM (spec 3.8)
# ---------------------------------------------------------------------------


def test_altman_safe_company():
    z = forensic.altman_z_em(
        current_assets=[200.0], current_liabilities=[100.0], total_assets=[1000.0],
        retained_earnings=[300.0], ebit=[150.0], equity=[600.0],
        total_liabilities=[400.0],
    )
    # 3.25 + 6.56*.1 + 3.26*.3 + 6.72*.15 + 1.05*1.5
    assert z == pytest.approx(7.467, abs=0.01)
    assert z > 2.6


def test_altman_distress_company():
    z = forensic.altman_z_em(
        current_assets=[50.0], current_liabilities=[200.0], total_assets=[1000.0],
        retained_earnings=[-100.0], ebit=[-200.0], equity=[100.0],
        total_liabilities=[900.0],
    )
    assert z == pytest.approx(0.713, abs=0.01)
    assert z < 1.1  # distress zone


def test_altman_none_without_total_assets():
    assert forensic.altman_z_em(
        current_assets=[50.0], current_liabilities=[200.0], total_assets=[None],
        retained_earnings=[-100.0], ebit=[-200.0], equity=[100.0],
        total_liabilities=[900.0],
    ) is None


# ---------------------------------------------------------------------------
# Statement enrichment: ROCE, accruals, FCF, gross profitability, etc.
# ---------------------------------------------------------------------------


def _fixture_financials():
    periods = ["2021-03-31", "2022-03-31", "2023-03-31"]
    return {
        "status": "ok",
        "income_periods": periods,
        "balance_periods": periods,
        "cashflow_periods": periods,
        "income": {
            "Total Revenue": [800.0, 900.0, 1000.0],
            "Cost Of Revenue": [500.0, 560.0, 600.0],
            "Operating Income": [120.0, 150.0, 180.0],
            "Net Income": [80.0, 95.0, 110.0],
            "Interest Expense": [10.0, 10.0, 12.0],
        },
        "balance": {
            "Total Assets": [800.0, 900.0, 1000.0],
            "Current Liabilities": [200.0, 220.0, 250.0],
            "Current Assets": [300.0, 330.0, 360.0],
            "Stockholders Equity": [400.0, 450.0, 500.0],
            "Retained Earnings": [150.0, 200.0, 260.0],
            "Total Liabilities Net Minority Interest": [400.0, 450.0, 500.0],
            "Net PPE": [300.0, 340.0, 380.0],
            "Inventory": [100.0, 110.0, 120.0],
            "Receivables": [80.0, 90.0, 100.0],
            "Accounts Payable": [60.0, 66.0, 70.0],
            "Total Debt": [200.0, 220.0, 260.0],
        },
        "cashflow": {
            "Operating Cash Flow": [100.0, 120.0, 140.0],
            "Capital Expenditure": [-40.0, -45.0, -50.0],
        },
    }


def test_enrich_roce_and_derived_fields():
    snap = CompanySnapshot(ticker="T.NS", sector="Information Technology",
                           market_cap=1e10, pe_trailing=20.0)
    enrich_snapshot_with_financials(snap, _fixture_financials())

    assert snap.financials_status == "ok"
    assert snap.is_financial is False
    # ROCE latest = 180 / (1000 - 250) = 0.24
    assert snap.roce == pytest.approx(0.24, abs=1e-4)
    assert snap.roce_via_proxy is False
    assert len(snap.roce_series) == 3
    assert snap.roce_series[0] == pytest.approx(0.20, abs=1e-4)
    # Gross profitability = (1000 - 600) / 1000 = 0.4
    assert snap.gross_profitability == pytest.approx(0.4, abs=1e-4)
    # Accruals = (110 - 140) / 1000 = -0.03
    assert snap.accruals_ratio == pytest.approx(-0.03, abs=1e-4)
    # Interest coverage = 180 / 12 = 15
    assert snap.interest_coverage == pytest.approx(15.0, abs=1e-4)
    # Asset turnover = 1000 / 1000 = 1.0
    assert snap.asset_turnover == pytest.approx(1.0, abs=1e-4)
    # Capex intensity = 50 / 1000 = 0.05
    assert snap.capex_intensity == pytest.approx(0.05, abs=1e-4)
    # FCF series [60, 75, 90]; latest 90; posrate 1.0; neg years 0
    assert snap.fcf_series == [60.0, 75.0, 90.0]
    assert snap.fcf == pytest.approx(90.0)
    assert snap.fcf_posrate == pytest.approx(1.0)
    assert snap.fcf_neg_years == 0
    # OCF / NP = 360 / 285
    assert snap.ocf_to_np_multiyear == pytest.approx(360.0 / 285.0, abs=1e-4)
    # Working-capital days
    assert snap.dso == pytest.approx(365 * 100 / 1000, abs=1e-3)
    assert snap.dio == pytest.approx(365 * 120 / 600, abs=1e-3)
    assert snap.dpo == pytest.approx(365 * 70 / 600, abs=1e-3)
    # Earnings CAGR from NI [80,95,110] over 2 yrs
    assert snap.earnings_cagr == pytest.approx((110.0 / 80.0) ** 0.5 - 1.0, abs=1e-4)
    # PEG = 20 / (100 * cagr)
    assert snap.peg == pytest.approx(20.0 / (100.0 * snap.earnings_cagr), abs=1e-4)
    # Altman computed for a non-financial
    assert snap.altman_z == pytest.approx(7.0788, abs=0.01)
    assert snap.debt_rising is True  # 200 -> 260


def test_enrich_financial_skips_roce_and_altman():
    snap = CompanySnapshot(ticker="BANK.NS", sector="Financial Services")
    enrich_snapshot_with_financials(snap, _fixture_financials())
    assert snap.is_financial is True
    assert snap.roce is None
    assert snap.altman_z is None
    assert snap.gross_profitability is None


def test_enrich_graceful_on_failed_financials():
    snap = CompanySnapshot(ticker="X.NS", sector="Industrials")
    enrich_snapshot_with_financials(snap, {"status": "failed"})
    assert snap.financials_status == "failed"
    assert snap.roce is None
    assert snap.fcf_series == []


def test_enrich_roce_proxy_fallback():
    snap = CompanySnapshot(ticker="Y.NS", sector="Industrials", roic=0.18)
    fin = _fixture_financials()
    # Remove EBIT so ROCE series cannot be built -> falls back to ROIC proxy.
    fin["income"]["Operating Income"] = [None, None, None]
    enrich_snapshot_with_financials(snap, fin)
    assert snap.roce == pytest.approx(0.18)
    assert snap.roce_via_proxy is True


# ---------------------------------------------------------------------------
# Sector-relative percentile ranking (spec 5)
# ---------------------------------------------------------------------------


def test_sector_percentile_thin_sector_falls_back_to_global():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 10.0, 0.0]
    sectors = ["A"] * 6 + ["B", "B"]
    out = scoring.sector_percentile_ranks(values, sectors, min_peers=6)
    # Sector A (6 members) ranked within sector: 0.0 .. 1.0
    assert out[0] == pytest.approx(0.0)
    assert out[5] == pytest.approx(1.0)
    # Sector B (thin) falls back to whole-universe rank: 10 is global max, 0 min
    assert out[6] == pytest.approx(1.0)
    assert out[7] == pytest.approx(0.0)


def test_sector_percentile_preserves_none():
    out = scoring.sector_percentile_ranks([1.0, None, 3.0], ["A", "A", "A"], min_peers=2)
    assert out[1] is None


# ---------------------------------------------------------------------------
# Pillar composite + governance neutral default
# ---------------------------------------------------------------------------


def _rich_snap(ticker, sector, **over):
    base = dict(
        ticker=ticker, name=ticker, sector=sector,
        roce=0.25, roe=0.22, gross_profitability=0.5, asset_turnover=1.1,
        cash_conversion=1.1, accruals_ratio=-0.02, fcf_posrate=1.0,
        fcf_yield=0.06, ocf_to_np_multiyear=1.2, altman_z=6.0,
        net_debt_to_ebitda=0.5, interest_coverage=12.0, current_ratio=2.5,
        earnings_cagr=0.2, peg=0.9, earnings_yield=0.08,
        gross_margin_series=[0.4, 0.41, 0.42], operating_margin_series=[0.2, 0.21, 0.22],
        capex_intensity=0.05, momentum_12_1=0.3, momentum_6_1=0.15,
        roce_series=[0.24, 0.25, 0.26],
    )
    base.update(over)
    return CompanySnapshot(**base)


def test_pillar_ranking_orders_and_governance_neutral():
    strong = _rich_snap("STRONG.NS", "Information Technology")
    weak = _rich_snap(
        "WEAK.NS", "Information Technology",
        roce=0.05, roe=0.04, gross_profitability=0.1, asset_turnover=0.4,
        cash_conversion=0.5, accruals_ratio=0.15, fcf_posrate=0.2,
        fcf_yield=0.0, ocf_to_np_multiyear=0.6, altman_z=2.0,
        net_debt_to_ebitda=4.0, interest_coverage=2.0, current_ratio=0.9,
        earnings_cagr=0.02, peg=4.0, earnings_yield=0.02,
        gross_margin_series=[0.2, 0.15, 0.1], operating_margin_series=[0.1, 0.06, 0.03],
        capex_intensity=0.3, momentum_12_1=-0.1, momentum_6_1=-0.05,
        roce_series=[0.1, 0.05, 0.02],
    )
    mid = _rich_snap(
        "MID.NS", "Information Technology",
        roce=0.15, roe=0.13, gross_profitability=0.3, asset_turnover=0.8,
        cash_conversion=0.9, accruals_ratio=0.02, fcf_posrate=0.6,
        ocf_to_np_multiyear=0.9, altman_z=3.5, net_debt_to_ebitda=2.0,
        interest_coverage=6.0, current_ratio=1.5, earnings_cagr=0.1, peg=1.5,
        earnings_yield=0.05, capex_intensity=0.12,
        roce_series=[0.16, 0.15, 0.14],
    )
    reports = rank_multibagger([weak, mid, strong], sector_relative=False)
    order = [r.ticker for r in reports]
    assert order[0] == "STRONG.NS"
    assert order[-1] == "WEAK.NS"
    # Governance pillar has no Tier-C data -> neutral 0.5 for all.
    for r in reports:
        assert r.pillar_scores["promoter_governance"] == pytest.approx(0.5)
        assert r.scoring_mode == "multibagger"
    # Consistency stats surfaced.
    top = reports[0]
    assert top.consistency_stats["roce_mean"] is not None


# ---------------------------------------------------------------------------
# Hard red-flag veto pass (spec 6)
# ---------------------------------------------------------------------------


def _report_with(composite=0.8):
    r = FactorReport(ticker="Z.NS", name="Z", sector="Industrials")
    r.composite_score = composite
    return r


def test_veto_altman_distress():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials", altman_z=0.7)
    r = run_veto_pass(_report_with(), snap)
    assert r.composite_score is None
    assert any("RF4" in v for v in r.vetoes)


def test_veto_beneish_manipulator():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials", beneish_m=-0.5)
    r = run_veto_pass(_report_with(), snap)
    assert r.composite_score is None
    assert any("RF3" in v for v in r.vetoes)


def test_veto_structural_cash_burn():
    snap = CompanySnapshot(
        ticker="Z.NS", sector="Industrials",
        fcf_series=[-10.0, -5.0, -8.0, 2.0], fcf_neg_years=3,
    )
    r = run_veto_pass(_report_with(), snap)
    assert r.composite_score is None
    assert any("RF1" in v for v in r.vetoes)


def test_veto_earnings_not_cash_backed():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials", ocf_to_np_multiyear=0.3)
    r = run_veto_pass(_report_with(), snap)
    assert r.composite_score is None
    assert any("RF2" in v for v in r.vetoes)


def test_veto_promoter_pledge_manual():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials", promoter_pledge_pct=62.0)
    r = run_veto_pass(_report_with(), snap)
    assert r.composite_score is None
    assert any("RF6" in v for v in r.vetoes)


def test_soft_veto_working_capital_trap_penalises_not_drops():
    snap = CompanySnapshot(
        ticker="Z.NS", sector="Industrials",
        dso_delta=10.0, dio_delta=8.0, dpo_delta=-5.0, cfo_np_falling=True,
    )
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is not None
    assert r.composite_score < 0.8  # penalised toward the median
    assert any("RF9" in s for s in r.soft_flags)


def test_no_veto_when_data_absent():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials")
    r = run_veto_pass(_report_with(0.7), snap)
    assert r.composite_score == pytest.approx(0.7)
    assert r.vetoes == []


def test_financial_not_vetoed_on_altman():
    snap = CompanySnapshot(ticker="BANK.NS", sector="Financial Services",
                           is_financial=True, altman_z=0.5)
    r = run_veto_pass(_report_with(0.7), snap)
    # Altman not meaningful for financials -> no RF4.
    assert r.composite_score == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# M-1: ROCE / operating-margin use OPERATING income, not yfinance "EBIT"
# ---------------------------------------------------------------------------


def test_enrich_roce_uses_operating_income_not_ebit():
    # yfinance returns BOTH an "EBIT" row (which includes non-operating / other
    # income) and an "Operating Income" row. ROCE and the operating-margin series
    # must use OPERATING income (spec 3.2, M-1 fix); interest coverage / Altman
    # keep the true EBIT.
    fin = _fixture_financials()
    fin["income"]["EBIT"] = [200.0, 240.0, 300.0]  # inflated by other income
    # "Operating Income" stays [120, 150, 180].
    snap = CompanySnapshot(ticker="T.NS", sector="Information Technology")
    enrich_snapshot_with_financials(snap, fin)
    # ROCE latest uses operating income: 180 / (1000 - 250) = 0.24, NOT 300/750=0.40.
    assert snap.roce == pytest.approx(0.24, abs=1e-4)
    assert snap.roce_series[-1] == pytest.approx(0.24, abs=1e-4)
    # Operating-margin series uses operating income: 180 / 1000 = 0.18 latest.
    assert snap.operating_margin_series[-1] == pytest.approx(0.18, abs=1e-4)
    # Interest coverage keeps the true EBIT: 300 / 12 = 25.
    assert snap.interest_coverage == pytest.approx(300.0 / 12.0, abs=1e-3)


# ---------------------------------------------------------------------------
# M-2: robust log-linear growth (blunts lumpy base years)
# ---------------------------------------------------------------------------


def test_robust_growth_tames_lumpy_base_year():
    from src.data.provider import _robust_growth

    lumpy = [10.0, 100.0, 110.0, 120.0, 130.0]  # depressed base year
    endpoint = (130.0 / 10.0) ** (1.0 / 4) - 1.0  # naive first->last CAGR ~90%/yr
    robust = _robust_growth(lumpy)
    assert robust is not None
    assert robust < endpoint
    assert endpoint - robust > 0.15  # base-year distortion materially reduced


def test_robust_growth_keeps_positional_alignment_through_none():
    from src.data.provider import _robust_growth

    # Interior None keeps its slot; a mid-series gap does not misdate endpoints.
    assert _robust_growth([10.0, None, 12.0, 14.0]) is not None
    # Needs >= 2 positive observations.
    assert _robust_growth([None, 5.0]) is None
    assert _robust_growth([-3.0, -2.0]) is None


def test_enrich_earnings_cagr_is_robust_estimate():
    from src.data.provider import _robust_growth

    snap = CompanySnapshot(ticker="T.NS", sector="Information Technology",
                           pe_trailing=20.0)
    enrich_snapshot_with_financials(snap, _fixture_financials())
    # NI series [80, 95, 110] -> log-linear robust growth (not endpoint CAGR).
    assert snap.earnings_cagr == pytest.approx(_robust_growth([80.0, 95.0, 110.0]), abs=1e-6)


# ---------------------------------------------------------------------------
# Consistency level leg uses the multi-year MEAN (consistency > peak)
# ---------------------------------------------------------------------------


def test_roce_level_uses_series_mean_not_latest():
    # A high latest ROCE but low, stable history -> level leg = the mean, not TTM.
    snap = _rich_snap("A.NS", "Information Technology",
                      roce=0.40, roce_series=[0.10, 0.10, 0.10])
    assert multibagger.SIGNAL_EXTRACTORS["roce_level"](snap) == pytest.approx(0.10)
    # Falls back to the latest value when the series is too short for a mean.
    snap2 = _rich_snap("B.NS", "Information Technology", roce=0.33, roce_series=[])
    assert multibagger.SIGNAL_EXTRACTORS["roce_level"](snap2) == pytest.approx(0.33)
    # roe_level similarly ranks the roe_series mean.
    snap3 = _rich_snap("C.NS", "Information Technology", roe=0.40, roe_series=[0.12, 0.12])
    assert multibagger.SIGNAL_EXTRACTORS["roe_level"](snap3) == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# RF5: rising net-debt/EBITDA trend (not the gross-debt proxy)
# ---------------------------------------------------------------------------


def test_veto_rf5_net_debt_ebitda_rising():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           interest_coverage=1.0, net_debt_ebitda_rising=True)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF5" in v for v in r.vetoes)


def test_veto_rf5_not_fired_on_gross_debt_alone():
    # Gross debt rose but net-debt/EBITDA did NOT rise -> no RF5 (the fix).
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           interest_coverage=1.0, debt_rising=True,
                           net_debt_ebitda_rising=False)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score == pytest.approx(0.8)
    assert not any("RF5" in v for v in r.vetoes)


def test_enrich_net_debt_ebitda_trend_computed():
    snap = CompanySnapshot(ticker="T.NS", sector="Industrials")
    enrich_snapshot_with_financials(snap, _fixture_financials())
    # Gross debt rose (200->260) but EBITDA grew faster, so net-debt/EBITDA fell:
    # the two signals legitimately diverge (the whole point of the RF5 fix).
    assert snap.debt_rising is True
    assert snap.net_debt_ebitda_rising is False


# ---------------------------------------------------------------------------
# RF8: PE re-rated far beyond EPS leg
# ---------------------------------------------------------------------------


def test_veto_rf8_binding_leg_still_fires():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           pe_trailing=55.0, earnings_cagr=-0.02)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF8" in v for v in r.vetoes)


def test_veto_rf8_price_rerated_beyond_eps():
    # PE > 40, earnings essentially flat, but price compounded ~55%/yr -> the
    # multiple re-rated far beyond EPS. RF8 fires via the re-rating leg.
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           pe_trailing=45.0, earnings_cagr=0.0, price_cagr=0.55)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF8" in v for v in r.vetoes)


def test_no_rf8_when_price_tracks_eps():
    # Price and EPS grew together at a moderate PE -> no perception-only re-rating.
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           pe_trailing=25.0, earnings_cagr=0.20, price_cagr=0.22)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score == pytest.approx(0.8)
    assert not any("RF8" in v for v in r.vetoes)


# ---------------------------------------------------------------------------
# RF1: >= 3 of the LAST 5 years
# ---------------------------------------------------------------------------


def test_veto_rf1_only_counts_last_5_years():
    # 3 negatives, but they are OUTSIDE the trailing 5-year window -> no RF1.
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           fcf_series=[-1.0, -1.0, -1.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score == pytest.approx(0.8)
    assert not any("RF1" in v for v in r.vetoes)


def test_veto_rf1_fires_within_last_5_years():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           fcf_series=[5.0, 6.0, -1.0, -2.0, -3.0, 4.0])
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF1" in v for v in r.vetoes)


# ---------------------------------------------------------------------------
# RF2: consecutive-year clause + cumulative-NI<=0 handling
# ---------------------------------------------------------------------------


def test_veto_rf2_consecutive_low_cfo_ni():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           cfo_np_below_half_streak=3)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF2" in v and "consecutive" in v for v in r.vetoes)


def test_veto_rf2_cumulative_losses():
    snap = CompanySnapshot(ticker="Z.NS", sector="Industrials",
                           cum_np_nonpositive=True)
    r = run_veto_pass(_report_with(0.8), snap)
    assert r.composite_score is None
    assert any("RF2" in v for v in r.vetoes)


def test_enrich_cumulative_losses_sets_rf2_flag():
    fin = _fixture_financials()
    fin["income"]["Net Income"] = [-50.0, -40.0, -30.0]  # persistent losses
    snap = CompanySnapshot(ticker="L.NS", sector="Industrials")
    enrich_snapshot_with_financials(snap, fin)
    # cum(CFO)/cum(NP) is meaningless (cum NP <= 0) -> left None but flagged.
    assert snap.ocf_to_np_multiyear is None
    assert snap.cum_np_nonpositive is True


def test_enrich_cfo_ni_streak_computed():
    fin = _fixture_financials()
    fin["income"]["Net Income"] = [200.0, 220.0, 240.0]
    fin["cashflow"]["Operating Cash Flow"] = [50.0, 55.0, 60.0]  # CFO << NI each yr
    snap = CompanySnapshot(ticker="S.NS", sector="Industrials")
    enrich_snapshot_with_financials(snap, fin)
    assert snap.cfo_np_below_half_streak == 3


# ---------------------------------------------------------------------------
# Early-stage / reinvestment growth exception (spec section 6, RF1/RF2 note)
# ---------------------------------------------------------------------------


def _grower_snap(**over):
    """A capex/working-capital-heavy but genuinely PROFITABLE + SAFE grower:
    negative FCF and low cash-conversion, yet high returns and safe balance
    sheet (the HAL / BDL / Mazagon / Fine Organic archetype)."""
    base = dict(
        ticker="G.NS", sector="Industrials",
        net_income_series=[100.0, 120.0, 140.0, 160.0, 180.0],
        operating_margin_series=[0.10, 0.12, 0.13, 0.15, 0.17],
        roce_series=[0.16, 0.18, 0.20, 0.22, 0.21],
        roe_series=[0.18, 0.19, 0.20, 0.21, 0.20],
        altman_z=5.0,
        fcf_series=[-50.0, -60.0, -40.0, -55.0, -30.0],   # FCF<0 in >=3 of 5
        fcf_neg_years=5,
        ocf_to_np_multiyear=0.30,                          # low cash-conversion
        cum_np_nonpositive=False,
    )
    base.update(over)
    return CompanySnapshot(**base)


def test_early_stage_exception_true_for_profitable_capex_grower():
    assert is_early_stage_growth_exception(_grower_snap()) is True


def test_grower_not_vetoed_by_rf1_or_rf2():
    # A capex-heavy, profitable, safe grower must survive both cash-flow vetoes.
    r = run_veto_pass(_report_with(0.8), _grower_snap())
    assert r.composite_score == pytest.approx(0.8)
    assert not any(v.startswith("RF1") for v in r.vetoes)
    assert not any(v.startswith("RF2") for v in r.vetoes)
    assert r.early_stage_growth_exception is True


def test_cash_burner_is_still_vetoed_by_rf1_and_rf2():
    # Persistent operating losses (negative margins, cumulative NP<=0) are NOT a
    # growth exception - RF1 and RF2 must both still fire (KFA/Jet archetype).
    burner = _grower_snap(
        net_income_series=[-50.0, -60.0, -40.0, -30.0, -20.0],
        operating_margin_series=[-0.10, -0.20, -0.15, -0.10, -0.05],
        cum_np_nonpositive=True,
        altman_z=3.0,           # keep out of distress zone to isolate RF1/RF2
    )
    assert is_early_stage_growth_exception(burner) is False
    r = run_veto_pass(_report_with(0.8), burner)
    assert r.composite_score is None
    assert any(v.startswith("RF1") for v in r.vetoes)
    assert any(v.startswith("RF2") for v in r.vetoes)


def test_exception_denied_for_low_flat_returns():
    # Low, flat ROCE/ROE and low flat margins (the Gitanjali/ABB archetype):
    # safe balance sheet is NOT enough - it stays RF2-vetoed.
    flat = _grower_snap(
        roce_series=[0.08, 0.07, 0.07, 0.09, 0.09],
        roe_series=[0.09, 0.08, 0.09, 0.10, 0.10],
        operating_margin_series=[0.05, 0.05, 0.05, 0.06, 0.06],
        altman_z=9.0,
        ocf_to_np_multiyear=0.20,
    )
    assert is_early_stage_growth_exception(flat) is False
    r = run_veto_pass(_report_with(0.8), flat)
    assert r.composite_score is None
    assert any(v.startswith("RF2") for v in r.vetoes)


def test_exception_via_improvement_trajectory_low_but_rising():
    # Low absolute returns but a strong scale-up (ROCE expands ~9x off a positive
    # base, operating margin rising) - the Trent/Zudio archetype qualifies.
    scaleup = _grower_snap(
        net_income_series=[100.0, 60.0, 80.0, 90.0],
        roce_series=[0.01, 0.03, 0.05, 0.09],
        roe_series=[0.09, 0.04, 0.05, 0.06],
        operating_margin_series=[0.01, 0.03, 0.05, 0.08],
        altman_z=9.0,
        fcf_series=[-50.0, -20.0, -30.0, -40.0],
        ocf_to_np_multiyear=None,   # isolate RF1
    )
    assert is_early_stage_growth_exception(scaleup) is True
    r = run_veto_pass(_report_with(0.8), scaleup)
    assert not any(v.startswith("RF1") for v in r.vetoes)


def test_exception_denied_when_distressed_altman():
    # A grower's numbers but a distressed balance sheet: the safety leg fails, so
    # the exception is refused AND RF4 fires independently.
    distressed = _grower_snap(altman_z=0.9)
    assert is_early_stage_growth_exception(distressed) is False
    r = run_veto_pass(_report_with(0.8), distressed)
    assert r.composite_score is None
    assert any(v.startswith("RF4") for v in r.vetoes)


def test_exception_does_not_relax_beneish_or_distress():
    # Even a qualifying grower is still caught by RF3 (manipulation): the
    # exception only ever relaxes the cash-flow vetoes RF1/RF2.
    manip = _grower_snap(beneish_m=-0.5)
    assert is_early_stage_growth_exception(manip) is True
    r = run_veto_pass(_report_with(0.8), manip)
    assert r.composite_score is None
    assert any(v.startswith("RF3") for v in r.vetoes)
    assert not any(v.startswith("RF1") for v in r.vetoes)


def test_exception_requires_multi_year_window():
    # A 2-year window is too short to grant the carve-out.
    short = _grower_snap(
        net_income_series=[100.0, 120.0],      # only 2 income years -> too short
        operating_margin_series=[0.12, 0.15],
        roce_series=[0.18, 0.20],
        roe_series=[0.19, 0.20],
        fcf_series=[-50.0, -60.0, -40.0],      # 3 negative FCF years -> RF1 trigger
    )
    assert is_early_stage_growth_exception(short) is False
    r = run_veto_pass(_report_with(0.8), short)
    assert any(v.startswith("RF1") for v in r.vetoes)
