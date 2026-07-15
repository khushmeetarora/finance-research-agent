"""Bull vs Bear researcher debate.

Each round, both researchers see all analyst signals + factor scores for the
shortlist and produce a short bull/bear case. State accumulates DebateTurn
entries that the Research Manager later reconciles.
"""

from __future__ import annotations

from ..graph.state import AgentState, DebateTurn
from ..llm.factory import get_llm
from . import _common
from .prompt_builders import RESEARCHER_SYSTEM_PROMPT, generate_researcher_prompt


def _signals_summary(state: AgentState) -> list[dict]:
    by_ticker: dict[str, list[dict]] = {}
    for s in state.analyst_signals:
        if not s.ticker:
            continue
        by_ticker.setdefault(s.ticker, []).append(
            {"role": s.role, "stance": s.stance, "score": s.score, "confidence": s.confidence}
        )
    out = []
    for ctx in _common.shortlist_context(state):
        out.append(
            {
                "ticker": ctx["ticker"],
                "name": ctx["name"],
                "composite_score": ctx["composite_score"],
                "factor_scores": ctx["factor_scores"],
                "signals": by_ticker.get(ctx["ticker"], []),
            }
        )
    return out


def _ask(side: str, payload: list[dict], round_idx: int, history: list[DebateTurn]) -> str:
    llm = get_llm()
    history_text = "\n".join(
        f"{t.side.upper()} (r{t.round_idx}): {t.text}" for t in history
    ) or "(no prior turns)"
    user = generate_researcher_prompt(side, payload, round_idx, history_text)
    return llm.complete(user, system=RESEARCHER_SYSTEM_PROMPT)


def run(state: AgentState, round_idx: int = 0) -> AgentState:
    if not state.shortlist:
        return state
    payload = _signals_summary(state)
    bull_text = _ask("bull", payload, round_idx, state.debate)
    state.debate.append(DebateTurn(side="bull", round_idx=round_idx, text=bull_text or "(empty)"))
    bear_text = _ask("bear", payload, round_idx, state.debate)
    state.debate.append(DebateTurn(side="bear", round_idx=round_idx, text=bear_text or "(empty)"))
    return state
