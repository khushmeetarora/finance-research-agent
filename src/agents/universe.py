"""Universe Builder agent.

Resolves the user's free-text target ("best IT stocks in India", "SAP.DE",
"best banks") into a concrete list of candidate tickers using the seeded
constituent lists in src/data/{india,germany_global}.py.

This node is deterministic - no LLM call. It uses simple keyword routing.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..data import germany_global, india, universe_live
from ..graph.state import AgentState


# Heuristic sector keyword map.
_SECTOR_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Information Technology", ["it ", "software", "tech", "saas", "cloud", "semiconductor", "semis"]),
    ("Financials", ["bank", "finance", "insurance", "nbfc", "lender"]),
    ("Health Care", ["pharma", "health", "biotech", "medical", "hospital"]),
    ("Energy", ["energy", "oil", "gas", "petroleum"]),
    ("Consumer Staples", ["fmcg", "staples", "consumer staple", "food"]),
    ("Consumer Discretionary", ["auto", "retail", "discretionary", "luxury", "ecommerce"]),
    ("Industrials", ["industrial", "defense", "defence", "infrastructure", "engineering"]),
    ("Materials", ["materials", "cement", "steel", "metal", "chemical", "mining"]),
    ("Utilities", ["utility", "utilities", "power"]),
    ("Communication Services", ["telecom", "media", "communication"]),
    ("Real Estate", ["real estate", "realty", "reit"]),
]


_TICKER_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9\.\-]{0,14}$")


def _detect_sector(text: str) -> str | None:
    t = text.lower()
    for sector, kws in _SECTOR_KEYWORDS:
        for kw in kws:
            if kw in t:
                return sector
    return None


def _looks_like_ticker(text: str) -> bool:
    text = text.strip()
    return bool(_TICKER_LIKE.match(text)) and " " not in text


def _add_yahoo_suffix(symbol: str, profile: dict) -> str:
    """If symbol has no exchange suffix, append the profile-default one."""
    if "." in symbol or "-" in symbol[-3:]:
        return symbol
    suffix = profile.get("universe", {}).get("yahoo_suffix", "")
    return f"{symbol}{suffix}" if suffix else symbol


def _candidate_pool(profile: dict, universe_name: str | None) -> list[tuple[str, str, str]]:
    country = profile.get("country", "").upper()
    universe_name = (universe_name or profile.get("universe", {}).get("default", ""))
    # Try live first (with seed fallback baked in).
    try:
        rows = universe_live.get_constituents(country, universe_name)
        if rows:
            return rows
    except Exception:
        pass
    if country == "IN":
        return india.get_constituents(universe_name)
    return germany_global.get_constituents(universe_name)


def _filter_by_sector(
    pool: Iterable[tuple[str, str, str]], sector: str | None
) -> list[tuple[str, str, str]]:
    if not sector:
        return list(pool)
    matched = [t for t in pool if t[2] == sector]
    return matched or list(pool)


def run(state: AgentState) -> AgentState:
    profile = state.profile
    target = (state.target or "").strip()

    # Path 1: target looks like a ticker -> single-name research.
    if _looks_like_ticker(target):
        ticker = _add_yahoo_suffix(target.upper(), profile)
        state.candidate_tickers = [ticker]
        state.candidate_meta = [
            {"ticker": ticker, "name": target.upper(), "sector": None}
        ]
        return state

    # Path 2: domain/world search -> filter the pool by sector keywords.
    sector = _detect_sector(target) or _detect_sector(state.domain or "")
    pool = _candidate_pool(profile, state.universe_name)

    # Allow user-supplied --domain to additionally narrow the pool.
    if state.domain:
        sec = _detect_sector(state.domain)
        if sec:
            sector = sec

    filtered = _filter_by_sector(pool, sector)

    # If the target mentioned a country not matching the profile (e.g. "best
    # global tech"), we still use the profile pool but flag it. Future work:
    # cross-country pools.
    candidates = filtered

    state.candidate_tickers = [
        _add_yahoo_suffix(sym, profile) for sym, _name, _sec in candidates
    ]
    state.candidate_meta = [
        {
            "ticker": _add_yahoo_suffix(sym, profile),
            "name": name,
            "sector": sec,
        }
        for sym, name, sec in candidates
    ]
    return state
