"""As-of (point-in-time) event-study helpers for the multibagger backtest.

Additive module for Phase 3. It does NOT modify the classic engine, the metric
files, or ``src/factors/multibagger.py`` - it only *reuses* their public
primitives:

- ``rank_multibagger`` / ``run_veto_pass`` (the 7-pillar scorer + veto pass)
- ``enrich_snapshot_with_financials`` (Tier-B statement enrichment)

The single new piece of logic is:

1. ``as_of_financials`` - truncate a fetched statement bundle to only the
   fiscal periods that had *closed and been reportable* on/before a screening
   date (with the ~90-day Indian reporting-lag buffer). This is the crux of the
   look-ahead-avoidance effort described in ``docs/FRA_V2_BACKTEST_PLAN.md`` 5.1.
2. ``score_one`` - the thin adapter the Phase-2 notes suggested: score ONE name
   against an as-of peer panel by dropping it into ``rank_multibagger`` with the
   peers and returning just its report (pillar scores are cross-sectional
   percentiles, so a single name needs a panel).

Nothing here fabricates data: when statements are missing the derived fields
stay ``None`` and the caller marks the name INDETERMINATE.
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Iterable

from ..data.provider import CompanySnapshot, enrich_snapshot_with_financials
from ..factors.engine import FactorReport
from ..factors.multibagger import rank_multibagger

REPORTING_LAG_DAYS = 90


def _parse_period(p: str) -> _dt.date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return _dt.datetime.strptime(p, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def as_of_financials(
    fin: dict, asof: _dt.date, lag_days: int = REPORTING_LAG_DAYS
) -> dict:
    """Return a copy of a ``get_financials`` bundle truncated to periods that
    ended on/before ``asof - lag_days``.

    Each statement (income/balance/cashflow) carries a period list and a set of
    line-item series aligned to it; we keep only the leading columns whose
    period-end date is admissible and trim every series to match. Status is
    recomputed (``failed`` when nothing survives, ``shallow`` when < 3 remain).
    """
    cutoff = asof - _dt.timedelta(days=lag_days)
    out: dict = {"status": "failed"}
    max_kept = 0
    for stmt, per_key in (
        ("income", "income_periods"),
        ("balance", "balance_periods"),
        ("cashflow", "cashflow_periods"),
    ):
        periods = list((fin or {}).get(per_key) or [])
        items = dict((fin or {}).get(stmt, {}) or {})
        keep_idx = []
        for i, p in enumerate(periods):
            d = _parse_period(str(p))
            if d is not None and d <= cutoff:
                keep_idx.append(i)
        out[per_key] = [periods[i] for i in keep_idx]
        out[stmt] = {
            line: [series[i] for i in keep_idx if i < len(series)]
            for line, series in items.items()
        }
        max_kept = max(max_kept, len(keep_idx))
    if max_kept == 0:
        out["status"] = "failed"
    elif max_kept < 3:
        out["status"] = "shallow"
    else:
        out["status"] = "ok"
    out["_asof"] = asof.isoformat()
    out["_cutoff"] = cutoff.isoformat()
    return out


def usable_period_count(fin: dict) -> int:
    return max(
        len((fin or {}).get("income_periods") or []),
        len((fin or {}).get("balance_periods") or []),
        len((fin or {}).get("cashflow_periods") or []),
    )


def build_asof_snapshot(
    base: CompanySnapshot,
    fin_asof: dict,
    *,
    asof_price: float | None = None,
    asof_eps: float | None = None,
    momentum_12_1: float | None = None,
    momentum_6_1: float | None = None,
    manual: dict | None = None,
) -> CompanySnapshot:
    """Construct a point-in-time snapshot for one name.

    Starts from the identity fields of ``base`` (name/sector/currency) but
    DROPS all live ``.info``-derived valuation/quality/momentum values (which
    reflect *today* and would leak look-ahead), then enriches purely from the
    as-of statement bundle. Valuation is reconstructed from the as-of price and
    as-of trailing EPS where both exist; momentum from the as-of price series.
    """
    snap = CompanySnapshot(
        ticker=base.ticker,
        name=base.name,
        currency=base.currency,
        sector=base.sector,
        industry=base.industry,
        country=base.country,
    )
    # As-of valuation only (never today's .info).
    if asof_price is not None and asof_eps not in (None, 0) and asof_eps > 0:
        snap.pe_trailing = asof_price / asof_eps
        snap.earnings_yield = 1.0 / snap.pe_trailing
    snap.momentum_12_1 = momentum_12_1
    snap.momentum_6_1 = momentum_6_1
    enrich_snapshot_with_financials(snap, fin_asof, manual=manual)
    return snap


def score_one(
    snap: CompanySnapshot,
    peer_snapshots_asof: Iterable[CompanySnapshot],
    *,
    sector_relative: bool = True,
    min_peers: int = 6,
    cyclical_mode: bool = False,
    apply_vetoes: bool = True,
) -> FactorReport:
    """Score a single name against an as-of peer panel.

    Thin adapter around ``rank_multibagger``: the target is prepended to the
    peer panel (percentile pillars need a cross-section), the whole panel is
    ranked, and the target's own report is returned. Peers are only used to
    define the cross-sectional distribution; the returned report is the target's.
    """
    panel = [snap] + [p for p in peer_snapshots_asof if p.ticker != snap.ticker]
    reports = rank_multibagger(
        panel,
        sector_relative=sector_relative,
        min_peers=min_peers,
        cyclical_mode=cyclical_mode,
        apply_vetoes=apply_vetoes,
    )
    for r in reports:
        if r.ticker == snap.ticker:
            return r
    # Should not happen; return an empty report rather than raising.
    return FactorReport(ticker=snap.ticker, name=snap.name, sector=snap.sector)
