"""Tests for the backtest module using mocked price histories."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from src.backtest.engine import BacktestConfig, run_backtest
from src.data import provider as provider_mod


def _synth_history(start: str, days: int, drift: float) -> list[dict]:
    out = []
    px = 100.0
    d = date.fromisoformat(start)
    for i in range(days):
        d2 = d + timedelta(days=i)
        # Skip weekends.
        if d2.weekday() >= 5:
            continue
        px *= 1 + drift
        out.append(
            {"date": d2.isoformat(), "open": px, "high": px,
             "low": px, "close": px, "volume": 1000}
        )
    return out


def test_backtest_runs_and_writes_excel(tmp_path, monkeypatch):
    """Simple smoke: 4 tickers, deterministic histories, no errors,
    metrics computed, equity curve non-empty, Excel file written."""
    histories = {
        "WIN1": _synth_history("2020-01-01", 1500, 0.0008),  # +0.08%/day
        "WIN2": _synth_history("2020-01-01", 1500, 0.0007),
        "LOSE1": _synth_history("2020-01-01", 1500, -0.0002),
        "LOSE2": _synth_history("2020-01-01", 1500, -0.0003),
    }

    def fake_get_history(self, ticker, period="2y"):
        return histories.get(ticker, [])

    monkeypatch.setattr(provider_mod.DataProvider, "get_history", fake_get_history)

    cfg = BacktestConfig(
        profile_id="t",
        profile={"tax": {"long_term_rate": 0.1}},
        tickers=list(histories.keys()),
        start="2020-01-01",
        top_n=2,
        transaction_cost_bps=5,
    )
    res = run_backtest(cfg)
    assert res.metrics
    assert res.metrics["rebalances"] >= 1
    # Winners should bias the held set after the first rebalance.
    assert any("WIN1" in held or "WIN2" in held for _, held in res.holdings_log)
    assert res.equity_curve
    out_xlsx = tmp_path / "bt.xlsx"
    res.to_excel(str(out_xlsx))
    assert out_xlsx.exists()
    assert out_xlsx.stat().st_size > 1000
