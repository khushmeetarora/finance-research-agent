"""Deep-history free fundamentals from screener.in (multibagger PIT unlock).

screener.in publishes ~10-12 years of annual P&L / Balance-Sheet / Cash-Flow
line items on each company's public page - far deeper than yfinance's ~4-5
recent fiscal years. That depth is the single biggest free-data unlock for a
genuine point-in-time (PIT) historical backtest of the multibagger scorer
(see ``docs/FRA_V2_RESEARCH.md`` sec 1/3.2 and ``docs/FRA_V2_AUDIT.md`` C-1).

Design goals (mirrors ``src/data/provider.py``):
- **Same output shape as** ``DataProvider.get_financials`` so the existing
  ``enrich_snapshot_with_financials`` + ``src/backtest/asof.py`` gate can consume
  it with zero changes:
    {income, balance, cashflow, income_periods, balance_periods,
     cashflow_periods, status, source}
- **Aggressive on-disk cache** under ``data/_screener_cache`` (like
  ``data/_price_cache``); statements barely change so the TTL is long.
- **Polite**: a real desktop User-Agent, a global minimum request interval, and
  ret/backoff on transient errors. Low volume (~136 names) + cache => gentle.
- **Robust HTML parsing** tolerant of layout drift (regex table extraction,
  case/space-insensitive row matching, exact period-ends from ``data-date-key``
  with a "Mon YYYY" fallback).
- **Graceful failure**: every path returns a status dict, never raises.

Important honesty caveats (documented, not hidden):
- screener numbers are **restated** (latest vintage), not as-first-reported, so
  even after the as-of reporting-lag gate a residual restatement bias remains
  (``docs/FRA_V2_RESEARCH.md`` sec 3.4 / sec 6). This is a *restated-vintage
  upper bound*, and it is still a large honesty improvement over yfinance which
  cannot reconstruct pre-run fundamentals at all.
- the public page carries only raw *summary* schedules; a few granular lines
  (COGS/Gross Profit, receivables/inventory/payables, cash split) live in
  AJAX-only sub-schedules and are therefore left absent -> the ratios that need
  them (gross profitability, working-capital days, Beneish) degrade to ``None``
  rather than being faked. Capital-employed for ROCE is reconstructed as
  Equity + Borrowings (a standard, defensible convention) and free cash flow is
  taken from screener's own FCF row.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
import time
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
_CACHE_DIR = REPO_ROOT / "data" / "_screener_cache"
_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days; statements are near-static

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BASE_URL = "https://www.screener.in/company/{sym}/{variant}"

# Politeness: a global minimum interval between *network* fetches, plus bounded
# retries with exponential backoff on transient failures.
_MIN_INTERVAL_S = 3.0
_last_request_ts = [0.0]
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 5.0
_TIMEOUT_S = 25


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def screener_symbol(ticker: str) -> str:
    """Map an FRA/yfinance ticker to a screener company symbol.

    ``TITAN.NS`` -> ``TITAN``; ``500114.BO`` -> ``500114``; ``INFY`` -> ``INFY``.
    """
    t = (ticker or "").strip().upper()
    for suf in (".NS", ".BO", ".NSE", ".BSE"):
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    return t


_LOCAL_DIR = REPO_ROOT / "data" / "_manual_financials"


def get_local_financials(ticker: str) -> dict[str, Any]:
    """Load a normalized statement bundle for ``ticker`` from a local, human-
    curated FREE-source store (``data/_manual_financials/<sym>.json``).

    This is the honest, TOS-clean fallback for the pre-~FY2015 statements that
    NO free *structured* feed reliably serves: screener's free depth stops
    ~FY2015 for March-end filers, and BSE/NSE XBRL is gappy and rate/TOS-limited
    (see ``docs/FRA_V2_RESEARCH.md`` 1 & 3.2). A researcher can transcribe a
    company's OWN freely-published annual-report P&L / Balance-Sheet / Cash-Flow
    into the ``get_financials`` dict shape and drop it here; this loader
    normalizes it, attributes ``source = "local_manual"``, and NEVER fabricates
    anything. The directory is **empty by default**, so determinacy is never
    manufactured - it only ever unlocks names a human has actually entered.

    Returns the standard bundle (status ``failed`` when no file / unparseable).
    """
    sym = screener_symbol(ticker)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sym)
    path = _LOCAL_DIR / f"{safe}.json"
    if not path.exists():
        return _empty("failed", source="local_absent")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty("failed", source="local_unparseable")

    out: dict[str, Any] = {
        "income": _coerce_items(raw.get("income")),
        "balance": _coerce_items(raw.get("balance")),
        "cashflow": _coerce_items(raw.get("cashflow")),
        "income_periods": list(raw.get("income_periods") or []),
        "balance_periods": list(raw.get("balance_periods") or []),
        "cashflow_periods": list(raw.get("cashflow_periods") or []),
        "source": "local_manual",
    }
    n = _period_count(out)
    out["status"] = "failed" if n == 0 else ("shallow" if n < 3 else "ok")
    return out


def _coerce_items(items: Any) -> dict[str, list[float | None]]:
    """Coerce a JSON {line: [values...]} map to float|None lists (never raise)."""
    if not isinstance(items, dict):
        return {}
    out: dict[str, list[float | None]] = {}
    for key, series in items.items():
        if not isinstance(series, (list, tuple)):
            continue
        vals: list[float | None] = []
        for v in series:
            try:
                vals.append(float(v) if v is not None else None)
            except (TypeError, ValueError):
                vals.append(None)
        out[str(key)] = vals
    return out


def get_screener_financials(
    ticker: str,
    *,
    prefer_consolidated: bool = True,
    use_cache: bool = True,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Fetch ~10y annual statements for ``ticker`` from screener.in.

    Returns the same dict shape as ``DataProvider.get_financials`` plus a
    ``source`` key. ``status`` is ``ok`` (>=3 periods), ``shallow`` (1-2), or
    ``failed`` (nothing / network off). Never raises.
    """
    sym = screener_symbol(ticker)
    if use_cache:
        cached = _cache_get(sym)
        if cached is not None:
            return cached

    if not allow_network:
        return _empty("failed", source="screener_no_network")

    variants = ["consolidated/", ""] if prefer_consolidated else ["", "consolidated/"]
    result: dict[str, Any] | None = None
    best_periods = -1
    for variant in variants:
        html = _fetch_html(sym, variant)
        if not html:
            continue
        parsed = parse_statements_html(html)
        parsed["source"] = (
            "screener_consolidated" if variant == "consolidated/" else "screener_standalone"
        )
        n = _period_count(parsed)
        # Best-of-variants: keep whichever variant yields the DEEPER usable
        # history (more admissible annual periods). This matters because some
        # names file a rich consolidated set but a thin standalone one (or vice
        # versa); the previous "first non-failed wins" rule could lock onto the
        # shallower variant and needlessly cap PIT determinacy. We still short-
        # circuit once a clearly-deep (>=3y) preferred variant is found so we do
        # not always pay for the second fetch.
        if n > best_periods:
            best_periods = n
            result = parsed
        if variant == variants[0] and n >= 3:
            break

    if result is None:
        result = _empty("failed", source="screener_unreachable")

    if use_cache:
        _cache_put(sym, result)
    return result


def _period_count(fin: dict[str, Any]) -> int:
    """Max admissible annual periods across the three statements (0 = failed)."""
    return max(
        len(fin.get("income_periods") or []),
        len(fin.get("balance_periods") or []),
        len(fin.get("cashflow_periods") or []),
    )


# --------------------------------------------------------------------------
# HTML parsing (pure; unit-testable offline)
# --------------------------------------------------------------------------
def parse_statements_html(html: str) -> dict[str, Any]:
    """Parse a screener company page into the ``get_financials`` dict shape.

    Pure function (no network) so it can be unit-tested with a saved fixture.
    Tolerant of missing sections / rows: anything absent stays empty/None.
    """
    if not html:
        return _empty("failed", source="screener_empty_html")

    pl = _parse_section(html, "profit-loss")
    bs = _parse_section(html, "balance-sheet")
    cf = _parse_section(html, "cash-flow")

    income = _normalize_income(pl)
    balance = _normalize_balance(bs)
    cashflow = _normalize_cashflow(cf, pl)

    out: dict[str, Any] = {
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "income_periods": pl.get("periods", []),
        "balance_periods": bs.get("periods", []),
        "cashflow_periods": cf.get("periods", []),
    }
    n = max(
        len(out["income_periods"]),
        len(out["balance_periods"]),
        len(out["cashflow_periods"]),
    )
    if n == 0:
        out["status"] = "failed"
    elif n < 3:
        out["status"] = "shallow"
    else:
        out["status"] = "ok"
    return out


def _parse_section(html: str, section_id: str) -> dict[str, Any]:
    """Extract {periods:[iso...], items:{normkey:[float|None...]}} for a section.

    Locates the section by id, takes its first ``<table>``, reads column
    period-ends from the header (``data-date-key`` preferred, else "Mon YYYY"),
    and maps each body row's cells to those columns. A trailing non-dated
    column (e.g. "TTM") is dropped so periods stay date-anchored.
    """
    table = _extract_first_table(html, section_id)
    if not table:
        return {"periods": [], "items": {}}

    head_m = re.search(r"<thead[^>]*>(.*?)</thead>", table, re.S | re.I)
    thead = head_m.group(1) if head_m else table
    ths = re.findall(r"<th\b[^>]*>(.*?)</th>", thead, re.S | re.I)
    th_attrs = re.findall(r"<th\b([^>]*)>(.*?)</th>", thead, re.S | re.I)

    # Build the column period list, skipping the first (label) column.
    periods: list[str] = []
    keep_cols: list[int] = []  # value-column indices (0-based over value cells)
    val_idx = -1
    for attrs, inner in th_attrs:
        text = _strip_tags(inner)
        if _is_label_header(attrs, text):
            continue  # the empty leading label column
        val_idx += 1
        iso = _header_to_iso(attrs, text)
        if iso is None:
            continue  # e.g. a "TTM" / non-dated trailing column -> drop
        periods.append(iso)
        keep_cols.append(val_idx)

    body_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", table, re.S | re.I)
    tbody = body_m.group(1) if body_m else table
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbody, re.S | re.I)

    items: dict[str, list[float | None]] = {}
    for row in rows:
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) < 2:
            continue
        label = _norm_label(_strip_tags(cells[0]))
        if not label:
            continue
        values_all = [_num(_strip_tags(c)) for c in cells[1:]]
        # Align kept columns; tolerate short rows.
        vals = [values_all[i] if i < len(values_all) else None for i in keep_cols]
        items[label] = vals
    return {"periods": periods, "items": items}


# --------------------------------------------------------------------------
# Normalization to canonical line-item names (recognised by provider._pick)
# --------------------------------------------------------------------------
def _normalize_income(pl: dict[str, Any]) -> dict[str, list[float | None]]:
    it = pl.get("items", {})
    n = len(pl.get("periods", []))
    if n == 0:
        return {}
    sales = _row(
        it, n, "sales", "revenue", "totalrevenue", "sales+", "revenue+",
        "revenuefromoperations", "netsales", "totalincome", "income",
        "salesrevenue",
    )
    op = _row(it, n, "operatingprofit", "operatingprofit+", "operatingprofitebitda",
              "ebitda")
    other = _row(it, n, "otherincome", "otherincome+")
    interest = _row(it, n, "interest", "interest+", "financecost", "financecosts",
                    "interestexpense")
    dep = _row(it, n, "depreciation", "depreciation+", "depreciationamortisation",
               "depreciationandamortisation")
    net = _row(it, n, "netprofit", "netprofit+", "profitaftertax", "pat",
               "profitfortheyear", "profitfortheperiod", "consolidatedprofit",
               "netprofitfortheperiod")
    eps = _row(it, n, "epsinrs", "eps", "adjustedepsinrs", "basiceps", "epsrs",
               "basicepsrs")

    # Operating EBIT (excludes non-operating income; honours spec sec 3.2 / M-1):
    #   Operating Income = Operating Profit (EBITDA) - Depreciation
    operating_income = _combine(op, dep, lambda a, b: a - (b or 0.0))
    # True EBIT (includes non-operating income) for interest coverage / Altman X3:
    #   EBIT = Operating Profit - Depreciation + Other Income
    ebit = _combine(operating_income, other, lambda a, b: a + (b or 0.0))

    out: dict[str, list[float | None]] = {}
    _put(out, "Total Revenue", sales)
    _put(out, "Operating Income", operating_income)
    _put(out, "EBIT", ebit)
    _put(out, "Net Income", net)
    _put(out, "Interest Expense", interest)
    _put(out, "Reconciled Depreciation", dep)
    _put(out, "Diluted EPS", eps)
    return out


def _normalize_balance(bs: dict[str, Any]) -> dict[str, list[float | None]]:
    it = bs.get("items", {})
    n = len(bs.get("periods", []))
    if n == 0:
        return {}
    eq_cap = _row(it, n, "equitycapital", "sharecapital", "equitysharecapital")
    reserves = _row(it, n, "reserves", "reservesandsurplus", "otherequity")
    borrow = _row(it, n, "borrowings", "borrowings+", "totalborrowings", "debt")
    other_liab = _row(it, n, "otherliabilities", "otherliabilities+")
    total_assets = _row(it, n, "totalassets", "totalasset")
    fixed = _row(it, n, "fixedassets", "fixedassets+", "netblock",
                 "propertyplantandequipment", "netfixedassets")
    other_assets = _row(it, n, "otherassets", "otherassets+")

    equity = _combine(eq_cap, reserves, lambda a, b: a + (b or 0.0))
    # Capital-employed convention: TA - "Current Liabilities" == Equity+Borrowings.
    # screener's "Other Liabilities" == Total Assets - Equity - Borrowings, so
    # mapping it to Current Liabilities makes the enrichment ROCE denominator
    # (total_assets - current_liabilities) equal Equity + Borrowings (a standard
    # capital-employed definition). See module docstring.
    total_liab = _combine(borrow, other_liab, lambda a, b: a + (b or 0.0))

    out: dict[str, list[float | None]] = {}
    _put(out, "Total Assets", total_assets)
    _put(out, "Current Liabilities", other_liab)
    _put(out, "Current Assets", other_assets)  # approx (excl. fixed/CWIP/invest)
    _put(out, "Stockholders Equity", equity)
    _put(out, "Retained Earnings", reserves)
    _put(out, "Total Debt", borrow)
    _put(out, "Long Term Debt", borrow)
    _put(out, "Total Liabilities Net Minority Interest", total_liab)
    _put(out, "Net PPE", fixed)
    return out


def _normalize_cashflow(
    cf: dict[str, Any], pl: dict[str, Any]
) -> dict[str, list[float | None]]:
    it = cf.get("items", {})
    n = len(cf.get("periods", []))
    if n == 0:
        return {}
    cfo = _row(it, n, "cashfromoperatingactivity", "cashfromoperatingactivity+",
               "netcashfromoperatingactivities", "netcashflowfromoperatingactivities",
               "cashgeneratedfromoperations", "cashflowfromoperations",
               "netcashgeneratedfromoperatingactivities", "cashfromoperations")
    fcf = _row(it, n, "freecashflow", "fcf", "freecashflow+")
    # screener FCF == CFO - Capex  =>  Capex == CFO - FCF. Store capex negative
    # (yfinance convention) so enrichment's ``CFO - |capex|`` reproduces FCF.
    capex = _combine(cfo, fcf, lambda a, b: -(a - b))

    out: dict[str, list[float | None]] = {}
    _put(out, "Operating Cash Flow", cfo)
    _put(out, "Capital Expenditure", capex)
    return out


# --------------------------------------------------------------------------
# HTML helpers
# --------------------------------------------------------------------------
def _extract_first_table(html: str, section_id: str) -> str | None:
    i = html.find('id="%s"' % section_id)
    if i < 0:
        # tolerate single quotes / attribute ordering drift
        m = re.search(r"id=['\"]%s['\"]" % re.escape(section_id), html)
        if not m:
            return None
        i = m.start()
    j = html.find("<table", i)
    if j < 0:
        return None
    k = html.find("</table>", j)
    if k < 0:
        return None
    return html[j : k + len("</table>")]


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    # Decode HTML entities (numeric &#8722; minus, &nbsp;, &amp;, ...) so the
    # downstream label/number matchers see real characters, not raw entities.
    s = _html.unescape(s)
    s = s.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _norm_label(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("+", "").replace("%", "%")  # keep % so we can distinguish ratio rows
    t = re.sub(r"[^a-z0-9%/]", "", t)
    return t


def _is_label_header(attrs: str, text: str) -> bool:
    # The leading label column carries class="text" and no date-key / no text.
    if "data-date-key" in attrs:
        return False
    if _header_to_iso(attrs, text) is not None:
        return False
    return text == "" or 'class="text"' in attrs


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _header_to_iso(attrs: str, text: str) -> str | None:
    m = re.search(r'data-date-key="([0-9]{4}-[0-9]{2}-[0-9]{2})"', attrs)
    if m:
        return m.group(1)
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})$", (text or "").strip())
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            return "%s-%02d-%02d" % (m.group(2), mon, _MONTH_END[mon])
    return None


def _num(s: str) -> float | None:
    if s is None:
        return None
    # Normalise thousands separators and the various unicode minus glyphs
    # screener/Indian pages use (figure-dash / en-dash / true minus sign).
    s = (
        s.strip()
        .replace(",", "")
        .replace("\u2212", "-")   # MINUS SIGN
        .replace("\u2013", "-")   # EN DASH used as a sign
        .replace("\u2014", "-")   # EM DASH used as a sign
    )
    if s in ("", "-", "—", "–"):
        return None
    if s.endswith("%"):
        return None  # ratio rows (OPM%, Tax%, ...) are not raw statement lines
    # Accounting-style negatives, e.g. "(1,234)" -> -1234.
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


# --------------------------------------------------------------------------
# Series helpers
# --------------------------------------------------------------------------
def _row(items: dict[str, list], n: int, *aliases: str) -> list[float | None]:
    for a in aliases:
        key = a.lower().replace(" ", "")
        if key in items:
            v = list(items[key])
            if len(v) < n:
                v = v + [None] * (n - len(v))
            return v[:n]
    return [None] * n


def _combine(a: list, b: list, fn) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(a)):
        av = a[i]
        bv = b[i] if i < len(b) else None
        if av is None:
            out.append(None)
        else:
            try:
                out.append(fn(av, bv))
            except (TypeError, ValueError):
                out.append(None)
    return out


def _put(out: dict, key: str, series: list[float | None]) -> None:
    if any(v is not None for v in series):
        out[key] = series


def _empty(status: str, *, source: str) -> dict[str, Any]:
    return {
        "income": {}, "balance": {}, "cashflow": {},
        "income_periods": [], "balance_periods": [], "cashflow_periods": [],
        "status": status, "source": source,
    }


# --------------------------------------------------------------------------
# Network + on-disk cache
# --------------------------------------------------------------------------
def _cache_path(sym: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sym)
    return _CACHE_DIR / f"{safe}.json"


def _cache_get(sym: str) -> dict[str, Any] | None:
    path = _cache_path(sym)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - payload.get("_ts", 0) > _TTL_SECONDS:
        return None
    return payload.get("value")


def _cache_put(sym: str, value: dict[str, Any]) -> None:
    path = _cache_path(sym)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"_ts": time.time(), "value": value}, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        pass


def _rate_limit() -> None:
    dt = time.time() - _last_request_ts[0]
    if dt < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - dt)
    _last_request_ts[0] = time.time()


def _fetch_html(sym: str, variant: str) -> str | None:
    """GET a screener company page with politeness + retry/backoff. None on fail."""
    try:
        import requests  # lazy: keep import cost out of unit tests
    except Exception:
        return None
    url = _BASE_URL.format(sym=sym, variant=variant)
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    for attempt in range(_MAX_RETRIES):
        _rate_limit()
        try:
            r = requests.get(url, headers=headers, timeout=_TIMEOUT_S)
        except Exception:
            time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
            continue
        if r.status_code == 200 and r.text:
            return r.text
        if r.status_code in (404, 403):
            return None  # not found / forbidden for this variant - don't retry
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
            continue
        return None
    return None
