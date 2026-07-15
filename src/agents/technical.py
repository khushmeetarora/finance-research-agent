"""Technical analyst.

Uses momentum_12_1, momentum_6_1 and annualized volatility from the snapshot
to produce a stance per ticker. The LLM is asked to interpret the numbers
and add commentary; if absent we fall back to deterministic thresholds.
"""

from __future__ import annotations

from ..graph.state import AgentState, AnalystSignal
from ..llm.factory import get_llm, parse_json
from . import _common
from .prompt_builders import ANALYST_SYSTEM_PROMPT, generate_technical_prompt


def _heuristic_signal(ctx: dict) -> AnalystSignal:
    km = ctx.get("key_metrics", {}) or {}
    mom = km.get("momentum_12_1")
    vol = km.get("volatility_annualized")
    score = 0.0
    parts = []
    if mom is not None:
        score = max(-1.0, min(1.0, mom))  # cap at +/-100%
        parts.append(f"12-1m momentum={mom:.2%}")
    if vol is not None:
        parts.append(f"vol_ann={vol:.2%}")
        # heavy volatility dampens conviction
        score *= max(0.2, 1.0 - min(vol, 1.0))
    stance = "bullish" if score > 0.05 else ("bearish" if score < -0.05 else "neutral")
    return AnalystSignal(
        role="technical",
        ticker=ctx["ticker"],
        score=round(score, 3),
        stance=stance,
        confidence=0.5 if mom is not None else 0.2,
        rationale="Heuristic from price history: " + ", ".join(parts),
        evidence=parts,
    )


def run(state: AgentState) -> AgentState:
    if not state.shortlist:
        return state
    llm = get_llm()
    items = _common.shortlist_context(state)
    metrics = [
        {
            "ticker": c["ticker"],
            "name": c["name"],
            "sector": c["sector"],
            "metrics": {
                "momentum_12_1": c["key_metrics"]["momentum_12_1"],
                "volatility_annualized": c["key_metrics"]["volatility_annualized"],
            },
        }
        for c in items
    ]
    user = generate_technical_prompt(metrics)
    out = llm.complete(user, system=ANALYST_SYSTEM_PROMPT)
    parsed = parse_json(out) or {}
    by_ticker = {}
    for sig in parsed.get("signals") or []:
        try:
            t = sig.get("ticker")
            if not t:
                continue
            by_ticker[t] = AnalystSignal(
                role="technical",
                ticker=t,
                score=float(sig.get("score", 0.0) or 0.0),
                stance=sig.get("stance", "neutral"),
                confidence=float(sig.get("confidence", 0.5) or 0.5),
                rationale=str(sig.get("rationale", ""))[:600],
                evidence=[str(e)[:200] for e in (sig.get("evidence") or [])][:6],
            )
        except Exception:
            continue
    for ctx in items:
        state.analyst_signals.append(by_ticker.get(ctx["ticker"]) or _heuristic_signal(ctx))
    return state
