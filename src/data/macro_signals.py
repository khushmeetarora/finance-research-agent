"""Free macro / market data with point-in-time (PIT) safe access.

This is a NEW, self-contained module for the FRA V2 macro/regime overlay
(``docs/FRA_V2_MACRO.md``). It does NOT touch the scorer, the backtest, or the
existing provider - it only pulls a handful of free, no-key macro/market series
and exposes them as PIT-correct time series that ``src/factors/regime.py`` turns
into interpretable regime flags.

Design mirrors the rest of the data layer (``src/data/provider.py``):

* **Free sources only, no API key.** FRED's public no-key CSV endpoint
  (``fredgraph.csv?id=<ID>``) for rates / inflation / credit; yfinance daily
  history for crude / USD-INR / India-VIX / Nifty.
* **On-disk caching** via ``src.data.cache`` so unit tests + repeated runs never
  hammer the network.
* **Graceful failure.** Any network / parse error returns ``[]`` (a fetch) or
  ``None`` (a scalar) - never an exception - so the overlay degrades to
  "signal unavailable" instead of crashing the pipeline.

Point-in-time correctness (the whole reason this module exists) lives in the
**pure** transform functions at the bottom (``as_of_series``, ``momentum``,
``zscore`` ...). They take an already-fetched full series plus an ``as_of`` date
and a per-series ``publication_lag_days`` and return only the observations that
were *knowable* on/before ``as_of``. Because they are pure and network-free they
are the part the unit tests exercise directly with fixtures - there is no live
network in any test.

Series data model
-----------------
A "series" is a JSON-cacheable list of ``{"date": "YYYY-MM-DD", "value": float}``
dicts sorted ascending by date.
"""

from __future__ import annotations

import datetime as _dt
import io
import math
from pathlib import Path
from typing import Any

import yaml

from . import cache
from ..config import REPO_ROOT

# Cache TTLs (seconds). Macro series move slowly; a few hours is plenty and
# keeps historical backtests fully offline after the first pull.
_TTL_FRED = 60 * 60 * 12          # 12h
_TTL_YAHOO = 60 * 60 * 6          # 6h

_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"


# ---------------------------------------------------------------------------
# Configuration (free-source registry + thresholds).
# ---------------------------------------------------------------------------

# Built-in defaults kept in sync with config/macro.yaml so the module works even
# if the YAML is absent (graceful degradation).
DEFAULTS: dict[str, Any] = {
    "fred": {
        "india_repo_rate": {"id": "INTDSRINM193N", "publication_lag_days": 7},
        "india_cpi": {"id": "INDCPIALLMINMEI", "publication_lag_days": 21},
        "us_10y": {"id": "DGS10", "publication_lag_days": 1},
        "us_2y": {"id": "DGS2", "publication_lag_days": 1},
        "baa_spread": {"id": "BAA10Y", "publication_lag_days": 1},
    },
    "yahoo": {
        "crude_brent": {"ticker": "BZ=F", "publication_lag_days": 0},
        "crude_wti": {"ticker": "CL=F", "publication_lag_days": 0},
        "usdinr": {"ticker": "INR=X", "publication_lag_days": 0},
        "india_vix": {"ticker": "^INDIAVIX", "publication_lag_days": 0},
        "nifty": {"ticker": "^NSEI", "publication_lag_days": 0},
        "nifty_bank": {"ticker": "^NSEBANK", "publication_lag_days": 0},
    },
    "thresholds": {
        "rate_move_points": 0.25,
        "cpi_band": 0.06,
        "crude_spike_mom": 0.10,
        "inr_depreciation_mom": 0.02,
        "fx_stress_vol": 0.08,
        "vix_riskoff_pct": 0.80,
        "vix_riskon_pct": 0.30,
    },
    "lookbacks": {
        "rate_delta_days": 365,
        "cpi_yoy_days": 365,
        "cpi_short_days": 120,
        "crude_momentum_days": 20,
        "inr_momentum_days": 20,
        "vol_window_points": 20,
        "vix_percentile_days": 504,
        "nifty_trend_days": 252,
    },
}

_CONFIG_CACHE: dict[str, Any] | None = None


def load_macro_config(path: "str | Path | None" = None) -> dict[str, Any]:
    """Load ``config/macro.yaml`` merged over the built-in DEFAULTS.

    Missing file / parse error -> DEFAULTS (never raises). The result is cached
    in-process; pass an explicit ``path`` (e.g. in tests) to bypass the cache.
    """
    global _CONFIG_CACHE
    if path is None and _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    cfg_path = Path(path) if path is not None else REPO_ROOT / "config" / "macro.yaml"
    merged = _deep_copy(DEFAULTS)
    try:
        if cfg_path.exists():
            with cfg_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            _deep_merge(merged, loaded)
    except Exception:
        merged = _deep_copy(DEFAULTS)
    if path is None:
        _CONFIG_CACHE = merged
    return merged


def _deep_copy(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        out[k] = _deep_copy(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
    return out


def _deep_merge(base: dict, over: dict) -> None:
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Fetchers (network + cache + graceful failure). Return ascending series.
# ---------------------------------------------------------------------------


def fetch_fred_series(series_id: str, *, ttl: int = _TTL_FRED) -> list[dict[str, Any]]:
    """Download a FRED series via the free no-key CSV endpoint.

    Returns ``[{"date": "YYYY-MM-DD", "value": float}, ...]`` ascending, or
    ``[]`` on any failure. Missing observations (``"."``) are skipped.
    """
    sid = (series_id or "").strip()
    if not sid:
        return []
    cached = cache.get("macro_fred", sid, ttl)
    if cached is not None:
        return cached
    series: list[dict[str, Any]] = []
    try:
        import requests  # type: ignore

        url = _FRED_CSV.format(id=urllib_quote(sid))
        r = requests.get(url, timeout=15, headers={"User-Agent": "fra/0.1"})
        if r.status_code == 200 and r.text:
            series = _parse_fred_csv(r.text)
    except Exception:
        series = []
    cache.put("macro_fred", sid, series)
    return series


def _parse_fred_csv(text: str) -> list[dict[str, Any]]:
    """Parse FRED CSV (``DATE,<ID>`` or ``observation_date,<ID>``)."""
    import csv

    out: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return out
    for row in rows[1:]:  # skip header
        if len(row) < 2:
            continue
        d, raw = row[0].strip(), row[1].strip()
        if not d or raw in ("", "."):
            continue
        val = _to_float(raw)
        if val is None:
            continue
        out.append({"date": d, "value": val})
    out.sort(key=lambda p: p["date"])
    return out


def fetch_yahoo_series(ticker: str, *, ttl: int = _TTL_YAHOO) -> list[dict[str, Any]]:
    """Daily close series from yfinance (auto-adjusted), ascending.

    Uses the full ('max') history so historical ``as_of`` runs can reach back.
    Returns ``[]`` on any failure. yfinance is imported lazily so unit tests can
    stay fully offline.
    """
    tkr = (ticker or "").strip()
    if not tkr_ok(tkr):
        return []
    cached = cache.get("macro_yahoo", tkr, ttl)
    if cached is not None:
        return cached
    series: list[dict[str, Any]] = []
    try:
        import yfinance as yf  # type: ignore

        df = yf.Ticker(tkr).history(period="max", auto_adjust=True)
        for ts, row in df.iterrows():
            close = _to_float(row.get("Close"))
            if close is None or close <= 0:
                continue
            try:
                d = str(ts.date())
            except Exception:
                d = str(ts)[:10]
            series.append({"date": d, "value": close})
        series.sort(key=lambda p: p["date"])
    except Exception:
        series = []
    cache.put("macro_yahoo", tkr, series)
    return series


def tkr_ok(t: str) -> bool:
    return bool(t)


def urllib_quote(s: str) -> str:
    import urllib.parse

    return urllib.parse.quote(s, safe="")


# ---------------------------------------------------------------------------
# Default series provider: logical name -> full (unfiltered) series.
# ---------------------------------------------------------------------------


def default_series_provider(config: dict[str, Any] | None = None):
    """Return ``provider(name) -> series`` mapping a logical series name from
    the config (e.g. ``"india_vix"``) to its full fetched series.

    Regime code depends only on this callable, so tests inject a dict-backed
    provider and never touch the network.
    """
    cfg = config or load_macro_config()
    fred = cfg.get("fred", {})
    yahoo = cfg.get("yahoo", {})

    def _provider(name: str) -> list[dict[str, Any]]:
        if name in fred:
            return fetch_fred_series(fred[name]["id"])
        if name in yahoo:
            return fetch_yahoo_series(yahoo[name]["ticker"])
        return []

    return _provider


def publication_lag(name: str, config: dict[str, Any] | None = None) -> int:
    """Configured publication lag (days) for a logical series name (default 0)."""
    cfg = config or load_macro_config()
    for group in ("fred", "yahoo"):
        spec = (cfg.get(group, {}) or {}).get(name)
        if spec is not None:
            return int(spec.get("publication_lag_days", 0) or 0)
    return 0


def source_label(name: str, config: dict[str, Any] | None = None) -> str:
    """Human-readable free-source label for a logical series name."""
    cfg = config or load_macro_config()
    spec = (cfg.get("fred", {}) or {}).get(name)
    if spec is not None:
        return f"FRED:{spec.get('id', name)}"
    spec = (cfg.get("yahoo", {}) or {}).get(name)
    if spec is not None:
        return f"yfinance:{spec.get('ticker', name)}"
    return name


# ---------------------------------------------------------------------------
# PURE, PIT-safe transforms (the network-free, unit-tested core).
# All functions operate on ascending ``[{"date","value"}]`` series and never
# look past ``as_of`` once ``as_of_series`` has been applied.
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> _dt.date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def as_of_series(
    series: list[dict[str, Any]] | None,
    as_of: _dt.date,
    publication_lag_days: int = 0,
) -> list[dict[str, Any]]:
    """Return the subset of ``series`` knowable on/before ``as_of``.

    A point stamped with period-end date ``D`` is only *knowable* on
    ``D + publication_lag_days`` (release lag). We keep it only when that
    knowledge date ``<= as_of``. This is the single PIT gate; every downstream
    statistic is computed on the result, so no future / not-yet-released
    observation can leak into a historical regime read.
    """
    if not series:
        return []
    lag = _dt.timedelta(days=int(publication_lag_days or 0))
    out: list[dict[str, Any]] = []
    for p in series:
        d = _parse_date(str(p.get("date", "")))
        if d is None:
            continue
        if d + lag <= as_of:
            out.append({"date": p["date"], "value": p["value"]})
    out.sort(key=lambda x: x["date"])
    return out


def latest(series: list[dict[str, Any]] | None) -> float | None:
    if not series:
        return None
    return _to_float(series[-1].get("value"))


def latest_date(series: list[dict[str, Any]] | None) -> _dt.date | None:
    if not series:
        return None
    return _parse_date(str(series[-1].get("date", "")))


def _value_on_or_before(series: list[dict[str, Any]], target: _dt.date) -> float | None:
    """Last value whose date is <= ``target`` (series assumed ascending)."""
    best = None
    for p in series:
        d = _parse_date(str(p.get("date", "")))
        if d is None:
            continue
        if d <= target:
            best = _to_float(p.get("value"))
        else:
            break
    return best


def momentum(series: list[dict[str, Any]] | None, lookback_days: int) -> float | None:
    """Fractional change of the latest value vs the value ~``lookback_days`` before
    the latest date: ``(last - past) / |past|``. ``None`` if not computable.

    Date-based (not index-based) so it works for both monthly and daily series.
    """
    if not series:
        return None
    last_d = latest_date(series)
    last_v = latest(series)
    if last_d is None or last_v is None:
        return None
    past = _value_on_or_before(series, last_d - _dt.timedelta(days=lookback_days))
    if past is None or past == 0:
        return None
    return (last_v - past) / abs(past)


def delta(series: list[dict[str, Any]] | None, lookback_days: int) -> float | None:
    """Absolute change (level difference) over ``lookback_days`` - for rates/yields
    where a percentage change is not meaningful. ``None`` if not computable."""
    if not series:
        return None
    last_d = latest_date(series)
    last_v = latest(series)
    if last_d is None or last_v is None:
        return None
    past = _value_on_or_before(series, last_d - _dt.timedelta(days=lookback_days))
    if past is None:
        return None
    return last_v - past


def annualized_vol(
    series: list[dict[str, Any]] | None,
    window_points: int = 20,
    periods_per_year: int = 252,
) -> float | None:
    """Annualised stdev of simple returns over the last ``window_points`` points.

    Needs >= 3 usable points. ``None`` otherwise.
    """
    if not series:
        return None
    vals = [_to_float(p.get("value")) for p in series]
    vals = [v for v in vals if v is not None and v > 0]
    if len(vals) < 3:
        return None
    tail = vals[-(window_points + 1):] if window_points > 0 else vals
    rets = [tail[i] / tail[i - 1] - 1.0 for i in range(1, len(tail))]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def zscore(series: list[dict[str, Any]] | None, lookback_points: int) -> float | None:
    """Z-score of the latest value within the trailing ``lookback_points`` window."""
    if not series:
        return None
    vals = [_to_float(p.get("value")) for p in series]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    tail = vals[-lookback_points:] if lookback_points > 0 else vals
    if len(tail) < 3:
        return None
    mean = sum(tail) / len(tail)
    var = sum((v - mean) ** 2 for v in tail) / (len(tail) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    return (tail[-1] - mean) / sd


def percentile_rank(
    series: list[dict[str, Any]] | None, lookback_points: int
) -> float | None:
    """Percentile in [0,1] of the latest value within the trailing window
    (fraction of window observations <= the latest value)."""
    if not series:
        return None
    vals = [_to_float(p.get("value")) for p in series]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    tail = vals[-lookback_points:] if lookback_points > 0 else vals
    last = tail[-1]
    n = len(tail)
    below = sum(1 for v in tail if v <= last)
    return below / n


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f
