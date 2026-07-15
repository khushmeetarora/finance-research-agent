"""Factor decay / regime tracker.

Computes a *rolling factor return* for each factor on the candidate universe
by sorting tickers into top and bottom quintiles by that factor's score and
measuring the spread of trailing 12-1 month price returns.

This is a coarse but useful regime indicator: if Momentum's top-bottom
spread has been negative or near-zero for the trailing year, you're likely
in a regime where Momentum-tilted picks have been underperforming - we
surface that as a warning on the report so the user knows.

Limitations: only one historical window (we don't backtest), the universe
is whatever's currently in scope, and the spread is unweighted equal-spread.
For deeper validation use the dedicated backtest subcommand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..data.provider import CompanySnapshot


@dataclass
class FactorRegimeReport:
    factor_returns: dict[str, float | None] = field(default_factory=dict)
    regime_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "factor_returns": dict(self.factor_returns),
            "regime_warnings": list(self.regime_warnings),
        }


def _quintile_spread(scores: list[tuple[str, float, float]]) -> float | None:
    """Given (ticker, factor_score, return), return mean(top quintile return)
    minus mean(bottom quintile return)."""
    if len(scores) < 5:
        return None
    sorted_scores = sorted(scores, key=lambda t: t[1])
    cut = max(1, len(sorted_scores) // 5)
    bottom = sorted_scores[:cut]
    top = sorted_scores[-cut:]
    bottom_ret = sum(r for _, _, r in bottom) / len(bottom) if bottom else 0.0
    top_ret = sum(r for _, _, r in top) / len(top) if top else 0.0
    return top_ret - bottom_ret


def factor_regime(
    snapshots: Iterable[CompanySnapshot],
    factor_reports: Iterable[dict],
) -> FactorRegimeReport:
    """Build a regime report from already-computed factor reports.

    `factor_reports` is the list of FactorReport.to_dict() outputs.
    """
    snaps_by_t = {s.ticker: s for s in snapshots}
    regime = FactorRegimeReport()

    factor_names = ["quality", "value", "momentum", "financial_health", "earnings_quality"]
    for fname in factor_names:
        triples: list[tuple[str, float, float]] = []
        for rep in factor_reports:
            ticker = rep.get("ticker")
            score = (rep.get("factor_scores") or {}).get(fname)
            snap = snaps_by_t.get(ticker)
            if snap is None or score is None:
                continue
            ret = snap.momentum_12_1
            if ret is None:
                continue
            triples.append((ticker, float(score), float(ret)))

        spread = _quintile_spread(triples)
        regime.factor_returns[fname] = spread

        # Warn if the factor's recent 12-1m top-bottom spread was negative or
        # uninformative. -2% is an arbitrary but conservative threshold.
        if spread is not None and spread < -0.02:
            regime.regime_warnings.append(
                f"{fname.title()}: top-quintile minus bottom-quintile 12-1m return "
                f"is {spread*100:+.1f}%. Factor may be in a regime drawdown - "
                f"weight it cautiously."
            )

    return regime
