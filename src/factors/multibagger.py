"""Multibagger Quality Score - the 7-pillar scoring variant.

This module implements the strategy specified in ``docs/FRA_V2_STRATEGY.md`` as
an *additive* alternative to the classic 5-factor engine. It reuses the exact
percentile-rank + coverage-shrink machinery from ``scoring.py`` / ``engine.py``
but adds:

- **Direction-normalised signal extractors** (Tier-A + Tier-B) - each returns a
  raw value where "higher = better".
- **The consistency operator** (spec section 3.1) exposed as three separate
  signals (mean, stability = -cv, trend = slope) so the cross-sectional
  percentile machinery can rank them and a weighted average approximates
  ``mean_pct - 0.5*cv_pct + 0.25*slope_pct`` with positive weights on
  direction-normalised percentiles.
- **Sector-relative normalisation** (default ON) via
  ``scoring.sector_percentile_ranks``.
- **Weighted 7-pillar composite** with the spec weights.
- **A hard red-flag veto pass** (spec section 6) applied AFTER ranking.

Governance / Tier-C signals that lack data default to NEUTRAL (0.5) and are
never fabricated; they can be supplied via manual overrides on the snapshot.

LLMs never see this code path produce numbers directly - the engine produces
the scores, exactly like the classic path.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

from ..data.provider import CompanySnapshot
from . import scoring
from .engine import FactorReport, _cosine_sim, _normalize_weights, _stdev


# ---------------------------------------------------------------------------
# Consistency operator (spec section 3.1)
# ---------------------------------------------------------------------------


def series_mean(xs: list[float] | None) -> float | None:
    vals = [x for x in (xs or []) if x is not None]
    if len(vals) < 2:
        return None
    return sum(vals) / len(vals)


def series_min(xs: list[float] | None) -> float | None:
    vals = [x for x in (xs or []) if x is not None]
    if not vals:
        return None
    return min(vals)


def series_cv(xs: list[float] | None) -> float | None:
    """Coefficient of variation = stdev / |mean| (>=2 points)."""
    vals = [x for x in (xs or []) if x is not None]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if mean == 0:
        return None
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return (var**0.5) / abs(mean)


def series_stability(xs: list[float] | None) -> float | None:
    """Negated CV so that higher = more stable (better)."""
    cv = series_cv(xs)
    return None if cv is None else -cv


def series_slope(xs: list[float] | None) -> float | None:
    """OLS slope of x vs time index, normalised by |mean| (>=3 points)."""
    vals = [x for x in (xs or []) if x is not None]
    if len(vals) < 3:
        return None
    n = len(vals)
    xbar = (n - 1) / 2.0
    ybar = sum(vals) / n
    num = sum((i - xbar) * (v - ybar) for i, v in enumerate(vals))
    den = sum((i - xbar) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    if ybar == 0:
        return None
    return slope / abs(ybar)


# ---------------------------------------------------------------------------
# Signal extractors. Convention: each returns float|None where HIGHER = BETTER.
# Direction inversions (e.g. valuation, accruals, working-capital days) are
# applied here so the percentile machinery can treat everything uniformly.
# ---------------------------------------------------------------------------


def _neg(x: float | None) -> float | None:
    return None if x is None else -x


def _inv(x: float | None) -> float | None:
    if x is None or x <= 0:
        return None
    return 1.0 / x


def _level(series: list[float] | None, fallback: float | None) -> float | None:
    """Consistency level leg: the multi-year MEAN of the series ("consistency >
    peak", spec section 3.1 / caveat 7.1), falling back to the latest single-year
    value only when the series is too short (< 2 points) for a mean."""
    mean = series_mean(series)
    return mean if mean is not None else fallback


SIGNAL_EXTRACTORS: dict[str, Callable[[CompanySnapshot], float | None]] = {
    # --- Pillar 1: Profitability & Efficiency ---
    # Level leg ranks the multi-year MEAN (not the latest TTM value) so the
    # consistency operator rewards durable profitability over a single peak year.
    "roce_level": lambda s: _level(s.roce_series, s.roce),
    "roce_stability": lambda s: series_stability(s.roce_series),
    "roce_trend": lambda s: series_slope(s.roce_series),
    "roe_level": lambda s: _level(s.roe_series, s.roe),
    "gross_profitability": lambda s: s.gross_profitability,
    "asset_turnover": lambda s: s.asset_turnover,          # DuPont sanity
    # --- Pillar 2: Earnings Quality & Cash ---
    "cash_conversion": lambda s: s.cash_conversion,
    "neg_accruals": lambda s: _neg(s.accruals_ratio),      # Sloan: low better
    "fcf_posrate": lambda s: s.fcf_posrate,
    "fcf_yield": lambda s: s.fcf_yield,
    "ocf_to_np": lambda s: s.ocf_to_np_multiyear,
    "shareholder_yield": lambda s: s.shareholder_yield,
    # --- Pillar 3: Balance-Sheet Safety ---
    "altman_z": lambda s: s.altman_z,
    "neg_net_debt_ebitda": lambda s: _neg(s.net_debt_to_ebitda),
    "interest_coverage": lambda s: s.interest_coverage,
    "current_ratio": lambda s: s.current_ratio,
    # --- Pillar 4: Growth & Valuation / PEG ---
    "earnings_growth": lambda s: s.earnings_cagr if s.earnings_cagr is not None else s.earnings_growth,
    "neg_peg": lambda s: _neg(s.peg),                      # PEG: lower better
    "earnings_yield": lambda s: s.earnings_yield,          # Greenblatt leg / sector-rel PE
    # --- Pillar 5: Moat & Pricing Power ---
    "gm_mean": lambda s: series_mean(s.gross_margin_series),
    "gm_stability": lambda s: series_stability(s.gross_margin_series),
    "neg_capex_intensity": lambda s: _neg(s.capex_intensity),
    "margin_capture": lambda s: _margin_capture(s),        # OPM keeping pace with GM
    # --- Pillar 6: Promoter / Governance (Tier C; neutral when absent) ---
    "neg_pledge": lambda s: _neg(s.promoter_pledge_pct),
    "promoter_trend": lambda s: s.promoter_holding_trend,
    "insider_holding": lambda s: _num_raw(s, "heldPercentInsiders"),
    # --- Pillar 7: Re-rating Catalysts ---
    "momentum_12_1": lambda s: s.momentum_12_1,
    "momentum_6_1": lambda s: s.momentum_6_1,
    "growth_catalyst": lambda s: s.earnings_cagr if s.earnings_cagr is not None else s.earnings_growth,
}


def _num_raw(s: CompanySnapshot, key: str) -> float | None:
    v = (s.raw or {}).get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _margin_capture(s: CompanySnapshot) -> float | None:
    """slope(OPM) - slope(GM): >=0 means operating margin keeps pace with gross
    (no cost/opex leak). Negative = divergence (bearish). Spec M2."""
    gm_slope = series_slope(s.gross_margin_series)
    opm_slope = series_slope(s.operating_margin_series)
    if gm_slope is None or opm_slope is None:
        return None
    return opm_slope - gm_slope


# ---------------------------------------------------------------------------
# Pillar definitions: pillar -> {signal_name: member weight}
# Member weights encode the consistency operator (mean 1.0, stability 0.5,
# trend 0.25) and the relative emphasis within each pillar.
# ---------------------------------------------------------------------------

PILLARS: dict[str, dict[str, float]] = {
    "profitability": {
        "roce_level": 1.0,
        "roce_stability": 0.5,
        "roce_trend": 0.25,
        "roe_level": 0.5,
        "gross_profitability": 1.0,
        "asset_turnover": 0.25,
    },
    "earnings_quality": {
        "cash_conversion": 1.0,
        "neg_accruals": 1.0,
        "fcf_posrate": 1.0,
        "fcf_yield": 0.5,
        "ocf_to_np": 1.0,
        "shareholder_yield": 0.25,
    },
    "balance_sheet_safety": {
        "altman_z": 1.0,
        "neg_net_debt_ebitda": 0.5,
        "interest_coverage": 0.5,
        "current_ratio": 0.5,
    },
    "growth_valuation": {
        "earnings_growth": 1.0,
        "neg_peg": 1.0,
        "earnings_yield": 0.5,
    },
    "moat_pricing_power": {
        "gm_mean": 1.0,
        "gm_stability": 0.5,
        "neg_capex_intensity": 0.5,
        "margin_capture": 0.5,
    },
    # Tier-C: with no manual pledge / holding-trend data this pillar has no
    # available signals and defaults to NEUTRAL 0.5 (spec section 2.6/4) - a
    # name is never penalised for missing free-source governance data. The
    # `heldPercentInsiders` yfinance field is a known-unreliable proxy and is
    # deliberately NOT scored by default; RF6/RF7 vetoes stay live as optional
    # manual inputs.
    "promoter_governance": {
        "neg_pledge": 1.0,
        "promoter_trend": 0.5,
    },
    "rerating_catalysts": {
        "momentum_12_1": 1.0,
        "momentum_6_1": 0.5,
        "growth_catalyst": 0.5,
    },
}

# Default pillar weights (spec section 4). Overridable via the profile.
DEFAULT_PILLAR_WEIGHTS: dict[str, float] = {
    "profitability": 0.22,
    "earnings_quality": 0.18,
    "balance_sheet_safety": 0.15,
    "growth_valuation": 0.15,
    "moat_pricing_power": 0.12,
    "promoter_governance": 0.10,
    "rerating_catalysts": 0.08,
}

# Sectors treated as cyclical (PEG suppressed, consistency up-weighted).
CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Materials", "Consumer Cyclical"}

# The governance pillar defaults to this neutral score when Tier-C data is
# absent, so a name is neither rewarded nor unfairly penalised.
GOVERNANCE_NEUTRAL = 0.5


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def rank_multibagger(
    snapshots: Iterable[CompanySnapshot],
    pillar_weights: dict[str, float] | None = None,
    *,
    sector_relative: bool = True,
    min_peers: int = 6,
    coverage_fn: Callable[[CompanySnapshot], float] | None = None,
    coverage_weight_floor: float = 0.4,
    cyclical_mode: bool = False,
    apply_vetoes: bool = True,
    overlay: dict | None = None,
    overlay_by_ticker: dict[str, dict] | None = None,
) -> list[FactorReport]:
    """Rank a universe with the 7-pillar Multibagger Quality Score.

    Returns FactorReports (sorted desc by composite) whose ``factor_scores``
    hold the pillar scores, plus ``pillar_scores`` / ``consistency_stats`` /
    ``vetoes`` / ``soft_flags`` populated. Vetoed names are floored to a
    ``None`` composite (dropped to the bottom) with reasons attached.

    **Optional, opt-in macro/regime overlay** (``docs/FRA_V2_MACRO.md`` 4). Pass
    a plain-dict ``overlay`` (from ``regime.build_scorer_overlay``) to apply, per
    name, at the compositing stage ONLY:

      * ``pillar_tilts``   - multiplicative tilt on the pillar WEIGHTS before the
        composite (``_normalize_weights`` re-sums to 1, so it is a pure tilt).
      * ``rerating_boost`` - a small bounded additive boost to the
        ``rerating_catalysts`` pillar SCORE (clamped to [0, 1]).
      * ``entry_context``  - advisory annotation stored on ``report.regime_context``
        (CONTEXT ONLY - it NEVER adds/removes a veto or changes the veto pass).

    ``overlay_by_ticker`` supplies a per-name overlay (used by the PIT backtest,
    where each name's regime is computed at its own as-of date); a name absent
    from the map falls back to ``overlay``. When BOTH are ``None`` the function
    is byte-for-byte identical to the pre-overlay behaviour (a strict no-op), so
    the classic/live defaults and all existing tests are unchanged.
    """
    snaps = list(snapshots)
    if not snaps:
        return []

    raw_weights = pillar_weights or DEFAULT_PILLAR_WEIGHTS
    default_weights = _normalize_weights(raw_weights)
    sectors = [s.sector for s in snaps]

    def _overlay_for(ticker: str) -> dict | None:
        if overlay_by_ticker is not None:
            return overlay_by_ticker.get(ticker, overlay)
        return overlay

    def _weights_for(ov: dict | None) -> dict[str, float]:
        tilts = (ov or {}).get("pillar_tilts") if ov else None
        if not tilts:
            return default_weights
        return _normalize_weights(
            {p: raw_weights.get(p, 0.0) * float(tilts.get(p, 1.0)) for p in raw_weights}
        )

    # 1. Extract raw signal values across the universe.
    raw: dict[str, list[float | None]] = {}
    for name, ext in SIGNAL_EXTRACTORS.items():
        col: list[float | None] = []
        for s in snaps:
            try:
                col.append(ext(s))
            except Exception:
                col.append(None)
        raw[name] = col

    # PEG suppression for cyclicals (spec 3.7 / section 4).
    for i, s in enumerate(snaps):
        if (s.sector in CYCLICAL_SECTORS) and "neg_peg" in raw:
            raw["neg_peg"][i] = None

    # 2. Percentile-rank each signal (sector-relative by default).
    pct: dict[str, list[float | None]] = {}
    for name, col in raw.items():
        if sector_relative:
            pct[name] = scoring.sector_percentile_ranks(col, sectors, min_peers)
        else:
            pct[name] = scoring.percentile_ranks(col)

    # 3. Per-ticker pillar scores + composite.
    reports: list[FactorReport] = []
    for i, snap in enumerate(snaps):
        report = FactorReport(
            ticker=snap.ticker, name=snap.name, sector=snap.sector,
            scoring_mode="multibagger",
        )
        ov = _overlay_for(snap.ticker)
        weights = _weights_for(ov)
        pillar_scores: dict[str, float | None] = {}
        present = 0
        total = 0
        for pillar, members in PILLARS.items():
            eff_members = dict(members)
            if cyclical_mode and pillar == "profitability":
                # Up-weight consistency for cyclicals.
                eff_members["roce_stability"] = eff_members.get("roce_stability", 0.5) * 2
                eff_members["roce_trend"] = eff_members.get("roce_trend", 0.25) * 2
            num = 0.0
            den = 0.0
            for sig, w in eff_members.items():
                total += 1
                p = pct.get(sig, [None] * len(snaps))[i]
                report.metric_values[f"{pillar}.{sig}"] = raw.get(sig, [None])[i]
                report.metric_percentiles[f"{pillar}.{sig}"] = p
                if p is not None:
                    present += 1
                    num += p * w
                    den += w
            if den > 0:
                pillar_scores[pillar] = num / den
            elif pillar == "promoter_governance":
                pillar_scores[pillar] = GOVERNANCE_NEUTRAL  # Tier-C neutral default
            else:
                pillar_scores[pillar] = None

        # Overlay 4.3: bounded additive boost to the re-rating pillar SCORE
        # (easing rates + sector tailwind + policy-catalyst news). Applied only
        # when the pillar is present; the score stays clamped to [0, 1] so the
        # downstream composite / coverage-shrink math is unchanged in form.
        boost = float((ov or {}).get("rerating_boost", 0.0) or 0.0) if ov else 0.0
        if boost and pillar_scores.get("rerating_catalysts") is not None:
            pillar_scores["rerating_catalysts"] = min(
                1.0, pillar_scores["rerating_catalysts"] + boost
            )

        report.pillar_scores = pillar_scores
        report.factor_scores = dict(pillar_scores)  # so downstream renders them

        # Overlay 4.2: advisory regime CONTEXT (never a veto/kill; the veto pass
        # below is untouched). Stored for the report/scorecard only.
        if ov and ov.get("entry_context"):
            ctx = dict(ov["entry_context"])
            if ov.get("regime_label"):
                ctx["regime_label"] = ov["regime_label"]
            if boost:
                ctx["rerating_boost"] = round(boost, 4)
            report.regime_context = ctx

        # Weighted composite over available pillars.
        wsum = 0.0
        wused = 0.0
        for pillar, score in pillar_scores.items():
            if score is not None:
                w = weights.get(pillar, 0.0)
                wsum += score * w
                wused += w
        raw_comp = wsum / wused if wused > 0 else None
        report.raw_composite = raw_comp

        # Coverage + coverage-shrink (identical math to engine.rank_universe).
        if coverage_fn is not None:
            report.coverage = float(coverage_fn(snap))
        elif total:
            report.coverage = present / total
        report.coverage_weight = coverage_weight_floor + (
            1.0 - coverage_weight_floor
        ) * max(0.0, min(1.0, report.coverage))
        if raw_comp is not None:
            shrink = 1.0 - report.coverage_weight
            report.composite_score = raw_comp * report.coverage_weight + 0.5 * shrink
        else:
            report.composite_score = None

        # Consistency stats surfaced for the scorecard.
        report.consistency_stats = {
            "roce_mean": series_mean(snap.roce_series),
            "roce_min": series_min(snap.roce_series),
            "roce_cv": series_cv(snap.roce_series),
            "fcf_posrate": snap.fcf_posrate,
            "beneish_m": snap.beneish_m,
            "altman_z": snap.altman_z,
        }
        report.factor_std_dev = _stdev(list(pillar_scores.values()))
        report.profile_fit = _cosine_sim(pillar_scores, weights)
        reports.append(report)

    # 4. Hard red-flag veto pass (spec section 6).
    if apply_vetoes:
        for report, snap in zip(reports, snaps):
            run_veto_pass(report, snap)

    # 5. Sort: non-vetoed by composite desc, vetoed (None composite) last.
    reports.sort(
        key=lambda r: (r.composite_score is None, -(r.composite_score or 0.0))
    )
    return reports


# ---------------------------------------------------------------------------
# Hard red-flag veto pass (spec section 6)
# ---------------------------------------------------------------------------

BENEISH_THRESHOLD = -1.78
ALTMAN_DISTRESS = 1.1
# RF8 re-rating leg: PE multiple expansion factor at/above which we call the
# re-rating "far beyond EPS" (i.e. the multiple roughly grew >= 1.5x).
RF8_PE_EXPANSION = 0.5

# ---------------------------------------------------------------------------
# Early-stage / reinvestment growth exception (spec section 6, RF1 note:
# "FCF<0 ... AND NOT a flagged early-stage growth exception"). We extend the
# spec's RF1 carve-out to also cover RF2's cash-conversion leg, because the same
# genuinely-investing-to-grow archetype (heavy capex or a working-capital build
# ahead of a growth run) simultaneously depresses free cash flow AND the
# CFO/NP ratio while the P&L is soundly profitable. See docs/FRA_V2_BACKTEST_
# RESULTS.md Phase 5 for the tuning against the labelled dataset (HAL, BDL,
# Mazagon Dock, Trent, Fine Organic were the wrongly-vetoed winners).
# ---------------------------------------------------------------------------
# A "quality" grower bar: the mean multi-year ROCE **or** ROE must clear this.
EARLY_STAGE_MIN_RETURN = 0.15
# Altman Z"-EM safe-zone floor (non-financials): no distressed name qualifies.
EARLY_STAGE_SAFE_ALTMAN = 2.6
# Need a real multi-year window before granting the carve-out (no 1-2y flukes).
EARLY_STAGE_MIN_PERIODS = 3
# Improvement leg: latest ROCE must have expanded to >= this multiple of the
# earliest (off a positive base) with operating margin also rising.
EARLY_STAGE_ROCE_EXPANSION = 1.5
# The majority of years must be genuinely profitable (NI > 0).
EARLY_STAGE_MIN_NI_POSRATE = 0.6


def is_early_stage_growth_exception(snap: CompanySnapshot) -> bool:
    """Return True when a name qualifies for the spec's RF1 (extended to RF2)
    "early-stage growth exception": a demonstrably PROFITABLE and financially
    SAFE business whose negative free cash flow / low cash-conversion is driven
    by growth **reinvestment** (capex) or a **working-capital build** rather than
    operational losses or a genuine cash burn.

    Deliberately CONSERVATIVE and computable from the free (screener/yfinance)
    statement bundle. Requires ALL of:

      1. **A real multi-year window** - >= 3 income periods, so the carve-out is
         never granted on a 1-2 year fluke.
      2. **Genuine accounting profitability (NOT operational losses)** -
         cumulative net profit positive, the majority of years with NI > 0, and
         both the latest and mean operating margin positive. This is what
         separates a reinvesting compounder from a loss-making cash-burner
         (KFA/Jet/Hathway all fail here on negative margins / cumulative losses).
      3. **Balance-sheet safety** - Altman Z"-EM in the safe zone (>= 2.6) for
         non-financials, so no distressed name is ever spared. RF4 (distress) and
         RF5 (insolvency) remain independently active regardless.
      4. **Quality returns OR a genuine scale-up** - mean ROCE >= 15% OR mean ROE
         >= 15% (a high-return franchise whose cash is merely tied up in growth),
         OR ROCE expanded to >= 1.5x its earliest (positive) level with operating
         margin also rising (a real operating-leverage scale-up, e.g. Trent's
         Zudio ramp) - the leg that catches low-absolute-ROCE names that are
         clearly on an improving trajectory while still rejecting flat, low-return
         names (Gitanjali, ABB).

    The exception ONLY relaxes RF1/RF2 (the cash-flow vetoes). RF3 (Beneish
    manipulation), RF4 (Altman distress), RF5 (insolvency), RF6/RF7 (governance)
    and RF8/RF9 are never touched, so a manipulator / distressed / pledged /
    over-valued name is still caught even if it looks like a grower here.
    """
    # (1) real multi-year window
    ni = [x for x in (snap.net_income_series or []) if x is not None]
    if len(ni) < EARLY_STAGE_MIN_PERIODS:
        return False

    # (2) genuine accounting profitability - not operational losses
    if snap.cum_np_nonpositive is True:
        return False
    if ni[-1] <= 0:
        return False
    if sum(1 for x in ni if x > 0) / len(ni) < EARLY_STAGE_MIN_NI_POSRATE:
        return False
    opm = [x for x in (snap.operating_margin_series or []) if x is not None]
    opm_mean = series_mean(opm)
    if not opm or opm[-1] <= 0 or opm_mean is None or opm_mean <= 0:
        return False

    # (3) balance-sheet safety (non-financials carry a computable Altman)
    if not snap.is_financial:
        if snap.altman_z is None or snap.altman_z < EARLY_STAGE_SAFE_ALTMAN:
            return False

    # (4) quality returns OR a genuine improvement trajectory
    roce_mean = series_mean(snap.roce_series)
    roe_mean = series_mean(snap.roe_series)
    high_return = (
        (roce_mean is not None and roce_mean >= EARLY_STAGE_MIN_RETURN)
        or (roe_mean is not None and roe_mean >= EARLY_STAGE_MIN_RETURN)
    )
    improving = False
    rs = [x for x in (snap.roce_series or []) if x is not None]
    if len(rs) >= 2 and rs[0] > 0 and rs[-1] > 0 and rs[-1] >= EARLY_STAGE_ROCE_EXPANSION * rs[0]:
        improving = len(opm) >= 2 and opm[-1] > opm[0]
    return bool(high_return or improving)


def _pe_rerated_beyond_eps(snap: CompanySnapshot) -> bool:
    """Approximate RF8 leg (b): has PE re-rated far beyond EPS over the window?

    A genuine multi-year PE path is unavailable from free data, so we proxy it
    from the multi-year PRICE CAGR vs the EARNINGS CAGR. Since PE = Price / EPS,
    the multiple's expansion factor over the window is
    ``(1+price_cagr)/(1+eps_cagr) - 1``. We call it a perception-only re-rating
    when the multiple expanded by >= RF8_PE_EXPANSION while earnings barely grew.
    Returns False (not None) when the proxy cannot be computed so callers can
    treat it as "leg not established".
    """
    pc = snap.price_cagr
    g5 = snap.earnings_cagr
    if pc is None or g5 is None or (1.0 + g5) <= 0:
        return False
    pe_expansion = (1.0 + pc) / (1.0 + g5) - 1.0
    return pe_expansion >= RF8_PE_EXPANSION and g5 <= 0.10


def run_veto_pass(report: FactorReport, snap: CompanySnapshot) -> FactorReport:
    """Apply the spec's hard red-flag vetoes to a single report in place.

    Hard vetoes floor the composite to None (drop to bottom) with a reason.
    Soft vetoes (RF9 working-capital trap) apply a heavy multiplicative penalty
    instead. Missing data never triggers a veto (graceful degradation).
    """
    vetoes: list[str] = []
    soft: list[str] = []

    # Spec section-6 RF1 carve-out (extended to RF2's cash-conversion leg): a
    # genuinely investing-to-grow, profitable, safe business is spared the
    # cash-flow vetoes. Computed once; the distress / manipulation / governance
    # / valuation vetoes below are NEVER relaxed by it.
    early_stage = is_early_stage_growth_exception(snap)
    report.early_stage_growth_exception = early_stage

    # RF1 Structural cash burn: FCF < 0 in >= 3 of the LAST 5 years (spec section
    # 6), UNLESS the name is a flagged early-stage growth exception. We count
    # negatives within the trailing 5-year window rather than over the whole
    # history so a long-ago cluster of bad years does not veto a name that has
    # since turned cash-generative.
    if snap.fcf_series and not early_stage:
        last5 = snap.fcf_series[-5:]
        neg_last5 = sum(1 for f in last5 if f < 0)
        if neg_last5 >= 3:
            vetoes.append(
                f"RF1 structural cash burn: FCF<0 in {neg_last5} of last "
                f"{len(last5)} yrs"
            )

    # RF2 Earnings not cash-backed (spec section 6 / E6). Fires on ANY of:
    #   (a) cum(CFO)/cum(NP) < 0.5 over the window, OR
    #   (b) CFO/NI < 0.5 for 3 consecutive years, OR
    #   (c) cumulative net profit <= 0 over the window (persistent losses -> the
    #       cum ratio is left None but the earnings are plainly not cash-backed).
    # Same early-stage carve-out as RF1: a demonstrably profitable+safe grower
    # whose CFO is temporarily depressed by reinvestment / working-capital build
    # is not "earnings not cash-backed" (its earnings ARE real; the cash is tied
    # up in growth). Clause (c) can never be spared because the exception itself
    # requires cumulative net profit to be POSITIVE.
    if early_stage:
        pass
    elif snap.ocf_to_np_multiyear is not None and snap.ocf_to_np_multiyear < 0.5:
        vetoes.append(
            f"RF2 earnings not cash-backed: cumCFO/cumNP={snap.ocf_to_np_multiyear:.2f} < 0.5"
        )
    elif (
        snap.cfo_np_below_half_streak is not None
        and snap.cfo_np_below_half_streak >= 3
    ):
        vetoes.append(
            f"RF2 earnings not cash-backed: CFO/NI < 0.5 for "
            f"{snap.cfo_np_below_half_streak} consecutive yrs"
        )
    elif snap.cum_np_nonpositive is True:
        vetoes.append(
            "RF2 earnings not cash-backed: cumulative net profit <= 0 over window"
        )

    # RF3 Manipulation flag: Beneish M > -1.78 (when computable).
    if snap.beneish_m is not None and snap.beneish_m > BENEISH_THRESHOLD:
        vetoes.append(f"RF3 Beneish M={snap.beneish_m:.2f} > {BENEISH_THRESHOLD}")

    # RF4 Distress: Altman Z" < 1.1 (non-financials only).
    if (
        not snap.is_financial
        and snap.altman_z is not None
        and snap.altman_z < ALTMAN_DISTRESS
    ):
        vetoes.append(f"RF4 Altman Z\"={snap.altman_z:.2f} < {ALTMAN_DISTRESS}")

    # RF5 Insolvency-risk debt: interest coverage < 1.5 AND rising net-debt/EBITDA
    # over the window (spec section 6). Uses the net-debt/EBITDA trend computed in
    # enrichment rather than the coarse gross-debt-rising proxy, so cash build and
    # EBITDA growth are properly netted out.
    if (
        snap.interest_coverage is not None
        and snap.interest_coverage < 1.5
        and snap.net_debt_ebitda_rising is True
    ):
        vetoes.append(
            f"RF5 insolvency risk: interest coverage={snap.interest_coverage:.2f} "
            "< 1.5 and net-debt/EBITDA rising"
        )

    # RF6 High promoter pledge (Tier-C manual): > 50%.
    if snap.promoter_pledge_pct is not None and snap.promoter_pledge_pct > 50.0:
        vetoes.append(f"RF6 promoter pledge {snap.promoter_pledge_pct:.0f}% > 50%")

    # RF7 Auditor red flag (Tier-C manual / news proxy).
    if snap.auditor_red_flag is True:
        vetoes.append("RF7 auditor red flag (manual/news)")

    # RF8 Perception-only re-rating (spec section 6 / V6 / R5): the name is priced
    # on perception, not earnings. Two legs:
    #   (a) binding leg  -> PE > 40 with 5y earnings growth <= 0, AND
    #   (b) re-rating leg -> PE re-rated far beyond EPS over 3-5y.
    # A clean multi-year PE history is not available from free (yfinance) data, so
    # leg (b) is approximated from the multi-year PRICE CAGR vs the EARNINGS CAGR:
    # PE multiple expansion factor ~= (1+price_cagr)/(1+eps_cagr); "far beyond" is
    # PE roughly doubling (>= ~50% multiple expansion). When price_cagr is
    # unavailable leg (b) is unknown and we DON'T block on it, so the binding leg
    # (a) still governs (preserving the prior behaviour rather than silently
    # neutering the veto). NOTE (spec deviation): the spec joins the two legs with
    # AND; because leg (b) is only an approximation and often uncomputable on free
    # data, we keep leg (a) sufficient on its own and let a clearly-computed leg
    # (b) reinforce/extend it, rather than requiring both.
    pe = snap.pe_trailing
    g5 = snap.earnings_cagr
    binding = pe is not None and pe > 40 and g5 is not None and g5 <= 0
    rerated = _pe_rerated_beyond_eps(snap)
    if binding:
        extra = " and PE re-rated >> EPS" if rerated else ""
        vetoes.append(
            f"RF8 perception-only re-rating: PE={pe:.0f} > 40 with "
            f"5y earnings CAGR={g5*100:.0f}% <= 0{extra}"
        )
    elif rerated and pe is not None and pe > 40:
        vetoes.append(
            f"RF8 perception-only re-rating: PE={pe:.0f} > 40 and PE re-rated far "
            "beyond EPS over the window"
        )

    # RF9 Working-capital trap (SOFT): DSO up & DIO up & DPO down & CFO/NP falling.
    if (
        snap.dso_delta is not None and snap.dso_delta > 0
        and snap.dio_delta is not None and snap.dio_delta > 0
        and snap.dpo_delta is not None and snap.dpo_delta < 0
        and snap.cfo_np_falling is True
    ):
        soft.append(
            "RF9 working-capital trap: DSO/DIO rising, DPO falling, CFO/NP falling"
        )

    report.vetoes = vetoes
    report.soft_flags = soft

    if vetoes:
        # Hard veto: floor composite so the name drops to the bottom.
        report.composite_score = None
    elif soft and report.composite_score is not None:
        # Soft veto: heavy penalty toward the universe median.
        report.composite_score = 0.5 + (report.composite_score - 0.5) * 0.4

    return report
