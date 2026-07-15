"""Tests for the Universe Builder agent."""

from __future__ import annotations

from src.agents import universe
from src.config import load_profile
from src.graph.state import AgentState


def _state(profile_id: str, target: str, **kw):
    profile = load_profile(profile_id)
    return AgentState(profile_id=profile_id, profile=profile, target=target, **kw)


def test_single_ticker_target_india():
    s = universe.run(_state("india_adult", "INFY"))
    assert s.candidate_tickers == ["INFY.NS"]


def test_single_ticker_target_germany():
    s = universe.run(_state("germany_student", "SAP"))
    assert s.candidate_tickers == ["SAP.DE"]


def test_explicit_suffix_preserved():
    s = universe.run(_state("germany_student", "AAPL.US"))
    # If user gives a suffix we don't add another.
    assert s.candidate_tickers == ["AAPL.US"]


def test_domain_filters_pool_india():
    s = universe.run(_state("india_adult", "best IT stocks in India"))
    # Should find at least the IT seeded names with .NS suffix.
    assert any(t.endswith(".NS") for t in s.candidate_tickers)
    sectors = {m["sector"] for m in s.candidate_meta}
    assert sectors == {"Information Technology"}


def test_domain_filters_pool_germany_banking():
    s = universe.run(_state("germany_student", "best banks in Germany"))
    sectors = {m["sector"] for m in s.candidate_meta}
    assert sectors == {"Financials"}


def test_no_match_falls_back_to_full_pool():
    s = universe.run(_state("india_adult", "best stocks"))
    assert len(s.candidate_tickers) > 5
