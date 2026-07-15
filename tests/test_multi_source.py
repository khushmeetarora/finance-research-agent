"""Tests for multi-source data and Stooq enrichment."""

from __future__ import annotations

import pytest

from src.data import provider as provider_mod
from src.data.provider import CompanySnapshot, DataProvider, _stooq_symbol, _rel_diff


def test_stooq_symbol_translation():
    assert _stooq_symbol("AAPL") == "aapl.us"
    assert _stooq_symbol("INFY.NS") == "infy.in"
    assert _stooq_symbol("SAP.DE") == "sap.de"
    assert _stooq_symbol("ULVR.L") == "ulvr.uk"


def test_rel_diff_basics():
    assert _rel_diff(100, 100) == 0.0
    assert _rel_diff(100, 110) == pytest.approx(0.10, rel=1e-6)
    assert _rel_diff(None, 100) is None
    assert _rel_diff(100, None) is None
    assert _rel_diff(0, 100) is None  # avoid divide-by-zero


def test_enrich_with_stooq_records_disagreement(monkeypatch):
    # Force Stooq to return a price 5% higher than yfinance's.
    monkeypatch.setattr(provider_mod, "_stooq_close", lambda t: 105.0)

    snap = CompanySnapshot(ticker="A", price=100.0, fetch_status="ok",
                           data_sources=["yfinance"])
    DataProvider()._enrich_with_stooq(snap)
    assert "stooq" in snap.data_sources
    assert snap.field_disagreements.get("price") == pytest.approx(0.05, rel=1e-6)
    assert snap.data_agreement is not None
    assert 0.94 <= snap.data_agreement <= 0.96


def test_enrich_with_stooq_no_secondary_keeps_none_agreement(monkeypatch):
    monkeypatch.setattr(provider_mod, "_stooq_close", lambda t: None)
    snap = CompanySnapshot(ticker="A", price=100.0, fetch_status="ok",
                           data_sources=["yfinance"])
    DataProvider()._enrich_with_stooq(snap)
    assert snap.data_agreement is None
