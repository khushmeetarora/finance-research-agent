# FRA V2 — Labeled Multibagger Dataset

> **Status:** Phase-3 data engineering. **No source code changed.** This document
> describes a standalone, reproducible, price-**verified** labeled dataset of
> multibagger vs non-multibagger Indian equities, built for evaluating the FRA V2
> "Multibagger Quality Score" (see `docs/FRA_V2_STRATEGY.md`).
>
> **Artifacts**
> - `data/multibagger_dataset.csv` — the labeled dataset (136 rows).
> - `tools/build_multibagger_dataset.py` — the reproducible, idempotent builder.
> - `data/_price_cache/` — per-symbol raw adjusted-close cache (idempotent re-runs).
>
> **Golden rule honoured throughout:** every multiple in the CSV is computed from
> **actual prices pulled from yfinance**. Web research was used **only** to
> *discover candidate names*; no multiple, price, or label is taken from a web claim.

---

## 1. What this dataset is (and is not)

- **Is:** a hand-curated, sector- and cohort-diversified panel of Indian (NSE/BSE)
  names, each anchored to a specific **entry date**, with the realized **3-year**
  and **5-year** forward price multiples and the **peak** multiple inside the
  5-year window computed from adjusted prices, plus a reproducible **label**.
- **Is not:** a point-in-time backtest, a survivorship-corrected universe, or a
  claim about the FRA scorer's hit-rate. It is a *ground-truth outcome panel* for
  studying what did/didn't become a multibagger. See **§7 Limitations** — this
  panel inherits the **C-1 (non-point-in-time)** and **H-1 (survivorship)** risks
  documented in `docs/FRA_V2_AUDIT.md`.

---

## 2. Label definitions

For each `(ticker, entry_date)` the builder computes, from adjusted close prices:

- `entry_price` — adjusted close on the nearest trading day to `entry_date`
  (±20-day tolerance).
- `mult_3y = price(entry+3y) / entry_price` (realized 3-year multiple).
- `mult_5y = price(entry+5y) / entry_price` (realized 5-year multiple).
- `peak_mult_5y = max(adjusted close in [entry, entry+5y]) / entry_price`
  (best multiple reached at any point inside the 5-year window).

Labels combine a **peak-based** rule for winners with a **realized-5y** rule for
the control cut:

| Label | Rule | Meaning |
|---|---|---|
| `multibagger_strong` | `peak_mult_5y >= 5.0` | Reached ≥5× within ≤5y (a realizable 5-bagger). |
| `multibagger` | `3.0 <= peak_mult_5y < 5.0` | Reached ≥3× within ≤5y. |
| `intermediate` | `peak_mult_5y < 3.0` **and** `mult_5y >= 1.5` | Solid gainer, never a 3-bagger. |
| `non_multibagger` | `peak_mult_5y < 3.0` **and** `mult_5y < 1.5` | **Control:** survived but did not multiply. |
| `unlabeled_partial` | window < 5y **and** peak never reached 3× | Cannot yet confirm (not present in current build). |

**Why peak for winners but realized-5y for controls?**
"Multibagger = ≥3× *within* ≤5y" is naturally a peak/"reached-it" statement: if a
name tripled at any point you could have realized it. But a pure peak rule
mislabels **transient-pop-then-collapse** names: e.g. Gitanjali Gems ticked to
~2.0× before the PNB fraud took it to ~0.19×, and Vodafone Idea popped ~1.6× then
fell to ~0.34×. Using the **realized 5-year** multiple for the control cut
correctly files these as `non_multibagger` rather than `intermediate`. The CSV
keeps both `peak_mult_5y` and `mult_5y` so either convention is auditable.

**Total-return-ish prices.** Prices come from
`yfinance … history(period="max", auto_adjust=True)`, which back-adjusts for
**both splits and dividends**. Multiples are therefore total-return-ish
(dividends implicitly reinvested via back-adjustment). Where a name never paid
dividends this equals a pure price multiple. This is documented rather than
mixing in a separate dividend feed, which is not reliably free.

---

## 3. Methodology (how the builder works)

`tools/build_multibagger_dataset.py`:

1. **Candidate discovery (free sources only).** A curated `CANDIDATES` list
   (winners + controls + value-destroyers) drawn from reputable free writeups —
   Motilal Oswal Annual Wealth Creation Studies (2016–21), BusinessToday,
   ETNow, stockpricearchive, Rediff/PetroleumBazaar PSU-laggard reports,
   Lakshmishree 5-yr blue-chip returns, BCG/Ambit specialty-chemicals notes — and
   from the repo's earlier `data/multibagger_ground_truth.csv` /
   `data/value_destroyers.csv`. Each row carries a `discovery` citation string.
   **These sources only nominate candidates; they never set a multiple or label.**
2. **Symbol resolution.** For each base ticker try `<base>.NS` (NSE) then
   `<base>.BO` (BSE); record the resolved `yahoo_symbol`.
3. **Price pull + cache.** Pull full adjusted history once; cache to
   `data/_price_cache/<symbol>.csv`. Re-runs read the cache (idempotent);
   `--refresh` forces a re-pull.
4. **Multiple computation.** Snap `entry_date` to the nearest trading day, then
   compute `mult_3y`, `mult_5y`, and `peak_mult_5y` from the pulled series.
5. **Verification gate.** A row is kept (`verified = True`) only if the entry is
   priceable and there are **≥3 years** of forward data. Names whose history does
   not reach the entry date (or are delisted) are **dropped** and logged.
6. **Labeling.** Apply the rules in §2. Output is sorted by `(sector, entry_date,
   ticker)` for a deterministic, diff-friendly CSV.

**Reproduce:**
```
conda run -n fra python tools/build_multibagger_dataset.py            # uses cache
conda run -n fra python tools/build_multibagger_dataset.py --refresh  # re-pull all
```

### CSV schema (`data/multibagger_dataset.csv`)

`ticker, yahoo_symbol, company, sector, entry_date, entry_price, price_3y,
mult_3y, price_5y, mult_5y, peak_price_5y, peak_mult_5y,
holding_years_available, label, data_source, verified, notes`

(`notes` carries the discovery citation, the snapped entry date, the observed
history range, whether the 5-year window is complete, and the label basis.)

---

## 4. Coverage

**Verified rows: 136.  Dropped: 3.  Price-verified rate: 136 / 139 = 97.8%.**

### 4.1 Per-label counts

| Label | Count | Share |
|---|---:|---:|
| multibagger_strong | 53 | 39.0% |
| multibagger | 21 | 15.4% |
| intermediate | 18 | 13.2% |
| non_multibagger (control) | 44 | 32.4% |
| **Total** | **136** | 100% |

Winners (`strong` + `multibagger`) = **74**; clear controls = **44**;
in-between = **18**. The control group is deliberately large and mixes two kinds
of non-multibaggers: **flat/laggard survivors** (PSU/large-caps that simply did
not compound) and **value destroyers** (governance/leverage/fraud blowups).

### 4.2 Per-sector counts (and label mix)

| Sector | strong | multibagger | intermediate | non_multibagger | Total |
|---|---:|---:|---:|---:|---:|
| Auto | 7 | 2 | 0 | 1 | 10 |
| CapitalGoods | 7 | 1 | 1 | 6 | 15 |
| Chemicals | 9 | 3 | 1 | 0 | 13 |
| Consumer | 7 | 3 | 2 | 1 | 13 |
| Defense | 3 | 0 | 0 | 1 | 4 |
| Energy | 0 | 0 | 0 | 3 | 3 |
| FMCG | 3 | 2 | 4 | 2 | 11 |
| Financials | 5 | 3 | 2 | 6 | 16 |
| IT | 5 | 2 | 1 | 2 | 10 |
| Industrials | 0 | 1 | 2 | 2 | 5 |
| Infra | 1 | 0 | 1 | 0 | 2 |
| Materials | 2 | 1 | 1 | 1 | 5 |
| Metals | 0 | 1 | 0 | 7 | 8 |
| Pharma | 4 | 2 | 2 | 4 | 12 |
| Telecom | 0 | 0 | 0 | 4 | 4 |
| Utilities | 0 | 0 | 1 | 4 | 5 |
| **Total** | **53** | **21** | **18** | **44** | **136** |

The sector mix is intentionally **not uniform**: it mirrors reality. Specialty
Chemicals, Consumer, Auto-ancillaries and Financials produced most 2010s
multibaggers, while Metals, Energy, Utilities and Telecom are dominated by
controls/destroyers. Financials (16) are flagged `is_financial` conceptually —
ROCE/Altman are not meaningful for banks/NBFCs (spec §5); this panel only labels
*outcomes*, so that caveat matters when the outcomes are later joined to scores.

### 4.3 Per-cohort counts (entry year)

| Entry year | Count |
|---|---:|
| 2010 | 20 |
| 2011 | 12 |
| 2012 | 16 |
| 2013 | 5 |
| 2014 | 19 |
| 2015 | 15 |
| 2016 | 24 |
| 2017 | 5 |
| 2018 | 9 |
| 2019 | 8 |
| 2020 | 2 |
| 2021 | 1 |

Cohorts span **2010–2021** to avoid single-regime bias (covers the 2010–13
sideways market, the 2014–17 mid-cap bull, the 2018–19 NBFC/mid-cap drawdown, and
the 2020–21 post-COVID surge). A few flagship names appear in **two cohorts**
(e.g. Titan 2010 & 2016, Bajaj Finance 2012 & 2016, Pidilite 2010 & 2015, Trent
2016 & 2019) to test cohort sensitivity. Entry years require a full ≥5y forward
window for the control cut; all 2010–2021 entries satisfy this as of the build
date (2026-07).

---

## 5. Summary statistics

Per-label distribution of the verified multiples (from pulled prices):

| Label | n | median peak_mult_5y | median mult_5y | min peak | max peak |
|---|---:|---:|---:|---:|---:|
| multibagger_strong | 53 | 8.49× | 7.14× | 5.04× | 67.81× |
| multibagger | 21 | 4.13× | 3.61× | 3.02× | 4.98× |
| intermediate | 18 | 2.51× | 2.08× | 1.74× | 2.94× |
| non_multibagger | 44 | 1.37× | 0.65× | 1.01× | 2.50× |

The `non_multibagger` median **realized** 5y multiple of **0.65×** (i.e. a ~35%
loss) vs a median **peak** of 1.37× is exactly the signature the realized-5y
control cut is designed to capture: names that at best drifted up modestly (or
briefly popped) and then ended the window flat-to-deeply-negative. The extreme
`multibagger_strong` max (Tanla, ~67.8× peak from 2019) reflects genuine outlier
compounding, not a data error — it reconciles with the raw series in the cache.

**Cross-check against prior verified pulls.** Values match the repo's earlier
`data/backtest_results_multibaggers.csv` closely (e.g. TCS 2010 `mult_5y` 3.77×
vs 3.76×; Titan 2010 5.52× vs 5.62×; Asian Paints 2010 4.39× vs 4.57×; small
gaps are the ±20-day entry-snap difference), giving independent confidence the
price extraction is correct.

---

## 6. Verification approach

- **Prices are authoritative, web is advisory.** Multiples are recomputed from
  `auto_adjust` adjusted closes; discovery citations live only in `notes`.
- **Availability gate.** Rows require a priceable entry and ≥3y of forward data;
  otherwise they are dropped and logged (see §7).
- **Determinism/idempotency.** The per-symbol cache + deterministic sort mean a
  re-run reproduces byte-stable output; `--refresh` re-pulls to detect vendor
  drift.
- **Reconciliation.** Spot values were cross-checked against the repo's earlier
  independently-generated backtest CSVs (§5) and against the qualitative
  `multibagger_ground_truth.csv` narratives.

---

## 7. Limitations (read before using)

1. **Survivorship bias (H-1).** Free price feeds only reliably serve names that
   still trade. Truly wiped-out names that were **delisted or renamed** cannot be
   priced back and were **dropped**:
   - `TATAMOTORS` — NSE symbol returns 404 (2025 demerger/rename churn).
   - `IBULHSGFIN` — Indiabulls Housing renamed to *Sammaan Capital* (2024); old
     symbol no longer served.
   - `DHFL` — liquidated/delisted 2021 (equity wiped).
   Their **absence biases the control group toward "soft" losers** (names that
   fell but survived, e.g. Yes Bank ~0.07×, Vakrangee ~0.07×, Manpasand ~0.01×)
   rather than total zeros. We mitigate by *including* every blown-up name that
   still has price history, but the hardest failures are structurally missing.
2. **Not point-in-time (C-1).** Entry/exit prices are historical, but this panel
   is an **outcome** table — it carries no as-of fundamentals. Do **not** join it
   to `get_snapshot_enriched()` / `get_financials()` for a hit-rate claim without
   the PIT fixes in `docs/FRA_V2_AUDIT.md` (C-1/H-1); today's statements and
   today's surviving peer set would leak future/restated information.
3. **Dividends via back-adjustment, not a separate feed.** `auto_adjust` folds
   dividends into the price, approximating total return. It is not a clean
   dividends-reinvested TR index and can differ slightly from an official TRI;
   for high-yield/low-growth names this modestly *raises* the measured multiple.
4. **Adjusted-price vendor risk.** yfinance split/bonus/dividend adjustments are
   occasionally imperfect for older Indian corporate actions. Multiples for the
   oldest cohorts (2010–2012) are the most exposed; the `_price_cache/` snapshot
   makes any future correction auditable.
5. **Curated, not exhaustive; selection bias in discovery.** The universe is a
   hand-picked ~140 names, not the full NIFTY500. Winners were surfaced *because*
   they were famous winners — good for a labeled ground-truth panel, but it is
   **not a random sample** and its base rates (54% multibagger) are far above the
   market's true multibagger frequency. Treat label *balance* as a design choice,
   not an estimate of real-world odds.
6. **Entry-date snapping / listing gaps.** Post-2016 IPOs (e.g. Polycab, HAL,
   Mazagon Dock, Fine Organic, AU Bank) have entries snapped to their first
   available trading month; their windows are shorter and the 2020–2021 cohorts
   are thin (only names with a complete 5y window as of 2026-07 are labeled).
7. **`intermediate` is a genuine middle, not a control.** The 18 `intermediate`
   names (solid 1.5×–3× compounders that never tripled) are excluded from both
   the winner and control groups by design; include or drop them explicitly in
   any downstream analysis.

---

## 8. Discovery sources (candidate nomination only)

- Motilal Oswal **26th Annual Wealth Creation Study, 2016–2021** — biggest/
  fastest/most-consistent wealth creators (Deepak Nitrite, Tanla, APL Apollo,
  Alkyl Amines, Vinati, Aarti, SRF, Astral, Adani Enterprises, …).
- BusinessToday (2025) — "500–1800% in five years" (Persistent, Dixon, BEL, HAL,
  Varun Beverages, JSW Energy, Tata Power).
- ETNow (2023) — Trent / Varun Beverages / ESAB beat Nifty 7 straight years.
- Lakshmishree (2024) — 5-year blue-chip returns (HAL, Trent, VBL, Polycab, BEL,
  Siemens, ABB).
- Rediff.com & PetroleumBazaar — PSU laggards/wealth-destroyers 2010–2020 (BHEL
  −90%, SAIL −87%, NMDC −78%, ONGC −53%, Coal India −60%, GAIL −20%).
- BusinessInsider — decade losers (Tata Motors, Coal India, NTPC, Tata Power).
- BCG (2018) & Ambit (2024) — India specialty-chemicals TSR / FY17–22 golden
  period.
- stockpricearchive — per-year adjusted price histories used only to *nominate*
  (all multiples independently recomputed from yfinance).
- Repo seeds: `data/multibagger_ground_truth.csv`, `data/value_destroyers.csv`.

*All numeric multiples and labels in `data/multibagger_dataset.csv` are computed
by `tools/build_multibagger_dataset.py` from yfinance-pulled adjusted prices, not
from any source above.*
