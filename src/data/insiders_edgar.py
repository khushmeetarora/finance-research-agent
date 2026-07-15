"""SEC EDGAR Form 4 insider-transaction fetcher (free, US tickers only).

Form 4 captures insider buys/sells. We use the EDGAR full-text search to find
recent Form 4 filings for a given ticker, then count net buys/sells over the
trailing window. The output is an `InsiderSignal` summary that the news
sentiment / fundamentals analyst can consume.

EDGAR requires a polite User-Agent ("name email") per their fair-use policy.
We default to a benign one but encourage users to set EDGAR_USER_AGENT.

Limitations:
- US tickers only. Indian (SEBI SAST) and German (BaFin) disclosures are
  separate sources with different formats - left as future work.
- We approximate net direction by parsing the filing's tag content for
  "P-Purchase" vs "S-Sale" rather than the full XML transaction breakdown
  (which would require XBRL parsing). This is a cheap-and-cheerful signal.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import cache


_TTL = 60 * 60 * 6  # 6h - filings drip in throughout the day
_BASE = "https://efts.sec.gov/LATEST/search-index"


@dataclass
class InsiderSignal:
    ticker: str
    window_days: int = 90
    n_filings: int = 0
    n_buys: int = 0
    n_sells: int = 0
    score: float = 0.0           # net = (buys - sells) / max(filings, 1) in [-1, 1]
    rationale: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "window_days": self.window_days,
            "n_filings": self.n_filings,
            "n_buys": self.n_buys,
            "n_sells": self.n_sells,
            "score": self.score,
            "rationale": self.rationale,
            "sources": list(self.sources),
        }


def _user_agent() -> str:
    return os.environ.get(
        "EDGAR_USER_AGENT", "fra-finance-research-agent contact@example.com"
    )


_BUY_HINT = re.compile(r"P[\s\-]*Purchase", re.IGNORECASE)
_SELL_HINT = re.compile(r"S[\s\-]*Sale", re.IGNORECASE)


def _us_eligible(ticker: str) -> bool:
    if not ticker or "." in ticker:
        return False  # foreign listings (.NS, .DE etc)
    return True


def get_insider_signal(ticker: str, *, window_days: int = 90) -> InsiderSignal:
    sig = InsiderSignal(ticker=ticker, window_days=window_days)
    if not _us_eligible(ticker):
        sig.rationale = "Non-US listing - EDGAR Form 4 not applicable."
        return sig

    cache_key = f"{ticker}|{window_days}"
    cached = cache.get("insiders_edgar", cache_key, _TTL)
    if cached is not None:
        s = InsiderSignal(**{k: cached[k] for k in cached if k != "sources"})
        s.sources = list(cached.get("sources") or [])
        return s

    try:
        import requests  # type: ignore

        params = {
            "q": '"Form 4"',
            "dateRange": "custom",
            "forms": "4",
            "ticker": ticker,
        }
        # EDGAR's edgar/search-index API; we keep it simple by relying on the
        # UI-facing JSON endpoint.
        url = "https://efts.sec.gov/LATEST/search-index?" + "&".join(
            f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()
        )
        r = requests.get(url, timeout=10, headers={"User-Agent": _user_agent()})
        if r.status_code != 200:
            cache.put("insiders_edgar", cache_key, sig.to_dict())
            return sig
        data = r.json()
        hits = (data.get("hits") or {}).get("hits") or []
        sig.sources.append("edgar")
        sig.n_filings = len(hits)
        for h in hits:
            blob = (h.get("_source") or {})
            txt = " ".join(str(v) for v in blob.values() if isinstance(v, (str, int)))
            if _BUY_HINT.search(txt):
                sig.n_buys += 1
            elif _SELL_HINT.search(txt):
                sig.n_sells += 1
        denom = max(sig.n_buys + sig.n_sells, 1)
        sig.score = (sig.n_buys - sig.n_sells) / denom
        if sig.n_filings == 0:
            sig.rationale = "No Form 4 filings found in window."
        else:
            sig.rationale = (
                f"Trailing {window_days}d Form 4 filings: "
                f"{sig.n_buys} buys vs {sig.n_sells} sales "
                f"(net score {sig.score:+.2f})."
            )
    except Exception as e:
        sig.rationale = f"EDGAR fetch failed: {type(e).__name__}"
    cache.put("insiders_edgar", cache_key, sig.to_dict())
    return sig
