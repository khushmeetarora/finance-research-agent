"""Scratch: dump PIT fundamentals for key determinate names to tune the
early-stage growth exception. Offline (uses cached screener + price data)."""
from __future__ import annotations

import datetime as _dt

from src.data.provider import DataProvider, CompanySnapshot
from scripts.backtest_multibagger import (
    load_dataset, load_price_series, build_pit_snapshot, MANUAL_TIER_C,
)

WINNERS = {"HAL.NS", "BDL.NS", "MAZDOCK.NS", "TRENT.NS", "FINEORG.NS",
           "DIXON.NS", "TATAELXSI.NS", "POLYCAB.NS", "APLAPOLLO.NS"}
LOSERS = {"GITANJALI.NS", "ABB.NS", "KFA.NS", "JETAIRWAYS.NS", "HATHWAY.NS",
          "IDEA.NS", "MANPASAND.NS", "VAKRANGEE.NS"}


def fmt(xs, n=2):
    if xs is None:
        return "None"
    if isinstance(xs, list):
        return "[" + ", ".join(f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v) for v in xs) + "]"
    if isinstance(xs, (int, float)):
        return f"{xs:.{n}f}"
    return str(xs)


def main():
    dp = DataProvider(use_stooq=False)
    rows = load_dataset()
    want = WINNERS | LOSERS
    seen = []
    for row in rows:
        sym = row["yahoo_symbol"].strip()
        if sym not in want:
            continue
        try:
            asof = _dt.date.fromisoformat(row["entry_date"].strip())
        except ValueError:
            asof = _dt.date(int(row["entry_date"][:4]), 1, 1)
        series = load_price_series(sym)
        snap, fin, source = build_pit_snapshot(dp, row, asof, series, prefer_deep=True)
        tag = "WIN " if sym in WINNERS else "LOSE"
        print(f"\n==== {tag} {sym} @ {asof} ({row.get('label')}) periods={len(fin.get('income_periods',[]))} ====")
        print(f"  roce={fmt(snap.roce,3)} roce_series={fmt(snap.roce_series,3)}")
        print(f"  roe_series={fmt(snap.roe_series,3)}")
        print(f"  rev_series={fmt(snap.revenue_series,0)}")
        print(f"  ni_series={fmt(snap.net_income_series,0)}")
        print(f"  cfo_series={fmt(snap.cfo_series,0)}")
        print(f"  fcf_series={fmt(snap.fcf_series,0)} posrate={fmt(snap.fcf_posrate,2)} neg_years={snap.fcf_neg_years}")
        print(f"  opm_series={fmt(snap.operating_margin_series,3)}")
        print(f"  capex_intensity={fmt(snap.capex_intensity,3)} altman={fmt(snap.altman_z,2)}")
        print(f"  earnings_cagr={fmt(snap.earnings_cagr,3)} ocf/np={fmt(snap.ocf_to_np_multiyear,2)} cum_np_nonpos={snap.cum_np_nonpositive}")
        print(f"  cfo_np_streak={snap.cfo_np_below_half_streak}")
        # revenue CAGR (robust) from revenue_series
        from src.data.provider import _robust_growth
        print(f"  rev_cagr(robust)={fmt(_robust_growth(snap.revenue_series),3)}")
        # NEW: exception + veto pass
        from src.factors.multibagger import (
            is_early_stage_growth_exception, run_veto_pass,
        )
        from src.factors.engine import FactorReport
        exc = is_early_stage_growth_exception(snap)
        rep = FactorReport(ticker=sym, name=sym, sector=snap.sector)
        rep.composite_score = 0.6
        run_veto_pass(rep, snap)
        print(f"  >> early_stage_exception={exc}  vetoes_after={rep.vetoes}")
        seen.append(sym)
    print("\nseen:", sorted(seen))
    print("missing:", sorted(want - set(seen)))


if __name__ == "__main__":
    main()
