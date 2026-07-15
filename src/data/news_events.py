"""News / event keyword layer (free, PIT-aware) built on top of GDELT.

NEW, self-contained module for the FRA V2 macro/regime/news overlay
(``docs/FRA_V2_MACRO.md``). It *reuses* the existing free GDELT feed
(``src/data/news_gdelt.get_news_gdelt`` - no API key) and classifies the
returned headlines into a small taxonomy of catalyst / risk events:

* ``war_geopolitics``  - war / conflict / sanctions / geopolitical shocks
* ``policy_catalyst``  - PLI, import duty, China+1, privatization, budget/PLI
* ``earnings_upgrade``  - results beat, rating upgrade, guidance raise, order win
* ``governance_risk``  - auditor resignation, SFIO / forensic, pledge, fraud

Nothing here fabricates data: the classifier only fires on literal keyword hits
in the (free) headline text, and the whole thing degrades to empty results when
GDELT is unreachable (matching the quiet-failure contract of ``news_gdelt``).

Point-in-time notes (READ THIS - honest about GDELT's limits)
-------------------------------------------------------------
* ``get_news_gdelt`` uses a ``timespan`` query that is relative to *now*, so it
  is only naturally PIT for near-real-time (forward) use. For a HISTORICAL
  ``as_of`` you must date-bound the query; GDELT's DOC API supports
  ``startdatetime`` / ``enddatetime`` but the shared feed does not expose them.
  Therefore this layer treats ``as_of`` as a strict SAFETY GATE: it drops any
  returned article whose publish date is after ``as_of`` (``pit_filter_articles``).
  This prevents look-ahead, but a true historical event scan needs a
  date-bounded GDELT query (documented limitation, not implemented here to keep
  the change additive and offline-testable).
* Article publish dates come from GDELT's ``seendate`` (``YYYYMMDDTHHMMSSZ``) or
  a fallback ISO string; unparseable dates are treated as NOT admissible under a
  historical ``as_of`` (conservative) and admissible when ``as_of`` is None.
* Reliability caveats: GDELT headline text is noisy, English-only here, and
  keyword matching yields false positives (e.g. "no fraud found"). These signals
  are FLAGS FOR REVIEW / soft tilts, never silent vetoes - consistent with the
  strategy's Tier-C free-data-honesty guardrail (FRA_V2_STRATEGY.md 7).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from .news_gdelt import get_news_gdelt

# Event taxonomy: category -> list of lowercase keyword/phrase triggers.
EVENT_KEYWORDS: dict[str, list[str]] = {
    "war_geopolitics": [
        "war", "conflict", "invasion", "airstrike", "missile", "border clash",
        "sanction", "sanctions", "geopolitic", "ceasefire", "military",
        "strait of hormuz", "red sea", "escalation", "terror",
    ],
    "policy_catalyst": [
        "pli", "production linked incentive", "import duty", "customs duty",
        "china+1", "china plus one", "privatization", "privatisation",
        "disinvestment", "budget", "gst cut", "capex push", "make in india",
        "incentive scheme", "tariff", "export ban", "subsidy",
    ],
    "earnings_upgrade": [
        "beats estimates", "profit jumps", "profit surges", "record profit",
        "rating upgrade", "upgraded to", "raises guidance", "guidance raise",
        "order win", "bags order", "wins order", "new contract", "bulk deal",
        "record revenue", "margin expansion", "q1 results", "q2 results",
        "q3 results", "q4 results", "earnings beat",
    ],
    "governance_risk": [
        "auditor resign", "auditor resignation", "qualified opinion", "sfio",
        "forensic audit", "fraud", "sebi probe", "sebi order", "pledge",
        "pledged shares", "insolvency", "nclt", "default", "downgrade to",
        "resignation of cfo", "cfo resigns", "promoter sells", "stake sale",
    ],
}

# Categories that are (net) bullish catalysts vs bearish risk flags.
BULLISH = ("policy_catalyst", "earnings_upgrade")
BEARISH = ("governance_risk",)  # war_geopolitics is regime-level, handled apart

FetchFn = Callable[..., list[dict]]


# ---------------------------------------------------------------------------
# PIT helpers.
# ---------------------------------------------------------------------------


def _parse_pubdate(raw: Any) -> _dt.date | None:
    """Parse a GDELT ``seendate`` (``YYYYMMDDTHHMMSSZ``) or ISO-ish string."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # GDELT compact form: 20240115T120000Z
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    # Epoch seconds (yfinance-style providerPublishTime).
    try:
        n = float(s)
        if n > 1e8:
            return _dt.datetime.utcfromtimestamp(n).date()
    except (ValueError, TypeError):
        pass
    return None


def pit_filter_articles(
    articles: list[dict], as_of: "_dt.date | str | None"
) -> list[dict]:
    """Drop any article published after ``as_of`` (look-ahead safety gate).

    ``as_of=None`` -> pass everything through (live/forward mode). When ``as_of``
    is set, articles with an unparseable date are dropped (conservative).
    """
    if as_of is None:
        return list(articles or [])
    if isinstance(as_of, str):
        as_of = _parse_pubdate(as_of) or _try_iso(as_of)
    if as_of is None:
        return list(articles or [])
    out = []
    for a in articles or []:
        d = _parse_pubdate(a.get("published"))
        if d is not None and d <= as_of:
            out.append(a)
    return out


def _try_iso(s: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Classification.
# ---------------------------------------------------------------------------


def classify_article(article: dict) -> set[str]:
    """Return the set of event categories an article's text matches."""
    text = " ".join(
        str(article.get(k, "") or "") for k in ("title", "summary")
    ).lower()
    hits: set[str] = set()
    if not text.strip():
        return hits
    for category, keywords in EVENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                hits.add(category)
                break
    return hits


def classify_articles(articles: list[dict]) -> dict[str, Any]:
    """Aggregate classification over a list of articles.

    Returns ``{category: {"count": int, "matches": [ {title, publisher, published} ]}}``
    for every taxonomy category (count 0 when none), so downstream code can rely
    on all keys being present.
    """
    result: dict[str, Any] = {
        cat: {"count": 0, "matches": []} for cat in EVENT_KEYWORDS
    }
    for a in articles or []:
        for cat in classify_article(a):
            result[cat]["count"] += 1
            result[cat]["matches"].append(
                {
                    "title": a.get("title"),
                    "publisher": a.get("publisher"),
                    "published": a.get("published"),
                }
            )
    return result


# ---------------------------------------------------------------------------
# Public scans.
# ---------------------------------------------------------------------------


def scan_company_events(
    company_name: str | None,
    ticker: str,
    *,
    as_of: "_dt.date | str | None" = None,
    days: int = 21,
    limit: int = 50,
    fetch_fn: FetchFn | None = None,
) -> dict[str, Any]:
    """PIT-aware per-company event scan.

    Fetches recent GDELT coverage (via the free feed, or an injected ``fetch_fn``
    in tests), applies the ``as_of`` look-ahead safety gate, classifies, and adds
    convenience flags + a coarse ``event_bias`` in [-1, 1] (bullish catalysts
    minus governance risks). Empty / unreachable feed -> all-zero result.
    """
    fetch = fetch_fn or get_news_gdelt
    try:
        articles = fetch(company_name, ticker, days=days, limit=limit) or []
    except Exception:
        articles = []
    articles = pit_filter_articles(articles, as_of)
    classified = classify_articles(articles)

    flags = {
        "war_geopolitics": classified["war_geopolitics"]["count"] > 0,
        "policy_catalyst": classified["policy_catalyst"]["count"] > 0,
        "earnings_upgrade": classified["earnings_upgrade"]["count"] > 0,
        "governance_risk": classified["governance_risk"]["count"] > 0,
    }
    bull = sum(classified[c]["count"] for c in BULLISH)
    bear = sum(classified[c]["count"] for c in BEARISH)
    total = bull + bear
    event_bias = 0.0 if total == 0 else (bull - bear) / total

    result = dict(classified)
    result.update(
        {
            "ticker": ticker,
            "as_of": as_of.isoformat() if isinstance(as_of, _dt.date) else as_of,
            "n_articles": len(articles),
            "flags": flags,
            "event_bias": event_bias,
        }
    )
    return result


# Broad, market-level geopolitics/conflict query terms (company-agnostic).
_MACRO_CONFLICT_QUERIES = ("war", "geopolitical", "conflict")


def scan_macro_geopolitics(
    *,
    as_of: "_dt.date | str | None" = None,
    days: int = 7,
    limit: int = 50,
    fetch_fn: FetchFn | None = None,
) -> dict[str, Any]:
    """Market-level geopolitical-risk proxy from GDELT conflict-theme volume.

    Sums article volume across a few conflict query terms; a high count is a
    coarse risk-off proxy. This is a NOISY proxy (see module docstring) - use as
    a soft regime tilt, not a hard signal. Returns
    ``{"available": bool, "conflict_volume": int, "flag_elevated": bool}``.
    """
    fetch = fetch_fn or get_news_gdelt
    total = 0
    any_ok = False
    for q in _MACRO_CONFLICT_QUERIES:
        try:
            arts = fetch(q, q, days=days, limit=limit) or []
            any_ok = True
        except Exception:
            arts = []
        arts = pit_filter_articles(arts, as_of)
        total += len(arts)
    # Heuristic threshold: many conflict-tagged articles in a short window.
    elevated = total >= max(1, limit)  # near-saturation across the terms
    return {
        "available": any_ok,
        "conflict_volume": total,
        "flag_elevated": bool(any_ok and elevated),
        "as_of": as_of.isoformat() if isinstance(as_of, _dt.date) else as_of,
        "window_days": days,
    }
