"""Research Manager.

Reconciles factor scores + analyst signals + debate transcripts into a final
ranked list of `FinalPick`s with thesis, risks, confidence, suggested holding
horizon, and per-pick tax notes.

Has two entry points:
- `run`: full pipeline (LLM available).
- `run_quant_only`: deterministic synthesis from the factor engine only.
"""

from __future__ import annotations

from ..factors.after_tax import compute_after_tax
from ..graph.state import AgentState, FinalPick
from ..llm.factory import get_llm, parse_json
from . import _common
from .prompt_builders import ANALYST_SYSTEM_PROMPT, generate_manager_prompt


def _aggregate_signal_score(state: AgentState, ticker: str) -> tuple[float, list[str]]:
    rationales: list[str] = []
    weighted_sum = 0.0
    weight = 0.0
    for s in state.analyst_signals:
        if s.ticker != ticker:
            continue
        weighted_sum += s.score * s.confidence
        weight += s.confidence
        if s.rationale:
            rationales.append(f"[{s.role}] {s.rationale}")
    avg = weighted_sum / weight if weight else 0.0
    return avg, rationales


def _suggested_horizon(profile: dict, snap: dict | None) -> str:
    country = profile.get("country", "").upper()
    if country == "IN" and profile.get("tax", {}).get("prefer_long_term_holding"):
        return ">12 months (LTCG eligibility)"
    if country == "DE":
        return "Multi-year (no holding-period tax distinction; favor compounding)"
    return "Multi-year"


def _per_pick_tax_notes(profile: dict, snap: dict | None) -> list[str]:
    country = profile.get("country", "").upper()
    notes: list[str] = []
    tax = profile.get("tax", {}) or {}
    if country == "IN":
        notes.append(
            f"Hold > {tax.get('short_term_threshold_days', 365)} days for LTCG "
            f"({tax.get('long_term_rate', 0)*100:.2f}%); "
            f"first Rs {tax.get('long_term_annual_exemption_inr', 0)/1e5:.2f} L LTCG/year is exempt."
        )
    elif country == "DE":
        notes.append(
            f"Capital gains taxed at {tax.get('long_term_rate', 0)*100:.3f}% "
            f"flat (Abgeltungssteuer); Sparerpauschbetrag "
            f"{tax.get('long_term_annual_exemption_eur', 0):.0f} EUR/yr applies."
        )
        if snap and snap.get("dividend_yield"):
            notes.append("Dividend-paying name: foreign withholding tax may apply (e.g. US 15%).")
    return notes


def _fill_quant_fields(pick: FinalPick, rep: dict, snap: dict | None, profile: dict) -> None:
    pick.profile_fit = rep.get("profile_fit")
    pick.factor_std_dev = rep.get("factor_std_dev")
    pick.coverage = rep.get("coverage")
    pick.floor_breaches = list(rep.get("floor_breaches") or [])
    pick.is_cross_currency = bool((snap or {}).get("is_cross_currency", False))
    at = compute_after_tax(rep.get("composite_score"), profile=profile)
    if at is not None:
        pick.expected_gross_return = at.expected_gross_return
        pick.expected_after_tax_return = at.expected_after_tax_return
        pick.tax_notes.extend(at.notes)
    if pick.is_cross_currency:
        pick.tax_notes.append(
            "Cross-currency exposure: FX move between the ticker's "
            "currency and your profile currency materially affects returns."
        )
    if pick.floor_breaches:
        pick.key_risks.append(
            "Per-factor floor breach(es): " + "; ".join(pick.floor_breaches)
        )
    # Surface multibagger red-flag vetoes / soft flags as key risks.
    for v in rep.get("vetoes") or []:
        pick.key_risks.append(f"VETO {v}")
    for sf in rep.get("soft_flags") or []:
        pick.key_risks.append(f"SOFT-FLAG {sf}")


def run_quant_only(state: AgentState) -> AgentState:
    """Synthesize picks straight from factor reports - no LLM required."""
    snap_by_t = {s["ticker"]: s for s in state.snapshots}
    picks: list[FinalPick] = []
    for rank, rep in enumerate(state.factor_reports[: state.top_n], start=1):
        snap = snap_by_t.get(rep["ticker"])
        composite = rep.get("composite_score")
        thesis_parts = []
        # Iterate over whatever factor/pillar keys the engine produced (classic
        # 5-factor names or the 7 multibagger pillar names).
        for fname, v in (rep.get("factor_scores") or {}).items():
            if v is not None:
                thesis_parts.append(f"{fname}={v:.2f}")
        label = (
            "Multibagger pillar ranking: "
            if rep.get("scoring_mode") == "multibagger"
            else "Factor composite ranking: "
        )
        thesis = label + ", ".join(thesis_parts)
        pick = FinalPick(
            ticker=rep["ticker"],
            name=rep.get("name"),
            composite_score=composite,
            rank=rank,
            thesis=thesis,
            key_risks=["No LLM analysis - factor-engine ranking only.",
                       "Single-source data (yfinance) may be stale or incomplete."],
            confidence=round(min(0.6, (composite or 0.5)), 2),
            suggested_horizon=_suggested_horizon(state.profile, snap),
            tax_notes=_per_pick_tax_notes(state.profile, snap),
        )
        _fill_quant_fields(pick, rep, snap, state.profile)
        picks.append(pick)
    state.picks = picks
    return state


def run(state: AgentState) -> AgentState:
    if not state.shortlist:
        return state
    items = _common.shortlist_context(state)
    debate_text = "\n".join(
        f"{t.side.upper()} r{t.round_idx}: {t.text}" for t in state.debate
    ) or "(no debate)"

    user = generate_manager_prompt(items, debate_text, state.top_n)
    out = get_llm().complete(user, system=ANALYST_SYSTEM_PROMPT)
    parsed = parse_json(out) or {}

    snap_by_t = {s["ticker"]: s for s in state.snapshots}
    rep_by_t = {r["ticker"]: r for r in state.factor_reports}
    picks: list[FinalPick] = []
    seen: set[str] = set()
    for sig in (parsed.get("picks") or []):
        ticker = sig.get("ticker")
        if not ticker or ticker not in state.shortlist or ticker in seen:
            continue
        seen.add(ticker)
        snap = snap_by_t.get(ticker)
        rep = rep_by_t.get(ticker, {})
        pick = FinalPick(
            ticker=ticker,
            name=(snap or {}).get("name") or rep.get("name"),
            composite_score=rep.get("composite_score"),
            rank=int(sig.get("rank", len(picks) + 1)),
            thesis=str(sig.get("thesis", ""))[:1200],
            key_risks=[str(r)[:300] for r in (sig.get("key_risks") or [])][:5],
            confidence=float(sig.get("confidence", 0.5) or 0.5),
            suggested_horizon=str(sig.get("suggested_horizon", ""))[:200]
            or _suggested_horizon(state.profile, snap),
            tax_notes=_per_pick_tax_notes(state.profile, snap),
        )
        _fill_quant_fields(pick, rep, snap, state.profile)
        picks.append(pick)

    # Backfill any shortlisted ticker the LLM omitted using the quant-only path.
    for rank, rep in enumerate(state.factor_reports[: state.top_n], start=1):
        if rep["ticker"] in seen:
            continue
        snap = snap_by_t.get(rep["ticker"])
        avg_signal, rationales = _aggregate_signal_score(state, rep["ticker"])
        thesis_bits = [
            f"composite={rep.get('composite_score'):.2f}" if rep.get("composite_score") is not None else "",
            f"avg analyst score={avg_signal:.2f}",
        ]
        pick = FinalPick(
            ticker=rep["ticker"],
            name=(snap or {}).get("name") or rep.get("name"),
            composite_score=rep.get("composite_score"),
            rank=rank,
            thesis="; ".join(p for p in thesis_bits if p),
            key_risks=["Manager backfilled this entry from quant + analyst signals."],
            confidence=0.4,
            suggested_horizon=_suggested_horizon(state.profile, snap),
            tax_notes=_per_pick_tax_notes(state.profile, snap),
        )
        _fill_quant_fields(pick, rep, snap, state.profile)
        picks.append(pick)

    # Re-sort by rank, then composite.
    picks.sort(
        key=lambda p: (
            p.rank,
            -(p.composite_score or 0.0),
        )
    )
    # Renumber ranks 1..N.
    for i, p in enumerate(picks, start=1):
        p.rank = i
    state.picks = picks
    return state
