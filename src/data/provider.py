"""Free-data provider abstraction backed by yfinance.

Design goals:
- Single provider interface used by agents and the factor engine.
- All numerical values come from real APIs - LLMs never invent them.
- Aggressive on-disk caching with TTLs (price/news short, fundamentals longer).
- Graceful fallbacks: missing fields return None, never crash the pipeline.

The provider is deliberately thin - swap to MCP servers or paid APIs by
implementing the same interface.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import cache

# yfinance is heavy and chatty; import lazily so unit tests can mock it.
_yf = None


def _yf_module():
    global _yf
    if _yf is None:
        import yfinance as yf  # type: ignore

        _yf = yf
    return _yf


# Cache TTLs (seconds)
_TTL_QUOTE = 60 * 15           # 15m
_TTL_HISTORY = 60 * 60 * 6     # 6h - daily history is intraday-stable
_TTL_FUNDAMENTALS = 60 * 60 * 24  # 24h
_TTL_NEWS = 60 * 30            # 30m


@dataclass
class CompanySnapshot:
    """Minimal cross-market snapshot used by factor engine + analysts."""

    ticker: str
    name: str | None = None
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    market_cap: float | None = None
    price: float | None = None
    # Income statement / valuation
    pe_trailing: float | None = None
    pe_forward: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_to_ebitda: float | None = None
    ev_to_revenue: float | None = None
    earnings_yield: float | None = None       # 1 / pe_trailing when available
    fcf_yield: float | None = None
    dividend_yield: float | None = None
    # Quality
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    # Health
    debt_to_equity: float | None = None
    net_debt_to_ebitda: float | None = None
    current_ratio: float | None = None
    interest_coverage: float | None = None
    # Earnings quality
    cash_conversion: float | None = None      # (op cash flow) / net income
    accruals_ratio: float | None = None       # (NI - CFO) / total assets
    # Growth
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    # Momentum (computed from price history)
    momentum_12_1: float | None = None        # 12-month return excluding last month
    momentum_6_1: float | None = None
    volatility_annualized: float | None = None
    # Misc
    beta: float | None = None

    # ------------------------------------------------------------------
    # Tier-B statement-derived fields (multibagger variant).
    # Populated by get_financials() + enrich_snapshot_with_financials().
    # All default to None/empty so the classic v1 path is unaffected.
    # ------------------------------------------------------------------
    roce: float | None = None                  # EBIT / (total assets - current liab)
    roce_via_proxy: bool = False               # True if fell back to EBITDA proxy
    gross_profitability: float | None = None   # (revenue - COGS) / total assets
    fcf: float | None = None                   # latest CFO - Capex
    fcf_posrate: float | None = None           # fraction of years FCF > 0
    fcf_neg_years: int | None = None           # count of years FCF < 0 in window
    ocf_to_np_multiyear: float | None = None   # cum(CFO) / cum(NP) over window
    beneish_m: float | None = None             # Beneish M-score (t vs t-1)
    altman_z: float | None = None              # Altman Z"-EM
    peg: float | None = None                   # PE_trailing / (100 * g5)
    earnings_cagr: float | None = None         # multi-year EPS/NI CAGR (decimal)
    capex_intensity: float | None = None       # |capex| / revenue
    asset_turnover: float | None = None        # revenue / total assets (DuPont)
    shareholder_yield: float | None = None      # (dividends + buybacks) / market cap
    # Working-capital days (latest) + deltas over the available window.
    dso: float | None = None
    dio: float | None = None
    dpo: float | None = None
    ccc: float | None = None
    dso_delta: float | None = None
    dio_delta: float | None = None
    dpo_delta: float | None = None
    ccc_delta: float | None = None
    # Red-flag helper flags derived from the statement series.
    is_financial: bool = False
    debt_rising: bool | None = None            # total debt rising over window
    net_debt_ebitda_rising: bool | None = None  # net-debt/EBITDA rising (RF5)
    cfo_np_falling: bool | None = None         # CFO/NP ratio falling over window
    cfo_np_below_half_streak: int | None = None  # max consecutive yrs CFO/NI<0.5 (RF2)
    cum_np_nonpositive: bool | None = None     # cumulative net profit <= 0 over window (RF2)
    price_cagr: float | None = None            # multi-year price CAGR (RF8 re-rating proxy)
    # Multi-year series (chronological ascending: oldest .. latest).
    roce_series: list[float] = field(default_factory=list)
    roe_series: list[float] = field(default_factory=list)
    gross_margin_series: list[float] = field(default_factory=list)
    operating_margin_series: list[float] = field(default_factory=list)
    revenue_series: list[float] = field(default_factory=list)
    net_income_series: list[float] = field(default_factory=list)
    cfo_series: list[float] = field(default_factory=list)
    fcf_series: list[float] = field(default_factory=list)
    financials_periods: list[str] = field(default_factory=list)
    financials_status: str = "absent"          # absent|ok|shallow|failed
    # Tier-C manual overrides (never fabricated; None => treated as neutral).
    promoter_pledge_pct: float | None = None
    promoter_holding_trend: float | None = None
    auditor_red_flag: bool | None = None

    raw: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Data quality / multi-source bookkeeping
    # ------------------------------------------------------------------
    fetch_status: str = "ok"             # "ok" | "partial" | "failed"
    data_sources: list[str] = field(default_factory=list)
    # per-field disagreement (relative diff) between the primary source
    # (yfinance) and any secondary source (e.g. stooq) where comparable.
    field_disagreements: dict[str, float] = field(default_factory=dict)
    # Aggregate agreement in [0..1]; 1.0 = perfect agreement, 0.0 = total
    # mismatch or no secondary source available.
    data_agreement: float | None = None
    # FX exposure: is the ticker's currency different from the user's
    # profile currency? Set by the quant node after profile is known.
    is_cross_currency: bool = False
    # Trailing FX volatility (annualised) for cross-currency picks.
    fx_volatility_annualized: float | None = None


class DataProvider:
    """yfinance-backed free data provider with on-disk caching.

    Optionally cross-checks price-level fields against Stooq (free, no key)
    to compute a per-ticker `data_agreement` score in [0, 1].
    """

    def __init__(self, polite_sleep_s: float = 0.0, use_stooq: bool = True):
        self._sleep = polite_sleep_s
        self._use_stooq = use_stooq

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _info(self, ticker: str) -> dict[str, Any]:
        cached = cache.get("info", ticker, _TTL_FUNDAMENTALS)
        if cached is not None:
            return cached
        try:
            yf = _yf_module()
            t = yf.Ticker(ticker)
            try:
                info = t.get_info()  # newer yfinance
            except AttributeError:
                info = t.info  # older
            info = {k: v for k, v in (info or {}).items() if _json_safe(v)}
        except Exception as e:  # network errors, ticker not found, etc.
            info = {"_error": str(e)}
        cache.put("info", ticker, info)
        if self._sleep:
            time.sleep(self._sleep)
        return info

    def _history_csv(self, ticker: str, period: str = "2y") -> list[dict[str, Any]]:
        """Daily OHLCV as a list of dicts (JSON-cacheable)."""
        key = f"{ticker}|{period}"
        cached = cache.get("history", key, _TTL_HISTORY)
        if cached is not None:
            return cached
        try:
            yf = _yf_module()
            df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            rows: list[dict[str, Any]] = []
            for ts, row in df.iterrows():
                rows.append(
                    {
                        "date": str(ts.date()),
                        "open": float(row.get("Open", 0.0) or 0.0),
                        "high": float(row.get("High", 0.0) or 0.0),
                        "low": float(row.get("Low", 0.0) or 0.0),
                        "close": float(row.get("Close", 0.0) or 0.0),
                        "volume": float(row.get("Volume", 0.0) or 0.0),
                    }
                )
        except Exception:
            rows = []
        cache.put("history", key, rows)
        if self._sleep:
            time.sleep(self._sleep)
        return rows

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_history(self, ticker: str, period: str = "2y") -> list[dict[str, Any]]:
        return self._history_csv(ticker, period=period)

    def get_financials(
        self,
        ticker: str,
        as_of: "date | None" = None,
        *,
        prefer_deep: bool = True,
    ) -> dict[str, Any]:
        """Fetch annual financial statements (income / balance / cash flow).

        Returns a JSON-cacheable dict:
            {
              "income":   {line_item: [oldest..latest]},
              "balance":  {line_item: [oldest..latest]},
              "cashflow": {line_item: [oldest..latest]},
              "income_periods":   [date str ascending],
              "balance_periods":  [...],
              "cashflow_periods": [...],
              "status": "ok" | "shallow" | "failed",
            }

        yfinance typically returns ~4 annual periods; we degrade gracefully to
        "shallow" when < 3 periods and "failed" when nothing is retrievable.
        Cached with the fundamentals TTL (24h) like the rest of the provider.

        Point-in-time (audit C-1): when ``as_of`` is supplied the method
        (1) prefers the deep free source (screener.in, ~10y annual statements)
        so pre-run fundamentals are actually reconstructable, falling back to
        yfinance when screener is unavailable; and (2) drops every fiscal period
        whose period-end + a ~90-day reporting lag is after ``as_of`` (via the
        audited ``src.backtest.asof.as_of_financials`` gate), so no future or
        not-yet-reported statement can leak. ``as_of=None`` is the default and
        preserves the exact classic/live behaviour (yfinance only, no gating),
        so existing callers and tests are unaffected.
        """
        if as_of is not None:
            return self._get_financials_asof(ticker, as_of, prefer_deep=prefer_deep)
        return self._yfinance_financials(ticker)

    def _get_financials_asof(
        self, ticker: str, as_of: "date", *, prefer_deep: bool = True
    ) -> dict[str, Any]:
        """Deep-source-preferred, point-in-time-gated statements for ``as_of``.

        Source preference (deepest / most authoritative first):
          1. a local human-curated free-source store (``data/_manual_financials``;
             empty by default - the honest fallback for pre-~FY2015 statements no
             free scraper serves; see ``screener.get_local_financials``);
          2. screener.in's ~10-12y annual statements (the main free deep source);
          3. yfinance's shallow ~4-5y window.
        All three share the identical ``get_financials`` dict shape, so the
        downstream PIT gate + enrichment consume any of them unchanged.
        """
        base: dict[str, Any] | None = None
        if prefer_deep:
            try:
                from . import screener  # lazy: keep requests import out of hot path

                local = screener.get_local_financials(ticker)
                if local and local.get("status") != "failed":
                    base = local
                if base is None:
                    deep = screener.get_screener_financials(ticker)
                    if deep and deep.get("status") != "failed":
                        base = deep
            except Exception:
                base = None
        if base is None:
            base = self._yfinance_financials(ticker)
        source = base.get("source", "yfinance")

        # Audited PIT gate (drop periods reportable only after as_of).
        from ..backtest.asof import as_of_financials  # lazy to avoid import cycle

        gated = as_of_financials(base, as_of)
        gated["source"] = source
        return gated

    def _yfinance_financials(self, ticker: str) -> dict[str, Any]:
        """Original yfinance-backed statement fetch (classic path, cached 24h)."""
        cached = cache.get("financials", ticker, _TTL_FUNDAMENTALS)
        if cached is not None:
            return cached
        out: dict[str, Any] = {
            "income": {}, "balance": {}, "cashflow": {},
            "income_periods": [], "balance_periods": [], "cashflow_periods": [],
            "status": "failed",
        }
        try:
            yf = _yf_module()
            t = yf.Ticker(ticker)
            inc = _df_to_series_map(_safe_stmt(t, "income_stmt"))
            bal = _df_to_series_map(_safe_stmt(t, "balance_sheet"))
            cf = _df_to_series_map(_safe_stmt(t, "cashflow"))
            out["income"] = inc["items"]
            out["balance"] = bal["items"]
            out["cashflow"] = cf["items"]
            out["income_periods"] = inc["periods"]
            out["balance_periods"] = bal["periods"]
            out["cashflow_periods"] = cf["periods"]
            n = max(len(inc["periods"]), len(bal["periods"]), len(cf["periods"]))
            if n == 0:
                out["status"] = "failed"
            elif n < 3:
                out["status"] = "shallow"
            else:
                out["status"] = "ok"
        except Exception as e:  # network / parsing / API drift
            out["status"] = "failed"
            out["_error"] = str(e)
        cache.put("financials", ticker, out)
        if self._sleep:
            time.sleep(self._sleep)
        return out

    def get_snapshot_enriched(
        self,
        ticker: str,
        manual: dict[str, Any] | None = None,
        as_of: "date | None" = None,
    ) -> CompanySnapshot:
        """Like get_snapshot() but also fetches statements and populates the
        Tier-B multibagger fields. Used by the multibagger scoring variant.

        When ``as_of`` is supplied the snapshot is built **point-in-time**
        (audit C-1): deep screener statements gated to ``as_of``, live ``.info``
        TTM valuation/quality discarded, and valuation/momentum reconstructed
        from the as-of price and as-of trailing EPS. ``as_of=None`` (default) is
        the unchanged live path.
        """
        if as_of is not None:
            return self._get_snapshot_enriched_asof(ticker, as_of, manual=manual)
        snap = self.get_snapshot(ticker)
        fin = self.get_financials(ticker)
        enrich_snapshot_with_financials(snap, fin, manual=manual)
        # RF8 re-rating proxy: a multi-year price CAGR, compared against the
        # earnings CAGR in the veto pass. This is the closest free-data proxy for
        # a genuine PE path (see RF8 note in run_veto_pass). Best-effort only.
        try:
            rows = self._history_csv(ticker, period="5y")
            closes = [r["close"] for r in rows if r.get("close", 0) > 0]
            if len(closes) >= 252 * 2:  # need a few years to be meaningful
                yrs = len(closes) / 252.0
                first, last = closes[0], closes[-1]
                if first > 0 and last > 0 and yrs >= 1.0:
                    snap.price_cagr = (last / first) ** (1.0 / yrs) - 1.0
        except Exception:
            pass
        return snap

    def _get_snapshot_enriched_asof(
        self, ticker: str, as_of: "date", manual: dict[str, Any] | None = None
    ) -> CompanySnapshot:
        """Point-in-time enriched snapshot (audit C-1) for the live/backtest path.

        Identity comes from the base snapshot; ALL live valuation/quality is
        discarded. Statements are the deep (screener-preferred) source gated to
        ``as_of``; valuation is rebuilt from the as-of price x as-of trailing
        EPS; momentum from the as-of price series. When no admissible pre-as_of
        statement exists the snapshot is returned with ``financials_status`` !=
        ``ok`` so the caller can mark the name INDETERMINATE rather than guess.
        """
        from ..backtest.asof import build_asof_snapshot  # lazy (import cycle)

        base = self.get_snapshot(ticker)
        fin = self.get_financials(ticker, as_of=as_of)

        # As-of price + trailing EPS (latest admissible income period).
        asof_price = self._price_as_of(ticker, as_of)
        asof_eps = None
        eps_series = (fin.get("income", {}) or {}).get("Diluted EPS") or (
            fin.get("income", {}) or {}
        ).get("Basic EPS")
        if eps_series:
            for v in reversed(eps_series):
                if v is not None:
                    asof_eps = v
                    break
        m12, m6 = self._momentum_as_of(ticker, as_of)
        snap = build_asof_snapshot(
            base, fin, asof_price=asof_price, asof_eps=asof_eps,
            momentum_12_1=m12, momentum_6_1=m6, manual=manual,
        )
        snap.data_sources = [fin.get("source", "screener")]
        return snap

    def _price_as_of(self, ticker: str, as_of: "date") -> float | None:
        """Latest adjusted close on/before ``as_of`` from 'max' history. None if
        the series does not reach back that far (delisted / listed-later)."""
        rows = self._history_csv(ticker, period="max")
        best = None
        target = as_of.isoformat()
        for r in rows:
            d = r.get("date")
            if d and d <= target and r.get("close", 0) > 0:
                best = r["close"]
            elif d and d > target:
                break
        return best

    def _momentum_as_of(self, ticker: str, as_of: "date"):
        rows = self._history_csv(ticker, period="max")
        target = as_of.isoformat()
        closes = [r["close"] for r in rows if r.get("date", "") <= target and r.get("close", 0) > 0]
        m12 = m6 = None
        if len(closes) >= 252 + 21:
            past, recent = closes[-(252 + 21)], closes[-21]
            if past > 0:
                m12 = recent / past - 1.0
        if len(closes) >= 126 + 21:
            past6, recent = closes[-(126 + 21)], closes[-21]
            if past6 > 0:
                m6 = recent / past6 - 1.0
        return m12, m6

    def get_news(self, ticker: str, limit: int = 10) -> list[dict[str, Any]]:
        cached = cache.get("news", ticker, _TTL_NEWS)
        if cached is not None:
            return cached[:limit]
        try:
            yf = _yf_module()
            news = yf.Ticker(ticker).news or []
            cleaned = []
            for n in news[:limit]:
                # yfinance schemas vary - accept either flat or nested.
                content = n.get("content", n)
                cleaned.append(
                    {
                        "title": content.get("title") or n.get("title"),
                        "publisher": content.get("provider", {}).get("displayName")
                        or n.get("publisher"),
                        "link": (
                            content.get("clickThroughUrl", {}).get("url")
                            or content.get("canonicalUrl", {}).get("url")
                            or n.get("link")
                        ),
                        "published": content.get("pubDate") or n.get("providerPublishTime"),
                        "summary": content.get("summary") or n.get("summary"),
                    }
                )
        except Exception:
            cleaned = []
        cache.put("news", ticker, cleaned)
        return cleaned[:limit]

    def get_snapshot(self, ticker: str) -> CompanySnapshot:
        """Build a CompanySnapshot for the factor engine."""
        info = self._info(ticker)
        snap = CompanySnapshot(ticker=ticker, raw=info)
        if not info or info.get("_error"):
            # still try to compute momentum from price history
            snap.fetch_status = "failed"
            self._fill_momentum(snap)
            if self._use_stooq:
                self._enrich_with_stooq(snap)
            return snap

        # Identity
        snap.name = info.get("longName") or info.get("shortName")
        snap.currency = info.get("currency")
        snap.sector = info.get("sector")
        snap.industry = info.get("industry")
        snap.country = info.get("country")
        snap.market_cap = _num(info.get("marketCap"))
        snap.price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))

        # Valuation
        snap.pe_trailing = _num(info.get("trailingPE"))
        snap.pe_forward = _num(info.get("forwardPE"))
        snap.pb = _num(info.get("priceToBook"))
        snap.ps = _num(info.get("priceToSalesTrailing12Months"))
        snap.ev_to_ebitda = _num(info.get("enterpriseToEbitda"))
        snap.ev_to_revenue = _num(info.get("enterpriseToRevenue"))
        if snap.pe_trailing and snap.pe_trailing > 0:
            snap.earnings_yield = 1.0 / snap.pe_trailing
        snap.dividend_yield = _num(info.get("dividendYield"))

        free_cf = _num(info.get("freeCashflow"))
        if free_cf and snap.market_cap:
            snap.fcf_yield = free_cf / snap.market_cap

        # Quality
        snap.roe = _num(info.get("returnOnEquity"))
        snap.roa = _num(info.get("returnOnAssets"))
        # yfinance does not expose ROIC directly; approximate from EBIT/(Equity+Debt)
        ebitda = _num(info.get("ebitda"))
        total_debt = _num(info.get("totalDebt"))
        equity = _num(info.get("totalStockholderEquity")) or _num(
            info.get("bookValue") or 0
        )
        if ebitda is not None and equity and total_debt is not None:
            invested = (equity or 0) + (total_debt or 0)
            if invested > 0:
                snap.roic = ebitda / invested  # rough proxy
        snap.gross_margin = _num(info.get("grossMargins"))
        snap.operating_margin = _num(info.get("operatingMargins"))
        snap.profit_margin = _num(info.get("profitMargins"))

        # Health
        snap.debt_to_equity = _num(info.get("debtToEquity"))
        if snap.debt_to_equity is not None and snap.debt_to_equity > 5:
            # yfinance reports debtToEquity as percent-like (e.g. 120 = 1.2)
            snap.debt_to_equity = snap.debt_to_equity / 100.0
        snap.current_ratio = _num(info.get("currentRatio"))
        if ebitda and total_debt is not None:
            cash = _num(info.get("totalCash") or 0) or 0
            snap.net_debt_to_ebitda = (total_debt - cash) / ebitda if ebitda else None

        # Earnings quality - cash conversion (op CF / NI)
        op_cf = _num(info.get("operatingCashflow"))
        net_income = _num(info.get("netIncomeToCommon")) or _num(info.get("netIncome"))
        if op_cf is not None and net_income and net_income != 0:
            snap.cash_conversion = op_cf / net_income

        # Growth
        snap.revenue_growth = _num(info.get("revenueGrowth"))
        snap.earnings_growth = _num(info.get("earningsGrowth"))

        snap.beta = _num(info.get("beta"))
        snap.data_sources.append("yfinance")
        snap.fetch_status = "ok"

        self._fill_momentum(snap)
        if self._use_stooq:
            self._enrich_with_stooq(snap)
        return snap

    def _enrich_with_stooq(self, snap: CompanySnapshot) -> None:
        """Cross-check yfinance's price field against Stooq's latest close.

        Records `stooq_close` -> raw, `field_disagreements['price']`, and
        updates `data_agreement` (1 - mean disagreement, capped to [0,1]).
        """
        stooq_close = _stooq_close(snap.ticker)
        if stooq_close is None:
            # Even with no second source, attribute primary success.
            if snap.fetch_status == "ok":
                snap.data_agreement = None  # unknown agreement
            return
        snap.data_sources.append("stooq")
        snap.raw["_stooq_close"] = stooq_close

        # Compare against yfinance price.
        if snap.price is not None:
            diff = _rel_diff(snap.price, stooq_close)
            if diff is not None:
                snap.field_disagreements["price"] = diff

        # Aggregate agreement: 1 - mean(disagreements), bounded.
        if snap.field_disagreements:
            mean_diff = sum(snap.field_disagreements.values()) / len(
                snap.field_disagreements
            )
            snap.data_agreement = max(0.0, min(1.0, 1.0 - mean_diff))
        else:
            # Source available but nothing to compare yet.
            snap.data_agreement = 1.0

    def _fill_momentum(self, snap: CompanySnapshot) -> None:
        rows = self._history_csv(snap.ticker, period="2y")
        if len(rows) < 30:
            return
        closes = [r["close"] for r in rows if r["close"] > 0]
        if len(closes) < 30:
            return
        # 12-1 month momentum: return from t-252 to t-21 (skip last ~21 trading days)
        if len(closes) >= 252 + 21:
            past = closes[-(252 + 21)]
            recent = closes[-21]
            if past > 0:
                snap.momentum_12_1 = recent / past - 1.0
        if len(closes) >= 126 + 21:
            past6 = closes[-(126 + 21)]
            recent = closes[-21]
            if past6 > 0:
                snap.momentum_6_1 = recent / past6 - 1.0
        # annualized volatility from daily returns
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                rets.append(closes[i] / closes[i - 1] - 1.0)
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
            snap.volatility_annualized = (var**0.5) * (252**0.5)


# ---------------------------------------------------------------------------
# Stooq second-source enrichment.
# Stooq publishes free CSV time series; we use the latest close as a sanity
# cross-check against yfinance. No API key required.
# ---------------------------------------------------------------------------


def _stooq_symbol(ticker: str) -> str | None:
    """Translate a yfinance-style ticker to Stooq's symbol convention.

    Examples:
      AAPL    -> aapl.us
      INFY.NS -> infy.in
      SAP.DE  -> sap.de
      BRK-B   -> brk-b.us
    """
    t = ticker.strip()
    if not t:
        return None
    if "." in t:
        base, suf = t.rsplit(".", 1)
        suf = suf.lower()
        mapping = {
            "ns": "in", "bo": "in",     # India
            "de": "de", "f": "de",        # Germany
            "us": "us",                   # already explicit
            "l": "uk",                    # London
            "to": "ca",                   # Toronto
            "hk": "hk",                   # Hong Kong
        }
        if suf in mapping:
            return f"{base.lower()}.{mapping[suf]}"
        return f"{base.lower()}.{suf}"
    return f"{t.lower()}.us"


def _stooq_close(ticker: str) -> float | None:
    """Fetch the latest close from Stooq (free CSV). Returns None on failure."""
    sym = _stooq_symbol(ticker)
    if not sym:
        return None
    cached = cache.get("stooq_close", sym, _TTL_QUOTE)
    if cached is not None:
        return cached if isinstance(cached, (int, float)) else None
    try:
        import requests  # type: ignore

        url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
        r = requests.get(url, timeout=8, headers={"User-Agent": "fra/0.1"})
        if r.status_code != 200 or not r.text:
            cache.put("stooq_close", sym, None)
            return None
        body = r.text.strip()
        if body.lower().startswith("<!doctype") or "no data" in body.lower():
            cache.put("stooq_close", sym, None)
            return None
        # Last non-empty CSV line, 5th column = Close.
        last = None
        for line in body.splitlines():
            if "," in line and not line.lower().startswith("date,"):
                last = line
        if not last:
            cache.put("stooq_close", sym, None)
            return None
        parts = last.split(",")
        if len(parts) < 5:
            cache.put("stooq_close", sym, None)
            return None
        try:
            close = float(parts[4])
        except ValueError:
            close = None
        cache.put("stooq_close", sym, close)
        return close
    except Exception:
        cache.put("stooq_close", sym, None)
        return None


# ---------------------------------------------------------------------------
# Financial-statement enrichment (Tier-B) for the multibagger variant.
# ---------------------------------------------------------------------------


def _safe_stmt(ticker_obj, attr: str):
    """Return a yfinance statement DataFrame or None (never raise)."""
    try:
        return getattr(ticker_obj, attr, None)
    except Exception:
        return None


def _df_to_series_map(df) -> dict[str, Any]:
    """Convert a yfinance statement DataFrame to {periods, items}.

    Columns are period-end timestamps (newest first in yfinance); we reorder
    ascending (oldest..latest). Rows are line-item names. Everything is coerced
    to float|None so the result is JSON-cacheable.
    """
    result: dict[str, Any] = {"periods": [], "items": {}}
    if df is None:
        return result
    try:
        cols = list(df.columns)
        index = list(df.index)
    except Exception:
        return result
    if not cols or not index:
        return result

    def _col_key(c) -> str:
        try:
            return str(c.date())
        except Exception:
            return str(c)

    col_keys = [_col_key(c) for c in cols]
    order = sorted(range(len(cols)), key=lambda i: col_keys[i])  # ascending
    result["periods"] = [col_keys[i] for i in order]
    for item in index:
        try:
            row = df.loc[item]
        except Exception:
            continue
        vals: list[float | None] = []
        for i in order:
            try:
                v = row.iloc[i]
            except Exception:
                try:
                    v = row[cols[i]]
                except Exception:
                    v = None
            vals.append(_num(v))
        result["items"][str(item)] = vals
    return result


def _pick(items: dict[str, list], n: int, *aliases: str) -> list[float | None]:
    """Return the first matching line-item series among aliases (case/space
    tolerant), else a list of None of length n."""
    if items:
        norm = {k.lower().replace(" ", ""): v for k, v in items.items()}
        for a in aliases:
            key = a.lower().replace(" ", "")
            if key in norm:
                return list(norm[key])
    return [None] * n


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _tail_align(*series: list) -> list[list]:
    """Trim every series to a common tail length (align latest periods)."""
    lengths = [len(s) for s in series if s is not None]
    if not lengths:
        return [list(s or []) for s in series]
    m = min(lengths)
    return [list((s or [])[-m:]) for s in series]


def _robust_growth(series: list[float | None] | None) -> float | None:
    """Robust annual growth estimate from a positionally-aligned series.

    Fits ``ln(value) = a + b * t`` by OLS where ``t`` is the period INDEX
    (0..n-1), then returns ``exp(b) - 1`` as the per-period growth rate. Using
    the regression slope over ALL observations blunts base-year effects (M-2)
    that a raw first->last endpoint CAGR would amplify.

    ``series`` is expected to be positionally aligned (oldest..latest) and may
    contain ``None`` / non-positive entries; those are skipped but keep their
    time index, so an interior gap does not misdate the remaining points. Needs
    at least two positive observations, else returns ``None``.
    """
    import math

    if not series:
        return None
    pts = [(i, v) for i, v in enumerate(series) if v is not None and v > 0]
    if len(pts) < 2:
        return None
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    den = sum((x - xbar) ** 2 for x in xs)
    if den == 0:
        return None
    slope = num / den
    try:
        return math.exp(slope) - 1.0
    except (ValueError, OverflowError):
        return None


# yfinance ``.info``-derived TTM fields that reflect *today* and therefore must
# not enter a point-in-time historical score (audit C-1). pe_trailing /
# earnings_yield / momentum_* are intentionally excluded: the PIT caller
# reconstructs those from the as-of price and as-of statements.
_LOOKAHEAD_TTM_FIELDS = (
    "roe", "roa", "roic", "gross_margin", "operating_margin", "profit_margin",
    "revenue_growth", "earnings_growth", "cash_conversion", "net_debt_to_ebitda",
    "current_ratio", "fcf_yield", "dividend_yield", "beta", "pb", "ps",
    "ev_to_ebitda", "ev_to_revenue", "pe_forward",
)


def _strip_lookahead_ttm_fields(snap: CompanySnapshot) -> None:
    """Null out live TTM ``.info`` fields so they can't leak into a PIT score."""
    for f in _LOOKAHEAD_TTM_FIELDS:
        setattr(snap, f, None)


def enrich_snapshot_with_financials(
    snap: CompanySnapshot,
    fin: dict[str, Any],
    manual: dict[str, Any] | None = None,
    as_of: "date | None" = None,
) -> CompanySnapshot:
    """Populate Tier-B statement-derived fields on `snap` from `fin`.

    Robust to yfinance's shallow (~4 period) history and to entirely missing
    lines: every derived field is left as None when its inputs are absent.
    `manual` optionally supplies Tier-C overrides (promoter_pledge_pct,
    promoter_holding_trend, auditor_red_flag) which are NEVER fabricated.

    Point-in-time (audit C-1): when ``as_of`` is supplied this (1) defensively
    re-applies the reporting-lag gate to ``fin`` (idempotent if the caller
    already gated it), and (2) NULLS OUT any live yfinance ``.info``-derived TTM
    valuation/quality fields that may already sit on ``snap`` (ROE/ROA/margins/
    growth/PB/PS/EV.../beta/current-ratio/net-debt-EBITDA/FCF-yield/dividend), so
    they cannot leak "today" into a historical score. ``pe_trailing`` /
    ``earnings_yield`` / ``momentum_*`` are left untouched because the PIT caller
    reconstructs those from the as-of price and as-of statements. ``as_of=None``
    (default) preserves the exact classic/live behaviour.
    """
    if as_of is not None:
        try:  # defensive, idempotent PIT gate on the statements
            from ..backtest.asof import as_of_financials

            fin = as_of_financials(fin or {}, as_of)
        except Exception:
            pass
        _strip_lookahead_ttm_fields(snap)
    status = (fin or {}).get("status", "failed")
    snap.financials_status = status
    snap.financials_periods = list((fin or {}).get("income_periods") or [])

    # Tier-C manual overrides (default None => neutral downstream).
    if manual:
        if manual.get("promoter_pledge_pct") is not None:
            snap.promoter_pledge_pct = _num(manual.get("promoter_pledge_pct"))
        if manual.get("promoter_holding_trend") is not None:
            snap.promoter_holding_trend = _num(manual.get("promoter_holding_trend"))
        if manual.get("auditor_red_flag") is not None:
            snap.auditor_red_flag = bool(manual.get("auditor_red_flag"))

    # Is this a bank / NBFC / insurer? ROCE / gross margin / Altman are not
    # meaningful for financials (spec section 5).
    sector = (snap.sector or "").lower()
    snap.is_financial = "financial" in sector or "bank" in sector or "insurance" in sector

    if status == "failed" or not fin:
        return snap

    inc = fin.get("income", {}) or {}
    bal = fin.get("balance", {}) or {}
    cf = fin.get("cashflow", {}) or {}
    n_inc = len(fin.get("income_periods") or [])
    n_bal = len(fin.get("balance_periods") or [])
    n_cf = len(fin.get("cashflow_periods") or [])

    # --- Income statement lines --------------------------------------------
    revenue = _pick(inc, n_inc, "Total Revenue", "Operating Revenue", "Total Revenues")
    cogs = _pick(inc, n_inc, "Cost Of Revenue", "Cost Of Goods Sold", "Reconciled Cost Of Revenue")
    gross_profit = _pick(inc, n_inc, "Gross Profit")
    # M-1 fix: ROCE and the operating-margin series must use OPERATING income
    # (spec section 3.2: "EBIT = operating income"), NOT yfinance's "EBIT" line
    # which includes non-operating / other income and inflates the 0.22-weighted
    # profitability pillar. We therefore keep TWO distinct extractions:
    #   * operating_income -> ROCE + operating_margin_series (prefers Operating Income)
    #   * ebit -> interest coverage + Altman X3 (prefers the true EBIT = earnings
    #     before interest & tax, which may legitimately include non-operating items).
    operating_income = _pick(
        inc, n_inc, "Operating Income", "Total Operating Income As Reported", "EBIT"
    )
    ebit = _pick(inc, n_inc, "EBIT", "Operating Income", "Total Operating Income As Reported")
    net_income = _pick(inc, n_inc, "Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
    interest = _pick(inc, n_inc, "Interest Expense", "Interest Expense Non Operating")
    sga = _pick(inc, n_inc, "Selling General And Administration", "Selling General And Administrative")
    dep_inc = _pick(inc, n_inc, "Reconciled Depreciation")
    diluted_eps = _pick(inc, n_inc, "Diluted EPS", "Basic EPS")

    # --- Balance sheet lines -----------------------------------------------
    total_assets = _pick(bal, n_bal, "Total Assets")
    curr_liab = _pick(bal, n_bal, "Current Liabilities", "Total Current Liabilities")
    curr_assets = _pick(bal, n_bal, "Current Assets", "Total Current Assets")
    total_liab = _pick(bal, n_bal, "Total Liabilities Net Minority Interest", "Total Liabilities")
    equity = _pick(bal, n_bal, "Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
    retained = _pick(bal, n_bal, "Retained Earnings")
    ppe = _pick(bal, n_bal, "Net PPE", "Net Property Plant And Equipment", "Properties")
    inventory = _pick(bal, n_bal, "Inventory")
    receivables = _pick(bal, n_bal, "Receivables", "Net Receivables", "Accounts Receivable")
    payables = _pick(bal, n_bal, "Accounts Payable", "Payables", "Payables And Accrued Expenses")
    total_debt = _pick(bal, n_bal, "Total Debt")
    long_term_debt = _pick(bal, n_bal, "Long Term Debt")
    cash_bs = _pick(bal, n_bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")

    # --- Cash-flow lines ----------------------------------------------------
    cfo = _pick(cf, n_cf, "Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities")
    capex = _pick(cf, n_cf, "Capital Expenditure", "Capital Expenditures", "Purchase Of PPE")
    dividends = _pick(cf, n_cf, "Cash Dividends Paid", "Common Stock Dividend Paid")
    buyback = _pick(cf, n_cf, "Repurchase Of Capital Stock", "Repurchase Of Common Stock")
    dep_cf = _pick(cf, n_cf, "Depreciation And Amortization", "Depreciation Amortization Depletion")

    def _series(fn, *cols_):
        cols_aligned = _tail_align(*cols_)
        out: list[float] = []
        for tup in zip(*cols_aligned):
            v = fn(*tup)
            if v is not None:
                out.append(v)
            else:
                out.append(None)  # keep alignment; filtered later
        return [x for x in out if x is not None]

    # Gross margin series = (rev - cogs)/rev  (prefer explicit gross profit).
    gm_series: list[float] = []
    rev_a, cogs_a, gp_a = _tail_align(revenue, cogs, gross_profit)
    for r, c, gp in zip(rev_a, cogs_a, gp_a):
        if r and r != 0:
            if gp is not None:
                gm_series.append(gp / r)
            elif c is not None:
                gm_series.append((r - c) / r)
    snap.gross_margin_series = gm_series

    # Operating margin series = operating income / revenue (genuine OPM, M-1).
    opm_series: list[float] = []
    rev_a, oi_a = _tail_align(revenue, operating_income)
    for r, e in zip(rev_a, oi_a):
        if r and r != 0 and e is not None:
            opm_series.append(e / r)
    snap.operating_margin_series = opm_series

    # ROCE series = operating income / (total assets - current liabilities).
    # Uses OPERATING income per spec section 3.2 (M-1 fix), not yfinance "EBIT".
    if not snap.is_financial:
        roce_series: list[float] = []
        oi_a, ta_a, cl_a = _tail_align(operating_income, total_assets, curr_liab)
        for e, ta, cl in zip(oi_a, ta_a, cl_a):
            if e is not None and ta is not None and cl is not None:
                ce = ta - cl
                if ce and ce != 0:
                    roce_series.append(e / ce)
        snap.roce_series = roce_series
        if roce_series:
            snap.roce = roce_series[-1]
        elif snap.roic is not None:
            # Fall back to the existing EBITDA-based ROIC proxy.
            snap.roce = snap.roic
            snap.roce_via_proxy = True

    # ROE series = NI / equity.
    roe_series: list[float] = []
    ni_a, eq_a = _tail_align(net_income, equity)
    for ni, eq in zip(ni_a, eq_a):
        if ni is not None and eq and eq != 0:
            roe_series.append(ni / eq)
    snap.roe_series = roe_series

    # Revenue / NI series (for growth + CAGR).
    snap.revenue_series = [x for x in revenue if x is not None]
    snap.net_income_series = [x for x in net_income if x is not None]

    # CFO series.
    snap.cfo_series = [x for x in cfo if x is not None]

    # FCF series = CFO - |Capex|  (yfinance capex is negative).
    fcf_series: list[float] = []
    cfo_a, capex_a = _tail_align(cfo, capex)
    for o, cx in zip(cfo_a, capex_a):
        if o is not None and cx is not None:
            fcf_series.append(o - abs(cx))
    snap.fcf_series = fcf_series
    if fcf_series:
        snap.fcf = fcf_series[-1]
        snap.fcf_neg_years = sum(1 for f in fcf_series if f < 0)
        snap.fcf_posrate = sum(1 for f in fcf_series if f > 0) / len(fcf_series)

    # Latest-year scalars.
    ta_last = total_assets[-1] if total_assets else None
    rev_last = revenue[-1] if revenue else None
    cogs_last = cogs[-1] if cogs else None
    gp_last = gross_profit[-1] if gross_profit else None
    ni_last = net_income[-1] if net_income else None
    cfo_last = cfo[-1] if cfo else None
    ebit_last = ebit[-1] if ebit else None
    capex_last = capex[-1] if capex else None
    interest_last = interest[-1] if interest else None

    # Gross profitability = (rev - COGS) / total assets (Novy-Marx).
    if not snap.is_financial and ta_last:
        if gp_last is not None:
            snap.gross_profitability = gp_last / ta_last
        elif rev_last is not None and cogs_last is not None:
            snap.gross_profitability = (rev_last - cogs_last) / ta_last

    # Accruals ratio = (NI - CFO) / total assets (Sloan). Low/negative better.
    if ni_last is not None and cfo_last is not None and ta_last:
        snap.accruals_ratio = (ni_last - cfo_last) / ta_last

    # Interest coverage = EBIT / |interest expense|.
    if ebit_last is not None and interest_last not in (None, 0):
        snap.interest_coverage = ebit_last / abs(interest_last)

    # Asset turnover (DuPont) = revenue / total assets.
    snap.asset_turnover = _div(rev_last, ta_last)

    # Capex intensity = |capex| / revenue.
    if capex_last is not None and rev_last:
        snap.capex_intensity = abs(capex_last) / rev_last

    # OCF vs NP over the multi-year window: cum(CFO) / cum(NP).
    cfo_a, ni_a = _tail_align(cfo, net_income)
    cfo_vals = [c for c in cfo_a if c is not None]
    ni_vals = [n for n in ni_a if n is not None]
    if cfo_vals and ni_vals and sum(ni_vals) > 0:
        snap.ocf_to_np_multiyear = sum(cfo_vals) / sum(ni_vals)
    elif ni_vals and sum(ni_vals) <= 0:
        # RF2 fix: a persistently loss-making firm has non-positive cumulative
        # net profit, so cum(CFO)/cum(NP) is meaningless (left None) but the
        # firm's earnings are clearly not cash-backed - flag it so RF2 can fire.
        snap.cum_np_nonpositive = True
    # Per-year CFO/NP ratio falling? (used by working-capital-trap veto) plus the
    # longest run of consecutive years with CFO/NI < 0.5 (RF2 alternative clause).
    ratios = []
    streak = 0
    best_streak = 0
    have_ratio = False
    for o, ni in zip(cfo_a, ni_a):
        if o is not None and ni not in (None, 0):
            r = o / ni
            ratios.append(r)
            have_ratio = True
            if r < 0.5:
                streak += 1
                best_streak = max(best_streak, streak)
            else:
                streak = 0
        else:
            streak = 0
    if len(ratios) >= 2:
        snap.cfo_np_falling = ratios[-1] < ratios[0]
    if have_ratio:
        snap.cfo_np_below_half_streak = best_streak

    # Shareholder yield = (|dividends| + |buyback|) / market cap.
    div_last = dividends[-1] if dividends else None
    bb_last = buyback[-1] if buyback else None
    if snap.market_cap and (div_last is not None or bb_last is not None):
        returned = abs(div_last or 0.0) + abs(bb_last or 0.0)
        snap.shareholder_yield = returned / snap.market_cap

    # Working-capital days (latest) + deltas over the window.
    def _days(numer, denom):
        if numer is None or denom is None or denom == 0:
            return None
        return 365.0 * numer / abs(denom)

    pay_last = payables[-1] if payables else None
    recv_last = receivables[-1] if receivables else None
    inv_last = inventory[-1] if inventory else None
    snap.dso = _days(recv_last, rev_last)
    snap.dio = _days(inv_last, cogs_last if cogs_last else rev_last)
    snap.dpo = _days(pay_last, cogs_last if cogs_last else rev_last)
    if snap.dso is not None and snap.dio is not None and snap.dpo is not None:
        snap.ccc = snap.dso + snap.dio - snap.dpo

    def _first_days(numer_series, denom_series):
        na, da = _tail_align(numer_series, denom_series)
        for nn, dd in zip(na, da):
            d = _days(nn, dd)
            if d is not None:
                return d
        return None

    dso_first = _first_days(receivables, revenue)
    dio_first = _first_days(inventory, cogs if any(c is not None for c in cogs) else revenue)
    dpo_first = _first_days(payables, cogs if any(c is not None for c in cogs) else revenue)
    if snap.dso is not None and dso_first is not None:
        snap.dso_delta = snap.dso - dso_first
    if snap.dio is not None and dio_first is not None:
        snap.dio_delta = snap.dio - dio_first
    if snap.dpo is not None and dpo_first is not None:
        snap.dpo_delta = snap.dpo - dpo_first
    if snap.dso_delta is not None and snap.dio_delta is not None and snap.dpo_delta is not None:
        snap.ccc_delta = snap.dso_delta + snap.dio_delta - snap.dpo_delta

    # Total debt rising over the window (retained as a coarse signal).
    debt_ser = [d for d in total_debt if d is not None] or [
        d for d in long_term_debt if d is not None
    ]
    if len(debt_ser) >= 2:
        snap.debt_rising = debt_ser[-1] > debt_ser[0]

    # RF5 fix: rising NET-DEBT / EBITDA trend over the window (spec section 6),
    # which - unlike the gross-debt proxy above - accounts for cash build and
    # EBITDA growth. net_debt = total_debt - cash; EBITDA = EBIT + depreciation.
    # Uses the true EBIT (earnings before interest & tax), not operating income.
    debt_for_nde = total_debt if any(d is not None for d in total_debt) else long_term_debt
    dep_for_nde = dep_cf if any(d is not None for d in dep_cf) else dep_inc
    d_a, cash_a, ebit_a, dep_a = _tail_align(debt_for_nde, cash_bs, ebit, dep_for_nde)
    nde_series: list[float] = []
    for d, csh, e, dp in zip(d_a, cash_a, ebit_a, dep_a):
        if d is None or e is None:
            continue
        ebitda = e + (dp or 0.0)
        if ebitda and ebitda > 0:
            net_debt = d - (csh or 0.0)
            nde_series.append(net_debt / ebitda)
    if len(nde_series) >= 2:
        snap.net_debt_ebitda_rising = nde_series[-1] > nde_series[0]

    # Earnings growth (g5): prefer EPS path, fall back to NI path.
    # M-2 fix: use a ROBUST log-linear (OLS) growth estimate instead of the raw
    # first->last endpoint CAGR, which is swung sharply by a single depressed or
    # inflated base year. The estimate is the slope of ln(value) vs the period
    # INDEX, so interior gaps (None) keep their positional slot and do not
    # misdate the endpoints (the old code collapsed interior None before taking
    # endpoints). Requires >= 2 positive observations.
    snap.earnings_cagr = _robust_growth(diluted_eps)
    if snap.earnings_cagr is None:
        snap.earnings_cagr = _robust_growth(net_income)

    # PEG (5y): PE_trailing / (100 * g5). Guard g5 <= 0 (shrinking != cheap).
    if (
        snap.pe_trailing is not None
        and snap.pe_trailing > 0
        and snap.earnings_cagr is not None
        and snap.earnings_cagr > 0
    ):
        snap.peg = snap.pe_trailing / (100.0 * snap.earnings_cagr)

    # Beneish M-score and Altman Z"-EM via the pure forensic functions.
    try:
        from ..factors import forensic  # lazy import to avoid import cycle

        snap.beneish_m = forensic.beneish_m_score(
            revenue=revenue, cogs=cogs, sga=sga, net_income=net_income,
            cfo=cfo, receivables=receivables, current_assets=curr_assets,
            ppe=ppe, total_assets=total_assets, depreciation=dep_cf if any(
                d is not None for d in dep_cf
            ) else dep_inc,
            current_liabilities=curr_liab, long_term_debt=long_term_debt,
        )
        if not snap.is_financial:
            snap.altman_z = forensic.altman_z_em(
                current_assets=curr_assets, current_liabilities=curr_liab,
                total_assets=total_assets, retained_earnings=retained,
                ebit=ebit, equity=equity, total_liabilities=total_liab,
            )
    except Exception:
        pass

    return snap


def _rel_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return abs(a - b) / abs(a)


def _num(v: Any) -> float | None:
    """Coerce to float or None - filter out infs/nans/strings."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _json_safe(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool, list, dict, type(None)))
