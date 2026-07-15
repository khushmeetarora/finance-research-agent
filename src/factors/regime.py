"""Macro regime layer - interpretable, PIT-safe regime flags for an ``as_of``.

NEW, self-contained module for the FRA V2 macro/regime/news overlay
(``docs/FRA_V2_MACRO.md``). It converts the free macro/market series from
``src/data/macro_signals.py`` into a small dict of human-readable regime
signals (rates easing/tightening, inflation band, crude spike, INR depreciation,
risk-on/off via India-VIX, equity trend, credit/curve proxy, and an optional
per-sector tailwind).

**It deliberately does NOT modify the scorer or the backtest.** Instead it
exposes a clean, pure integration API (``regime_pillar_tilts``,
``regime_entry_context``, ``rerating_catalyst_boost``) that a *later* wiring
step can overlay on the 7-pillar composite as a tilt / veto-context /
re-rating-catalyst booster. The intended integration point is documented in
``docs/FRA_V2_MACRO.md`` and in the docstrings below.

Point-in-time guarantee: every series is passed through
``macro_signals.as_of_series`` with the per-series ``publication_lag_days``
BEFORE any statistic is computed, so a regime read for a historical date can
only use observations that were released on/before that date. All computation
is driven by an injectable ``series_provider`` callable, so tests run offline
with fixture series.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from ..data import macro_signals as ms

SeriesProvider = Callable[[str], list[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Individual regime signal builders. Each returns a small dict:
#   {"available": bool, "value": float|None, "regime"/"flags": ...,
#    "source": str, "n_points": int}
# A missing/short series yields available=False and neutral values, never raises.
# ---------------------------------------------------------------------------


def _prep(
    provider: SeriesProvider, name: str, as_of: _dt.date, cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch the full series then PIT-gate it to ``as_of`` with its config lag."""
    try:
        full = provider(name) or []
    except Exception:
        full = []
    lag = ms.publication_lag(name, cfg)
    return ms.as_of_series(full, as_of, publication_lag_days=lag)


def _rate_regime(provider, as_of, cfg) -> dict[str, Any]:
    lb = cfg["lookbacks"]["rate_delta_days"]
    thr = cfg["thresholds"]["rate_move_points"]
    s = _prep(provider, "india_repo_rate", as_of, cfg)
    d = ms.delta(s, lb)
    level = ms.latest(s)
    if not s or d is None:
        return {"available": False, "value": None, "level": level,
                "regime": "unknown", "flag_rates_rising": None,
                "source": ms.source_label("india_repo_rate", cfg), "n_points": len(s)}
    if d <= -thr:
        regime = "easing"
    elif d >= thr:
        regime = "tightening"
    else:
        regime = "neutral"
    return {
        "available": True, "value": d, "level": level, "regime": regime,
        "flag_rates_rising": d >= thr,
        "source": ms.source_label("india_repo_rate", cfg), "n_points": len(s),
    }


def _inflation_regime(provider, as_of, cfg) -> dict[str, Any]:
    yoy_days = cfg["lookbacks"]["cpi_yoy_days"]
    short_days = cfg["lookbacks"]["cpi_short_days"]
    band = cfg["thresholds"]["cpi_band"]
    s = _prep(provider, "india_cpi", as_of, cfg)
    yoy = ms.momentum(s, yoy_days)      # index -> YoY inflation as a fraction
    short = ms.momentum(s, short_days)
    if not s or yoy is None:
        return {"available": False, "value": None, "regime": "unknown",
                "flag_above_band": None, "flag_rising": None,
                "source": ms.source_label("india_cpi", cfg), "n_points": len(s)}
    # Annualise the short window so it is comparable to the YoY figure.
    short_ann = None
    if short is not None and short_days > 0:
        try:
            short_ann = (1.0 + short) ** (365.0 / short_days) - 1.0
        except (ValueError, OverflowError):
            short_ann = None
    rising = None if short_ann is None else short_ann > yoy
    if yoy >= band:
        regime = "hot"
    elif yoy <= band / 2.0:
        regime = "cool"
    else:
        regime = "moderate"
    return {
        "available": True, "value": yoy, "regime": regime,
        "flag_above_band": yoy >= band, "flag_rising": rising,
        "source": ms.source_label("india_cpi", cfg), "n_points": len(s),
    }


def _crude_regime(provider, as_of, cfg) -> dict[str, Any]:
    lb = cfg["lookbacks"]["crude_momentum_days"]
    thr = cfg["thresholds"]["crude_spike_mom"]
    # Prefer Brent, fall back to WTI.
    s = _prep(provider, "crude_brent", as_of, cfg)
    used = "crude_brent"
    if not s:
        s = _prep(provider, "crude_wti", as_of, cfg)
        used = "crude_wti"
    mom = ms.momentum(s, lb)
    level = ms.latest(s)
    if not s or mom is None:
        return {"available": False, "value": None, "level": level,
                "flag_spike": None, "source": ms.source_label(used, cfg),
                "n_points": len(s)}
    return {
        "available": True, "value": mom, "level": level,
        "flag_spike": mom >= thr, "flag_crash": mom <= -thr,
        "source": ms.source_label(used, cfg), "n_points": len(s),
    }


def _fx_regime(provider, as_of, cfg) -> dict[str, Any]:
    lb = cfg["lookbacks"]["inr_momentum_days"]
    volw = cfg["lookbacks"]["vol_window_points"]
    dep_thr = cfg["thresholds"]["inr_depreciation_mom"]
    vol_thr = cfg["thresholds"]["fx_stress_vol"]
    s = _prep(provider, "usdinr", as_of, cfg)
    mom = ms.momentum(s, lb)          # USDINR up = INR depreciation
    vol = ms.annualized_vol(s, volw)
    level = ms.latest(s)
    if not s or mom is None:
        return {"available": False, "value": None, "level": level, "vol": vol,
                "flag_inr_depreciating": None, "flag_fx_stress": None,
                "source": ms.source_label("usdinr", cfg), "n_points": len(s)}
    stress = bool((vol is not None and vol >= vol_thr) or abs(mom) >= dep_thr)
    return {
        "available": True, "value": mom, "level": level, "vol": vol,
        "flag_inr_depreciating": mom >= dep_thr,
        "flag_inr_appreciating": mom <= -dep_thr,
        "flag_fx_stress": stress,
        "source": ms.source_label("usdinr", cfg), "n_points": len(s),
    }


def _risk_regime(provider, as_of, cfg) -> dict[str, Any]:
    lb = cfg["lookbacks"]["vix_percentile_days"]
    off = cfg["thresholds"]["vix_riskoff_pct"]
    on = cfg["thresholds"]["vix_riskon_pct"]
    s = _prep(provider, "india_vix", as_of, cfg)
    pct = ms.percentile_rank(s, lb)
    level = ms.latest(s)
    if not s or pct is None:
        return {"available": False, "value": None, "level": level,
                "regime": "unknown", "flag_risk_off": None, "flag_risk_on": None,
                "source": ms.source_label("india_vix", cfg), "n_points": len(s)}
    if pct >= off:
        regime = "risk_off"
    elif pct <= on:
        regime = "risk_on"
    else:
        regime = "neutral"
    return {
        "available": True, "value": pct, "level": level, "regime": regime,
        "flag_risk_off": pct >= off, "flag_risk_on": pct <= on,
        "source": ms.source_label("india_vix", cfg), "n_points": len(s),
    }


def _equity_trend(provider, as_of, cfg) -> dict[str, Any]:
    lb = cfg["lookbacks"]["nifty_trend_days"]
    s = _prep(provider, "nifty", as_of, cfg)
    mom = ms.momentum(s, lb)
    level = ms.latest(s)
    if not s or mom is None:
        return {"available": False, "value": None, "level": level,
                "flag_uptrend": None, "source": ms.source_label("nifty", cfg),
                "n_points": len(s)}
    return {
        "available": True, "value": mom, "level": level,
        "flag_uptrend": mom > 0.0, "flag_downtrend": mom < 0.0,
        "source": ms.source_label("nifty", cfg), "n_points": len(s),
    }


def _credit_curve(provider, as_of, cfg) -> dict[str, Any]:
    """Global rate-impulse + credit-appetite proxy (documented as a proxy).

    A truly free, programmatic India AAA-vs-GSec spread is not reliably
    available (see docs/FRA_V2_MACRO.md), so we use FRED's BAA-10Y credit spread
    (widening = risk-off) and the US 10Y-2Y curve slope as global proxies. These
    co-move with, but are not identical to, India's own credit conditions.
    """
    s10 = _prep(provider, "us_10y", as_of, cfg)
    s2 = _prep(provider, "us_2y", as_of, cfg)
    spread = _prep(provider, "baa_spread", as_of, cfg)
    y10 = ms.latest(s10)
    y2 = ms.latest(s2)
    slope = (y10 - y2) if (y10 is not None and y2 is not None) else None
    spread_level = ms.latest(spread)
    spread_mom = ms.momentum(spread, 60)  # ~3 months widening?
    available = spread_level is not None or slope is not None
    return {
        "available": available,
        "curve_slope_10y_2y": slope,
        "credit_spread": spread_level,
        "flag_credit_widening": (None if spread_mom is None else spread_mom > 0.0),
        "flag_curve_inverted": (None if slope is None else slope < 0.0),
        "source": "FRED:BAA10Y/DGS10/DGS2",
        "n_points": max(len(s10), len(s2), len(spread)),
    }


# ---------------------------------------------------------------------------
# Sector tailwind (optional). A small, transparent mapping - documented as a
# heuristic, not a fitted model. Returns a tilt in [-1, 1] for the given sector
# implied by the macro regime.
# ---------------------------------------------------------------------------

# sector (yfinance-style) -> (macro flag key path, sign). Positive sign = the
# flag being True is a TAILWIND for that sector.
_SECTOR_RULES: dict[str, list[tuple[str, float]]] = {
    "Energy": [("crude.flag_spike", +1.0), ("crude.flag_crash", -1.0)],
    "Basic Materials": [("crude.flag_spike", -0.5)],
    "Materials": [("crude.flag_spike", -0.5)],
    "Industrials": [("rates.easing", +0.5), ("equity.flag_uptrend", +0.5)],
    "Consumer Cyclical": [("rates.easing", +1.0), ("risk.flag_risk_off", -0.5)],
    "Consumer Defensive": [("risk.flag_risk_off", +0.5), ("crude.flag_spike", -0.25)],
    "Technology": [("fx.flag_inr_depreciating", +1.0)],
    "Information Technology": [("fx.flag_inr_depreciating", +1.0)],
    "Healthcare": [("fx.flag_inr_depreciating", +0.5)],
    "Financial Services": [("rates.easing", +0.5), ("credit.flag_credit_widening", -1.0)],
    "Financials": [("rates.easing", +0.5), ("credit.flag_credit_widening", -1.0)],
    "Utilities": [("rates.tightening", -0.5)],
}


def _flag_value(signals: dict[str, Any], path: str) -> bool | None:
    """Resolve a dotted flag path against the computed signals dict.

    Supports synthetic paths ``rates.easing`` / ``rates.tightening`` derived from
    the rate regime string, plus direct ``group.flag_x`` lookups.
    """
    group, _, key = path.partition(".")
    sig = signals.get(group, {})
    if group == "rates" and key in ("easing", "tightening", "neutral"):
        return sig.get("regime") == key
    return sig.get(key)


def _sector_tailwind(sector: str | None, signals: dict[str, Any]) -> dict[str, Any]:
    if not sector:
        return {"available": False, "sector": None, "tilt": 0.0, "reasons": []}
    rules = _SECTOR_RULES.get(sector)
    if not rules:
        return {"available": False, "sector": sector, "tilt": 0.0, "reasons": []}
    tilt = 0.0
    reasons: list[str] = []
    for path, sign in rules:
        val = _flag_value(signals, path)
        if val:
            tilt += sign
            reasons.append(f"{path}:{'+' if sign > 0 else '-'}")
    # Clamp to [-1, 1].
    tilt = max(-1.0, min(1.0, tilt))
    return {"available": True, "sector": sector, "tilt": tilt, "reasons": reasons}


# ---------------------------------------------------------------------------
# Top-level regime computation.
# ---------------------------------------------------------------------------


def compute_regime(
    as_of: "_dt.date | str",
    *,
    sector: str | None = None,
    series_provider: SeriesProvider | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the PIT-safe regime dict for ``as_of`` (optionally for a ``sector``).

    Parameters
    ----------
    as_of:
        Decision date (``datetime.date`` or ``YYYY-MM-DD`` string). Only data
        knowable on/before this date is used.
    sector:
        Optional yfinance-style sector name; when given, a per-sector macro
        tailwind (in [-1, 1]) is added under ``["sector"]``.
    series_provider:
        ``name -> full series`` callable (see ``macro_signals.default_series_provider``).
        Injected by tests with fixture series so nothing hits the network.
    config:
        Parsed ``config/macro.yaml`` (defaults auto-loaded).

    Returns a dict:
        {
          "as_of": "YYYY-MM-DD",
          "sector": <sector or None>,
          "signals": { rates, inflation, crude, fx, risk, equity, credit },
          "sector_tailwind": {...},
          "composite": {"label": "risk_on|risk_off|neutral", "risk_on": bool, ...},
          "available": [names...], "missing": [names...],
        }
    """
    if isinstance(as_of, str):
        parsed = ms._parse_date(as_of)
        if parsed is None:
            raise ValueError(f"Unparseable as_of date: {as_of!r}")
        as_of = parsed
    cfg = config or ms.load_macro_config()
    provider = series_provider or ms.default_series_provider(cfg)

    signals: dict[str, Any] = {
        "rates": _rate_regime(provider, as_of, cfg),
        "inflation": _inflation_regime(provider, as_of, cfg),
        "crude": _crude_regime(provider, as_of, cfg),
        "fx": _fx_regime(provider, as_of, cfg),
        "risk": _risk_regime(provider, as_of, cfg),
        "equity": _equity_trend(provider, as_of, cfg),
        "credit": _credit_curve(provider, as_of, cfg),
    }
    sector_tw = _sector_tailwind(sector, signals)

    available = [k for k, v in signals.items() if v.get("available")]
    missing = [k for k, v in signals.items() if not v.get("available")]

    composite = _composite(signals)

    return {
        "as_of": as_of.isoformat(),
        "sector": sector,
        "signals": signals,
        "sector_tailwind": sector_tw,
        "composite": composite,
        "available": available,
        "missing": missing,
    }


def _composite(signals: dict[str, Any]) -> dict[str, Any]:
    """Blend the individual flags into one coarse risk label + drivers.

    Conservative: unknown signals simply do not vote. ``risk_on`` requires an
    affirmative risk-on / uptrend read and the absence of active stress flags.
    """
    risk = signals["risk"]
    equity = signals["equity"]
    fx = signals["fx"]
    crude = signals["crude"]

    off_votes = 0
    on_votes = 0
    drivers: list[str] = []

    if risk.get("flag_risk_off"):
        off_votes += 2; drivers.append("vix_high")
    if risk.get("flag_risk_on"):
        on_votes += 2; drivers.append("vix_low")
    if equity.get("flag_downtrend"):
        off_votes += 1; drivers.append("nifty_downtrend")
    if equity.get("flag_uptrend"):
        on_votes += 1; drivers.append("nifty_uptrend")
    if fx.get("flag_fx_stress"):
        off_votes += 1; drivers.append("fx_stress")
    if crude.get("flag_spike"):
        off_votes += 1; drivers.append("crude_spike")

    if off_votes == 0 and on_votes == 0:
        label = "unknown"
    elif off_votes > on_votes:
        label = "risk_off"
    elif on_votes > off_votes:
        label = "risk_on"
    else:
        label = "neutral"
    return {
        "label": label,
        "risk_on": label == "risk_on",
        "risk_off": label == "risk_off",
        "on_votes": on_votes,
        "off_votes": off_votes,
        "drivers": drivers,
    }


# ===========================================================================
# INTEGRATION API (pure; NOT wired into the scorer - see docs/FRA_V2_MACRO.md).
# A later step overlays these on rank_multibagger(...) as tilts / context.
# ===========================================================================

# The pillar names below MUST match src/factors/multibagger.DEFAULT_PILLAR_WEIGHTS.
_PILLARS = (
    "profitability",
    "earnings_quality",
    "balance_sheet_safety",
    "growth_valuation",
    "moat_pricing_power",
    "promoter_governance",
    "rerating_catalysts",
)


def regime_pillar_tilts(
    regime: dict[str, Any], *, strength: float = 0.15
) -> dict[str, float]:
    """Multiplicative pillar-weight tilts implied by the regime (all ~1.0).

    Returns ``{pillar: factor}`` where ``factor`` in roughly
    ``[1-strength, 1+strength]``. The intended use (documented, NOT wired) is::

        tilts = regime_pillar_tilts(regime)
        w = {p: DEFAULT_PILLAR_WEIGHTS[p] * tilts[p] for p in DEFAULT_PILLAR_WEIGHTS}
        rank_multibagger(snaps, pillar_weights=w)   # _normalize_weights re-sums to 1

    Logic (spec docs/FRA_V2_RESEARCH.md 4):
      * easing / risk-on  -> up-weight growth_valuation + rerating_catalysts,
                             slightly down-weight balance_sheet_safety.
      * tightening / risk-off / FX stress -> up-weight balance_sheet_safety +
                             earnings_quality, down-weight rerating_catalysts.
    Unknown signals contribute nothing (factor stays 1.0), so a fully-offline
    run returns all-1.0 (a no-op tilt) - safe by construction.
    """
    tilts = {p: 1.0 for p in _PILLARS}
    s = max(0.0, float(strength))

    rates = regime.get("signals", {}).get("rates", {})
    risk = regime.get("signals", {}).get("risk", {})
    fx = regime.get("signals", {}).get("fx", {})
    comp = regime.get("composite", {})

    if rates.get("regime") == "easing" or comp.get("risk_on"):
        tilts["growth_valuation"] += s
        tilts["rerating_catalysts"] += s
        tilts["balance_sheet_safety"] -= s * 0.5
    if rates.get("regime") == "tightening" or comp.get("risk_off") or fx.get("flag_fx_stress"):
        tilts["balance_sheet_safety"] += s
        tilts["earnings_quality"] += s * 0.5
        tilts["rerating_catalysts"] -= s
    if risk.get("flag_risk_off"):
        tilts["profitability"] += s * 0.25  # flight to quality

    # Never let a factor go non-positive.
    for p in tilts:
        tilts[p] = max(0.1, tilts[p])
    return tilts


def regime_entry_context(regime: dict[str, Any]) -> dict[str, Any]:
    """Veto-context / entry-filter hints for a later wiring step (does NOT veto).

    Returns advisory flags the scorer or a downstream entry filter can consult,
    e.g. tighten vetoes and avoid initiating rich-multiple names in a risk-off
    tape. Consistent with the strategy's "screens, not verdicts" guardrail: this
    is CONTEXT, never a silent kill.
    """
    comp = regime.get("composite", {})
    signals = regime.get("signals", {})
    cautions: list[str] = []
    if comp.get("risk_off"):
        cautions.append("risk_off_tape")
    if signals.get("fx", {}).get("flag_fx_stress"):
        cautions.append("fx_stress")
    if signals.get("crude", {}).get("flag_spike"):
        cautions.append("crude_spike")
    if signals.get("credit", {}).get("flag_credit_widening"):
        cautions.append("credit_widening")
    if signals.get("inflation", {}).get("flag_above_band"):
        cautions.append("inflation_above_band")
    return {
        "tighten_vetoes": bool(comp.get("risk_off")),
        "avoid_new_rich_multiples": bool(comp.get("risk_off")),
        "prefer_balance_sheet_safety": bool(
            comp.get("risk_off") or signals.get("rates", {}).get("regime") == "tightening"
        ),
        "cautions": cautions,
    }


def rerating_catalyst_boost(
    regime: dict[str, Any],
    events: dict[str, Any] | None = None,
    *,
    max_boost: float = 0.10,
) -> float:
    """A small, bounded booster in ``[0, max_boost]`` for the re-rating-catalysts
    pillar (spec R3/R4), combining the macro regime with optional news/event
    signals from ``src/data/news_events.py``.

    Contributors (each additive, then clamped): easing rates, a positive sector
    tailwind, and any policy-catalyst event hits (PLI / import-duty / China+1 /
    privatization). Intended to be ADDED to the R4 leg during a later wiring
    step - it is NOT applied here.
    """
    boost = 0.0
    signals = regime.get("signals", {})
    if signals.get("rates", {}).get("regime") == "easing":
        boost += 0.03
    tw = regime.get("sector_tailwind", {}).get("tilt", 0.0) or 0.0
    if tw > 0:
        boost += 0.04 * min(1.0, tw)
    if events:
        pol = events.get("policy_catalyst", {})
        count = pol.get("count", 0) if isinstance(pol, dict) else 0
        if count:
            boost += min(0.05, 0.02 * count)
    return max(0.0, min(max_boost, boost))


def build_scorer_overlay(
    regime: dict[str, Any],
    events: dict[str, Any] | None = None,
    *,
    strength: float = 0.15,
    max_boost: float = 0.10,
) -> dict[str, Any]:
    """Bundle the three pure overlay functions into ONE plain-dict payload that
    the scorer (``multibagger.rank_multibagger(..., overlay=...)``) can apply
    without importing this module.

    Returns::

        {
          "pillar_tilts":   {pillar: multiplicative factor, ...},  # 4.1
          "rerating_boost": float in [0, max_boost],               # 4.3
          "entry_context":  {tighten_vetoes, cautions[...], ...},  # 4.2 (advisory)
          "regime_label":   "risk_on|risk_off|neutral|unknown",
          "as_of":          "YYYY-MM-DD" or None,
          "sector":         <sector or None>,
        }

    Keeping this a pure dict (a) lets ``rank_multibagger`` stay dependency-free
    and fully unit-testable with a hand-built overlay, and (b) makes the wiring
    a one-liner at each PIT rebalance date / in the live path. An all-unknown
    regime yields all-1.0 tilts + 0.0 boost + empty context, i.e. a no-op.
    """
    return {
        "pillar_tilts": regime_pillar_tilts(regime, strength=strength),
        "rerating_boost": rerating_catalyst_boost(regime, events, max_boost=max_boost),
        "entry_context": regime_entry_context(regime),
        "regime_label": regime.get("composite", {}).get("label"),
        "as_of": regime.get("as_of"),
        "sector": regime.get("sector"),
    }
