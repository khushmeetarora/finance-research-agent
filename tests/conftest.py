"""Shared test fixtures.

We patch the yfinance-backed DataProvider with a deterministic stub so the
tests run offline and quickly.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repo root is importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_dirs(monkeypatch, tmp_path):
    """Redirect cache / memory / reports to a temp dir per test, and force
    every fetcher that would otherwise call the network to return None /
    empty so tests run hermetically."""
    cache = tmp_path / "cache"
    memory = tmp_path / "memory"
    reports = tmp_path / "reports"
    cache.mkdir()
    memory.mkdir()
    reports.mkdir()
    monkeypatch.setenv("FRA_CACHE_DIR", str(cache))
    monkeypatch.setattr("src.config.DEFAULT_CACHE_DIR", cache)
    monkeypatch.setattr("src.config.DEFAULT_MEMORY_DIR", memory)
    monkeypatch.setattr("src.config.DEFAULT_REPORTS_DIR", reports)
    # Disable network-bound free fetchers in unit tests by default.
    monkeypatch.setattr("src.data.universe_live.get_constituents", lambda *a, **kw: None)
    monkeypatch.setattr("src.data.news_gdelt.get_news_gdelt", lambda *a, **kw: [])
    monkeypatch.setattr(
        "src.data.insiders_edgar.get_insider_signal",
        lambda ticker, **kw: __import__(
            "src.data.insiders_edgar", fromlist=["InsiderSignal"]
        ).InsiderSignal(ticker=ticker),
    )
    monkeypatch.setattr("src.data.provider._stooq_close", lambda ticker: None)
    yield


def _fake_snapshot(ticker: str, idx: int):
    """Synthesize a deterministic snapshot for a fixed list of seed companies."""
    from src.data.provider import CompanySnapshot

    base = (idx + 1) * 11.0
    return CompanySnapshot(
        ticker=ticker,
        name=f"FakeCo {idx}",
        currency="INR" if ticker.endswith(".NS") else "EUR" if ticker.endswith(".DE") else "USD",
        sector="Information Technology" if idx % 2 == 0 else "Financials",
        industry="Software",
        country="IN" if ticker.endswith(".NS") else "DE" if ticker.endswith(".DE") else "US",
        market_cap=1e12 + idx * 1e10,
        price=100 + idx,
        pe_trailing=10 + idx,
        pe_forward=9 + idx,
        pb=1.5 + 0.1 * idx,
        ps=2.0 + 0.05 * idx,
        ev_to_ebitda=8 + idx * 0.2,
        ev_to_revenue=2 + idx * 0.1,
        earnings_yield=1 / (10 + idx),
        fcf_yield=0.05 + 0.005 * idx,
        dividend_yield=0.01 + 0.002 * idx,
        roe=0.15 + 0.01 * idx,
        roa=0.07 + 0.005 * idx,
        roic=0.12 + 0.008 * idx,
        gross_margin=0.45,
        operating_margin=0.20,
        profit_margin=0.15,
        debt_to_equity=0.3 + 0.02 * idx,
        net_debt_to_ebitda=1.0 + 0.1 * idx,
        current_ratio=2.0,
        cash_conversion=1.0 + 0.05 * idx,
        revenue_growth=0.10,
        earnings_growth=0.12,
        momentum_12_1=0.05 + 0.01 * idx,
        momentum_6_1=0.03 + 0.005 * idx,
        volatility_annualized=0.25,
        beta=1.0,
        raw={},
    )


@pytest.fixture
def fake_provider(monkeypatch):
    """Patch DataProvider.get_snapshot / get_news / get_history."""
    from src.data import provider as provider_mod
    from src.agents import quant as quant_mod

    counter = {"i": 0}

    def _get_snapshot(self, ticker):
        idx = counter["i"]
        counter["i"] += 1
        return _fake_snapshot(ticker, idx)

    def _get_news(self, ticker, limit=10):
        return [{"title": f"{ticker}: solid quarter", "publisher": "FakeWire"}]

    def _get_history(self, ticker, period="2y"):
        return []

    monkeypatch.setattr(provider_mod.DataProvider, "get_snapshot", _get_snapshot)
    monkeypatch.setattr(provider_mod.DataProvider, "get_news", _get_news)
    monkeypatch.setattr(provider_mod.DataProvider, "get_history", _get_history)
    yield


@pytest.fixture
def force_stub_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")  # no key -> stub
    yield
