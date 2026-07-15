# FRA V2 — Multibagger Research Brief (free-data build guide)

> **Status:** Research only. No source code was modified to produce this document.
> This is the actionable brief a Phase-4 implementation worker can build from,
> using **only free / open resources**, to improve the FRA "Multibagger Quality
> Score" (`docs/FRA_V2_STRATEGY.md`) and make its historical validation
> point-in-time (PIT) safe.
>
> **Companion docs (pre-existing, unaltered):** `FRA_V2_STRATEGY.md` (7-pillar
> spec), `FRA_V2_FEASIBILITY.md` (data inventory), `FRA_V2_AUDIT.md` (adversarial
> audit — findings C1/H1/H2), `FRA_V2_BACKTEST_PLAN.md` + `FRA_V2_BACKTEST_RESULTS.md`
> (the as-of event study already executed).
>
> **The end objective:** identify multibagger stocks (esp. Indian NSE/BSE small/
> mid caps) *ahead of time*, and validate that ability against historical
> multibaggers **without look-ahead or survivorship bias**.

---

## 0. Where the repo already is (so we don't re-solve solved problems)

Reading the source (`src/factors/multibagger.py`, `src/factors/forensic.py`,
`src/data/provider.py`, `src/backtest/asof.py`, `src/backtest/engine.py`) shows
the strategy is **substantially implemented already**. What exists:

- **7-pillar scorer** with sector-relative percentiles, coverage-shrink, and the
  hard red-flag veto pass (`rank_multibagger`, `run_veto_pass`).
- **Tier-B statement enrichment** (`get_financials` + `enrich_snapshot_with_financials`):
  true ROCE + series, gross profitability (Novy-Marx), Sloan accruals, true FCF +
  sign-rate, CFO/NP multiyear, working-capital days + deltas, interest coverage,
  asset turnover, capex intensity, shareholder yield, earnings CAGR + PEG.
- **Forensic scores**: Beneish M-Score and Altman Z″-EM (`forensic.py`), wired to
  vetoes RF3/RF4.
- **A PIT event-study harness** (`src/backtest/asof.py`): `as_of_financials()`
  truncates statements to periods reportable on/before `screening_date − 90d`,
  `build_asof_snapshot()` discards live `.info` and rebuilds valuation from as-of
  price × as-of EPS, and `score_one()` ranks one name against an as-of peer panel.
- **A completed backtest** (`FRA_V2_BACKTEST_RESULTS.md`) whose dominant finding is
  a **data** finding: yfinance carries only ~4–5 recent fiscal years, so under a
  strict PIT reading **100% of the 26 curated multibaggers are INDETERMINATE** for
  screening dates in 2010–2019 — the free data cannot reconstruct their pre-run
  fundamentals.

**Therefore the highest-leverage remaining work is not more ratios — it is
free data that is (a) deeper in history and (b) India-specific governance
(pledge/holding/auditor), plus (c) macro/regime features (entirely absent
today), and (d) a survivorship-free historical universe.** Everything below is
prioritized against that reality.

**Audit findings this brief must reconcile (per the task):**
- **C1** — scoring is not point-in-time (fundamentals fetched "as of now").
- **H1** — the ROCE/ROE *level* leg uses the latest year, not a multi-year mean.
- **H2** — cross-statement fiscal-year alignment is *positional* (`_tail_align` /
  negative-index), not *date-matched*.

(The audit doc's own numbering additionally flags H-1 = survivorship peer panel,
M-1 = ROCE numerator uses yfinance "EBIT" incl. non-operating income, M-2 =
endpoint-CAGR fragility. These are folded into the recommendations below.)

---

## 1. Executive summary

1. **The binding constraint is historical-fundamental depth + PIT, not signal
   design.** The single biggest free-data unlock is a **screener.in / BSE-NSE
   scrape** that yields ~10 years of annual statements and ~13 quarters (vs
   yfinance's ~4–5y), which simultaneously (a) lets the 5-year consistency
   operators actually run on 5+ years and (b) makes the historical event study
   determinate rather than ~100% INDETERMINATE. It is *restated*, not
   as-first-reported, so residual restatement bias remains and must be declared.

2. **True PIT requires you to build it going forward.** No free source gives
   as-first-reported (unrestated) India fundamentals timestamped by filing date.
   The only honest free path is an **append-only, dated snapshot store** you
   populate from today onward (quarterly), plus the ~90-day reporting-lag gate
   already in `asof.py`. Use Wayback-Machine captures of screener pages for
   opportunistic backfill (spotty).

3. **India governance data (pledge / promoter-holding trend / auditor changes) is
   now free and programmatic** via NSE/BSE shareholding-pattern endpoints and
   screener.in scrapers — today these feed RF6/RF7 only as *manual* inputs. The
   backtest showed ~half of all destroyer rejections depend on those manual
   flags, so **automating them is the highest-value governance win.**

4. **Survivorship-free universe is a free download.** A rolling-20y Nifty-50
   constituents dataset and a Wikipedia change-log reconstruction method both
   exist; combined with delisted-name bhavcopy prices they fix the survivorship
   half of audit H-1.

5. **Macro/regime is missing entirely and is cheap to add.** Repo rate, USD/INR,
   Brent/WTI, India 10Y G-Sec, India VIX, and FII/DII net flows are all free
   (FRED + yfinance + NSE/NSDL) and encode into a handful of PIT-safe regime
   features and veto/entry filters.

6. **A few small correctness fixes close the audit gaps** (H1 multi-year level,
   H2 date-matched alignment, M-1 operating-income numerator) — cheap, high-trust.

### 1.1 Top ~10 recommended free-data features (prioritized)

Priority = (expected value) × (feasibility) given the repo's current state.
"Maps-to" points at the concrete file/function to change.

| # | Feature | Formula / definition | Free data source | Maps-to (existing/new) | Expected value | PIT caveats |
|---|---|---|---|---|---|---|
| 1 | **Deep fundamental history (10y annual / 13q)** | replace shallow yfinance statements with screener.in P&L/BS/CF tables | screener.in scrape (`screenercli`, `openscreener`, `screener-ai-tool`); BSE/NSE XBRL | new source behind `DataProvider.get_financials()` (same dict schema) | Unlocks real 5y consistency (P2/P3/E3/E6), makes event study determinate | Restated, not as-first-reported; needs reporting-lag gate; scrape TOS/rate limits |
| 2 | **Promoter pledge %** (auto) | pledged shares / promoter holding; & / total capital | NSE/BSE shareholding-pattern; `dalal.shareholding()`, screener scrapers | populate `snap.promoter_pledge_pct` → RF6 / G1 | Automates the #1 India red flag (death-spiral) now manual-only | Only ~current + a few quarters back; historical pledge hard to backfill |
| 3 | **Promoter-holding trend** (auto) | Δ promoter stake over 4–8 quarters | same shareholding source | `snap.promoter_holding_trend` → G2 | Conviction/de-risking signal; feeds governance pillar | Quarterly cadence; renamed/merged entities break history |
| 4 | **Survivorship-free universe + PIT membership** | index constituents *as of* each rebalance | HuggingFace `AMP4010/Historical_Nifty_50_Constituent_Weights_20Y`; Wikipedia change-log method; delisted prices via NSE bhavcopy (`jugaad-data`) | new `data/universe_pit.py`; feed `backtest` peer panel | Fixes survivorship half of audit **H-1**; puts losers back in the test | Only Nifty-50/large free w/ history; small-cap PIT membership still hard |
| 5 | **Piotroski F-Score (0–9)** | 9 binary tests (profitability, leverage/liquidity, efficiency) | statements (source #1) | new signal in `multibagger.py` earnings-quality/quality pillar | Adds a well-evidenced composite the repo lacks; complements accruals | Needs t vs t-1 → date-match (audit **H2**) |
| 6 | **Magic Formula earnings yield (EBIT/EV)** | `EY = EBIT / EV`, combine-rank with ROC | statements EBIT + EV (mktcap + net debt) | replace Tier-A `earnings_yield=1/PE` (audit L-5) in `growth_valuation` | Proper Greenblatt leg (ignores capital-structure less) | EV needs as-of price & as-of net debt in backtest |
| 7 | **FII/DII net-flow regime feature** | z-score of rolling FII & DII net cash | NSE FII/DII report; `fii-diidata.mrchartist.com` free JSON; NSDL/CDSL | new `data/flows.py`; regime input to `macro` agent / entry filter | Cheap flow/liquidity regime proxy; timing tailwind | Provisional evening figures revised next morning — lag 1 day |
| 8 | **Macro regime filter (rates/FX/oil/yield/VIX)** | repo rate Δ, USD/INR mom+vol, Brent 5d, 10Y-2Y G-Sec spread, India VIX pct | FRED (`INTDSRINM193N`, `INDCPIALLMINMEI`) + yfinance (`USDINR=X`, `BZ=F`/`CL=F`, `^INDIAVIX`) | new `data/macro_regime.py`; `cyclical_mode`/weight tilts | Adds missing regime layer; PEG/cyclical suppression smarter | Use *release-dated* macro values; CPI/repo have publication lag |
| 9 | **India insider / bulk-block deals** | SAST/insider buys; bulk & block deal net | NSE `bulk_deals`/`block_deals` (`dalal`, `financeindia`); SEBI SAST | extend `insiders_edgar.py` pattern → `insiders_india.py` | Conviction signal (repo has US-only EDGAR today) | Deal history depth varies; map names→symbols carefully |
| 10 | **Auditor-change / forensic news flag** (proxy) | keyword hits: "auditor resignation", "qualified opinion", "SFIO/forensic" | BSE corporate-announcements API; GDELT DOC API; existing `news_gdelt` | auto-populate `snap.auditor_red_flag` → RF7 (as *proxy*, human-confirmable) | Automates the other manual veto that caught 6 destroyers | High false-positive; keep as flag-for-review, not silent veto |

**Honorable mentions (lower priority):** quarterly earnings *acceleration* /
revision momentum (from screener quarterly tables); QMJ-style composite z-scores
(needs a clean peer panel); low-vol already present via `volatility_annualized`;
contingent-liabilities / related-party — **still not feasible free** (annual-report
footnotes only; leave as Tier-C manual).

---

## 2. Factor techniques — formula, threshold, evidence, pitfall, free-computable, repo status

The `FRA_V2_STRATEGY.md` §1/§8 already documents most academic anchors well. This
section is the *implementation-oriented* view: is it computable from free data,
and does the repo already have it?

| Technique | Formula (as usable) | Threshold | Evidence | Key pitfall | Free? | Repo status |
|---|---|---|---|---|---|---|
| **Greenblatt Magic Formula** | rank(ROC=EBIT/(NWC+NFA)) + rank(EY=EBIT/EV) | top decile of combined rank | Beats market in Greenblatt's tests; robust in many replications | Peak-margin cyclicals look "cheap"; ignores debt/consistency | Yes (statements + EV) | **Partial** — ROCE done; EY is `1/PE` not EBIT/EV (audit L-5). **Add feature #6.** |
| **Piotroski F-Score** | 9 binary tests, sum 0–9 | ≥8 strong, ≤2 weak; ~23%/yr H−L 1976–96 | Piotroski (2000), strongest in high B/M small caps | Designed for value names; weaker in growth/large | Yes (t vs t-1 statements) | **Missing. Add feature #5.** |
| **Novy-Marx gross profitability** | GP/Assets=(Rev−COGS)/TA | higher = better (x-sec rank) | Novy-Marx (2013), predicts returns ~as well as B/M | Asset-light vs heavy sector bias → sector-relative | Yes | **Done** (`gross_profitability`). |
| **QMJ (Asness-Frazzini-Pedersen)** | z(Profitability)+z(Growth)+z(Safety)+z(Payout) | long high-Q / short junk | AFP (2019), quality earns a premium | Composite hides driver; z needs clean peers | Yes (statements) | **Partial** — pillars overlap QMJ legs but no explicit z-composite. |
| **Sloan accruals** | (NI−CFO)/TA, low better | high-accrual underperform ~10% hedge | Sloan (1996) | WC-heavy growers look "high accrual" benignly | Yes | **Done** (`accruals_ratio`, `neg_accruals`). |
| **Beneish M-Score** | 8-var model; M>−1.78 ⇒ manipulator | −1.78 (−2.22 conservative) | Beneish (1999); flagged Enron ex-ante | Breaks w/o COGS/SGA split (common in India); false-pos on growers | Yes when COGS disclosed | **Done** (`forensic.beneish_m_score`) — but **positional t/t-1 (audit H2/L-4)**. |
| **Altman Z″-EM** | 3.25+6.56X1+3.26X2+6.72X3+1.05X4 | >2.6 safe / 1.1–2.6 grey / <1.1 distress | Altman EM revision | Penalizes young growers; not for financials | Yes | **Done** (`forensic.altman_z_em`), skipped for financials. |
| **PEG / GARP (Lynch)** | PE/(100·g5) | <1 attractive | Practitioner-standard for growth-at-price | Meaningless on cyclicals/neg growth | Yes | **Done** but **endpoint-CAGR fragility (audit M-2)** — use median/regression g. |
| **FCF yield** | (CFO−Capex)/EV | positive & consistent 3–5y | Owner-earnings; hard to fake | Lumpy capex distorts single years | Yes | **Done** (`fcf_yield`, `fcf_posrate`). |
| **ROCE level + consistency** | EBIT/(TA−CL); mean−λ·stdev over 5y | ~≥18–20% & stable | Core practitioner compounder test | Single peak year misleads | Yes | **Done** — but **level = latest year (audit H1)** and numerator uses yfinance "EBIT" incl. non-op income (audit **M-1**). |
| **Size / small-cap premium** | market-cap band | Rs 200–5,000 cr for 10x headroom | Banz (1981); "multibaggers born small" | Illiquidity, higher fraud base rate | Yes | **Done** (`min_market_cap_inr_crore` floor; add upper band). |
| **Low volatility** | annualized σ of daily returns | lower = better | Low-vol anomaly | Crowded; regime-dependent | Yes | **Done** (`volatility_annualized`). |
| **Momentum (12-1, 6-1)** | trailing return ex-last-month | positive supports entry | Jegadeesh-Titman | Crashes at reversals | Yes | **Done** (`momentum_12_1/6_1`). |
| **Earnings revisions / acceleration** | ΔEPS QoQ / analyst-est revisions | positive & accelerating | Post-earnings-announcement drift | Analyst coverage thin in small caps | Partial (quarterly results yes; broker ests mostly not free) | **Missing** — computable from screener quarterly tables. |
| **Promoter pledge** | pledged/promoter holding | >20% caution, >50% veto | SEBI LODR Reg 31; Indian blow-up base rate | Not in yfinance | Yes (NSE/BSE now) | **Manual-only** → **automate (feature #2)**. |

**Takeaway:** the repo covers the profitability/quality/cash/forensic/valuation
frameworks well. The genuine *gaps* are Piotroski (#5), a proper Magic-Formula
earnings yield (#6), earnings-revision momentum, and — most importantly — the
*data depth* to make any of the multi-year variants actually fire.

---

## 3. Free data sources for Indian equities (programmatic)

### 3.1 Prices, universe, corporate actions
- **yfinance** — already used. Good adjusted daily history for *surviving* names;
  ~4–5y statements; live `.info` only (no PIT). Delisted names return nothing
  (survivorship hole).
- **jugaad-data** (`pip install jugaad-data`, ~537★, actively maintained through
  2026, supports the *new* NSE site + built-in caching) —
  https://github.com/jugaad-py/jugaad-data . Historical stock/index data, **daily
  bhavcopies** (crucial: bhavcopy archives include *delisted* names → measure
  destroyer returns and build survivorship-free price panels), F&O, and **RBI
  current rates**. This is the best free backbone for a survivorship-free Indian
  price/universe layer.
- **nsefeed** (https://github.com/shubhamnayak1708/nsefeed) / **nselib** —
  yfinance-style API over NSE archives; `constituent_stock_list(...)` gives
  *current* index members (historical index OHLC currently deprecated on NSE).
- **dalal** (`pip install dalal`, MIT, no keys — https://pypi.org/project/dalal/) —
  unified NSE+BSE: `quote`, `history`, `actions` (splits/bonus/div — important for
  clean adjustment), `shareholding()` (promoter/FII/DII), `bulk_deals`,
  `block_deals`, `announcements`, `index()` constituents, BSE `fundamentals()`
  (3-period) + `meta()` (PE/ROE/PB). One-stop for several Tier-C items.
- **indian-market-data** (https://pypi.org/project/indian-market-data/, MIT) —
  bhavcopy / indices / F&O as DataFrames, AWS-Lambda-ready, polars option.

### 3.2 Fundamentals with real history (the depth unlock — feature #1)
- **screener.in** (no official API; public pages) — ~10y annual P&L/BS/CF, ~13
  quarters, key ratios, **shareholding pattern (incl. promoter pledge)**,
  pros/cons, concall/annual-report links. Scrapers:
  - `screenercli` (https://github.com/mayur1064/screenercli) — CLI → normalized
    JSON (P&L, BS, CF, ratios, shareholding); courtesy delay + 5-min cache.
  - `openscreener` (https://pypi.org/project/openscreener/) — Playwright lib;
    `Stock("RELIANCE").shareholding`, statements, index constituent pagination.
  - `screener-ai-tool` (https://github.com/singhvedant/screener-ai-tool) — async
    lib + CLI + MCP server; bulk fetch, peers, events/announcements.
  - `screener-mcp` (https://github.com/ronyv89/screener-mcp) — MCP server, 5-min
    cache, no key.
  - `BuildAlgos/screener-scraper` — screener + **BSE corporate-announcement API**
    (auditor/results announcements) with pagination helpers.
  - **Caveat:** screener numbers are aggregated/derived and **can be wrong** — a
    well-known example is ROIC/ROCE mis-including cash in capital employed
    (https://hackmd.io/@indiainvestments/r1NY1u2XO). Prefer pulling *raw
    statement lines* and computing ratios yourself (the repo already does this),
    and cross-check against BSE/annual reports. Respect robots.txt + rate limits.
- **Tijori / Trendlyne / Tickertape** — richer ROIC/segment data but largely
  gated/anti-scrape; treat as **manual reference**, not a programmatic free feed.

### 3.3 Governance / disclosure (Tier-C, now partly free)
- **Shareholding pattern & pledge**: NSE/BSE shareholding filings, `dalal.shareholding()`,
  screener shareholding tables. Enough for *current + a few quarters*; deep
  historical pledge is not reliably backfillable free.
- **Corporate announcements / auditor changes**: BSE announcements API (via
  `screener-scraper`), NSE announcements (`dalal.announcements()`). Keyword-filter
  for auditor resignation / qualified opinion / SFIO — feed RF7 as a *proxy for
  review*, not a silent veto.
- **Bulk/block deals & SAST insider**: `dalal.bulk_deals()`/`block_deals()`,
  `financeindia` (NSE bulk deals + insider disclosures). India analogue to the
  repo's US-only EDGAR Form-4 path.

### 3.4 Free point-in-time fundamentals — honest verdict
There is **no free source of as-first-reported (unrestated), filing-dated** India
fundamentals. Options, best→worst honesty:
1. **Build your own append-only dated store** from today forward (snapshot
   screener/BSE quarterly into `data/pit/<yyyy-qq>/…`, keyed by capture date).
   Only this is truly PIT going forward.
2. **Restated deep history + reporting-lag gate** (screener 10y + the existing
   `asof.py` `−90d` rule). Determinate and cheap, but restatement bias remains —
   **must be declared** (see §6).
3. **Wayback Machine** captures of screener pages for opportunistic historical
   backfill — spotty coverage, best-effort only.

---

## 4. Macro / geopolitical / news / event signals — free proxies & PIT-safe encoding

The repo's `macro` agent produces one narrative paragraph and consumes **no
per-ticker macro numbers**; there is no regime layer. All proxies below are free.
**Golden rule: encode each signal using the value that was *published/known* on
the decision date** — CPI, repo, and flow prints have real publication lags; use
release-dated series, never the latest revision, in any historical test.

| Signal | Why it moves Indian equities | Free proxy (source) | Encoding as feature / regime filter | PIT / lookahead note |
|---|---|---|---|---|
| **Policy rate (repo)** | Discount rate; small/mid-cap & duration-sensitive re-rating | FRED `INTDSRINM193N`; RBI via `jugaad-data` | Δrepo over 6–12m; "easing vs tightening" regime flag → up-weight growth/rerating in easing | RBI decides on scheduled MPC dates — use decision-date step function |
| **Inflation (CPI)** | Real rates, margin pressure, RBI reaction fn | FRED `INDCPIALLMINMEI`; MOSPI | 3M vs 12M CPI momentum; "above 6% band" flag | CPI released ~12th of next month — lag ~2–6 weeks |
| **Crude oil (Brent/WTI)** | India imports >80% oil → CAD, imported inflation, INR | yfinance `BZ=F`/`CL=F` | 5d/20d crude momentum; sector tag: negative for OMCs/paints/aviation input cost, positive for upstream | Continuous futures — same-day, low lag |
| **USD/INR** | FX stress, FPI flows, import-cost, IT-export tailwind | yfinance `USDINR=X`, `INR=X` | INR 20d momentum + annualized vol → "FX stress" flag; up-weight exporters (IT/pharma) on depreciation | Same-day; watch weekend gaps |
| **G-Sec yield curve** | Rate expectations, risk appetite, NBFC funding | India 10Y (yfinance/Investing exports); 2Y from tenors | 10Y-2Y spread; rising 10Y = tightening flag | Daily; use close-of-day |
| **India VIX** | Risk regime / drawdown proximity | yfinance `^INDIAVIX` | VIX percentile → "risk-off" regime; raise cash / tighten vetoes when high | Same-day |
| **FII/DII net flows** | Marginal buyer of Indian equities; liquidity | NSE FII/DII report; free JSON `fii-diidata.mrchartist.com/api/*`; NSDL/CDSL | z-score of rolling net FII & DII cash; persistent FII selling = headwind flag | **Evening figures provisional**, revised next AM → lag 1 day |
| **War / conflict / geopolitics** | Oil shock, risk-off, defense/PSU tailwind | GDELT DOC/Event API (free, 1979→, 15-min); yfinance oil/gold/VIX | GDELT conflict-theme volume spike + oil/VIX co-move → risk-off regime; defense-sector positive tag | GDELT timestamped by article — dedupe, use publish date |
| **Elections / policy (PLI, import duties, China+1, privatization)** | Sector-specific structural re-rating (EMS, defense, chem, rail) | Budget/PIB docs (manual); GDELT DOC search; AION Indian Market Intelligence free tier (`sector_vector`) | Event → sector-impact tag → temporary sector-tilt / catalyst score (R4) | Use announcement date; beware post-hoc narrative fitting |
| **Sector rotation** | Multiples migrate across sectors (chem→defense→EMS) | sector median PE Δ from own universe; yfinance sector ETFs | rolling sector-median-PE momentum → R3 tailwind | Compute from PIT peer panel only |
| **Monsoon / agri** | Rural demand (autos, FMCG, fertilizer, tractors) | IMD rainfall bulletins (manual); GDELT monsoon theme | seasonal rural-demand flag for exposed sectors | Seasonal; align to IMD publish dates |
| **Commodity cycles / credit spreads** | Input costs; NBFC/credit risk | yfinance metals/energy; AAA-vs-G-Sec spread (RBI/Investing) | commodity momentum sector tags; widening credit spread = risk-off | Daily/weekly; publication lag on some RBI series |

**Recommended encoding architecture (all PIT-safe):**
- A new `src/data/macro_regime.py` builds a **daily regime vector** (rate regime,
  inflation regime, FX-stress, risk-regime from VIX, flow-regime from FII/DII),
  each as a small categorical/z-score keyed by *knowledge date*.
- Wire it two ways: (a) as an **entry/exit regime filter** (e.g. de-emphasize new
  rich-multiple picks when VIX-percentile high and FII persistently selling), and
  (b) as **profile tilts** — the existing `cyclical_mode` flag and pillar weights
  can be nudged by regime (easing → up-weight growth/rerating; tightening/high-VIX
  → up-weight balance-sheet safety + consistency).
- Keep macro **out of the per-name fundamental score** to avoid double-counting;
  use it as a *gate/tilt*, consistent with the strategy's "screens, not verdicts"
  guardrail. Existing `news_gdelt`/`news_sentiment` can supply the event tags
  (R4/G4) without new infra.

---

## 5. Curated OSINT resource list (cited, with "why useful")

### Data libraries / feeds (free)
- **jugaad-py/jugaad-data** — https://github.com/jugaad-py/jugaad-data — maintained
  NSE/RBI history + **bhavcopy incl. delisted names** (survivorship-free prices);
  the best free Indian price/universe backbone.
- **dalal** — https://pypi.org/project/dalal/ — no-key NSE+BSE: shareholding,
  bulk/block deals, announcements, corporate actions, index constituents; covers
  several Tier-C items in one lib.
- **screenercli** — https://github.com/mayur1064/screenercli — clean JSON of 10y
  screener statements + shareholding for LLM/agents; the depth unlock (feature #1).
- **openscreener** — https://pypi.org/project/openscreener/ — Playwright screener
  scraper with normalized statements + index constituent pagination.
- **screener-ai-tool** — https://github.com/singhvedant/screener-ai-tool — async
  screener lib + MCP; bulk fetch, peers, events, shareholding.
- **screener-mcp** — https://github.com/ronyv89/screener-mcp — MCP server for
  screener data (drop-in for FRA's MCP-friendly design).
- **indian-market-data** — https://pypi.org/project/indian-market-data/ — bhavcopy/
  indices/F&O DataFrames, Lambda-ready.
- **FII & DII Data API (Mr. Chartist)** — https://fii-diidata.mrchartist.com/data-api.html —
  free no-key JSON: daily FII/DII cash, F&O participant OI, PCR, NSDL fortnightly
  FPI sector allocation; ready-made flow-regime feature.
- **NSE FII/DII report** — https://nseindia.com/reports/fii-dii ; **NSDL FPI** —
  https://www.fpi.nsdl.co.in/Reports/ReportsListing.aspx ; **CDSL FPI** —
  https://www.cdslindia.com/Publications/ForeignPortInvestor.html — authoritative
  flow sources (provisional vs final).

### Universe / survivorship
- **AMP4010/Historical_Nifty_50_Constituent_Weights_20Y** (HuggingFace) —
  https://huggingface.co/datasets/AMP4010/Historical_Nifty_50_Constituent_Weights_20Y —
  survivorship-bias-free Nifty-50 membership+weights from 2008, corporate-action
  adjusted (CC BY-NC-SA; non-commercial). Directly fixes survivorship for large caps.
- **kshitijbhandari/Portfolio-Construction---Factor-Model** —
  https://github.com/kshitijbhandari/Portfolio-Construction---Factor-Model —
  reusable *method*: scrape Wikipedia change-log, walk backwards to reconstruct
  PIT Nifty-50 membership since 2006 (survivorship-free universe recipe).
- **yfiua/index-constituents** — https://github.com/yfiua/index-constituents —
  current + historical index constituents (incl. nifty50) via MediaWiki revisions +
  Wayback; monthly-archived JSON/CSV.

### Backtesting / factor frameworks
- **eslazarev/purged-cross-validation** — https://github.com/eslazarev/purged-cross-validation —
  MIT, maintained, sklearn-compatible **PurgedKFold / CombinatorialPurgedCV /
  Deflated & Probabilistic Sharpe / PBO / MinBTL**; the exact PIT-validation toolkit
  for §6 (avoids buggy hand-rolled CV; superior to sklearn's single-`gap`
  `TimeSeriesSplit`).
- **marketcalls/vectorbt-backtesting-skills** — https://github.com/marketcalls/vectorbt-backtesting-skills —
  vectorbt templates with **realistic Indian transaction-cost models** (delivery
  0.111% etc.), NIFTY benchmarking, QuantStats tearsheets, walk-forward rules.
- **jeevanba273/Factor-Model-and-Smart-Beta-Portfolio-Builder** —
  https://github.com/jeevanba273/Factor-Model-and-Smart-Beta-Portfolio-Builder —
  NSE factor backtester (CAGR/Sharpe/Sortino/MDD vs NIFTY), corporate-action adjusted.
- **Mohit1053/indian-stock-backtesting** — https://github.com/Mohit1053/indian-stock-backtesting —
  fundamental scoring (Nifty-50, 14 metrics, 10y) + technical engine (2600+ stocks);
  a comparable fundamental-scoring reference.
- **qlib** (Microsoft), **vectorbt**, **backtrader**, **zipline-reloaded** — general
  factor/backtest frameworks; qlib notably has PIT-fundamental plumbing worth
  studying for the append-only store design (feature #1 / §6).

### Regime / macro
- **JatinNavani/MacroTerminal** — https://github.com/JatinNavani/MacroTerminal —
  reference impl: FRED (India CPI/repo) + yfinance (NIFTY/USDINR/VIX/crude) →
  regime classifier (inflation momentum, rates impulse, FX stress, risk regime).
  Direct blueprint for `macro_regime.py` (feature #8).
- **naman-n-choudhary/Market-Regime-Liquidity-Model** —
  https://github.com/naman-n-choudhary/Market-Regime-Liquidity-Model — HMM regime
  detection on NIFTY/India-VIX/G-Sec + RBI LAF liquidity.
- **AION Indian Market Intelligence** — https://github.com/AION-Analytics/aion-indian-market-intelligence —
  free-tier API mapping Indian headlines → `sector_vector` (policy/oil/monsoon/FX
  → sector impact); optional enrichment for R4 policy catalysts (external dependency).
- **GDELT** — https://www.gdeltproject.org/ — free global event/news DB + DOC/GEO
  JSON APIs; conflict/policy/monsoon theme volume for geopolitical regime tags.

### Practitioner checklists (skeptical read — heuristics, not evidence)
- **Zerodha Varsity — Investment Due Diligence** — https://zerodha.com/varsity/chapter/investment-due-diligence/ —
  a defensible 10-point quality checklist (GPM>20%, low debt, DCF valuation).
- **Smallcap Quality 20-point checklist** — https://smartinvestingindia.com/2025/10/26/smallcap-quality-checklist-for-india-a-20-point-framework-to-avoid-value-traps-%f0%9f%8e%af/ —
  OCF/Profit>0.9, D/E<0.5, interest coverage>3x, pledge red flags — aligns with the
  repo's vetoes; useful for threshold sanity, ignore the hype/return anecdotes.
- **Univest multibagger frameworks** — https://univest.in/blogs/how-to-find-multibagger-stocks —
  common screener thresholds (ROCE>20%, rev CAGR>20%, D/E<0.5, promoter>45% zero
  pledge, PEG<1, mcap Rs200–5,000cr). Popular retail consensus; treat as priors.
- **"Don't trust your stock screener blindly"** — https://hackmd.io/@indiainvestments/r1NY1u2XO —
  documents concrete ROIC/ROCE errors on screener.in/Morningstar (cash in capital
  employed). **Critical:** compute ratios from raw lines yourself (repo already does).

---

## 6. PIT-safe validation methodology (evaluating a multibagger screener)

The existing `FRA_V2_BACKTEST_PLAN.md` is already an honest event-study plan; this
section adds the *statistical-rigor* layer and the full-universe path.

### 6.1 Principles (avoiding the four biases)
- **Look-ahead / restatement bias.** Never let a fiscal period enter a snapshot
  before it was *knowable*. Keep the `asof.py` `screening_date − 90d` reporting-lag
  gate. Prefer **as-first-reported** values (append-only store, §3.4-1); if using
  restated screener depth, **label results "restated-vintage upper bound."** Never
  use live `.info` in a historical score (`build_asof_snapshot` already discards it).
- **Survivorship-free universe.** Rank each name only against **contemporaneous PIT
  constituents** (feature #4), and *include delisted losers* (bhavcopy prices) so
  the negative class is actually present when tested — the current backtest's
  destroyers were mostly INDETERMINATE precisely because they'd delisted.
- **Reporting-lag alignment.** Align features to *knowledge date*, not period-end
  (fundamentals) or article date (news/macro).
- **Walk-forward + purged/embargoed CV.** For any parameter/threshold tuning, use
  **Combinatorial Purged CV** with an embargo ≥ the max label horizon (multibagger
  labels look forward *years*, so embargo generously) to kill label leakage; report
  a **distribution** of paths, not one equity curve. Use
  `eslazarev/purged-cross-validation` rather than hand-rolling.
- **Multiple-testing honesty.** Report the **Deflated Sharpe Ratio** and
  **Probability of Backtest Overfitting**, deflated by the number of
  configurations actually tried (not the number of CPCV paths). Check
  **MinBTL** — if your backtest is shorter than the minimum track record length,
  a high Sharpe is likely selection luck.

### 6.2 How to measure a screener's ability to catch multibaggers
Keep the two classifiers **separate** (as the plan already does):
- **Recall / hit-rate** on known winners: of true multibaggers, what fraction did
  the screen retain (no veto, cleared the gate) *before* the run.
- **Specificity / rejection rate** on known destroyers: fraction correctly vetoed.
- **Base-rate & lift (the missing piece).** The curated event study cannot estimate
  precision. To get real predictive value you need a **full-universe walk-forward**:
  at each PIT rebalance, screen *every* eligible name, then measure
  - **precision / base rate**: of names the screen flagged, what fraction went on to
    ≥Nx over the horizon, vs the unconditional base rate of ≥Nx in that universe;
  - **lift** = P(multibagger | flagged) / P(multibagger) — the honest headline;
  - **decile spread**: forward returns of top vs bottom composite decile
    (top-minus-bottom), the classic factor-efficacy view (the repo's `decay.py`
    already computes a one-shot 12-1 quintile spread — generalize it to walk-forward);
  - **veto attribution**: which red flag caught which blow-up (untriggered vetoes are
    *untested*, not "safe").
- **Report with n, CIs, and the standing caveat** from the plan §6 — never quote a
  blended "accuracy" or convert historical recall into a forward probability.

### 6.3 Reconciliation with audit findings C1 / H1 / H2

**C1 — not point-in-time (the critical one).**
- *Already partly addressed* by `src/backtest/asof.py` (`as_of_financials` + the
  `−90d` gate + `.info`-discarding `build_asof_snapshot`). The **residual gaps**
  are: (i) only ~4–5y of yfinance statements exist, so pre-2022 dates are
  INDETERMINATE — **fixed by feature #1 (screener depth)**; (ii) restated (not
  as-first-reported) values — **only fully fixed by the append-only store
  (§3.4-1)**; (iii) `DataProvider.get_financials()` in the *live* path still has no
  `as_of` — recommend adding an optional `as_of: date | None` that internally calls
  `as_of_financials`, so live and backtest share one gate. Until (ii) exists, any
  historical number stays a **restated-vintage upper bound**, stated explicitly.

**H1 — ROCE/ROE *level* leg uses the latest year, not a multi-year mean.**
- In `multibagger.py`, `roce_level = s.roce` (= `roce_series[-1]`) and
  `roe_level = s.roe` (TTM). This lets a single peak year drive the highest-weighted
  pillar — contrary to the spec's "consistency > peak" guardrail.
- **Fix:** define the level leg as a **multi-year central tendency** —
  `series_mean(roce_series)` (or median, more robust to a spike), keeping
  `roce_stability`/`roce_trend`/`roce_min` as the consistency legs. Add
  `roe_series`-based level once deep history (feature #1) is wired (the field
  already exists but is unused by the pillar). This is a 1-line-per-signal change in
  `SIGNAL_EXTRACTORS` and materially de-noises Pillar 1. (Relatedly, audit **M-1**:
  make the ROCE numerator *operating income*, not yfinance "EBIT" incl. non-op
  income — reorder aliases in `enrich_snapshot_with_financials` `_pick(...)`.)

**H2 — cross-statement alignment is positional, not date-matched.**
- `_tail_align` trims income/balance/cashflow to a **common tail length** and
  `forensic.beneish_m_score` indexes by `-1/-2`. If the three statements return
  different period *counts* or misaligned fiscal ends (common once you mix screener
  + yfinance, or hit a stub/transition year), the t-1 Beneish terms and the
  ROCE/accruals joins can pull **mismatched fiscal years**.
- **Fix:** align by **matching period-end dates** before computing — intersect the
  `income_periods` / `balance_periods` / `cashflow_periods` date lists, build a
  date→value map per line item, and compute t and t-1 from the *same* fiscal-end
  date across statements. `asof.py` already carries per-statement period lists, so
  the fix is local to `enrich_snapshot_with_financials` and `beneish_m_score`
  (pass aligned dict/series keyed by date). This becomes **essential** once deep
  multi-source history (feature #1) is introduced, because vendors won't agree on
  period counts.

**Also reconcile audit H-1 (survivorship peer panel) and M-2 (CAGR fragility):**
H-1 is handled by feature #4 (PIT membership + delisted names in the panel). M-2
(endpoint CAGR driving PEG/RF8) → switch `_cagr` to a **median-anchored or OLS
regression growth** and stop collapsing interior `None`s before aligning
(preserve positional alignment) — this also removes the DEEPAKNTR/SRF-style RF8
false positives seen in the backtest.

---

## 7. Suggested implementation sequence (for the Phase-4 worker)

1. **Feature #1 (deep history behind `get_financials`)** — biggest single unlock;
   everything multi-year depends on it. Keep the existing return-dict schema so
   `enrich_snapshot_with_financials` and `asof.py` are untouched.
2. **Audit fixes H1 / H2 / M-1 / M-2** — cheap, high-trust, and *required* before
   depth data amplifies the bugs.
3. **Features #2/#3 (pledge + promoter trend auto)** and **#10 (auditor/announcement
   proxy)** — automate the governance vetoes that carried ~half the destroyer
   rejections.
4. **Feature #4 (survivorship-free PIT universe)** + fold delisted bhavcopy prices
   into the backtest panel.
5. **Features #7/#8 (FII/DII flow + macro regime)** as a gate/tilt layer.
6. **Features #5/#6 (Piotroski, Magic-Formula EY)** — additive signals.
7. **§6 statistical layer** — swap ad-hoc validation for CPCV + Deflated Sharpe +
   PBO; generalize `decay.py` to a walk-forward decile-spread.
8. **§3.4-1 append-only PIT store** — start capturing now so a *true* PIT
   full-universe walk-forward becomes possible in future.

## 8. What is explicitly NOT feasible for free (call it out)
- **As-first-reported (unrestated), filing-dated** India fundamentals for the past —
  build-your-own-forward only.
- **Contingent liabilities, related-party transactions, order book / L1 wins,
  segment detail** — annual-report footnotes only → remain **Tier-C manual**.
- **Deep historical promoter-pledge** time series — current + a few quarters at best.
- **Reliable analyst estimate revisions** for small caps — mostly gated/paid.
- **Point-in-time membership for small/mid-cap indices** (Nifty-500/BSE-500) with
  long history — only large-cap (Nifty-50) is cleanly free; small-cap PIT universe
  is the residual survivorship gap.
- **Screener/vendor derived ratios are not trustworthy** as-is (ROIC/ROCE errors) —
  always recompute from raw lines.

## 9. Key citations (URLs inline above; primary academic anchors)
- Greenblatt (2005), *The Little Book That Beats the Market* — Magic Formula.
- Piotroski (2000), *J. Accounting Research* 38 — F-Score.
- Novy-Marx (2013), *JFE* 108(1) — gross profitability.
- Asness, Frazzini, Pedersen (2019), *Rev. Acc. Studies* 24 — QMJ.
- Sloan (1996), *The Accounting Review* 71(3) — accruals anomaly.
- Beneish (1999), *Financial Analysts Journal* — M-Score (M > −1.78).
- Altman (1968; EM revision 1995) — Z″-EM; zones 2.6 / 1.1.
- Lynch (1989), *One Up on Wall Street* — PEG / GARP.
- Banz (1981) — size premium.
- López de Prado (2018), *Advances in Financial Machine Learning*, ch. 7 (purge/
  embargo) & ch. 12 (CPCV); Bailey & López de Prado (2014) — Deflated Sharpe Ratio.
  Purged-CV overview: https://en.wikipedia.org/wiki/Purged_cross-validation ;
  method notes: https://github.com/eslazarev/purged-cross-validation/blob/main/docs/methodology.md
- SEBI LODR Reg. 31 + 07-Aug-2019 pledge-disclosure circular (≥50% of promoter
  holding or ≥20% of total capital).

*(Data-source and OSINT URLs are cited inline in §3–§5. Practitioner threshold
conventions in §2/§5 are heuristics, not peer-reviewed evidence, and are labeled
as such.)*








