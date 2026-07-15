"""Fundamentals analyst.

Reads quality/value/financial-health/earnings-quality scores from the factor
engine and asks the LLM to summarize the strongest/weakest drivers per ticker.
"""

from __future__ import annotations

from ..data.insiders_edgar import get_insider_signal
from ..graph.state import AgentState, AnalystSignal
from ..llm.factory import get_llm, grade_rationale, parse_json
from . import _common
from .prompt_builders import (
    ANALYST_SYSTEM_PROMPT,
    generate_fundamentals_prompt,
)


def _heuristic_signal(ctx: dict) -> AnalystSignal:
    """Fallback signal if LLM is unavailable or returns nothing usable."""
    fs = ctx.get("factor_scores", {}) or {}
    quality = fs.get("quality")
    value = fs.get("value")
    health = fs.get("financial_health")
    eq = fs.get("earnings_quality")
    parts = []
    score = 0.0
    weight = 0.0
    for label, val, w in [
        ("quality", quality, 0.4),
        ("value", value, 0.3),
        ("health", health, 0.2),
        ("earnings_quality", eq, 0.1),
    ]:
        if val is not None:
            score += val * w
            weight += w
            parts.append(f"{label}={val:.2f}")
    avg = (score / weight) if weight else 0.5
    stance = "bullish" if avg > 0.6 else ("bearish" if avg < 0.4 else "neutral")
    return AnalystSignal(
        role="fundamentals",
        ticker=ctx["ticker"],
        score=round(avg * 2 - 1, 3),
        stance=stance,
        confidence=round(min(weight, 1.0), 2),
        rationale=(
            f"Heuristic from factor engine: composite={ctx.get('composite_score')!r}; "
            + ", ".join(parts)
        ),
        evidence=parts,
    )


def run(state: AgentState) -> AgentState:
    if not state.shortlist:
        return state
    llm = get_llm()
    items = _common.shortlist_context(state)

    # Enrich each shortlist context with a best-effort insider signal.
    # Only US tickers will return non-empty data; non-US tickers get a noop
    # rationale that the LLM is instructed to ignore. Failure is silent.
    for ctx in items:
        try:
            insider = get_insider_signal(ctx["ticker"])
            if insider.n_filings or insider.score != 0:
                ctx["insider_signal"] = insider.to_dict()
        except Exception:
            pass

    user = generate_fundamentals_prompt(items)
    out = llm.complete(user, system=ANALYST_SYSTEM_PROMPT)
    parsed = parse_json(out) or {}

    metrics_by_ticker = {ctx["ticker"]: ctx.get("key_metrics") or {} for ctx in items}
    signals_by_ticker: dict[str, AnalystSignal] = {}
    for sig in (parsed.get("signals") or []):
        try:
            ticker = sig.get("ticker")
            if not ticker:
                continue
            rationale = str(sig.get("rationale", ""))[:600]
            base_conf = float(sig.get("confidence", 0.5) or 0.5)
            grade = grade_rationale(rationale, metrics_by_ticker.get(ticker, {}))
            signals_by_ticker[ticker] = AnalystSignal(
                role="fundamentals",
                ticker=ticker,
                score=float(sig.get("score", 0.0) or 0.0),
                stance=sig.get("stance", "neutral"),
                confidence=round(base_conf * grade, 2),
                rationale=rationale,
                evidence=[str(e)[:200] for e in (sig.get("evidence") or [])][:6],
            )
        except Exception:
            continue

    for ctx in items:
        sig = signals_by_ticker.get(ctx["ticker"]) or _heuristic_signal(ctx)
        state.analyst_signals.append(sig)
    return state
