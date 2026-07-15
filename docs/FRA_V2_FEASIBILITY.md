# FRA V2 Feasibility Report — Multibagger-Focused Redesign (Phase 1)

**Status:** Read-only investigation. No code was modified.
**Repo:** `finance-research-agent` (FRA) — multi-agent Indian/German equity research pipeline.
**Scope:** Map the scoring engine, inventory the *actually available* data, produce a feasibility
matrix for an Indian expert's multibagger stock-picking techniques, and honestly assess whether the
existing backtest can verify "would this strategy have caught multibagger X before its run-up."

> **Bottom line up front.** The FRA is a cleanly-architected, cross-sectional **percentile-rank**
> factor engine fed almost entirely by **yfinance `.info`** (a single trailing snapshot per ticker).
> It is easy to extend with *new ratio factors that yfinance already exposes as trailing numbers*
> (ROCE proxy, PEG, working-capital ratios via the statement APIs), but it is **structurally
> unable, today, to support point-in-time historical fundamentals**, and it has **no access at all**
> to the India-specific disclosure data that the expert's edge relies on (promoter **pledge %**,
> related-party transactions, order book / L1 wins, auditor changes, contingent-liability
> footnotes). The existing `backtest` command is a **price-only momentum proxy** — it does *not*
> use fundamentals and therefore cannot answer "would the fundamental strategy have flagged the
> multibagger beforehand." A credible fundamental backtest requires a new point-in-time data source.

---

## 1. Scoring-engine architecture map

### 1.1 Pipeline flow

Orchestrated in `src/graph/orchestrator.py` (`_seq_run`, and an equivalent LangGraph in
`_build_langgraph`). Order:

1. `src/agents/universe.py:run` — resolve free-text target → candidate tickers (deterministic
   keyword routing, seed lists in `src/data/india.py` / `germany_global.py`, optional live fetch
   `src/data/universe_live.py`). **No LLM.**
2. `src/agents/quant.py:run` — **the heart**. Fetches a `CompanySnapshot` per ticker
   (`src/data/provider.py`), applies profile risk constraints (`_passes_constraints`), builds the
   data-health card (`src/data/health.py:build_card`), then calls the factor engine
   (`src/factors/engine.py:rank_universe`). Also computes the factor-regime report
   (`src/factors/decay.py`) and a reproducibility `input_hash`.
3. If an LLM is available (`src/graph/conditional_logic.py:should_run_llm`): analysts
   (`fundamentals`, `technical`, `news_sentiment`, `macro`), then N rounds of bull/bear
   `researchers`, then `risk_profile`, then `manager.run`. Otherwise `manager.run_quant_only`.
4. `src/report/generator.py` + `src/report/excel.py` write the outputs; `src/memory/store.py`
   persists the run.

**Key architectural fact:** *All numbers are produced by the deterministic factor engine. LLMs only
reason over pre-computed scores; they never generate metric values.* (Stated in
`src/factors/engine.py` docstring and enforced by the data flow.)

### 1.2 Factor engine internals (`src/factors/engine.py:rank_universe`)

There are exactly **5 factors**, defined as extractor functions in
`src/factors/metrics.py:FACTORS`:

| Factor | Metrics used (from `CompanySnapshot`) | "Higher = better" transform |
|---|---|---|
| `quality` | `roic`, `roe`, `gross_margin`, `operating_margin`, `profit_margin` | direct |
| `value` | `earnings_yield`, `fcf_yield`, `1/pb`, `1/ps`, `1/ev_to_ebitda` | valuation inverted (cheaper = higher) |
| `momentum` | `momentum_12_1`, `momentum_6_1` | direct |
| `financial_health` | `-net_debt_to_ebitda`, `-debt_to_equity`, `current_ratio` | leverage negated |
| `earnings_quality` | `cash_conversion` (= operating CF / net income) | direct |

**Computation sequence (per `rank_universe`):**

1. **Extract** each factor's raw metric dict for every ticker (`metrics.FACTORS[...]`).
2. **Normalize = cross-sectional percentile rank** per metric column across the whole universe
   (`src/factors/scoring.py:percentile_ranks`, ties get average rank, result ∈ `[0,1]`, `None`
   preserved). **This is NOT a z-score and NOT sector-relative** — it is a plain rank over whatever
   tickers are in scope for the run.
3. **Factor score** = simple mean of that factor's available metric percentiles
   (`scoring.average`; `None`s skipped).
4. **Composite (raw)** = weight-normalized average of factor scores. Weights come from the profile's
   `factor_weights` and are re-normalized to sum to 1 (`_normalize_weights`). Only factors with a
   non-`None` score contribute, and the denominator is the *used* weight (so a missing factor
   doesn't zero the composite, it just drops out).
5. **Coverage weighting / shrinkage** — the distinctive part. Per-ticker `coverage` (fraction of
   ~23 numeric fields present, from `src/data/health.py:coverage_of`) maps to
   `coverage_weight ∈ [coverage_weight_floor, 1.0]`. Final composite is shrunk toward the universe
   median 0.5:
   `composite = raw_composite * coverage_weight + 0.5 * (1 - coverage_weight)`.
   Sparse-data names are pulled toward mediocre, not rewarded.
6. **Optional orthogonalization** (`orthogonalize_eq`, off in both shipped profiles): residualize
   Earnings Quality against Quality (`_orthogonalize_eq_against_quality`) — a cheap, OLS-free
   mean-subtraction then re-percentile. This is the *only* de-correlation in the system; the other
   four factors are **not** orthogonalized against each other.
7. **Diagnostics per pick:** `factor_std_dev` (spread across the 5 factor scores — flags one-factor
   picks), `profile_fit` (cosine similarity between the pick's factor vector and the weight vector,
   `_cosine_sim`), and `floor_breaches` (any factor below `per_factor_floor` is *flagged, not
   rejected*).
8. **Sort** by `composite_score` desc; `None` last.

### 1.3 Where new factors / weights are configured

- **Add a new factor:** (a) add the underlying field(s) to `CompanySnapshot` and populate them in
  `src/data/provider.py:get_snapshot`; (b) add an extractor to `src/factors/metrics.py` and register
  it in the `FACTORS` dict; (c) add a matching weight key to each profile's `factor_weights`
  (`config/profiles/*.yaml`). The engine, coverage math, and reports pick it up automatically.
- **Add a metric to an existing factor:** just add a key to that factor's extractor dict in
  `metrics.py` (and the field on the snapshot). No engine changes.
- **Weights / knobs:** per-profile YAML — `factor_weights` (5 keys) and `factor_config`
  (`per_factor_floor`, `coverage_weight_floor`, `orthogonalize_eq`). Weights need not sum to 1;
  `_normalize_weights` handles it.
- **Coverage denominator** lives in `src/data/health.py:_NUMERIC_FIELDS` — adding fields there
  changes how coverage/shrinkage is computed.

### 1.4 Important limitations of the current design (relevant to V2)

- **No sector-neutrality.** Percentile ranks are computed over the entire run universe. A run of
  "best banks" ranks banks against banks (OK), but a mixed run ranks (e.g.) an IT name's margins
  against a bank's — cross-sector distortion. There is no sector-relative normalization hook.
- **No z-scoring / winsorization.** Rank-only means it's robust to outliers but loses magnitude
  information (a 60% ROCE and a 25% ROCE that are the top two both just become "near 1.0").
- **Growth is fetched but unused as a factor.** `revenue_growth` and `earnings_growth` exist on the
  snapshot and are shown to the LLM (`_common.shortlist_context`) but are **not** in any factor
  extractor, so they don't affect the composite score.
- **ROIC is a rough proxy**, not true ROCE (see §2).

---

## 2. Agent contributions & fundamental fields used

All agents live in `src/agents/`. LLM agents fall back to deterministic heuristics if no LLM is
reachable (the pipeline never hard-fails on a missing LLM).

| Agent (`src/agents/…`) | Role in final pick | Fundamental fields it consumes |
|---|---|---|
| `universe.py` | Builds candidate list from target/sector keywords. Deterministic. | none (name/sector metadata only) |
| `quant.py` | **Produces the composite ranking + shortlist.** This *is* the quantitative pick. | the full `CompanySnapshot` (all fields in §3) |
| `fundamentals.py` | LLM summarizes strongest/weakest factor drivers; also pulls a US-only insider signal (`insiders_edgar.py`). Heuristic fallback blends quality/value/health/EQ factor scores. | reads factor scores + `key_metrics` from `_common.shortlist_context` (PE, PB, EV/EBITDA, yields, ROE, ROIC, margins, D/E, ND/EBITDA, cash conversion, growth, momentum, div yield) |
| `technical.py` | Momentum/vol stance per ticker. | `momentum_12_1`, `volatility_annualized` |
| `news_sentiment.py` | GDELT (fallback yfinance) headline sentiment. | none numeric — headlines only |
| `macro.py` | One universe-wide macro paragraph by country. | none per-ticker |
| `researchers.py` | Bull vs bear debate over the shortlist. | factor scores + analyst signals (no new data) |
| `risk_profile.py` | Emits profile risk/tax notes; volatility/market-cap filtering happens in `quant.py`. | profile constraints/tax only |
| `manager.py` | Reconciles factor scores + analyst signals + debate → `FinalPick`s (thesis, risks, horizon, after-tax est.). `run_quant_only` synthesizes straight from factor reports. | factor reports + snapshots + `after_tax.py` |

**Net:** the *only* place fundamentals actually change the ranking is the factor engine via
`quant.py`. Everything downstream is narrative/reconciliation over those scores.

---

## 3. Data-availability inventory

### 3.1 What is fetched today

`src/data/provider.py:DataProvider.get_snapshot` reads **only** two things from yfinance:

1. `Ticker.get_info()` / `.info` — a **single flat trailing dict** (cached 24h).
2. `Ticker.history(period="2y")` — daily OHLCV, used only to compute `momentum_12_1`,
   `momentum_6_1`, `volatility_annualized`.

Plus a **Stooq** latest-close cross-check (price sanity only, no fundamentals) and **SEC EDGAR
Form 4** (US-only insider counts, `insiders_edgar.py`). News via **GDELT** (`news_gdelt.py`).

**Critically: the provider never calls yfinance's financial-statement APIs** — no `.income_stmt`,
`.balance_sheet`, `.cashflow`, `.quarterly_*`, `.get_shares_full`, `.major_holders`,
`.institutional_holders`, `.earnings_dates`, or `.recommendations`. (Confirmed by source search:
the only statement-derived numbers used are the pre-computed `freeCashflow` and `operatingCashflow`
scalars inside `.info`.) So **no historical statement data enters the system at all** today.

### 3.2 Field-by-field inventory for the expert's data needs

Legend for **Status**:
- **Now** = already fetched & on `CompanySnapshot`.
- **yf-unused** = obtainable from yfinance (usually via the statement APIs `.income_stmt` /
  `.balance_sheet` / `.cashflow`, or an unused `.info` key) but **not currently wired in**.
- **External** = not reliably available from yfinance/Stooq/GDELT/EDGAR; needs an India-specific
  source (screener.in, BSE/NSE filings, Trendlyne/Tijori, annual reports).

| Expert data need | Status | Where it is / would come from | Notes & caveats |
|---|---|---|---|
| **P/E** (trailing & forward) | **Now** | `.info: trailingPE, forwardPE` → `pe_trailing`, `pe_forward` | trailing snapshot only |
| **ROE** (net income / equity) | **Now** | `.info: returnOnEquity` → `roe` | single trailing value |
| **Net income & equity** (raw) | **yf-unused** | `.income_stmt` (Net Income), `.balance_sheet` (Total Stockholder Equity) | needed if you want to compute ratios yourself / historically |
| **ROCE** = EBIT / capital employed | **yf-unused (partial)** | Today only a crude **ROIC proxy** = `ebitda / (equity + totalDebt)` (`provider.py`, uses EBITDA not EBIT). True ROCE needs `.income_stmt` **EBIT/Operating Income** and `.balance_sheet` (total assets − current liabilities, or equity + debt). | current `roic` is *EBITDA-based*, overstates vs EBIT-based ROCE; fixable with statement fetch |
| **EBIT / operating profit** | **yf-unused** | `.income_stmt: EBIT / Operating Income`; `.info: operatingMargins` gives the margin but not level | only `ebitda` scalar is in `.info` |
| **Capital employed** | **yf-unused** | `.balance_sheet` (total assets, current liabilities, debt, equity) | derivable from statement lines |
| **Operating & gross margin (level)** | **Now** | `.info: operatingMargins, grossMargins` → snapshot | single trailing point |
| **Gross vs operating margin *history*** | **yf-unused (shallow)** | `.income_stmt` (annual, ~4 yrs) / `.quarterly_income_stmt` (~4-5 q) | **only a few periods**, not multi-year trend; see §4 |
| **Earnings growth (current)** | **Now (unused in scoring)** | `.info: earningsGrowth, revenueGrowth` → snapshot fields | on snapshot but **not a factor**; also `earningsQuarterlyGrowth` in `.info` (unused) |
| **PEG** (needs multi-yr EPS CAGR) | **yf-unused (partial)** | `.info: trailingPegRatio` exists (unused); a *proper* 5-yr PEG needs EPS history from `.income_stmt` (too short) or external | yfinance's peg is a single vendor number of uncertain provenance; **5-yr EPS CAGR is not reliably available** |
| **Full cash-flow statement (CFO, capex → FCF)** | **yf-unused** | `.cashflow` (Operating Cash Flow, Capital Expenditure). Today only `.info: freeCashflow, operatingCashflow` scalars are used. | FCF = CFO − capex computable per period from statements; history shallow |
| **Cash conversion (CFO/NI)** | **Now** | computed in `provider.py` from `.info` scalars → `cash_conversion` | trailing only |
| **Total debt** | **Now** | `.info: totalDebt` → used in `roic`, `net_debt_to_ebitda` | also on `.balance_sheet` |
| **Receivables / Inventory / Payables** | **yf-unused** | `.balance_sheet: Net Receivables, Inventory, Accounts Payable` | needed for debtor/inventory/DPO days |
| **Debtor days / Inventory days / DPO (working-capital cycle)** | **yf-unused (compute)** | derive from `.balance_sheet` + `.income_stmt` (revenue, COGS) | computable per period but only ~4 annual points; trend weak |
| **Tax paid vs tax provision** | **yf-unused (partial)** | `.income_stmt: Tax Provision`; `.cashflow` sometimes has taxes paid | "paid vs provision" comparison often needs the annual-report cash-flow detail → **partly external** |
| **Contingent liabilities** | **External** | annual-report footnotes / screener.in "other" | **not in yfinance** |
| **Promoter / insider holding %** | **partial** | `.info: heldPercentInsiders, heldPercentInstitutions` (unused). For India this loosely maps to promoter holding but is unreliable/stale. Authoritative = BSE/NSE shareholding pattern, screener.in. | use as weak signal; authoritative data is **External** |
| **Promoter PLEDGE %** | **External** | BSE/NSE shareholding-pattern filings, screener.in, Trendlyne | **not available from yfinance at all** — a core multibagger red-flag input |
| **Related-party transactions** | **External** | annual reports, screener.in | **not available** |
| **Order book / L1 (lowest-bidder) status** | **External** | company filings/announcements, exchange news, sector trackers | **not available** (GDELT news may *mention* it, not structured) |
| **Auditor changes / resignations** | **External** | BSE/NSE announcements, MCA filings | **not available** structured (GDELT may catch headlines) |
| **Dividend yield** | **Now** | `.info: dividendYield` → `dividend_yield` | — |
| **Beta / volatility** | **Now** | `.info: beta`; vol computed from history | — |
| **Momentum (12-1m, 6-1m)** | **Now** | computed from `.history` | — |
| **Market cap** | **Now** | `.info: marketCap` | native currency |
| **PB / PS / EV-EBITDA / EV-Rev** | **Now** | `.info` → snapshot | — |
| **Interest coverage** | **field exists, unpopulated** | `CompanySnapshot.interest_coverage` declared but never filled; needs `.income_stmt` (EBIT / interest expense) | quick win via statements |
| **Accruals ratio** | **field exists, unpopulated** | `CompanySnapshot.accruals_ratio` declared, never filled; needs NI, CFO, total assets | quick win |

**Summary counts:** ~14 fields already available; ~10 obtainable from yfinance statement APIs but
currently unused (with the *severe caveat* of shallow history, §4); ~6 India-specific disclosure
items are **only** obtainable from external sources (screener.in / BSE-NSE / Tijori / annual
reports) — and several of these (pledge %, RPTs, order book, auditor changes) are exactly where the
expert's differentiated edge lives.

---

## 4. Historical depth — the make-or-break constraint

- **Price history:** yfinance `.history()` gives many years of daily OHLCV (the backtest pulls
  `period="5y"`; longer is available). Adjusted closes are **survivorship-affected** (delisted names
  simply return nothing) but for surviving names, price depth is adequate.
- **Fundamental history via yfinance statements:** `.income_stmt` / `.balance_sheet` / `.cashflow`
  typically return **~4 annual periods**; `.quarterly_*` return **~4–5 quarters**. That is
  **far too shallow** for the expert's multi-year techniques (5-yr EPS CAGR for PEG, 5–10-yr margin
  and ROCE trend, working-capital-cycle trend).
- **Not point-in-time.** yfinance statements are the **latest/restated** figures, timestamped by
  fiscal period end, **not** by the date the market actually had them. Using them in a backtest
  injects **look-ahead bias** (you'd "know" FY23 numbers months before they were filed, and you'd
  get *restated* rather than as-first-reported values).
- **`.info` is a live snapshot only.** trailingPE, ROE, margins, etc. reflect *today*. There is no
  way to retrieve the `.info` values *as they were* on a past date. So even the fields we use now
  cannot be reconstructed historically from this source.
- **Survivorship bias in the universe.** Seed lists (`src/data/india.py` = today's NIFTY50) and the
  live fetchers return **current** constituents. A historical study over 2015→2025 using today's
  index members systematically excludes the delisted/demoted losers — inflating apparent success.

**Implication:** any genuine fundamental backtest of the expert's strategy needs a **point-in-time
fundamentals source with real historical constituents** (e.g. screener.in exports, a paid PIT
vendor, or a manually snapshotted panel). yfinance/Stooq cannot supply it.

---

## 5. Feasibility matrix — expert techniques vs FRA

**Available?** = yes / partial / no, with source. **Integration point** references the concrete
file/function to change. "Live screen" = usable for *today's* ranking; historical viability is
governed by §4 (mostly **no** without a new PIT source).

| # | Expert technique | Signal idea | Data needed | Available? | Integration point in FRA |
|---|---|---|---|---|---|
| 1 | **High ROCE / capital efficiency** | rank by EBIT/capital employed; prefer consistently high | EBIT, capital employed | **partial** — crude EBITDA-based `roic` now; true ROCE via `.income_stmt`+`.balance_sheet` (yf-unused, shallow history) | add `roce` to `provider.get_snapshot` + `metrics.quality` |
| 2 | **High & stable ROE** | reward high ROE, penalize volatile ROE | ROE (multi-yr) | **partial** — level **now**; *stability* needs history (yf shallow / External) | `metrics.quality` (level ok); stability needs new data |
| 3 | **Reasonable P/E** | avoid overpaying | trailing/forward PE | **yes** — `.info` **now** | already in `metrics.value` (`earnings_yield`) |
| 4 | **PEG (growth-adjusted value), ideally 5-yr** | PE ÷ EPS CAGR ≤ ~1 | 5-yr EPS growth | **no (reliable)** — yfinance `trailingPegRatio` is a black-box single number; 5-yr EPS CAGR **External** (screener.in) | new `value` metric once EPS history sourced |
| 5 | **Strong FCF generation** | CFO−capex positive & growing | CFO, capex | **partial** — trailing `fcf_yield` **now**; per-period & trend via `.cashflow` (yf-unused, shallow) | `metrics.value`/new `cashflow` factor |
| 6 | **High cash conversion / low accruals** | CFO ≈ or > net income; low accruals | CFO, NI, total assets | **partial** — `cash_conversion` **now**; `accruals_ratio` field exists but **unpopulated** (quick win) | populate in `provider`, add to `metrics.earnings_quality` |
| 7 | **Low / falling debt** | prefer low D/E, low net-debt/EBITDA | debt, equity, EBITDA | **yes** — **now** in `metrics.financial_health` | already integrated |
| 8 | **Interest coverage / solvency** | EBIT/interest comfortably high | EBIT, interest expense | **partial** — field exists, **unpopulated**; needs `.income_stmt` (yf-unused) | populate `interest_coverage`, add to `financial_health` |
| 9 | **Improving working-capital cycle** | falling debtor/inventory days, healthy DPO | receivables, inventory, payables, revenue, COGS | **partial** — computable from `.balance_sheet`/`.income_stmt` (yf-unused) but **only ~4 periods**; trend weak | new `working_capital` factor + snapshot fields |
| 10 | **Margin expansion (gross→operating trend)** | rising margins over years | multi-yr margins | **partial** — level **now**; multi-yr trend yf-shallow / **External** | new `growth`/`quality-trend` metric |
| 11 | **Earnings/revenue growth quality** | durable top- & bottom-line growth | growth series | **partial** — trailing `earnings_growth`/`revenue_growth` on snapshot but **not scored**; multi-yr **External** | wire existing fields into a `growth` factor in `metrics.py` (**quick win**) |
| 12 | **Tax: paid ≈ provision (earnings authenticity)** | flag low cash-tax vs P&L tax | tax provision, taxes paid | **partial/External** — `.income_stmt` tax provision (yf-unused); cash taxes paid often **External** (annual report) | new earnings-quality metric; partly needs external |
| 13 | **Low contingent liabilities** | off-balance-sheet risk check | footnote data | **no** — **External** (annual reports / screener.in) | not feasible via current sources |
| 14 | **High promoter holding** | skin in the game | shareholding pattern | **partial** — `.info: heldPercentInsiders` (unreliable proxy, yf-unused); authoritative **External** (BSE/NSE) | weak proxy now; real data External |
| 15 | **Low / zero promoter PLEDGE %** | key red-flag filter | pledge disclosures | **no** — **External** (BSE/NSE/screener.in/Trendlyne) | new data connector required; high-value gap |
| 16 | **Clean related-party transactions** | governance red-flag | RPT disclosures | **no** — **External** (annual reports) | not feasible via current sources |
| 17 | **Order book / L1 momentum** | forward-revenue visibility | order book, bid wins | **no** — **External** (filings/announcements); GDELT may surface unstructured headlines | news agent could flag mentions only |
| 18 | **Auditor change / resignation flag** | governance red-flag | filings | **no** — **External** (BSE/NSE/MCA); GDELT headline catch only | news agent could flag mentions only |
| 19 | **Insider buying** | conviction signal | insider trades | **partial** — **US-only** via EDGAR Form 4 (`insiders_edgar.py`); India SEBI SAST **External** | extend `insiders_edgar` pattern to an India source |
| 20 | **Momentum confirmation (don't buy falling knives)** | price trend filter | price history | **yes** — **now** (`momentum` factor) | already integrated |
| 21 | **Size / liquidity filter (small→mid for multibaggers)** | market-cap band | market cap | **yes** — **now** (`risk_constraints.min_market_cap*`) | `quant.py:_passes_constraints`; add an upper band for small/mid tilt |
| 22 | **Sector-relative quality/value** | rank within sector | sector tag + metrics | **partial** — sector tag **now**, but engine ranks **cross-universe** (no sector-neutral hook) | requires new logic in `engine.rank_universe` |

**Readily implementable now (yfinance-only, live screen):** #3, #7, #20, #21; plus **quick wins**
#6 (accruals), #8 (interest coverage), #11 (growth factor) that only need populating existing
snapshot fields and adding an extractor. A **true ROCE (#1)** and basic working-capital ratios
(#9) are implementable via the statement APIs but with shallow-history caveats and only as
*current-snapshot* screens.

**Blocked by data gaps (need External sources):** #4 (real 5-yr PEG), #13 (contingent liabilities),
#15 (**pledge %**), #16 (RPTs), #17 (order book/L1), #18 (auditor changes), authoritative #14
(promoter holding), and India-side #19 (SEBI insider). Several of these are precisely the expert's
differentiating "governance red-flag" screens — so a V2 that is faithful to the strategy **must add
at least one India fundamentals/disclosure connector** (screener.in, Tijori/Trendlyne, or BSE/NSE
filing parsers).

---

## 6. Backtesting feasibility & risks

### 6.1 What the `backtest` command actually does today

`src/cli.py:backtest` → `src/backtest/engine.py:run_backtest`:

- **Inputs:** `--profile` (for ticker universe + LT tax rate + transaction cost), `--universe`,
  `--start` (default `2020-01-01`), `--top` (equal-weight N), `--benchmark`. Transaction cost is
  **not** a flag — read from `return_model.transaction_cost_bps`. Rebalance is **quarterly and
  hardcoded**.
- **Universe:** built from `_candidate_pool` = the **current** seed/live constituents (§4
  survivorship problem).
- **Ranking proxy (hardcoded):** `score = mom12 + 0.5*mom6 − 0.3*sd` — i.e. **12-1m + 6-1m momentum
  minus recent volatility**. **No fundamentals whatsoever.** The engine's own docstring says so:
  *"Price-only proxy for the composite… No point-in-time fundamentals used."*
- **Mechanics:** intersect common trading dates across tickers, quarterly rebalance to top-N,
  subtract turnover×cost, apply the profile's long-term tax rate to year-end realized gains, output
  an Excel (Summary/EquityCurve/Holdings) with Sharpe, Sortino, max drawdown, total/annualized
  return.

### 6.2 Can it answer "would this strategy have caught multibagger X beforehand?"

**No — not the *fundamental* strategy.** As shipped, the backtest is a **momentum/low-vol** portfolio
simulator. It does not evaluate ROCE/PEG/FCF/pledge or any of the expert's fundamental picks, so it
cannot verify that a *fundamental* screen would have flagged a multibagger before its run-up. At
best it tells you whether a **price-momentum** rule would have.

The related `src/factors/decay.py` is also **not** a backtest: it computes a single
top-minus-bottom-quintile 12-1m spread on the *current* universe as a regime warning — one window,
no walk-forward, no fundamentals.

### 6.3 Explicit bias & data risks

- **Look-ahead bias (fundamentals):** yfinance statements are latest/restated and dated by fiscal
  period, not by availability date. Any fundamental backtest built naively on them would "see" data
  months early and use restated numbers — inflating results.
- **Look-ahead bias (`.info`):** trailing ratios can't be time-traveled at all; there's no PIT
  snapshot to reconstruct.
- **Survivorship bias:** universe = today's index members; losers/delistings are excluded. The
  engine even notes it silently drops delisted names. This alone can turn a mediocre strategy into a
  great-looking one.
- **Short fundamental history:** ~4 annual / ~5 quarterly periods can't support 5-yr CAGR / trend
  techniques or a decade-long walk-forward.
- **Universe realism:** seed lists are tiny (India = 50 names) and static; broader indices fall back
  to the seed unless the live fetcher succeeds — narrow, current-biased test bed.
- **No transaction realism beyond a flat bps** and equal-weight; no slippage/impact for the
  small/mid caps where multibaggers live.

### 6.4 Realistic backtest approach given the limits

1. **Short term (honest, cheap):** keep/extend the existing **price-only** backtest as a
   *momentum baseline only* and label it as such. It cannot validate the fundamental thesis.
2. **Medium term (the real answer):** build a **point-in-time fundamentals panel** — periodically
   snapshot screener.in / exchange filings (pledge %, promoter holding, statements) into a dated,
   append-only store, and record **historical index membership** to kill survivorship bias. Then add
   a fundamental scoring path to `backtest/engine.py` that, at each rebalance date, uses only data
   *stamped on or before that date*. This is the only way to answer "would it have caught X early."
3. **Interim validation for named multibaggers:** for a *specific* stock the user cares about,
   do a **manual/semi-automated event study** — reconstruct the fundamentals from that stock's
   historical annual reports/screener snapshots at chosen past dates, run the (new) fundamental
   screen on that vintage, and check whether it would have passed *before* the run-up. This sidesteps
   the missing universe-wide PIT panel but is per-name and labor-intensive; treat results as
   anecdotal, not statistical.
4. **Always report** survivorship/look-ahead caveats alongside any fundamental backtest number, the
   way the current engine already annotates its Summary sheet.

---

## 7. Deliverable

Report written to: `C:\Users\SURFACE\Projects\finance-research-agent\docs\FRA_V2_FEASIBILITY.md`
(this file).
