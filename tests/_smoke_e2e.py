"""Visible end-to-end smoke run.

Runs the orchestrator twice (India + Germany) with a faked DataProvider so it
works fully offline and writes Markdown reports to ./reports/ that the user
can inspect.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force the LLM stub (no network, deterministic).
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["LLM_PROVIDER"] = "openai"

from src.config import load_profile  # noqa: E402
from src.data import provider as provider_mod  # noqa: E402
from src.data.provider import CompanySnapshot  # noqa: E402
from src.graph.orchestrator import run as run_graph  # noqa: E402
from src.graph.state import AgentState  # noqa: E402


_counter = {"i": 0}


def _fake_snapshot(self, ticker):
    i = _counter["i"]
    _counter["i"] += 1
    spread = i * 0.07
    return CompanySnapshot(
        ticker=ticker,
        name=f"DemoCo-{i}",
        currency="INR" if ticker.endswith(".NS") else "EUR" if ticker.endswith(".DE") else "USD",
        sector="Information Technology" if i % 2 == 0 else "Financials",
        industry="Software" if i % 2 == 0 else "Bank",
        country="IN" if ticker.endswith(".NS") else "DE" if ticker.endswith(".DE") else "US",
        market_cap=1.5e12 + i * 5e10,
        price=100 + i * 3.0,
        pe_trailing=12 + spread,
        pe_forward=11 + spread,
        pb=2.0 + spread,
        ps=2.5 + spread,
        ev_to_ebitda=10 + spread,
        ev_to_revenue=2.2 + spread,
        earnings_yield=1.0 / (12 + spread),
        fcf_yield=0.05 + spread / 100,
        dividend_yield=0.018,
        roe=0.18 - spread / 50,
        roa=0.08,
        roic=0.14 - spread / 80,
        gross_margin=0.45,
        operating_margin=0.21,
        profit_margin=0.16,
        debt_to_equity=0.35 + spread / 30,
        net_debt_to_ebitda=1.2 + spread / 10,
        current_ratio=2.1,
        cash_conversion=1.05 - spread / 200,
        revenue_growth=0.12 - spread / 100,
        earnings_growth=0.14 - spread / 80,
        momentum_12_1=0.18 - spread,
        momentum_6_1=0.10 - spread / 1.5,
        volatility_annualized=0.27 + spread / 30,
        beta=1.05,
        raw={},
    )


def _fake_news(self, ticker, limit=10):
    return [
        {"title": f"{ticker} reports steady quarter", "publisher": "DemoWire"},
        {"title": f"{ticker} expands product line", "publisher": "DemoWire"},
    ][:limit]


def _fake_history(self, ticker, period="2y"):
    return []


provider_mod.DataProvider.get_snapshot = _fake_snapshot
provider_mod.DataProvider.get_news = _fake_news
provider_mod.DataProvider.get_history = _fake_history


def run_one(profile_id: str, target: str, top: int = 5):
    _counter["i"] = 0
    profile = load_profile(profile_id)
    state = AgentState(
        profile_id=profile_id,
        profile=profile,
        target=target,
        top_n=top,
        use_llm=False,
        max_debate_rounds=0,
    )
    out = run_graph(state)
    print(f"\n=== {profile_id} | target={target!r} ===")
    print(f"candidates considered: {len(out.candidate_tickers)}")
    print(f"report: {out.report_path}")
    print("top picks:")
    for p in out.picks:
        print(f"  {p.rank}. {p.ticker:<14} {(p.name or '')[:24]:<24}"
              f" composite={p.composite_score:.2f} conf={p.confidence:.2f}")
    return out.report_path


if __name__ == "__main__":
    p1 = run_one("india_adult", "best IT stocks in India", top=5)
    p2 = run_one("germany_student", "best banks in Germany", top=5)

    print("\n--- India report (head) ---")
    print(Path(p1).read_text(encoding="utf-8")[:1200])
    print("\n--- Germany report (head) ---")
    print(Path(p2).read_text(encoding="utf-8")[:1200])
