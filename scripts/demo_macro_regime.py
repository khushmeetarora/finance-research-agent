"""Runnable demo of the FRA V2 macro/regime overlay (docs/FRA_V2_MACRO.md).

Prints the PIT-safe regime read for a couple of historical dates and shows the
(unwired) integration outputs - pillar tilts, entry context, re-rating boost.

Two modes:
  * Default (OFFLINE, deterministic): uses a small built-in synthetic series
    provider so the demo runs anywhere with NO network - ideal for CI / docs.
  * --live: pulls the real free series (FRED no-key CSV + yfinance). Requires
    network; degrades gracefully to "unavailable" for any series that fails.

Usage (Windows / conda):
  conda run -n fra python scripts/demo_macro_regime.py
  conda run -n fra python scripts/demo_macro_regime.py --live --sector "Information Technology"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

# Make the repo root importable when run as a script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import macro_signals as ms  # noqa: E402
from src.factors import regime  # noqa: E402


def _synthetic_provider():
    """Deterministic offline series so the demo needs no network.

    Encodes an *easing + risk-on* backdrop up to ~2020, then a crude spike and a
    VIX blow-off in early-2020 (COVID) so the two demo dates land in visibly
    different regimes and the PIT gate is observable.
    """
    def daily(start, n, fn):
        d0 = _dt.date.fromisoformat(start)
        return [{"date": (d0 + _dt.timedelta(days=i)).isoformat(), "value": fn(i)} for i in range(n)]

    def monthly(start_year, n, fn):
        out, y, m = [], start_year, 1
        for i in range(n):
            out.append({"date": f"{y:04d}-{m:02d}-01", "value": fn(i)})
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return out

    series = {
        # Repo rate falling through 2018-2020 => easing.
        "india_repo_rate": monthly(2017, 40, lambda i: 6.5 - 0.03 * i),
        # CPI index drifting up ~4.5%/yr.
        "india_cpi": monthly(2017, 40, lambda i: 130.0 * (1.0 + 0.0037) ** i),
        # VIX: gently DECLINING through 2018-2019 (calm, low-percentile => risk-on)
        # then a blow-off spike in Mar-2020 (top-percentile => risk-off).
        "india_vix": (
            daily("2018-01-01", 800, lambda i: 22.0 - 0.012 * i)
            + daily("2020-03-01", 30, lambda i: 45.0 + i)
        ),
        # Nifty: steady uptrend, then a sharp COVID drawdown.
        "nifty": (
            daily("2018-01-01", 800, lambda i: 10000.0 + 6.0 * i)
            + daily("2020-03-01", 30, lambda i: 14800.0 - 120.0 * i)
        ),
        # Brent: quiet band through 2019, then a sharp spike into early-2020.
        "crude_brent": (
            daily("2018-01-01", 800, lambda i: 64.0 + 0.4 * (i % 4))
            + daily("2020-02-20", 40, lambda i: 66.0 * (1 + 0.006 * i))
        ),
        # USD/INR: gentle depreciation then a stress jump.
        "usdinr": (
            daily("2018-01-01", 800, lambda i: 68.0 + 0.004 * i)
            + daily("2020-03-01", 30, lambda i: 71.0 * (1 + 0.004 * i))
        ),
    }
    return lambda name: series.get(name, [])


def _print_regime(reg: dict) -> None:
    print(f"\n=== Regime @ {reg['as_of']}  (sector={reg['sector']}) ===")
    print(f"  composite : {reg['composite']['label']}  "
          f"(on={reg['composite']['on_votes']} off={reg['composite']['off_votes']} "
          f"drivers={reg['composite']['drivers']})")
    for name, sig in reg["signals"].items():
        if not sig.get("available"):
            print(f"  {name:10s}: unavailable ({sig.get('source', '?')})")
            continue
        summary = {k: v for k, v in sig.items()
                   if k in ("regime", "value", "level") or k.startswith("flag_")}
        print(f"  {name:10s}: {summary}")
    if reg["sector_tailwind"].get("available"):
        tw = reg["sector_tailwind"]
        print(f"  sector_tw : tilt={tw['tilt']:+.2f} reasons={tw['reasons']}")
    # Unwired integration outputs.
    tilts = regime.regime_pillar_tilts(reg)
    print(f"  pillar_tilts : {json.dumps({k: round(v, 3) for k, v in tilts.items()})}")
    print(f"  entry_context: {regime.regime_entry_context(reg)}")
    print(f"  rerate_boost : {regime.rerating_catalyst_boost(reg):+.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="use real free network sources")
    ap.add_argument("--sector", default="Information Technology")
    ap.add_argument(
        "--dates", nargs="*", default=["2019-06-30", "2020-03-31"],
        help="historical as_of dates (YYYY-MM-DD)",
    )
    args = ap.parse_args()

    if args.live:
        provider = ms.default_series_provider()
        print("[live] pulling free FRED + yfinance series (network required)...")
    else:
        provider = _synthetic_provider()
        print("[offline] using deterministic synthetic series (no network).")

    for d in args.dates:
        reg = regime.compute_regime(d, sector=args.sector, series_provider=provider)
        _print_regime(reg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
