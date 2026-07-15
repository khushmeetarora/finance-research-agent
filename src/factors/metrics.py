"""Per-factor metric extraction from a CompanySnapshot.

Each factor extractor returns a dict of {metric_name: value | None}. Higher
metric value => "better" for that factor (we invert valuation so cheaper is
better). Percentile ranking is done in scoring.py across the universe.
"""

from __future__ import annotations

from typing import Callable

from ..data.provider import CompanySnapshot


# ---------------------------------------------------------------------------
# Factor metric extractors
# Convention: each returns dict[str, float|None]; higher = better.
# ---------------------------------------------------------------------------


def quality(s: CompanySnapshot) -> dict[str, float | None]:
    return {
        "roic": s.roic,
        "roe": s.roe,
        "gross_margin": s.gross_margin,
        "operating_margin": s.operating_margin,
        "profit_margin": s.profit_margin,
    }


def value(s: CompanySnapshot) -> dict[str, float | None]:
    """Lower P/E etc. => better, so we invert (higher = cheaper)."""

    def inv(x: float | None) -> float | None:
        if x is None or x <= 0:
            return None
        return 1.0 / x

    return {
        "earnings_yield": s.earnings_yield,
        "fcf_yield": s.fcf_yield,
        "inv_pb": inv(s.pb),
        "inv_ps": inv(s.ps),
        "inv_ev_ebitda": inv(s.ev_to_ebitda),
    }


def momentum(s: CompanySnapshot) -> dict[str, float | None]:
    return {
        "momentum_12_1": s.momentum_12_1,
        "momentum_6_1": s.momentum_6_1,
    }


def financial_health(s: CompanySnapshot) -> dict[str, float | None]:
    """Lower leverage = better, so invert. Higher current ratio = better."""
    nd_ebitda = s.net_debt_to_ebitda
    if nd_ebitda is not None:
        # better = -nd_ebitda (less debt is better)
        nd_score = -nd_ebitda
    else:
        nd_score = None

    de = s.debt_to_equity
    de_score = -de if de is not None else None

    return {
        "neg_net_debt_ebitda": nd_score,
        "neg_debt_equity": de_score,
        "current_ratio": s.current_ratio,
    }


def earnings_quality(s: CompanySnapshot) -> dict[str, float | None]:
    return {
        "cash_conversion": s.cash_conversion,
    }


FACTORS: dict[str, Callable[[CompanySnapshot], dict[str, float | None]]] = {
    "quality": quality,
    "value": value,
    "momentum": momentum,
    "financial_health": financial_health,
    "earnings_quality": earnings_quality,
}
