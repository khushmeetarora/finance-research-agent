# FRA V2 — Multibagger Quality Strategy Spec

> **Status:** Phase 1 (research + design). **No code changes.** This document is
> the quantitative blueprint for a "multibagger-focused" scoring mode that Phase 2
> can implement directly against the existing FRA factor engine
> (`src/factors/engine.py`, `src/factors/metrics.py`, `src/data/provider.py`).
>
> **Origin of ideas:** an Indian equity practitioner's "multibagger" checklist
> (ROCE consistency, correct P/E use, PEG, FCF, working-capital traps, earnings
> quality, moats/pricing power, promoter behaviour, capital allocation, re-rating
> triggers). Each qualitative technique below is mapped to a **computable signal**
> and cross-referenced to an **established academic/practitioner analogue**.

---

## 0. How this fits the existing FRA engine

FRA today scores 5 factors (`quality`, `value`, `momentum`, `financial_health`,
`earnings_quality`) by:

1. extracting per-metric values from a `CompanySnapshot` (`metrics.py`),
2. **percentile-ranking each metric across the candidate universe** (`scoring.py`),
3. averaging metric percentiles into a factor score, then
4. weighting factors per profile and **coverage-shrinking** the composite toward
   the universe median 0.5 (`engine.py:rank_universe`).

**Critical data reality (grounds every "data-availability" note below):** the
snapshot is built almost entirely from yfinance's **point-in-time `info` dict
(TTM values)** plus 2y of price history and a Stooq close cross-check
(`provider.py:get_snapshot`). It contains **no multi-year statement history**.
Therefore every "**consistency over N years**", "trend", or two-period index
(Piotroski deltas, Beneish, Altman retained-earnings, working-capital days,
true FCF = CFO − Capex) is **not computable today** and requires a Phase-2
enrichment that pulls yfinance annual statements
(`Ticker.income_stmt`, `.balance_sheet`, `.cashflow`; ~4 fiscal years, sometimes
quarterly). These are **free but not yet wired**. Data that is neither in `info`
nor in yfinance statements (promoter pledge, related-party txns, contingent
liabilities, auditor changes, order book) is **hard-blocked** from free sources
and is marked optional/manual-input with a proxy where one exists.

The V2 mode reuses the **same percentile-rank + weight + coverage-shrink
machinery**; it only adds (a) new metric extractors, (b) a 7-pillar weight
vector, (c) sector-relative normalization, and (d) a **hard red-flag veto pass**
applied *after* ranking.

**Data tiers used throughout:**

- **Tier A — computable now** (in the current `info`-based snapshot).
- **Tier B — computable after statement enrichment** (yfinance annual/quarterly
  statements; free, needs a new fetch in `provider.py`).
- **Tier C — data-blocked from free sources** (needs NSE/BSE shareholding
  filings, screener.in-style scrapes, annual-report notes, or manual input);
  a computable proxy is proposed where possible.

---

## 1. Academic & practitioner backing (with pitfalls)

| Framework | Core formula (as we will use it) | What it captures | Typical threshold | Known pitfalls |
|---|---|---|---|---|
| **Greenblatt Magic Formula** (Greenblatt, *The Little Book That Beats the Market*, 2005) | Rank on **ROC = EBIT / (Net Working Capital + Net Fixed Assets)** and **Earnings Yield = EBIT / EV**; combine ranks | High return on capital bought cheap | Top decile of combined rank | Cyclicals game the "cheap" leg at peak margins; ignores debt quality & consistency |
| **Piotroski F-Score** (Piotroski, *J. Accounting Research*, 2000) | 9 binary tests (profitability, leverage/liquidity, efficiency); sum 0–9 | Fundamental-strength filter, esp. within value names | 8–9 strong, 0–2 weak; ~23%/yr high-minus-low 1976–96 | Designed for **high book-to-market** names; weaker in growth/large-cap; macro-sensitive |
| **Novy-Marx gross profitability** ("The Other Side of Value", *JFE*, 2013) | **GP/Assets = (Revenue − COGS) / Total Assets** | Cleanest raw profitability; predicts returns ~as well as B/M; hedges value | Higher = better; cross-sectional rank | Sector-sensitive (asset-light vs heavy); needs COGS (Tier B) |
| **Quality-Minus-Junk / QMJ** (Asness, Frazzini, Pedersen, *Rev. Accounting Studies*, 2019) | Quality = z(Profitability) + z(Growth) + z(Safety) + z(Payout) | "Quality at a reasonable price"; multi-dimensional quality earns premium | Long high-Q / short junk | Composite hides which leg drives it; z-scores need a clean peer set |
| **Sloan accrual anomaly** (Sloan, *The Accounting Review*, 1996) | **Accruals = (NI − CFO) / Total Assets**; low = better | Earnings quality: cash-backed earnings persist, accruals don't | High-accrual firms underperform (~10% hedge) | Working-capital-heavy growers look "high accrual" for benign reasons; needs CFO (Tier B) |
| **Beneish M-Score** (Beneish, *Financial Analysts Journal*, 1999) | 8-var model (see §3.6). **M > −1.78 ⇒ likely manipulator** | Forensic earnings-manipulation flag | −1.78 threshold (−2.22 conservative; grey zone between) | Needs t and t-1 statements; **breaks when COGS/SGA not split** (common in India — GMT could not compute for most Indian names); false positives on fast growers |
| **Altman Z″ (EM) score** (Altman, 1968; EM revision 1995) | **Z″ = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4** (see §3.8) | Bankruptcy / financial-distress screen for non-manufacturers & emerging markets | **>2.6 safe, 1.1–2.6 grey, <1.1 distress** | Retained-earnings term penalizes young high-growers; not for banks/financials |
| **PEG / GARP** (Lynch, *One Up on Wall Street*, 1989) | **PEG = PE / (5y earnings-growth % )** | Growth-adjusted valuation | <1 attractive, ~1 fair, >2 rich | Meaningless on cyclicals & negative growth; ignores debt & quality of growth |
| **FCF yield** (practitioner standard) | **FCF yield = (CFO − Capex) / EV (or MktCap)** | Owner cash return; harder to fake than EPS | Positive & consistent 3–5y; higher = better | Lumpy capex distorts single years; buybacks vs value-destroying M&A matter |
| **Promoter pledge red flag** (SEBI LODR Reg. 31; SEBI circular 07-Aug-2019) | Pledged % of promoter holding; disclosure trigger at **≥50% of promoter holding or ≥20% of total capital** | Governance / forced-selling ("death spiral") risk | >20% institutional exclusion; >50% critical | **Not in yfinance** — NSE/BSE quarterly shareholding only (Tier C) |
| **Sector-relative valuation** (industry practice) | z-score / percentile **within GICS sector** rather than whole market | Prevents comparing a bank PE to an FMCG PE | Rank within `sector` bucket | Thin sectors → unstable peer stats; needs a fallback |

Pitfall meta-lesson used in the design: **every one of these is a screen, not a
buy signal, and each fails on cyclicals or without sector context.** The
composite (§4) therefore blends pillars, normalizes within sector, and rewards
**consistency**, never ranking on a single peak-year metric.

---

## 2. Signal-by-signal table (technique → formula → inputs → data tier → direction)

> `t` = latest fiscal year; `t-k` = k years back. "Consistency" measures use the
> last **N = 5** fiscal years (fall back to N available, min 3; flag if < 3).
> All continuous signals are converted to a universe **percentile in [0,1]** and,
> where marked, **within the GICS `sector`** (see §5).

### 2.1 Profitability & efficiency

| # | Technique | Signal / formula | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| P1 | ROCE level | `ROCE = EBIT / (Total Assets − Current Liabilities)` (capital employed). Fallback to existing ROIC proxy `EBITDA/(Equity+Debt)` | EBIT, total assets, current liab. | B (A via proxy) | ↑ bullish; sector-relative |
| P2 | **ROCE consistency** (expert's core) | `ROCE_consistency = mean(ROCE_{t..t-4}) − λ·stdev(ROCE)` with λ≈1; also report `min(ROCE)` and `slope`. Stable-high beats spiky | 5y EBIT & capital employed | B | high mean + **low stdev** bullish; falling slope bearish |
| P3 | ROE level & consistency | `ROE = NI/Equity`; same mean − λ·stdev over 5y | 5y NI, equity | A (level) / B (series) | ↑; penalize if ROE inflated by leverage (cross-check D/E) |
| P4 | Gross profitability (Novy-Marx) | `GP/Assets = (Revenue − COGS)/Total Assets` | Revenue, COGS, assets | B | ↑ bullish; sector-relative |
| P5 | DuPont sanity | Decompose `ROE = margin × turnover × leverage`; flag ROE driven mostly by leverage | NI, revenue, assets, equity | B | leverage-driven ROE = caution |

### 2.2 Earnings quality & cash

| # | Technique | Signal / formula | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| E1 | Cash conversion (existing) | `CFO / Net Income` (TTM now; 5y avg after enrichment) | CFO, NI | A (1y) / B (5y) | ≥0.8 bullish; <0.5 bearish |
| E2 | **Accruals (Sloan)** | `Accruals = (NI − CFO)/Total Assets`; **low/negative = better** | NI, CFO, assets | B | low bullish; high bearish |
| E3 | **Free Cash Flow (true)** | `FCF = CFO − Capex`; report **sign-consistency**: `#(years FCF>0)/N` over 5y | CFO, Capex (5y) | B | positive & consistent bullish |
| E4 | FCF yield | `FCF / EV` (or `/MktCap`) | FCF, EV | B (A-ish: `info.freeCashflow` exists but is a single TTM figure) | ↑ bullish |
| E5 | **FCF use quality** | classify: dividends/buybacks (↓ share count) = good; rising goodwill / unrelated acquisitions = bad | dividends paid, buyback (Δshares), goodwill Δ | B (goodwill/acq intent partly C) | disciplined return of cash bullish |
| E6 | **OCF vs Net Profit divergence** (working-capital trap) | `cum(CFO)_{5y} / cum(NP)_{5y}`; and 1y `CFO/NP` | 5y CFO, NP | B | <0.5 persistent = **red flag** (see §6) |
| E7 | Tax paid vs provision | `cash tax paid / tax expense`; large persistent gap = aggressive accounting | tax expense (P&L), tax paid (cashflow) | B (tax-paid line often sparse in yfinance) → partly C | ratio ≪1 bearish |
| E8 | One-time gains / "other income" spike | `other_income_t / mean(other_income_{t-1..t-3})`; and share of PBT from non-operating | other income line | B (line sometimes missing) → partly C | spike bearish (quality of earnings ↓) |

### 2.3 Working-capital diagnostics

| # | Technique | Signal / formula | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| W1 | Debtor Days | `DSO = 365 · Receivables / Revenue`; use **Δ over 5y** | receivables, revenue | B | rising bearish |
| W2 | Inventory Days | `DIO = 365 · Inventory / COGS`; Δ over 5y; separate **seasonal (quarterly pattern) vs structural (rising trend)** | inventory, COGS | B | structural rise bearish |
| W3 | Payable Days (DPO) | `DPO = 365 · Payables / COGS`; **higher = bargaining power**, but *falling* DPO while DSO/DIO rise = squeeze | payables, COGS | B | high stable DPO bullish; falling DPO + rising DSO/DIO **combined = trap** |
| W4 | Cash conversion cycle | `CCC = DSO + DIO − DPO`; Δ over 5y | above | B | rising CCC bearish |

### 2.4 Growth & valuation / PEG

| # | Technique | Signal / formula | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| V1 | Earnings growth (5y) | `g = CAGR(EPS_{t-4..t})` (prefer normalized/median-year to blunt base effects) | 5y EPS | B (A: 1y `earningsGrowth`) | ↑, but *quality-adjusted* |
| V2 | **PEG (normalized)** | `PEG = PE_trailing / (100·g_5y)`; **skip if cyclical or g≤0** | PE, g_5y | B (A: 1y-PEG only) | <1 bullish; negative PEG = shrinking (do **not** treat as cheap) |
| V3 | PE zone map | 10–20 undervalued / 20–30 healthy / 30+ high-growth (must be justified by g) | PE | A | zone read is **sector-relative**, never absolute |
| V4 | Sector-relative PE | `PE_percentile within sector`; low PE ≠ cheap unless earnings quality passes | PE, sector | A | low-in-sector + quality bullish |
| V5 | Earnings-yield (Greenblatt leg) | `EBIT/EV` | EBIT, EV | B (A: `1/PE`) | ↑ bullish |
| V6 | Re-rating headroom | `g_5y + expected ΔPE` decomposition; flag names **already re-rated** (PE ↑ ≫ EPS ↑ over 3–5y) | 5y PE & EPS path | B | headroom bullish; "5x on perception, no earnings" **bearish** |

### 2.5 Moat & pricing-power proxies

| # | Technique | Signal / formula (proxy) | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| M1 | Pricing power | **Gross-margin durability**: `mean(GM_5y)` high **and** `stdev(GM_5y)` low **while** revenue grew — proxy for "raised prices without losing share" | 5y GM, revenue | B | high+stable GM with growth bullish |
| M2 | Margin trend divergence | `slope(GM) vs slope(OPM)`: GM up but OPM flat/down = cost/opex leak | 5y GM, OPM | B | divergence bearish |
| M3 | Moat (quant proxy) | composite: high **ROCE persistence** (P2) + high stable GM (M1) + **low capex intensity** `Capex/Revenue` + positive FCF (E3). No direct brand/network data | derived | B | high = durable-moat proxy |
| M4 | Capital-allocation focus | `Capex concentration`: reinvestment in core (stable segment mix, ROCE≥20% persistence) vs diversification (rising unrelated goodwill, debt-funded new segments) | capex, goodwill, segment (segment = C) | B/C | focused reinvestment bullish; diversification via debt bearish |

### 2.6 Promoter / governance (mostly Tier C)

| # | Technique | Signal / formula | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| G1 | **Promoter pledge %** | pledged shares / promoter holding; and / total capital | NSE/BSE quarterly shareholding | **C** (scrape or manual) | >20% caution, >50% **veto** (§6) |
| G2 | Promoter holding trend | Δ promoter stake over 4–8 quarters; increasing = confidence, selling = caution | shareholding pattern | **C** | rising bullish; steady selling bearish |
| G3 | Related-party transactions | RPT / revenue or / PBT | annual-report notes | **C** (manual) | high/rising bearish |
| G4 | Auditor red flags | resignation, repeated qualifications | filings/news | **C** (proxy: news-sentiment keyword flag via existing `news_sentiment` agent) | any hit = strong penalty/veto |

**Proxy when G-data absent:** treat the Promoter/Governance pillar weight as
**neutral (score 0.5, weight redistributed)** rather than penalizing, but keep
the **hard pledge/auditor vetoes as optional manual inputs** surfaced in the
report so a human can flip them on.

### 2.7 Re-rating catalysts

| # | Technique | Signal / formula (proxy) | Inputs | Tier | Direction |
|---|---|---|---|---|---|
| R1 | Earnings + PE expansion together | already in V6; require **both** legs positive | 5y EPS & PE | B | both up = genuine re-rating |
| R2 | Momentum confirm | existing `momentum_12_1`, `momentum_6_1` | price history | A | positive supports catalyst |
| R3 | Sector-wide re-rating | sector median PE Δ (specialty chem, defense, etc.) | sector PE series | B | rising sector multiple = tailwind |
| R4 | Policy triggers | PLI / import-duty / China+1 / privatization | news/theme tags | **C** (proxy: `news_sentiment` + macro agent keyword tags; manual override) | positive catalyst bullish |
| R5 | Perception-only red flag | PE re-rated ≫ EPS growth over 3–5y | 5y PE & EPS | B | "already re-rated on perception" bearish |

---

## 3. Precise formulas for the non-trivial signals (for Phase-2 implementers)

### 3.1 Consistency operator (used by P2, P3, E3, M1)
For a series `x_{t-N+1..t}` (N≥3, prefer 5):
```
mean   = average(x)
sd     = sample_stdev(x)
cv     = sd / |mean|                      # coefficient of variation
slope  = OLS_slope(year, x) / |mean|      # normalized trend
consistency_score = mean_percentile − 0.5*cv_percentile + 0.25*slope_percentile
```
Percentiles are cross-sectional (within sector). Report `min(x)` too — a single
bad year matters for "stable high ROCE".

### 3.2 ROCE (P1/P2)
```
Capital Employed = Total Assets − Current Liabilities
ROCE            = EBIT / Capital Employed          # EBIT = operating income
```
If EBIT missing, fall back to existing ROIC proxy `EBITDA/(Equity+TotalDebt)`
(already in `provider.py`), and flag the substitution.

### 3.3 Gross profitability (P4)
```
GP/Assets = (Revenue − COGS) / Total Assets
```

### 3.4 Accruals (E2, Sloan balance-sheet form acceptable)
```
Accruals_ratio = (Net Income − CFO) / Total Assets     # low/negative better
```
(A field `accruals_ratio` already exists on `CompanySnapshot` but is never
populated — Phase 2 should fill it.)

### 3.5 Free cash flow & consistency (E3/E4)
```
FCF_k      = CFO_k − Capex_k          for each of last N years
FCF_yield  = FCF_t / EV_t
FCF_posrate= count(FCF_k > 0) / N
```

### 3.6 Beneish M-Score (E-quality forensic, red-flag) — needs t and t-1
```
DSRI = (Recv_t/Sales_t) / (Recv_{t-1}/Sales_{t-1})
GMI  = GM_{t-1} / GM_t                        # GM = (Sales−COGS)/Sales
AQI  = [1 − (CA_t+PPE_t+Sec_t)/TA_t] / [1 − (CA_{t-1}+PPE_{t-1}+Sec_{t-1})/TA_{t-1}]
SGI  = Sales_t / Sales_{t-1}
DEPI = Dep_{t-1}/(Dep_{t-1}+PPE_{t-1}) ÷ Dep_t/(Dep_t+PPE_t)
SGAI = (SGA_t/Sales_t) / (SGA_{t-1}/Sales_{t-1})
LVGI = Lev_t / Lev_{t-1}                       # Lev = (CL+LTD)/TA
TATA = (ΔWC − ΔCash − Dep) / TA  ≈ (NI − CFO)/TA

M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
        + 0.115·DEPI − 0.172·SGAI − 0.327·LVGI + 4.679·TATA
```
**Decision:** `M > −1.78` ⇒ manipulation-likely veto/flag. **Caveat:** if COGS
or SGA are not separately disclosed (common for Indian names), M is
**not computable** — degrade gracefully to the accruals+cash-conversion signals
(E1/E2/E6) instead of guessing.

### 3.7 PEG (V2)
```
g5 = CAGR(EPS_{t-4..t})              # decimal, e.g. 0.18
PEG = PE_trailing / (100 · g5)       # so PE 20, g 20% -> PEG 1.0
```
Guards: return `None` if `g5 ≤ 0` (shrinking → not "cheap"); **suppress PEG for
sectors tagged cyclical** (materials, energy, autos) — use through-cycle
normalized earnings there instead.

### 3.8 Altman Z″ Emerging-Market score (balance-sheet safety, red-flag)
```
X1 = (Current Assets − Current Liabilities) / Total Assets
X2 = Retained Earnings / Total Assets
X3 = EBIT / Total Assets
X4 = Book Value of Equity / Total Liabilities

Z" = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
```
Zones: **Z″ > 2.6 safe · 1.1–2.6 grey · < 1.1 distress (veto).** Skip for
banks/NBFCs/financials (ratios not meaningful).

---

## 4. Composite "Multibagger Quality Score" blueprint

Seven pillars. Each pillar score = coverage-weighted average of its member
signal percentiles (same math as `engine.py`). Pillar scores combine with the
weights below (normalized to sum 1, exactly like `_normalize_weights`).

| Pillar | Weight | Member signals | Analogue anchor |
|---|---:|---|---|
| **1. Profitability & Efficiency** | **0.22** | P1 ROCE, **P2 ROCE consistency**, P3 ROE, P4 gross profitability, P5 DuPont | Greenblatt ROC, Novy-Marx, QMJ-profitability |
| **2. Earnings Quality & Cash** | **0.18** | E1 cash conversion, E2 accruals, E3 FCF+consistency, E4 FCF yield, E5 FCF use, E6 OCF/NP | Sloan, Beneish (as veto), practitioner FCF |
| **3. Balance-Sheet Safety** | **0.15** | Altman Z″, net-debt/EBITDA, interest coverage, current ratio | Altman, QMJ-safety |
| **4. Growth & Valuation / PEG** | **0.15** | V1 growth, V2 PEG, V3/V4 PE zone (sector-rel), V5 earnings yield, V6 re-rating headroom | Lynch GARP, Greenblatt earnings-yield |
| **5. Moat & Pricing Power** | **0.12** | M1 pricing power, M2 margin divergence, M3 moat proxy, M4 capital allocation | Buffett-style moat (proxied) |
| **6. Promoter / Governance** | **0.10** | G1 pledge, G2 holding trend, G3 RPT, G4 auditor | Indian governance red-flag literature |
| **7. Re-rating Catalysts** | **0.08** | R1–R5 | Momentum + event-study practice |
| **Total** | **1.00** | | |

**Coverage / graceful degradation.** Reuse `engine.py`'s coverage-shrink: a
pillar with mostly-missing inputs is shrunk toward 0.5 and its weight partially
redistributed. **The Promoter/Governance pillar defaults to neutral 0.5** when
Tier-C data is absent (so a name is not unfairly penalized for missing free
data), but its **vetoes stay live as optional manual inputs**.

**Sector-relative default ON.** Unlike v1 (whole-universe percentiles), V2
percentile-ranks **within GICS `sector`** for valuation, margins, ROCE, growth
(§5), because the expert repeatedly stresses "compare within sector."

**Suggested profile deltas for cyclical vs structural targets:** expose a
`cyclical_mode` flag that (a) suppresses PEG (V2), (b) down-weights single-year
valuation, (c) up-weights through-cycle ROCE consistency (P2) and balance-sheet
safety (Pillar 3).

### 4.1 How it plugs into FRA

- **New profile:** `config/profiles/india_multibagger.yaml` — same schema, but a
  new `scoring_mode: multibagger` plus a `pillar_weights` block (the table
  above) alongside/replacing `factor_weights`.
- **Engine:** extend `metrics.FACTORS` with the new pillar extractors, or add a
  parallel `PILLARS` registry so v1's 5-factor mode is untouched. `rank_universe`
  already supports arbitrary weight keys, per-factor floors, coverage-shrink and
  profile-fit — reuse verbatim.
- **Provider:** add `get_financials(ticker)` fetching yfinance `income_stmt`,
  `balance_sheet`, `cashflow` (cache 24h like fundamentals) to unlock all Tier-B
  signals; populate the already-declared-but-empty `accruals_ratio`, and add
  series fields for the consistency operator.
- **Red-flag pass:** a new post-rank filter (mirrors
  `quant.py:_passes_constraints`) that applies §6 vetoes: veto'd names are
  dropped or floored to composite `None` with a reason string surfaced in the
  report.
- **CLI:** `--mode multibagger` (or just select the new profile). No new
  mandatory flags.
- **Report:** add a "Multibagger scorecard" section listing pillar scores,
  the consistency stats (mean/stdev/min ROCE), triggered red flags, and the
  Tier-C manual-input checklist.

---

## 5. Sector-relative normalization

```
for each signal marked "sector-relative":
    peers = universe filtered to same GICS `sector` (fallback: `industry`,
            then whole universe if peer count < MIN_PEERS = 6)
    signal_percentile = percentile_rank(value, peers)
```
- **Fallback ladder** avoids unstable stats in thin sectors.
- **Financials (banks/NBFCs/insurers)** get a variant: skip Altman Z″, ROCE and
  gross margin (not meaningful); lean on ROE, ROA, NIM-type proxies, and cost
  metrics. Detect via `sector in {Financial Services}`.
- **Cyclicals** (materials/energy/autos) get PEG suppressed and consistency
  up-weighted (see §4).

---

## 6. Hard red-flag vetoes (override the score — a high composite cannot save these)

A picked name is **rejected** (or floored + loudly flagged) if **any** trigger
fires:

| # | Veto | Trigger | Tier | Notes |
|---|---|---|---|---|
| RF1 | **Structural cash burn** | `FCF < 0` in ≥3 of last 5 years (and not a flagged early-stage growth exception) | B | E3 |
| RF2 | **Earnings not cash-backed** | `cum(CFO)/cum(NP) < 0.5` over 5y (or `CFO/NI < 0.5` for 3 consecutive yrs) | B | E6 / Sloan spirit |
| RF3 | **Manipulation flag** | Beneish `M > −1.78` (when computable) | B | E-quality; degrade to RF2 if COGS/SGA missing |
| RF4 | **Distress** | Altman `Z″ < 1.1` (non-financials) | B | Pillar 3 |
| RF5 | **Insolvency-risk debt** | `interest_coverage < 1.5` **and** rising `net-debt/EBITDA` over 3y | B | |
| RF6 | **High promoter pledge** | pledge `> 50%` of promoter holding (or `> 20%` of total capital) | C (manual/scrape) | G1; death-spiral risk |
| RF7 | **Auditor red flag** | auditor resignation or repeated qualification | C (news proxy/manual) | G4 |
| RF8 | **Perception-only re-rating** | PE up ≫ EPS over 3–5y **and** PE > 40 with `g5 ≤ 0` | B | V6/R5 |
| RF9 | **Working-capital trap** | DSO↑ **and** DIO↑ **and** DPO↓ together over 3y **and** CFO/NP falling | B | soft-veto (heavy penalty); W1–W4 |

Tier-C vetoes (RF6/RF7) are **optional manual inputs**: default off, surfaced as
a checklist so the score is never silently wrong, and a human/analyst can toggle
them per name.

---

## 7. Caveats the design must honour (anti-naive-ranking guardrails)

1. **Consistency > peak.** Never rank on a single-year ROCE/margin/EPS. The
   consistency operator (§3.1) explicitly penalizes volatility and rewards a high
   `min()`.
2. **Sector context is mandatory** (§5). Absolute PE zones (V3) are read *within
   sector*; low PE is not "cheap" without earnings quality.
3. **Cyclicals ≠ structural compounders.** PEG and single-year valuation are
   suppressed for cyclicals; use through-cycle normalized earnings and
   balance-sheet safety instead.
4. **Valuation still matters.** A great business at PE 80 with no growth headroom
   (V6/RF8) is not a multibagger — re-rating needs earnings *and* multiple room.
5. **Screens, not verdicts.** Every framework in §1 is a filter; the composite
   blends them and defers hard governance calls (Tier C) to explicit manual
   inputs rather than fabricating data.
6. **Free-data honesty.** Anything Tier C (pledge, RPT, contingent liabilities,
   order book, auditor changes, policy catalysts) is flagged as such — the model
   degrades to proxies and neutral weighting instead of guessing.

---

## 8. Citations / links

- Greenblatt, J. (2005). *The Little Book That Beats the Market.* (Magic Formula: ROC + earnings yield.)
- Piotroski, J. (2000). "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers." *Journal of Accounting Research* 38 (Suppl.), 1–41. https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf
- Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics* 108(1). https://mysimon.rochester.edu/novy-marx/research/OSoV.pdf
- Asness, C., Frazzini, A., Pedersen, L. (2019). "Quality Minus Junk." *Review of Accounting Studies* 24. (SSRN 2312432.)
- Sloan, R. (1996). "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?" *The Accounting Review* 71(3). https://www.cuhk.edu.hk/acy2/workshop/June2009Wasley/1996TAR).pdf
- Beneish, M. (1999). "The Detection of Earnings Manipulation." *Financial Analysts Journal.* Threshold −1.78 (Beneish, Lee & Nichols 2013; Beneish & Vorst 2020). https://en.wikipedia.org/wiki/Beneish_M-score
- Altman, E. (1968); Altman et al. (1995) EM revision. Z″(EM) = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4; zones 2.6 / 1.1. https://en.wikipedia.org/wiki/Altman_Z-score
- Lynch, P. (1989). *One Up on Wall Street.* (PEG / GARP.)
- SEBI (2015) LODR Regulation 31; SEBI circular 07-Aug-2019 (effective 01-Oct-2019) on pledge disclosure (≥50% of promoter holding or ≥20% of total capital). https://www.reuters.com/article/business/sebi-tightens-rules-for-pledged-shares-mutual-funds-idUSKCN1TS1QQ/

*(Practitioner pledge-zone guidance — >20% institutional exclusion, >50%
critical — from Indian broker/analyst convention; treat as heuristic, not law.)*
