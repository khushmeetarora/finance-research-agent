"""Deterministic quant node: fetch snapshots, build the data-health card,
flag cross-currency picks, and run the factor engine."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json

from ..data.provider import DataProvider, enrich_snapshot_with_financials
from ..data.health import build_card, coverage_of, multibagger_coverage_of
from ..factors.engine import rank_universe
from ..factors.multibagger import rank_multibagger, DEFAULT_PILLAR_WEIGHTS
from ..factors.decay import factor_regime
from ..graph.state import AgentState


def run(state: AgentState) -> AgentState:
    if not state.candidate_tickers:
        return state

    scoring_mode = (state.profile.get("scoring_mode") or "classic").lower()
    manual_inputs = state.profile.get("manual_inputs") or {}

    provider = DataProvider()
    snapshots = []
    for ticker in state.candidate_tickers:
        snap = provider.get_snapshot(ticker)
        # Multibagger mode: enrich with annual statements (Tier-B signals).
        if scoring_mode == "multibagger":
            try:
                fin = provider.get_financials(ticker)
                enrich_snapshot_with_financials(
                    snap, fin, manual=manual_inputs.get(ticker)
                )
            except Exception:
                # Never let statement enrichment crash the pipeline; the
                # coverage shrink handles the resulting sparse data.
                pass
        # Cross-currency flag relative to the user's profile currency.
        profile_currency = (state.profile.get("currency") or "").upper()
        if (
            snap.currency
            and profile_currency
            and snap.currency.upper() != profile_currency
        ):
            snap.is_cross_currency = True
        snapshots.append(snap)

    # Apply risk constraints from profile (min market cap, max volatility).
    constraints = state.profile.get("risk_constraints", {}) or {}
    eligible = []
    for snap in snapshots:
        if not _passes_constraints(snap, constraints, state.profile):
            continue
        eligible.append(snap)

    # Fall back to all snapshots if filtering left nothing.
    pool = eligible or snapshots

    # Build the data-health card BEFORE ranking so it reflects the requested
    # universe, not the post-filter survivors.
    card = build_card(state.candidate_tickers, snapshots)
    state.data_health = card.to_dict()

    factor_cfg = state.profile.get("factor_config", {}) or {}
    if scoring_mode == "multibagger":
        pillar_weights = state.profile.get("pillar_weights") or DEFAULT_PILLAR_WEIGHTS
        # Opt-in macro/regime overlay (docs/FRA_V2_MACRO.md). OFF by default, so
        # the live multibagger default behaviour is byte-for-byte unchanged. When
        # enabled we compute a single market-level regime at the profile as_of
        # (no sector; degrades to a no-op overlay when series are unavailable).
        overlay = _macro_overlay(state, factor_cfg)
        reports = rank_multibagger(
            pool,
            pillar_weights,
            sector_relative=bool(factor_cfg.get("sector_relative", True)),
            min_peers=int(factor_cfg.get("min_sector_peers", 6)),
            coverage_fn=multibagger_coverage_of,
            coverage_weight_floor=float(factor_cfg.get("coverage_weight_floor", 0.4)),
            cyclical_mode=bool(factor_cfg.get("cyclical_mode", False)),
            overlay=overlay,
        )
    else:
        weights = state.profile.get("factor_weights", {}) or {}
        reports = rank_universe(
            pool,
            weights,
            coverage_fn=coverage_of,
            coverage_weight_floor=float(factor_cfg.get("coverage_weight_floor", 0.4)),
            per_factor_floor=factor_cfg.get("per_factor_floor"),
            profile_weights_for_fit=weights,
        )

    # Persist on state as plain dicts.
    state.snapshots = [_snap_to_dict(s) for s in pool]
    state.factor_reports = [r.to_dict() for r in reports]
    state.shortlist = [r.ticker for r in reports[: state.top_n]]

    # Factor regime / decay tracker.
    regime = factor_regime(pool, state.factor_reports)
    state.factor_regime = regime.to_dict()

    # Compute and persist a deterministic input hash for reproducibility.
    state.input_hash = _input_hash(state)
    return state


def _macro_overlay(state: AgentState, factor_cfg: dict):
    """Build a market-level macro/regime overlay for the live scorer, or None.

    Opt-in via ``factor_config.use_macro_overlay`` (default False -> returns
    None, a strict no-op). Never raises: any failure (offline / unavailable
    series) yields None or a no-op overlay so the live pipeline is unaffected.
    """
    if not factor_cfg.get("use_macro_overlay", False):
        return None
    try:
        from ..factors.regime import build_scorer_overlay, compute_regime

        as_of = getattr(state, "as_of", None) or None
        reg = compute_regime(as_of) if as_of else compute_regime(_dt.date.today())
        return build_scorer_overlay(reg)
    except Exception:
        return None


def _passes_constraints(snap, constraints: dict, profile: dict) -> bool:
    country = profile.get("country", "").upper()
    market_cap = snap.market_cap

    if country == "IN":
        floor_cr = constraints.get("min_market_cap_inr_crore")
        if floor_cr and market_cap is not None:
            # market_cap is in INR (yfinance reports native currency).
            crore = market_cap / 1e7
            if crore < floor_cr:
                return False
    else:
        floor_eur_m = constraints.get("min_market_cap_eur_million")
        if floor_eur_m and market_cap is not None:
            # yfinance returns native currency; we treat EUR/USD as comparable
            # for the floor (rough). For a stricter floor, FX-convert here.
            millions = market_cap / 1e6
            if millions < floor_eur_m:
                return False

    max_vol = constraints.get("max_volatility_annualized")
    if max_vol is not None and snap.volatility_annualized is not None:
        if snap.volatility_annualized > max_vol:
            return False

    return True


def _snap_to_dict(snap) -> dict:
    return {
        "ticker": snap.ticker,
        "name": snap.name,
        "currency": snap.currency,
        "sector": snap.sector,
        "industry": snap.industry,
        "country": snap.country,
        "market_cap": snap.market_cap,
        "price": snap.price,
        "pe_trailing": snap.pe_trailing,
        "pb": snap.pb,
        "ps": snap.ps,
        "ev_to_ebitda": snap.ev_to_ebitda,
        "earnings_yield": snap.earnings_yield,
        "fcf_yield": snap.fcf_yield,
        "dividend_yield": snap.dividend_yield,
        "roe": snap.roe,
        "roic": snap.roic,
        "gross_margin": snap.gross_margin,
        "operating_margin": snap.operating_margin,
        "profit_margin": snap.profit_margin,
        "debt_to_equity": snap.debt_to_equity,
        "net_debt_to_ebitda": snap.net_debt_to_ebitda,
        "current_ratio": snap.current_ratio,
        "cash_conversion": snap.cash_conversion,
        "revenue_growth": snap.revenue_growth,
        "earnings_growth": snap.earnings_growth,
        "momentum_12_1": snap.momentum_12_1,
        "momentum_6_1": snap.momentum_6_1,
        "volatility_annualized": snap.volatility_annualized,
        "beta": snap.beta,
        "data_agreement": snap.data_agreement,
        "data_sources": list(snap.data_sources),
        "fetch_status": snap.fetch_status,
        "is_cross_currency": snap.is_cross_currency,
        # Tier-B multibagger fields (None in classic mode).
        "roce": snap.roce,
        "roce_via_proxy": snap.roce_via_proxy,
        "gross_profitability": snap.gross_profitability,
        "accruals_ratio": snap.accruals_ratio,
        "interest_coverage": snap.interest_coverage,
        "fcf": snap.fcf,
        "fcf_posrate": snap.fcf_posrate,
        "ocf_to_np_multiyear": snap.ocf_to_np_multiyear,
        "beneish_m": snap.beneish_m,
        "altman_z": snap.altman_z,
        "peg": snap.peg,
        "earnings_cagr": snap.earnings_cagr,
        "capex_intensity": snap.capex_intensity,
        "dso": snap.dso,
        "dio": snap.dio,
        "dpo": snap.dpo,
        "ccc": snap.ccc,
        "is_financial": snap.is_financial,
        "financials_status": snap.financials_status,
        "promoter_pledge_pct": snap.promoter_pledge_pct,
        "auditor_red_flag": snap.auditor_red_flag,
    }


def _input_hash(state: AgentState) -> str:
    """Hash the normalized inputs so a re-run on identical data is verifiable."""
    payload = {
        "profile_id": state.profile_id,
        "target": state.target,
        "universe": state.universe_name,
        "domain": state.domain,
        "top_n": state.top_n,
        "as_of": state.as_of,
        "tickers": sorted(state.candidate_tickers),
        "snapshots": sorted(
            [
                # Hash-stable subset.
                {
                    "ticker": s["ticker"],
                    "price": s.get("price"),
                    "market_cap": s.get("market_cap"),
                    "pe": s.get("pe_trailing"),
                    "roe": s.get("roe"),
                    "mom_12_1": s.get("momentum_12_1"),
                }
                for s in state.snapshots
            ],
            key=lambda d: d["ticker"],
        ),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
