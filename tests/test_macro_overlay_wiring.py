"""Unit tests for the macro/regime overlay WIRING into the multibagger scorer
(``docs/FRA_V2_MACRO.md`` 4, now implemented).

These are hermetic (no network): the regime is either hand-built as a plain
overlay dict or computed from an injected fixture ``series_provider``. We assert:

* **No-op by default** - ``overlay=None`` (and a no-op unknown-regime overlay)
  reproduce the pre-overlay composites byte-for-byte.
* **Tilt math** - ``pillar_tilts`` re-weight the composite exactly (a
  rerating-dominant tilt makes ``raw_composite`` collapse to the rerating pillar).
* **Boost math** - ``rerating_boost`` adds to the re-rating pillar SCORE, clamped
  to [0, 1], and never below the off value.
* **Context, never a kill** - the overlay annotates ``report.regime_context`` and
  NEVER adds/removes a veto (a vetoed name stays vetoed with the overlay on).
* **Per-name overlay** - ``overlay_by_ticker`` applies independently per ticker.
* **PIT correctness in-backtest** - the per-name regime the backtest computes at a
  historical as-of does not leak a later spike.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.data.provider import CompanySnapshot
from src.factors import regime
from src.factors.multibagger import DEFAULT_PILLAR_WEIGHTS, rank_multibagger


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


def _weak_snap(ticker, sector):
    return _rich_snap(
        ticker, sector,
        roce=0.05, roe=0.04, gross_profitability=0.1, asset_turnover=0.4,
        cash_conversion=0.5, accruals_ratio=0.15, fcf_posrate=0.2,
        fcf_yield=0.0, ocf_to_np_multiyear=1.0, altman_z=3.0,
        net_debt_to_ebitda=3.0, interest_coverage=3.0, current_ratio=1.0,
        earnings_cagr=0.02, peg=4.0, earnings_yield=0.02,
        gross_margin_series=[0.2, 0.15, 0.1], operating_margin_series=[0.1, 0.06, 0.03],
        capex_intensity=0.3, momentum_12_1=-0.1, momentum_6_1=-0.05,
        roce_series=[0.1, 0.05, 0.02],
    )


def _panel():
    return [_rich_snap("A.NS", "Information Technology"),
            _weak_snap("B.NS", "Information Technology")]


def _noop_overlay():
    reg = regime.compute_regime("2021-01-01", series_provider=lambda n: [])
    return regime.build_scorer_overlay(reg)


# --- No-op invariance ------------------------------------------------------


def test_overlay_none_is_unchanged_vs_noop_overlay():
    off = rank_multibagger(_panel(), sector_relative=False)
    noop = rank_multibagger(_panel(), sector_relative=False, overlay=_noop_overlay())
    off_by = {r.ticker: r for r in off}
    for r in noop:
        assert r.composite_score == off_by[r.ticker].composite_score
        assert r.raw_composite == off_by[r.ticker].raw_composite


def test_overlay_none_leaves_regime_context_empty():
    off = rank_multibagger(_panel(), sector_relative=False)
    assert all(r.regime_context == {} for r in off)


def test_build_scorer_overlay_unknown_is_noop():
    ov = _noop_overlay()
    assert set(ov["pillar_tilts"]) == set(DEFAULT_PILLAR_WEIGHTS)
    assert all(abs(v - 1.0) < 1e-9 for v in ov["pillar_tilts"].values())
    assert ov["rerating_boost"] == 0.0
    assert ov["entry_context"]["tighten_vetoes"] is False
    assert ov["regime_label"] == "unknown"


# --- Tilt math -------------------------------------------------------------


def test_pillar_tilt_reweights_composite_toward_upweighted_pillar():
    # A rerating-dominant tilt should collapse raw_composite onto the rerating
    # pillar score (the compositing weight is essentially all on that pillar).
    tilts = {p: 0.001 for p in DEFAULT_PILLAR_WEIGHTS}
    tilts["rerating_catalysts"] = 1000.0
    ov = {"pillar_tilts": tilts}
    on = rank_multibagger(_panel(), sector_relative=False, overlay=ov)
    for r in on:
        rr = r.pillar_scores["rerating_catalysts"]
        assert rr is not None
        assert r.raw_composite == pytest.approx(rr, abs=1e-3)


def test_pillar_tilt_does_not_mutate_default_weights():
    before = dict(DEFAULT_PILLAR_WEIGHTS)
    falling = [{"date": f"2018-{(i % 12) + 1:02d}-01", "value": 6.5 - 0.05 * i} for i in range(24)]
    reg = regime.compute_regime("2020-01-15", series_provider=lambda n: falling if n == "india_repo_rate" else [])
    rank_multibagger(_panel(), sector_relative=False, overlay=regime.build_scorer_overlay(reg))
    assert DEFAULT_PILLAR_WEIGHTS == before


# --- Boost math ------------------------------------------------------------


def test_rerating_boost_adds_to_pillar_score_clamped():
    off = {r.ticker: r for r in rank_multibagger(_panel(), sector_relative=False)}
    ov = {"rerating_boost": 0.1}
    on = rank_multibagger(_panel(), sector_relative=False, overlay=ov)
    for r in on:
        off_rr = off[r.ticker].pillar_scores["rerating_catalysts"]
        on_rr = r.pillar_scores["rerating_catalysts"]
        if off_rr is not None:
            assert on_rr == pytest.approx(min(1.0, off_rr + 0.1))
            assert on_rr >= off_rr
            # A positive re-rating weight means the composite cannot fall.
            if r.composite_score is not None and off[r.ticker].composite_score is not None:
                assert r.composite_score >= off[r.ticker].composite_score - 1e-9


def test_boost_annotated_in_regime_context():
    ov = {"rerating_boost": 0.07, "entry_context": {"tighten_vetoes": False, "cautions": []},
          "regime_label": "risk_on"}
    on = rank_multibagger(_panel(), sector_relative=False, overlay=ov)
    for r in on:
        assert r.regime_context.get("rerating_boost") == 0.07
        assert r.regime_context.get("regime_label") == "risk_on"


# --- Context never kills ---------------------------------------------------


def test_overlay_never_adds_or_removes_a_veto():
    # RF4 (Altman distress) name is vetoed off; must stay vetoed with overlay on,
    # and a risk_off "tighten_vetoes" context must NOT silently kill a clean name.
    distressed = _rich_snap("D.NS", "Industrials", altman_z=0.7)
    clean = _rich_snap("C.NS", "Industrials")
    risk_off_ov = {
        "pillar_tilts": {p: 1.0 for p in DEFAULT_PILLAR_WEIGHTS},
        "rerating_boost": 0.0,
        "entry_context": {"tighten_vetoes": True, "avoid_new_rich_multiples": True,
                          "cautions": ["risk_off_tape"]},
        "regime_label": "risk_off",
    }
    off = {r.ticker: r for r in rank_multibagger([distressed, clean], sector_relative=False)}
    on = {r.ticker: r for r in rank_multibagger([distressed, clean], sector_relative=False, overlay=risk_off_ov)}
    # Same veto set both ways.
    assert on["D.NS"].vetoes == off["D.NS"].vetoes
    assert any("RF4" in v for v in on["D.NS"].vetoes)
    assert on["D.NS"].composite_score is None
    # Clean name is NOT killed by the tighten-vetoes context (still scored).
    assert on["C.NS"].composite_score is not None
    assert on["C.NS"].vetoes == []
    # But the context IS surfaced for review.
    assert "risk_off_tape" in on["C.NS"].regime_context.get("cautions", [])


# --- Per-name overlay ------------------------------------------------------


def test_overlay_by_ticker_applies_per_name():
    ov_a = {"rerating_boost": 0.1}
    off = {r.ticker: r for r in rank_multibagger(_panel(), sector_relative=False)}
    on = {r.ticker: r for r in rank_multibagger(
        _panel(), sector_relative=False, overlay_by_ticker={"A.NS": ov_a})}
    # A got the boost; B did not (fell back to overlay=None -> unchanged).
    assert on["A.NS"].pillar_scores["rerating_catalysts"] >= off["A.NS"].pillar_scores["rerating_catalysts"]
    assert on["B.NS"].composite_score == off["B.NS"].composite_score
    assert on["B.NS"].regime_context == {}


# --- PIT correctness of the in-backtest regime -----------------------------


def _series(start, values):
    d0 = dt.date.fromisoformat(start)
    return [{"date": (d0 + dt.timedelta(days=i)).isoformat(), "value": v}
            for i, v in enumerate(values)]


def test_backtest_per_name_regime_overlay_is_pit():
    # India-VIX is calm through the as-of, then spikes AFTER it. The regime the
    # backtest computes at the early as-of must NOT see the later risk-off spike.
    calm = _series("2020-01-01", [12.0 + (i % 5) for i in range(200)])
    spike = _series("2020-10-01", [80.0] * 10)
    vix = calm + spike

    def provider(name):
        return vix if name == "india_vix" else []

    reg = regime.compute_regime("2020-05-01", sector="Information Technology",
                                series_provider=provider)
    ov = regime.build_scorer_overlay(reg)
    # No look-ahead: the post-as_of blow-off does not flip us to risk_off.
    assert ov["regime_label"] != "risk_off"
    assert ov["entry_context"]["tighten_vetoes"] is False

    # And it threads through the scorer exactly as the backtest does.
    panel = _panel()
    reports = rank_multibagger(panel, sector_relative=False,
                               overlay_by_ticker={"A.NS": ov})
    rep_a = next(r for r in reports if r.ticker == "A.NS")
    assert rep_a.regime_context.get("regime_label") == ov["regime_label"]
