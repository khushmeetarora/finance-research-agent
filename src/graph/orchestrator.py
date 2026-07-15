"""LangGraph orchestrator wiring all nodes together.

Falls back to a plain-Python sequential runner if langgraph is unavailable
(useful for offline/no-LLM mode). The two paths take the same AgentState in
and out.
"""

from __future__ import annotations

from typing import Callable

from ..agents import (
    fundamentals,
    macro,
    manager,
    news_sentiment,
    quant,
    researchers,
    risk_profile,
    technical,
    universe,
)
from ..report.generator import generate_report
from ..memory.store import persist_run
from .state import AgentState
from .conditional_logic import should_run_llm


# --- Plain sequential runner (no langgraph dependency required) -----------


def _seq_run(state: AgentState) -> AgentState:
    state = universe.run(state)
    state = quant.run(state)  # data fetch + factor engine

    if should_run_llm(state) == "run_llm":
        state = fundamentals.run(state)
        state = technical.run(state)
        state = news_sentiment.run(state)
        state = macro.run(state)
        for round_idx in range(state.max_debate_rounds):
            state = researchers.run(state, round_idx=round_idx)
        state = risk_profile.run(state)
        state = manager.run(state)
    else:
        # Even without LLMs we still synthesize picks from the factor engine
        # so the report has something to render.
        state = manager.run_quant_only(state)
        state = risk_profile.run(state)

    state = generate_report(state)
    state = persist_run(state)
    return state


# --- Optional LangGraph wrapping ------------------------------------------


def _build_langgraph():
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
    except Exception:
        return None

    g = StateGraph(AgentState)

    def _wrap(fn: Callable[[AgentState], AgentState]):
        def node(state: AgentState):
            return fn(state)

        return node

    g.add_node("universe", _wrap(universe.run))
    g.add_node("quant", _wrap(quant.run))
    g.add_node("fundamentals", _wrap(fundamentals.run))
    g.add_node("technical", _wrap(technical.run))
    g.add_node("news", _wrap(news_sentiment.run))
    g.add_node("macro", _wrap(macro.run))

    def _researchers(state: AgentState) -> AgentState:
        for r in range(state.max_debate_rounds):
            state = researchers.run(state, round_idx=r)
        return state

    g.add_node("debate", _wrap(_researchers))
    g.add_node("risk", _wrap(risk_profile.run))
    g.add_node("manager", _wrap(manager.run))
    g.add_node("manager_quant", _wrap(manager.run_quant_only))
    g.add_node("report", _wrap(generate_report))
    g.add_node("memory", _wrap(persist_run))

    g.set_entry_point("universe")
    g.add_edge("universe", "quant")

    g.add_conditional_edges(
        "quant",
        should_run_llm,
        {"run_llm": "fundamentals", "skip_llm": "manager_quant"},
    )

    g.add_edge("fundamentals", "technical")
    g.add_edge("technical", "news")
    g.add_edge("news", "macro")
    g.add_edge("macro", "debate")
    g.add_edge("debate", "risk")
    g.add_edge("risk", "manager")
    g.add_edge("manager", "report")

    g.add_edge("manager_quant", "risk")  # risk also runs after quant-only path
    # to merge cleanly we just go quant_only -> risk -> manager -> report.
    # but we already routed risk -> manager above. So add an alt: manager_quant -> report.
    g.add_edge("manager_quant", "report")

    g.add_edge("report", "memory")
    g.add_edge("memory", END)

    return g.compile()


def run(state: AgentState) -> AgentState:
    graph = _build_langgraph()
    if graph is None:
        return _seq_run(state)
    try:
        result = graph.invoke(state)
        if isinstance(result, AgentState):
            return result
        # langgraph may return a dict
        return AgentState.model_validate(result)
    except Exception:
        # If anything goes wrong with langgraph, fall back to sequential.
        return _seq_run(state)
