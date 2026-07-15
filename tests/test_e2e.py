"""End-to-end smoke tests with a faked DataProvider and stub LLM.

These run the full graph for one India example and one Germany example and
assert that a report file is written with picks present.
"""

from __future__ import annotations

from pathlib import Path

from src.config import load_profile
from src.graph.orchestrator import run as run_graph
from src.graph.state import AgentState


def test_e2e_india_no_llm(fake_provider, force_stub_llm):
    profile = load_profile("india_adult")
    state = AgentState(
        profile_id="india_adult",
        profile=profile,
        target="best IT stocks in India",
        top_n=5,
        use_llm=False,
        max_debate_rounds=0,
    )
    out = run_graph(state)
    assert out.report_path is not None
    assert Path(out.report_path).exists()
    md = Path(out.report_path).read_text(encoding="utf-8")
    assert "Finance Research Agent" in md
    assert "STCG" in md or "LTCG" in md  # India tax notes present
    assert len(out.picks) > 0
    assert all(p.ticker.endswith(".NS") for p in out.picks)


def test_e2e_germany_no_llm(fake_provider, force_stub_llm):
    profile = load_profile("germany_student")
    state = AgentState(
        profile_id="germany_student",
        profile=profile,
        target="best banks in Germany",
        top_n=5,
        use_llm=False,
        max_debate_rounds=0,
    )
    out = run_graph(state)
    assert out.report_path is not None
    md = Path(out.report_path).read_text(encoding="utf-8")
    assert "Abgeltungssteuer" in md or "Sparerpauschbetrag" in md
    assert len(out.picks) > 0
    assert all(p.ticker.endswith(".DE") for p in out.picks)


def test_e2e_india_with_stub_llm(fake_provider, force_stub_llm):
    """Even with use_llm=True, the stub produces empty JSON; pipeline must still finish."""
    profile = load_profile("india_adult")
    state = AgentState(
        profile_id="india_adult",
        profile=profile,
        target="INFY",
        top_n=1,
        use_llm=True,
        max_debate_rounds=1,
    )
    out = run_graph(state)
    assert out.report_path is not None
    assert len(out.picks) >= 1
    assert out.picks[0].ticker == "INFY.NS"
