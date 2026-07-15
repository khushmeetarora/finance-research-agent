"""Conditional edges for the LangGraph orchestrator."""

from __future__ import annotations

from .state import AgentState


def should_run_llm(state: AgentState) -> str:
    """If --no-llm or empty shortlist, skip the LLM stages."""
    if not state.use_llm or not state.shortlist:
        return "skip_llm"
    return "run_llm"
