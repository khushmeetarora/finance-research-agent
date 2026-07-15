"""Live universe / index-constituent fetchers.

All sources here are free and require no API key. We always cache for 24h on
disk and fall back to the static seed lists in india.py / germany_global.py
if the live fetch fails (network outage, rate limit, etc.).

Sources:
- NSE archives CSV for NIFTY indices (https://nsearchives.nseindia.com)
- Wikipedia HTML tables for DAX 40 and S&P 500 (well-known stable convention)

The contract matches the seeds: list[(symbol, name, sector)].
"""

from __future__ import annotations

import csv
import io
from typing import Iterable

from . import cache
from . import germany_global as _de_seed
from . import india as _in_seed


_TTL_UNIVERSE = 60 * 60 * 24  # 24h
_HEADERS = {
    # NSE blocks generic UAs and Wikipedia is happier with one identifier.
    "User-Agent": "Mozilla/5.0 (compatible; fra/0.1; +https://example.com)",
    "Accept": "text/csv,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.7",
}


# ---------------------------------------------------------------------------
# NSE - NIFTY index constituents (CSV)
# ---------------------------------------------------------------------------

_NSE_INDEX_URLS = {
    "NIFTY50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY200": "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "NIFTY500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
}


def _fetch_nse_index(name: str) -> list[tuple[str, str, str]] | None:
    url = _NSE_INDEX_URLS.get(name.upper())
    if not url:
        return None
    cached = cache.get("universe_live", name, _TTL_UNIVERSE)
    if cached is not None:
        # cache stores list of [sym, name, sector] - tuple-ize.
        return [tuple(row) for row in cached]  # type: ignore[misc]
    try:
        import requests  # type: ignore

        r = requests.get(url, timeout=10, headers=_HEADERS)
        if r.status_code != 200 or not r.text:
            return None
        rows: list[tuple[str, str, str]] = []
        reader = csv.DictReader(io.StringIO(r.text))
        for raw in reader:
            sym = (raw.get("Symbol") or raw.get("SYMBOL") or "").strip()
            cname = (raw.get("Company Name") or raw.get("COMPANY NAME") or "").strip()
            sector = (raw.get("Industry") or raw.get("INDUSTRY") or "").strip()
            if sym:
                rows.append((sym, cname or sym, _gics_like(sector)))
        if rows:
            cache.put("universe_live", name, [list(r) for r in rows])
            return rows
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Wikipedia - DAX 40 + S&P 500
# ---------------------------------------------------------------------------


def _fetch_wikipedia_table(
    name: str, url: str, parser_fn
) -> list[tuple[str, str, str]] | None:
    cached = cache.get("universe_live", name, _TTL_UNIVERSE)
    if cached is not None:
        return [tuple(row) for row in cached]  # type: ignore[misc]
    try:
        import requests  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore

        r = requests.get(url, timeout=10, headers=_HEADERS)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        rows = parser_fn(soup)
        if rows:
            cache.put("universe_live", name, [list(rr) for rr in rows])
            return rows
        return None
    except Exception:
        return None


def _parse_dax(soup) -> list[tuple[str, str, str]]:
    """Parse the DAX components table from Wikipedia.

    The page exposes a table with id 'constituents'. Columns include Company,
    Ticker symbol, Prime Standard Sector. We're lenient because Wikipedia
    reorders columns occasionally.
    """
    out: list[tuple[str, str, str]] = []
    table = soup.find("table", {"id": "constituents"}) or soup.find("table", class_="wikitable")
    if not table:
        return out
    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    name_idx = _find_col(headers, ["company", "name"])
    ticker_idx = _find_col(headers, ["ticker", "symbol"])
    sector_idx = _find_col(headers, ["sector", "industry"])
    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) < 3:
            continue
        try:
            sym = cols[ticker_idx].split()[0] if ticker_idx is not None else ""
            company = cols[name_idx] if name_idx is not None else sym
            sector = cols[sector_idx] if sector_idx is not None else ""
        except IndexError:
            continue
        if sym:
            sym = _strip_known_suffix(sym)
            out.append((sym, company or sym, _gics_like(sector)))
    return out


def _parse_sp500(soup) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    table = soup.find("table", {"id": "constituents"}) or soup.find("table", class_="wikitable")
    if not table:
        return out
    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    sym_idx = _find_col(headers, ["symbol"])
    name_idx = _find_col(headers, ["security", "company"])
    sector_idx = _find_col(headers, ["gics sector", "sector"])
    for tr in table.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) < 3:
            continue
        try:
            sym = cols[sym_idx]
            name = cols[name_idx]
            sector = cols[sector_idx] if sector_idx is not None else ""
        except (IndexError, TypeError):
            continue
        if sym:
            sym = _strip_known_suffix(sym)
            out.append((sym, name or sym, _gics_like(sector)))
    return out


def _find_col(headers: list[str], candidates: Iterable[str]) -> int | None:
    for cand in candidates:
        for i, h in enumerate(headers):
            if cand in h:
                return i
    return None


def _strip_known_suffix(sym: str) -> str:
    """Strip a Yahoo-style exchange suffix (.DE, .NS, .L, etc.) so that the
    caller's profile-supplied yahoo_suffix can be appended cleanly. We only
    strip exactly-known suffixes to avoid mangling tickers that legitimately
    contain a dot (e.g. BRK.B)."""
    KNOWN = {"DE", "F", "NS", "BO", "L", "TO", "HK", "PA", "MI", "AS"}
    if "." in sym:
        base, suf = sym.rsplit(".", 1)
        if suf.upper() in KNOWN:
            return base
    return sym


def _gics_like(sector: str) -> str:
    """Best-effort normalize free-text sectors to GICS-ish labels we use."""
    if not sector:
        return ""
    s = sector.lower()
    if "tech" in s or "software" in s or "semicond" in s:
        return "Information Technology"
    if "bank" in s or "financ" in s or "insur" in s:
        return "Financials"
    if "health" in s or "pharma" in s or "biotech" in s:
        return "Health Care"
    if "energy" in s or "oil" in s or "gas" in s:
        return "Energy"
    if "consumer staple" in s or "food" in s or "beverage" in s or "fmcg" in s:
        return "Consumer Staples"
    if "consumer disc" in s or "auto" in s or "retail" in s or "apparel" in s:
        return "Consumer Discretionary"
    if "industrial" in s or "transport" in s or "aero" in s:
        return "Industrials"
    if "material" in s or "chemic" in s or "metal" in s or "mining" in s:
        return "Materials"
    if "utility" in s or "utilit" in s:
        return "Utilities"
    if "telecom" in s or "media" in s or "communicat" in s:
        return "Communication Services"
    if "real estate" in s or "reit" in s:
        return "Real Estate"
    return sector  # leave as-is


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_constituents(country: str, universe: str | None) -> list[tuple[str, str, str]]:
    """Live-fetch index constituents with seed fallback.

    Returns list of (bare_symbol, company_name, gics_like_sector). Symbol is
    the bare exchange code; the caller adds the yahoo_suffix.
    """
    universe = (universe or "").upper().strip()
    country = (country or "").upper().strip()

    if country == "IN":
        u = universe or "NIFTY500"
        rows = _fetch_nse_index(u)
        if rows:
            return rows
        return _in_seed.get_constituents(u)

    if country == "DE":
        if universe in {"", "DAX", "DAX_PLUS_MDAX", "EURO_STOXX_50"}:
            rows = _fetch_wikipedia_table(
                "DAX",
                "https://en.wikipedia.org/wiki/DAX",
                _parse_dax,
            )
            if rows:
                return rows
        return _de_seed.get_constituents(universe or "DAX_PLUS_MDAX")

    # Anything else falls through to GLOBAL_LARGE.
    if universe in {"", "GLOBAL_LARGE", "SP500", "S&P500", "SPX"}:
        rows = _fetch_wikipedia_table(
            "SP500",
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            _parse_sp500,
        )
        if rows:
            return rows
    return _de_seed.get_constituents(universe or "GLOBAL_LARGE")
