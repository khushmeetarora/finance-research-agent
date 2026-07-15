"""Macro overlay analyst.

Lightweight: emits one *universe-wide* macro note based on profile country.
We deliberately keep this simple - macro signals have low information per
ticker, and we want the report to surface a single contextual paragraph
rather than per-ticker noise.
"""

from __future__ import annotations

from ..graph.state import AgentState, AnalystSignal
from ..llm.factory import get_llm, parse_json
from .prompt_builders import MACRO_SYSTEM_PROMPT, generate_macro_prompt


def run(state: AgentState) -> AgentState:
    profile = state.profile
    country = profile.get("country", "")
    currency = profile.get("currency", "")

    llm = get_llm()
    user = generate_macro_prompt(country, currency)
    out = llm.complete(user, system=MACRO_SYSTEM_PROMPT)
    parsed = parse_json(out) or {}
    signal = AnalystSignal(
        role="macro",
        ticker=None,
        score=float(parsed.get("score", 0.0) or 0.0),
        stance="neutral",
        confidence=0.4 if parsed else 0.1,
        rationale=str(parsed.get("rationale", ""))[:600]
        or f"Macro context for {country} ({currency}) - LLM unavailable; using neutral default.",
        evidence=[str(e)[:200] for e in (parsed.get("evidence") or [])][:4],
    )
    state.analyst_signals.append(signal)
    return state
