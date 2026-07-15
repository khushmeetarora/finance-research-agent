"""Unit tests for the macro regime layer + its (unwired) integration API.

Hermetic: no network. A fixture ``series_provider`` returns synthetic full
series; the regime code PIT-gates and classifies them. We assert regime
classification, as_of gating (no future data leaks), graceful-failure paths,
and that the integration API returns sane, bounded tilts without touching the
scorer.
"""

from __future__ import annotations

import datetime as dt

from src.factors import regime
from src.factors.multibagger import DEFAULT_PILLAR_WEIGHTS


def _daily(start: str, values: list[float]) -> list[dict]:
    d0 = dt.date.fromisoformat(start)
    return [
        {"date": (d0 + dt.timedelta(days=i)).isoformat(), "value": v}
        for i, v in enumerate(values)
    ]


def _monthly(start_year: int, months: int, fn) -> list[dict]:
    out, y, m = [], start_year, 1
    for i in range(months):
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": fn(i)})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _build_provider(**series) -> "callable":
    """Return a provider callable backed by an in-memory dict of full series."""
    def _provider(name: str) -> list[dict]:
        return series.get(name, [])
    return _provider


# --- Rate regime -----------------------------------------------------------


def test_rate_regime_easing_and_tightening():
    # 24 months of a steadily FALLING repo rate -> easing.
    falling = _monthly(2018, 24, lambda i: 6.5 - 0.05 * i)
    reg = regime.compute_regime(
        "2020-01-15", series_provider=_build_provider(india_repo_rate=falling)
    )
    assert reg["signals"]["rates"]["available"] is True
    assert reg["signals"]["rates"]["regime"] == "easing"
    assert reg["signals"]["rates"]["flag_rates_rising"] is False

    rising = _monthly(2018, 24, lambda i: 4.0 + 0.05 * i)
    reg2 = regime.compute_regime(
        "2020-01-15", series_provider=_build_provider(india_repo_rate=rising)
    )
    assert reg2["signals"]["rates"]["regime"] == "tightening"
    assert reg2["signals"]["rates"]["flag_rates_rising"] is True


# --- Risk regime (VIX percentile) -----------------------------------------


def test_risk_regime_risk_off_when_vix_at_top():
    # Long calm history then a spike so the latest value is at the top percentile.
    vals = [12.0 + (i % 3) for i in range(500)] + [45.0]
    vix = _daily("2019-01-01", vals)
    reg = regime.compute_regime(
        "2021-06-01", series_provider=_build_provider(india_vix=vix)
    )
    r = reg["signals"]["risk"]
    assert r["available"] is True
    assert r["regime"] == "risk_off"
    assert r["flag_risk_off"] is True
    assert reg["composite"]["risk_off"] is True


def test_risk_regime_risk_on_when_vix_low():
    vals = [30.0 - (i % 5) for i in range(500)] + [9.0]
    vix = _daily("2019-01-01", vals)
    reg = regime.compute_regime(
        "2021-06-01", series_provider=_build_provider(india_vix=vix)
    )
    assert reg["signals"]["risk"]["regime"] == "risk_on"


# --- Crude + FX ------------------------------------------------------------


def test_crude_spike_flag():
    # Flat then +15% over the last 20 days -> spike.
    base = [80.0] * 40
    ramp = [80.0 * (1 + 0.15 * (i + 1) / 20) for i in range(20)]
    crude = _daily("2021-01-01", base + ramp)
    reg = regime.compute_regime(
        "2021-06-01", series_provider=_build_provider(crude_brent=crude)
    )
    assert reg["signals"]["crude"]["flag_spike"] is True


def test_fx_inr_depreciation_flag():
    # USDINR rising ~5% over the window = INR depreciation.
    usdinr = _daily("2021-01-01", [74.0 * (1 + 0.05 * i / 40) for i in range(41)])
    reg = regime.compute_regime(
        "2021-06-01", series_provider=_build_provider(usdinr=usdinr)
    )
    fx = reg["signals"]["fx"]
    assert fx["available"] is True
    assert fx["flag_inr_depreciating"] is True


# --- PIT / as_of gating ----------------------------------------------------


def test_as_of_gating_hides_future_points():
    # Series continues past as_of; the spike happens AFTER as_of and must not leak.
    # Calm phase oscillates in a low band (12..16), so the as_of-admissible read
    # sits mid/low-percentile - the ONLY thing that could push it to risk_off is
    # the post-as_of spike, which must be gated out.
    calm = _daily("2020-01-01", [12.0 + (i % 5) for i in range(200)])
    spike = _daily("2020-10-01", [80.0] * 10)
    vix = calm + spike
    reg = regime.compute_regime(
        "2020-05-01", series_provider=_build_provider(india_vix=vix)
    )
    # Latest admissible value is from the calm band, never the 80.0 spike.
    assert reg["signals"]["risk"]["level"] <= 16.0
    assert reg["signals"]["risk"]["flag_risk_off"] in (False, None)


def test_publication_lag_blocks_unreleased_cpi(monkeypatch):
    # A single CPI print stamped for a period-end just before as_of but whose
    # 21-day release lag pushes knowledge past as_of -> unavailable.
    cpi = [{"date": "2020-06-30", "value": 150.0}]
    reg = regime.compute_regime(
        "2020-07-05", series_provider=_build_provider(india_cpi=cpi)
    )
    # Only one point and it's not yet released -> inflation signal unavailable.
    assert reg["signals"]["inflation"]["available"] is False


# --- Graceful failure ------------------------------------------------------


def test_all_missing_series_gives_neutral_unknown():
    reg = regime.compute_regime("2021-01-01", series_provider=_build_provider())
    assert reg["available"] == []
    assert set(reg["missing"]) >= {"rates", "risk", "crude", "fx", "equity"}
    assert reg["composite"]["label"] == "unknown"


def test_provider_that_raises_is_swallowed():
    def _boom(name):
        raise RuntimeError("provider blew up")

    reg = regime.compute_regime("2021-01-01", series_provider=_boom)
    assert reg["composite"]["label"] == "unknown"


# --- Sector tailwind -------------------------------------------------------


def test_sector_tailwind_it_on_inr_depreciation():
    usdinr = _daily("2021-01-01", [74.0 * (1 + 0.05 * i / 40) for i in range(41)])
    reg = regime.compute_regime(
        "2021-06-01",
        sector="Information Technology",
        series_provider=_build_provider(usdinr=usdinr),
    )
    tw = reg["sector_tailwind"]
    assert tw["available"] is True
    assert tw["tilt"] > 0  # INR depreciation is a tailwind for IT exporters


def test_sector_tailwind_energy_on_crude_spike():
    base = [80.0] * 40
    ramp = [80.0 * (1 + 0.15 * (i + 1) / 20) for i in range(20)]
    crude = _daily("2021-01-01", base + ramp)
    reg = regime.compute_regime(
        "2021-06-01", sector="Energy", series_provider=_build_provider(crude_brent=crude)
    )
    assert reg["sector_tailwind"]["tilt"] > 0


# --- Integration API (unwired) --------------------------------------------


def test_pillar_tilts_are_bounded_and_cover_all_pillars():
    reg = regime.compute_regime("2021-01-01", series_provider=_build_provider())
    tilts = regime.regime_pillar_tilts(reg)
    # Every scorer pillar is present (contract for a later wiring step).
    assert set(tilts) == set(DEFAULT_PILLAR_WEIGHTS)
    # All-unknown regime -> no-op tilt (all 1.0).
    assert all(abs(v - 1.0) < 1e-9 for v in tilts.values())


def test_pillar_tilts_easing_upweights_growth_and_rerating():
    falling = _monthly(2018, 24, lambda i: 6.5 - 0.05 * i)
    reg = regime.compute_regime(
        "2020-01-15", series_provider=_build_provider(india_repo_rate=falling)
    )
    tilts = regime.regime_pillar_tilts(reg)
    assert tilts["growth_valuation"] > 1.0
    assert tilts["rerating_catalysts"] > 1.0
    assert all(v > 0 for v in tilts.values())


def test_entry_context_flags_risk_off():
    vals = [12.0 + (i % 3) for i in range(500)] + [45.0]
    vix = _daily("2019-01-01", vals)
    reg = regime.compute_regime(
        "2021-06-01", series_provider=_build_provider(india_vix=vix)
    )
    ctx = regime.regime_entry_context(reg)
    assert ctx["tighten_vetoes"] is True
    assert "risk_off_tape" in ctx["cautions"]


def test_rerating_boost_bounded():
    falling = _monthly(2018, 24, lambda i: 6.5 - 0.05 * i)
    reg = regime.compute_regime(
        "2020-01-15", sector="Consumer Cyclical",
        series_provider=_build_provider(india_repo_rate=falling),
    )
    events = {"policy_catalyst": {"count": 3}}
    boost = regime.rerating_catalyst_boost(reg, events)
    assert 0.0 <= boost <= 0.10


def test_pillar_tilts_do_not_mutate_default_weights():
    reg = regime.compute_regime("2021-01-01", series_provider=_build_provider())
    before = dict(DEFAULT_PILLAR_WEIGHTS)
    regime.regime_pillar_tilts(reg)
    assert DEFAULT_PILLAR_WEIGHTS == before
