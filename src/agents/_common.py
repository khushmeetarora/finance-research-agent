"""Shared helpers for LLM-using agents."""

from __future__ import annotations

from typing import Any

from ..graph.state import AgentState
from .prompt_builders import ANALYST_SYSTEM_PROMPT


def shortlist_context(state: AgentState) -> list[dict[str, Any]]:
    """Return a compact dict per shortlisted ticker for prompt construction.

    Combines snapshot + factor report so the LLM has all numbers it needs.
    """
    snap_by_t = {s["ticker"]: s for s in state.snapshots}
    rep_by_t = {r["ticker"]: r for r in state.factor_reports}
    out = []
    for t in state.shortlist:
        snap = snap_by_t.get(t, {"ticker": t})
        rep = rep_by_t.get(t, {})
        out.append(
            {
                "ticker": t,
                "name": snap.get("name"),
                "sector": snap.get("sector"),
                "currency": snap.get("currency"),
                "market_cap": snap.get("market_cap"),
                "price": snap.get("price"),
                "key_metrics": {
                    "pe_trailing": snap.get("pe_trailing"),
                    "pb": snap.get("pb"),
                    "ev_to_ebitda": snap.get("ev_to_ebitda"),
                    "earnings_yield": snap.get("earnings_yield"),
                    "fcf_yield": snap.get("fcf_yield"),
                    "roe": snap.get("roe"),
                    "roic": snap.get("roic"),
                    "operating_margin": snap.get("operating_margin"),
                    "debt_to_equity": snap.get("debt_to_equity"),
                    "net_debt_to_ebitda": snap.get("net_debt_to_ebitda"),
                    "cash_conversion": snap.get("cash_conversion"),
                    "revenue_growth": snap.get("revenue_growth"),
                    "earnings_growth": snap.get("earnings_growth"),
                    "momentum_12_1": snap.get("momentum_12_1"),
                    "volatility_annualized": snap.get("volatility_annualized"),
                    "dividend_yield": snap.get("dividend_yield"),
                },
                "factor_scores": rep.get("factor_scores", {}),
                "composite_score": rep.get("composite_score"),
                # Multibagger extras (present only in that mode; None/empty
                # otherwise). Supplied numbers only - the LLM still interprets,
                # never invents, per the analyst guardrail.
                "pillar_scores": rep.get("pillar_scores", {}),
                "red_flag_vetoes": rep.get("vetoes", []),
                "soft_flags": rep.get("soft_flags", []),
                "consistency_stats": rep.get("consistency_stats", {}),
            }
        )
    return out


# Canonical analyst system prompt now lives in `prompt_builders`; kept here as
# an alias so existing `_common.SYSTEM_RULES` references stay valid.
SYSTEM_RULES = ANALYST_SYSTEM_PROMPT
