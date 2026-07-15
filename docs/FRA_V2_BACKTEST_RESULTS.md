# FRA V2 - Multibagger Backtest Results

> This document now carries **four** as-run event studies:
>
> - **Phase 6 (below, newest): the macro/regime overlay wired into the scorer +
>   an A/B PIT backtest.** Wires the previously-unwired macro/regime overlay
>   (`docs/FRA_V2_MACRO.md` 4) into `rank_multibagger` and the PIT harness, and
>   re-runs the backtest BOTH without and with the overlay to measure its value.
>   Headline: the wiring is additive/PIT-correct and the overlay-off run
>   reproduces Phase 5 byte-for-byte; the overlay is **context/tilt only (never a
>   veto)** so it changes **no** verdict, and on this tiny determinate slice it
>   changes **no** quintile hit-rate either - an honest null on measured
>   separation, useful only as advisory regime context.
> - **Phase 5 (below): the RF1/RF2 early-stage growth exception + an
>   expanded, de-survivorshiped dataset.** Adds the spec's RF1/RF2 "early-stage
>   growth exception" so genuinely investing-to-grow, profitable, safe names are
>   no longer wrongly vetoed by the steady-state cash-flow rules, and widens the
>   labelled set from 136 -> 173 (more 2017-2021 cohort winners across sectors +
>   more failed value-destroyers) to push PIT-determinacy from 28 -> 51.
> - **Phase 4 (further down): the genuine point-in-time (PIT) run** powered by a
>   free deep-history fundamentals source, `src/data/screener.py` (screener.in,
>   ~10-12y annual statements). This is the run that finally makes a *strict*
>   PIT fundamental backtest possible on free data - it closes audit finding
>   **C-1** (point-in-time safety) and **H-1** (contemporaneous peer panel).
> - **Phase 3 (further down): the earlier yfinance-only run**, kept verbatim for
>   provenance. Its headline was a *data* finding: yfinance's ~4-5y statement
>   window makes 100% of pre-2022 screening dates INDETERMINATE under strict PIT.
>   Phase 4 is the direct answer to that limitation.

---

# Phase 6 - Macro/regime overlay wired + A/B PIT backtest

> **Status:** Executed on the same expanded labelled dataset as Phase 5
> (`data/multibagger_dataset.csv`, **173 names**), same screener-backed PIT
> harness, same determinate slice (**51 names**). The only change is that the
> macro/regime overlay is now **wired** and the harness runs an **A/B**
> (overlay-off vs overlay-on).
>
> **Code changed, all additive + opt-in (the `overlay=None` path is byte-for-byte
> the pre-overlay behaviour; the classic 5-factor engine and the live multibagger
> default are unchanged):**
> - `src/factors/regime.py` - new pure `build_scorer_overlay(regime, events=None)`
>   bundling the three §4 functions into a plain dict.
> - `src/factors/multibagger.py` - `rank_multibagger` gained keyword-only
>   `overlay` / `overlay_by_ticker` (default `None`). The overlay is applied at
>   the **compositing stage only**: pillar-weight **tilt** (re-normalised to 1),
>   a bounded **boost** added to the `rerating_catalysts` pillar score (clamped
>   `[0,1]`), and advisory **context** stored on the new
>   `FactorReport.regime_context`. The veto pass is **untouched**.
> - `src/factors/engine.py` - new `FactorReport.regime_context` field (empty by
>   default; additive to `to_dict`).
> - `scripts/backtest_multibagger.py` - computes a per-name regime at each name's
>   own `entry_date` (PIT-gated, no look-ahead), builds the overlay, and ranks
>   each cohort **twice** (A: off, B: on) via `overlay_by_ticker`.
> - `src/agents/quant.py` - opt-in live flag `factor_config.use_macro_overlay`
>   (**default false**).
>
> **Re-run** (conda env `fra`):
> ```powershell
> conda activate fra
> python -m scripts.backtest_multibagger              # A/B (overlay off + on)
> python -m scripts.backtest_multibagger --no-overlay # overlay-off only
> ```
> Outputs: `data/backtest_pit_results.csv` (== overlay-off),
> `data/backtest_pit_results_overlay_off.csv`, `..._overlay_on.csv`,
> `data/backtest_pit_summary.json` (== overlay-off), `..._overlay_off.json`,
> `..._overlay_on.json`, and `data/backtest_pit_ab_summary.json` (A/B delta).

## 6.0 TL;DR (honest)

1. **Determinism preserved.** Overlay-OFF is **byte-for-byte the Phase-5 run**:
   determinacy **51/173**, base rate **0.627**, precision **0.737**, recall
   **0.438**, lift **1.18x**, control-rejection **0.737**, quintile hit-rates
   **0.80 / 0.80 / 1.00 / 1.00 / 0.60 / 0.667**. The wiring did not disturb the
   baseline.
2. **The overlay changes NO verdict - by design.** The PASS/FAIL verdict is a
   veto + absolute-quality-gate decision that **does not read the composite**,
   and the overlay is explicitly context/tilt (never a veto). So base rate,
   precision, recall, lift and control-rejection are **identical** off vs on
   (`verdict_changes_off_to_on = 0`).
3. **The overlay moved composite *values* for 119/173 names but did NOT move any
   quintile hit-rate.** Overlay-ON quintiles are also
   **0.80 / 0.80 / 1.00 / 1.00 / 0.60 / 0.667** - identical to off. The ±15%
   pillar-weight tilt reorders composites only slightly, not enough to cross a
   quintile boundary at this n.
4. **The re-rating boost was near-silent on the determinate slice** (only **2/51**
   names got any boost, max **+0.02**) because news is omitted in the backtest
   (GDELT is forward-only PIT, `FRA_V2_MACRO.md` 5) and the reproducible
   easing+sector-tailwind boost rarely triggered. Regime labels on the
   determinate slice: **risk_on 40, neutral 9, risk_off 2**; **11/51** carried
   advisory cautions.
5. **Honest read: on this small determinate PIT sample the overlay does not help
   (and does not hurt).** Its only concrete contribution is advisory regime
   context on the report. We did **not** tune it to manufacture lift.

## 6.1 A/B metrics (overlay off vs on, determinate n=51)

| Metric | Overlay OFF | Overlay ON | Delta |
|---|---:|---:|---:|
| Determinate | 51 / 173 | 51 / 173 | 0 |
| Curated base rate | 0.627 | 0.627 | 0 |
| Screen precision | 0.737 | 0.737 | 0 |
| Screen recall | 0.438 | 0.438 | 0 |
| Lift over base rate | 1.18x | 1.18x | 0 |
| Control-rejection rate | 0.737 | 0.737 | 0 |
| Composite quintile hit-rates | 0.80/0.80/1.00/1.00/0.60/0.667 | 0.80/0.80/1.00/1.00/0.60/0.667 | none |
| Names with changed composite value | - | 119 / 173 | - |
| Verdict changes | - | 0 | - |

**Why the verdict metrics are invariant (not a bug):** `classify()` in the
harness fires on (a) applicable hard vetoes and (b) the absolute quality gate
(ROCE/ROE/FCF/cash-conversion thresholds). Neither reads the composite score, and
the overlay never touches the veto pass, so it *cannot* change a verdict. This is
the intended "screens, not verdicts / context, never a silent kill" contract
(`FRA_V2_STRATEGY.md` 7.5, `FRA_V2_MACRO.md` 4.2). The overlay's reach is limited
to the composite **ranking** and the advisory `regime_context`.

## 6.2 No look-ahead in the in-backtest regime (PIT proof)

The regime for each name is computed with `compute_regime(entry_date, sector=…)`,
which passes every macro/market series through `macro_signals.as_of_series` with
its configured publication lag **before** any statistic, so a regime read at
`entry_date` can only use observations knowable on/before that date. This is
unit-tested two ways: `tests/test_regime.py` (as-of hides future points;
publication-lag blocks an unreleased CPI print) and
`tests/test_macro_overlay_wiring.py::test_backtest_per_name_regime_overlay_is_pit`
(a post-as_of India-VIX spike does **not** flip the regime to risk-off, and the
overlay threads through `rank_multibagger` unchanged). News is deliberately
excluded from the backtest overlay because GDELT's shared feed is forward-only
PIT (`FRA_V2_MACRO.md` 5), so the backtest boost is the fully-reproducible
easing + sector-tailwind component only.

## 6.3 Veto/context attribution (determinate set, n=51)

Veto attribution is **identical to Phase 5** (5.6) because the overlay never
changes the veto pass - RF1 (losers 2 / winners 3), RF2 (6 / 6), RF4 (2 / 0),
RF5 (1 / 0), RF6 (1 / 0), RF7 (2 / 0), RF8 (3 / 4). The overlay's *own*
contribution is the advisory layer: **11/51** determinate names carry regime
`cautions` (risk-off tape / fx-stress / crude-spike / credit-widening /
inflation-above-band), surfaced on `regime_context` for review but never acted on
as a kill. Two determinate names received a small (`+0.02`) re-rating boost.

## 6.4 Caveats (mandatory - quote with any number)

All Phase-4/5 caveats hold verbatim (restated-vintage statements;
hindsight-selected, survivorship-affected dataset - 0.627 is a curated-set rate,
not a market base rate; tiny determinate n=51 with 19 flagged - no confidence
interval is meaningful; peer panel = dataset cohort; manual Tier-C flags are
hand-fed). **Additional Phase-6 caveats:**

1. **The overlay's measured value here is zero on separation.** That is the
   honest result on the free-data determinate slice we can PIT-reconstruct, not a
   tuning failure to paper over - and we did not loosen the overlay to force a
   difference. Treat it as advisory context, not alpha.
2. **News is out of the backtest overlay** (forward-only free feed), so the
   backtest exercises only the macro tilt + easing/sector boost, not the full
   catalyst layer the live path could use with a date-bounded query.
3. **Macro series are restated too** (yfinance/FRED latest vintage), though the
   headline market series (VIX, USD/INR, Nifty, crude) are prices/rates with
   negligible restatement vs fundamentals.

## 6.5 Tests & reproducibility (Phase 6)

- New tests: `tests/test_macro_overlay_wiring.py` (no-op invariance;
  tilt/boost math; overlay never adds/removes a veto; per-name overlay; PIT
  correctness of the in-backtest regime). Full suite: **165 passed**
  (155 prior + 10 new).
- Outputs regenerated: `data/backtest_pit_results.csv` +
  `data/backtest_pit_results_overlay_{off,on}.csv`,
  `data/backtest_pit_summary.json` +
  `data/backtest_pit_summary_overlay_{off,on}.json`,
  `data/backtest_pit_ab_summary.json`.
- The overlay-off outputs are byte-for-byte the Phase-5 numbers, so the A/B is a
  clean controlled comparison.

---

# Phase 5 - Early-stage growth exception + expanded PIT dataset

> **Status:** Executed on the expanded labelled dataset
> (`data/multibagger_dataset.csv`, **173 names**: 94 winners
> [63 `multibagger_strong` + 31 `multibagger`], 59 `non_multibagger`,
> 20 `intermediate`).
>
> **Code changed, all additive (the `as_of=None` classic/live path is byte-for-byte
> unchanged; the classic 5-factor engine is untouched):**
> - `src/factors/multibagger.py` - new `is_early_stage_growth_exception(snap)`
>   plus its wiring into `run_veto_pass` (RF1 + the RF2 cash-conversion legs a/b
>   only; clause (c) cum-loss and RF3-RF9 are never relaxed).
> - `src/data/screener.py` - parse resilience (accounting-parenthesis + unicode
>   minus negatives, `html.unescape`), more line-item aliases (income/balance/
>   cash-flow), best-of consolidated-vs-standalone variant selection, and an
>   optional highest-priority `data/_manual_financials/<SYM>.json` local fallback
>   for pre-FY2015 statements (empty by default - no manufactured determinacy).
> - `src/data/provider.py` - deep-source lookup order local -> screener ->
>   yfinance inside the `as_of` path only.
> - `tools/build_multibagger_dataset.py` - +37 net names (winners 2017-2021 and
>   more failed/collapsed controls), all multiples recomputed from actually-pulled
>   adjusted prices (9 candidates dropped for having no free price history).
>
> **Re-run** (conda env `fra`):
> ```powershell
> conda activate fra
> python tools/build_multibagger_dataset.py     # rebuild labelled set (173 rows)
> python -m scripts.backtest_multibagger         # screener-backed PIT
> ```
> Outputs: `data/backtest_pit_results.csv`, `data/backtest_pit_summary.json`.

## 5.0 TL;DR

1. **The early-stage growth exception works precisely on the named winners.**
   With the carve-out live, **HAL, BDL and Mazagon Dock go from RF1+RF2 vetoed to
   zero vetoes**, and **Trent** loses its RF1 cash-burn veto. Verified by re-running
   `run_veto_pass` on each name's PIT snapshot with the exception forced OFF vs ON
   (see 5.2). True cash-burners are still caught (5.3).
2. **Determinacy rose from 28/136 (20.6%) to 51/173 (29.5%)** - a real +23-name
   gain, driven by the parser hardening + the deeper 2017-2021 cohorts, still
   with **0/173 reconstructable by yfinance** and **no manufactured determinacy**
   (122 thin/old names left INDETERMINATE).
3. **Separation on the determinate slice is now positive but modest**, and we
   report it as a curated-set diagnostic, not a forward number: base rate 0.627,
   **precision 0.737, recall 0.438, lift 1.18x**, control-rejection 0.737.
4. **Honest residual limitation:** a few low-return winners (Saregama, Intellect,
   Radico, Angel One) are still hit by RF1/RF2 - correctly, by design: the
   exception is deliberately conservative and denies names that lack either a
   >=15% mean ROCE/ROE **or** a genuine rising-ROCE-with-rising-OPM scale-up. We
   did not loosen it to rescue them.

## 5.1 The early-stage growth exception - definition & rationale

Spec section 6, RF1 note: *"FCF<0 in >=3 of last 5 years AND NOT a flagged
early-stage growth exception."* Implemented in
`multibagger.is_early_stage_growth_exception(snap)` and applied to **RF1** and to
**RF2 legs (a) cumCFO/cumNP<0.5 and (b) CFO/NI<0.5 streak** only. A name qualifies
**iff ALL** of the following hold (all computable from the free screener/yfinance
bundle):

| # | Gate | Threshold | Why |
|---|---|---|---|
| 1 | Real multi-year window | `>= 3` income periods | No 1-2y flukes. |
| 2a | Genuine profitability | cumulative net profit **> 0** | Separates a reinvesting compounder from an operational cash-burner. |
| 2b | Latest year profitable | latest NI `> 0` | Not currently loss-making. |
| 2c | Majority of years profitable | NI>0 in `>= 60%` of years | Durable, not a one-off. |
| 2d | Operating margin positive | latest **and** mean OPM `> 0` | Losses are not being masked. |
| 3 | Balance-sheet safety | Altman Z" `>= 2.6` (non-financials) | No distressed name is ever spared; RF4/RF5 also stay live. |
| 4 | Quality returns **OR** genuine scale-up | mean ROCE **or** ROE `>= 15%` **OR** (latest ROCE `>= 1.5x` earliest positive ROCE **and** OPM rising) | High-return franchise reinvesting, **or** a real operating-leverage ramp (e.g. Trent/Zudio). Rejects flat low-return names. |

Rationale: the wrongly-vetoed winners are **profitable, safe businesses whose
negative FCF / depressed CFO is caused by capex or a working-capital build ahead
of a growth run**, not by losing money. Gates 2 + 3 enforce "profitable and not
distressed"; gate 4 enforces "a real quality or improvement signal." RF2 clause
(c) (cumulative net profit `<= 0`) can **never** be spared, because gate 2a
requires it to be positive - a persistent-loss name is structurally excluded.
The exception touches **only** the cash-flow vetoes; RF3 (Beneish), RF4 (Altman
distress), RF5 (insolvency), RF6/RF7 (governance) and RF8/RF9 (valuation/WC) are
never relaxed.

## 5.2 Before/after on the four named winners (verified)

Re-ran `run_veto_pass` on each name's reconstructed PIT snapshot twice - with
`is_early_stage_growth_exception` forced OFF (the pre-Phase-5 behaviour) vs live:

| Name | Entry | mean ROCE | Altman Z" | Vetoes BEFORE | Vetoes AFTER |
|---|---|---:|---:|---|---|
| Hindustan Aeronautics (HAL) | 2020 | 17.6% | 5.6 | **RF1, RF2** | **none** |
| Bharat Dynamics (BDL) | 2019 | 22.9% | 6.0 | **RF1, RF2** | **none** |
| Mazagon Dock (MAZDOCK) | 2021 | 5.4%* | 4.6 | **RF1, RF2** | **none** |
| Trent (TRENT) | 2019 | 4.1%* | 9.2 | **RF1** | **none** (cash-flow) |

*MAZDOCK and Trent clear the exception via **gate 4's scale-up leg** (rising ROCE
off a positive base with rising OPM), not the 15%-return leg. HAL and BDL clear
it via the high-return leg. **Note on Trent:** the cash-flow vetoes are removed,
but in the *full* PIT run Trent (2019) is still **FAILed by RF8** (PE=206 with a
negative 5y earnings CAGR) - a legitimate, independent *valuation* veto, exactly
the separation of concerns the exception is meant to preserve.

## 5.3 Cash-burners are still caught (unit-tested)

`tests/test_multibagger.py` adds cases proving the carve-out does not leak:
a loss-making cash-burner (negative cumulative NI / negative OPM) is still vetoed
by RF1 **and** RF2; a low-flat-return name is denied the exception; a distressed
name (low Altman) is denied; RF3 (Beneish) and RF4 (distress) still fire even when
the early-stage flag is set; and a <3-year window is denied (RF1 fires).

## 5.4 Determinacy - screener vs yfinance (expanded set)

| Metric | Phase 5 (173) | Phase 4 (136) |
|---|---:|---:|
| Names PIT-**determinate** (>=2y admissible statements) | **51 / 173** | 28 / 136 |
| Determinate rate | **29.5%** | 20.6% |
| yfinance PIT baseline | **0 / 173** | 0 / 136 |
| Rescued into determinacy by screener | **51** | 28 |
| Indeterminate (thin/old, correctly not scored) | 122 | 108 |

The gain comes from (a) parser hardening (accounting-parenthesis + unicode-minus
negatives, entity unescaping, more aliases) recovering rows that previously failed
to parse, and (b) adding more **2017-2021** cohort names, where screener's
~FY2015 free depth can assemble the >=2 admissible pre-`as_of` years. Determinacy
is still bounded by the free-tier depth floor - documented, not a bug.

## 5.5 Separation on the determinate set (n=51)

Winners among determinate: **32**; controls: **19**. Curated base rate = **0.627**
(a hindsight-curated rate, NOT a market base rate - see 5.7).

| Classifier | Value | Notes |
|---|---:|---|
| Flagged PASS (clears absolute gate, no veto) | 19 | of which winners: 14 |
| **Precision** (winners / flagged) | **0.737** | 14 / 19 |
| **Recall** (flagged winners / determinate winners) | **0.438** | 14 / 32 |
| **Lift** over base rate | **1.18x** | precision / base-rate; **> 1 = modest edge** |
| Control rejection rate (determinate controls FAILed) | **0.737** | 14 / 19 |

**Composite quintile hit-rates (determinate, ranked by composite):** top buckets
0.80 / 0.80 / 1.00 / 1.00, then 0.60 and a 0.667 tail - broadly monotone at the
top but noisy at this n (buckets of ~5). Treated as context, not decile lift.

## 5.6 Veto attribution (determinate set, n=51)

| Veto | Controls | Winners (false pos) | Read |
|---|---:|---:|---|
| RF1 structural cash burn | 2 | 3 | Down from a 4-winner FP cluster; residual 3 are low-return names correctly denied the exception. |
| RF2 earnings not cash-backed | 6 | 6 | Strongest control catch; residual winner FPs are low-ROCE / negative-CFO names outside the carve-out. |
| RF4 Altman distress | 2 | 0 | Clean. |
| RF5 insolvency | 1 | 0 | Clean. |
| RF6 promoter pledge (manual) | 1 | 0 | Hand-fed. |
| RF7 auditor red flag (manual) | 2 | 0 | Hand-fed. |
| RF8 perception-only re-rating | 3 | 4 | Valuation veto; the winner hits (incl. Trent 2019 at PE=206) are rich-multiple entries, an independent concern from cash flow. |

The four named winners no longer appear under RF1/RF2. The residual RF1/RF2
winner false-positives (**Saregama, Intellect, Radico, Angel One, CG Power,
PC Jeweller**) are names that genuinely fail the conservative gates - low/negative
mean ROCE (Saregama 7%, Intellect -6%, Radico 8%) and/or negative CFO/NP - so the
exception correctly declines to rescue them rather than over-fitting.

## 5.7 Caveats (mandatory - quote with any number)

All Phase-4 caveats (5.7 == 4.6) still hold verbatim: restated-vintage (not
first-print) statements; hindsight-selected, survivorship-affected dataset (0.627
is a curated-set rate, not a market base rate); tiny determinate n (51; 19
flagged) - no confidence interval is meaningful; peer panel = dataset cohort, not
historical index membership; manual Tier-C governance flags are hand-fed. The
lift > 1 here is a **curated-set diagnostic on capex-heavy 2016-2021 compounders**
and must **not** be converted into a forward probability.

## 5.8 Tests & reproducibility (Phase 5)

- New tests: `tests/test_multibagger.py` (early-stage exception: profitable
  capex-grower spared by RF1/RF2, cash-burner still vetoed, low-flat-return
  denied, improvement-trajectory granted, distressed denied, Beneish/distress not
  relaxed, <3y window denied) and `tests/test_screener.py` (parenthesis/unicode
  negatives, alternate aliases, best-of-variant depth preference, local-fallback
  absent-by-default + loads-and-normalises). Full suite: **155 passed**.
- Outputs regenerated: `data/multibagger_dataset.csv` (173 rows),
  `data/backtest_pit_results.csv`, `data/backtest_pit_summary.json`.
- Determinacy is time-sensitive: as screener's free window slides forward, the
  determinate cohort will extend to later entry years over time.

---

# Phase 4 - Genuine PIT event study (screener.in deep history)

> **Status:** Executed on the full labelled dataset
> (`data/multibagger_dataset.csv`, **136 names**: 74 winners
> [`multibagger`/`multibagger_strong`], 44 `non_multibagger`, 18 `intermediate`).
>
> **Harness:** `scripts/backtest_multibagger.py` (rewritten for Phase 4).
> New/changed code, all **additive**:
> - `src/data/screener.py` - deep free fundamentals scraper (cache +
>   rate-limit + retries + robust parse + graceful failure).
> - `src/data/provider.py` - `as_of` threaded through
>   `get_financials` / `enrich_snapshot_with_financials` /
>   `get_snapshot_enriched` (default `None` = unchanged classic behaviour).
> - `src/backtest/asof.py` - `as_of_financials` reporting-lag gate,
>   `build_asof_snapshot`, `usable_period_count` (reused).
>
> `src/factors/multibagger.py` and the classic 5-factor engine were **not
> modified**. All prior tests stay green; new tests added (see 4.7).
>
> **Re-run** (conda env `fra`):
> ```powershell
> conda activate fra
> python -m scripts.backtest_multibagger            # screener-backed PIT
> python -m scripts.backtest_multibagger --no-screener   # yfinance-only contrast
> ```
> Outputs: `data/backtest_pit_results.csv` (per-name PIT scorecard),
> `data/backtest_pit_summary.json` (aggregate metrics).

## 4.0 TL;DR

1. **The data win is real and is the headline.** screener.in rescued
   **28 / 136 names (20.6%) into strict PIT-determinacy**, versus the
   **yfinance baseline of 0 / 136**. For the first time we can reconstruct
   pre-decision fundamentals (ROCE/ROE history, multi-year FCF, cash conversion,
   Altman-Z, earnings CAGR) for a real, if bounded, slice of the dataset - with
   **no look-ahead**: statements are gated to periods reportable on/before
   `entry_date - 90d`.
2. **Determinacy is bounded by free-tier depth, honestly.** screener's free
   annual history reaches ~**FY2015** for March-end filers, so only cohorts with
   `entry_date >= ~2016/2017` can accumulate the >=2 admissible pre-`as_of`
   years the quality gate requires. All 108 indeterminate names are *correctly*
   left INDETERMINATE rather than force-scored - the pipeline never manufactures
   determinacy.
3. **On the 28 determinate names the scorer's separation is weak and noisy**,
   and we report it as such: absolute-gate **precision 0.50**, **recall 0.27**,
   **lift 0.93x** over the curated base rate (0.54). The composite-percentile
   quintiles do not rank winners monotonically at this n. The determinate set is
   tiny (n=28, of which 8 flagged) and skewed toward capex-heavy 2016-2021
   compounders, so **no positive lift can be demonstrated from free data here.**
4. **The veto pass is the part that works.** It rejected **9 / 13 determinate
   controls (69%)** and, notably, several data-only (RF1/RF2/RF4/RF5) not just
   manual-Tier-C catches. The trade-off: the FCF/cash-conversion vetoes (RF1,
   RF2) also fire on genuine winners that were *legitimately* FCF-negative at
   entry (HAL, BDL, Mazagon Dock, Trent, Fine Organic) - a real, documented
   limitation of applying steady-state cash rules to early-stage capex growers.

## 4.1 Determinacy - screener vs yfinance (the C-1 result)

| Metric | screener.in (PIT) | yfinance (PIT baseline) |
|---|---:|---:|
| Names PIT-**determinate** (>=2y admissible statements) | **28 / 136** | **0 / 136** |
| Determinate rate | **20.6%** | 0.0% |
| Names **rescued** into determinacy by screener | **28** | - |
| Indeterminate (thin/old, correctly not scored) | 108 | 136 |

**Why 28 and not more (honest bound):** entry-year distribution is
2010:20, 2011:12, 2012:16, 2013:5, 2014:19, 2015:15, 2016:24, 2017:5, 2018:9,
2019:8, 2020:2, 2021:1. The 90-day reporting-lag gate plus screener's ~FY2015
free-depth floor means pre-2016 dates cannot assemble two admissible years;
some 2016 names also fall just short (need FY2014). Determinacy is therefore
concentrated in the 2016-2021 cohorts - exactly where free deep history reaches.
This is a *free-data ceiling*, documented, not a bug.

## 4.2 Separation on the determinate set (n=28)

Winners among determinate: **15**; controls: **13**. Curated base rate
(winners / determinate) = **0.536** (this is a hindsight-curated rate, NOT a
market base rate - see 4.6).

| Classifier | Value | Notes |
|---|---:|---|
| Flagged PASS (clears absolute quality gate, no veto) | 8 | of which winners: 4 |
| **Precision** (winners / flagged) | **0.50** | 4 / 8 |
| **Recall** (flagged winners / determinate winners) | **0.267** | 4 / 15 |
| **Lift** over base rate | **0.93x** | precision / base-rate; **< 1 = no edge** |
| Control rejection rate (determinate controls FAILed) | **0.692** | 9 / 13 |

**Composite-percentile quintile hit-rates (determinate, ranked by composite):**
the top two buckets are 100% winners, but so are buckets 4 and 5, while bucket 3
and the tail are 0% - i.e. **no monotonic ordering**. At n=28 (buckets of ~2)
this is noise, not signal, and we do not claim decile lift.

## 4.3 Veto attribution (determinate set)

| Veto | Fired on controls | Fired on winners (**false positives**) | Read |
|---|---:|---:|---|
| RF1 structural cash burn (FCF<0) | 1 | 4 | Too strict for capex-stage growers (HAL, BDL, Mazagon, Trent) |
| RF2 earnings not cash-backed (CFO/NP) | 5 | 4 | Best control catch; but also hits FCF-negative winners |
| RF4 Altman-Z distress | 2 | 0 | Clean (KFA, Jet Airways) |
| RF5 insolvency (interest cover) | 1 | 0 | Clean (Hathway) |
| RF6 promoter pledge (manual) | 1 | 0 | DISHTV, hand-fed |
| RF7 auditor red flag (manual) | 2 | 0 | Gitanjali, Vakrangee, hand-fed |
| RF8 perception-only re-rating | 1 | 2 | Look-ahead-flavoured false positives (VBL, Trent) |

**Reading it honestly:** the *distress* vetoes (RF4/RF5) and the manual
governance vetoes (RF6/RF7) are clean. The *cash-flow* vetoes (RF1/RF2) do the
most control-rejection work **but** are the main source of winner false
positives, because several dataset winners were genuinely FCF-negative /
low-cash-conversion at their entry date (heavy capex ahead of a growth run). We
did **not** retune these formulas (out of scope; audited), we report the
trade-off.

## 4.4 What the PIT peer panel does (the H-1 result)

Each name is ranked **only against its contemporaneous cohort** (same entry
year), using pre-`as_of` snapshots - never against today's survivors. Free data
cannot supply true historical small/mid-cap **index membership**, so the
cohort-as-panel is the documented best-effort substitute (caveat in 4.6). This
removes the most egregious survivorship leak in ranking, but cohorts are small,
so the percentile composite is context only; **verdicts use absolute
thresholds** (identical bars to Phase 3 for comparability).

## 4.5 Representative determinate calls (audit trail)

- **DIXON (2019, +15.9x):** PIT ROCE 27%, CFO/NP 1.25, FCF+ 0.75, no veto ->
  **PASS**. A clean, no-look-ahead catch of a real multibagger.
- **TATAELXSI (2019, +9.0x):** PIT ROCE 54%, no veto -> **PASS**. Asset-light
  compounder recognised on its own pre-decision numbers.
- **HAL (2020, +13.3x) / MAZAGON (2021, +23.9x) / BDL (2019, +6.9x):** all
  **FAILed** by RF1+RF2 - genuinely FCF-negative defense/PSU names at entry.
  The cash-flow vetoes cost these winners; a documented false-positive cluster.
- **ABB (2016, control):** RF2 (CFO/NP 0.23) + RF8 (PE 146, negative 5y CAGR)
  -> **FAIL**. Correct data-only rejection of an over-valued laggard.
- **GITANJALI (2012, -100%):** determinate via screener, RF2 (CFO/NP 0.02) +
  manual RF7 -> **FAIL**. Note the *data* signal (near-zero cash conversion)
  independently corroborated the manual fraud flag.

## 4.6 Caveats (mandatory - quote with any number)

1. **Restated-vintage, not as-first-reported.** screener statements are the
   latest restated vintage. Even after the 90-day gate, every determinate figure
   is a *restated-vintage upper bound*; true first-print PIT would be weaker.
2. **Hindsight-selected, survivorship-affected dataset.** The 0.54 base rate is
   a curated-set artefact, not a market base rate. Precision/recall/lift here are
   **archetype diagnostics on a small determinate slice**, never a forward
   probability.
3. **Tiny determinate n (28; 8 flagged).** No confidence interval is meaningful.
   The <1 lift means: **on the free data we can actually PIT-reconstruct, the
   absolute quality gate did not beat the curated base rate.** That is the honest
   result, not a tuning failure to paper over.
4. **Peer panel = dataset cohort**, not historical index membership (free data
   gap). Documented under H-1.
5. **Manual Tier-C flags** (RF6/RF7 for 7 named destroyers) are hand-fed
   governance facts, always attributed `manual`; they are not autonomous
   detection.

## 4.7 Tests & reproducibility (Phase 4)

- New tests: `tests/test_screener.py` (parse: periods/TTM-drop, derived EBIT,
  capital-employed convention, capex-from-FCF, graceful empty/no-network) and
  `tests/test_asof_pit.py` (period dropping, reporting-lag exclusion,
  indeterminate case, screener-preferred gating, yfinance fallback, look-ahead
  TTM stripping). Full suite: **98 passed** (82 prior + 16 new).
- Outputs: `data/backtest_pit_results.csv`, `data/backtest_pit_summary.json`.
- Determinacy is time-sensitive: as screener's free window slides forward, the
  determinate cohort will extend to later entry years over time.

---

# Phase 3 - Earlier yfinance-only run (kept for provenance)

> **Status:** Executed. This is the honest, reproducible write-up of the
> historical event-study backtest defined in `docs/FRA_V2_BACKTEST_PLAN.md`,
> run against `data/multibagger_ground_truth.csv` (26 winners) and
> `data/value_destroyers.csv` (16 losers).
>
> **Harness:** `scripts/backtest_multibagger.py` (+ additive helper
> `src/backtest/asof.py`). The classic engine, the metric files and
> `src/factors/multibagger.py` were **not modified**.
>
> **Re-run command** (conda env `fra`):
> ```powershell
> conda activate fra
> python -m scripts.backtest_multibagger
> ```
> Outputs: `data/backtest_results_multibaggers.csv`,
> `data/backtest_results_destroyers.csv`, `data/backtest_results_summary.json`.

---

## 0. TL;DR - read this before any number

The single most important finding is a **data finding, not a strategy finding**:

- **yfinance only carries ~4-5 recent fiscal years of statements** (earliest
  period returned in this run was **FY2022, ending 2022-03-31**). Every
  ground-truth screening date is **2010-2019**. After applying the ~90-day
  reporting-lag buffer, **zero** statement periods are admissible as-of any
  screening date.
- Therefore, under a **strict point-in-time (PIT) reading, 100% of the 26
  multibaggers are INDETERMINATE** - the free data simply cannot reconstruct
  what their fundamentals looked like before the run. This confirms
  `docs/FRA_V2_FEASIBILITY.md` 4 exactly: *"a genuine fundamental backtest
  needs a point-in-time fundamentals source; yfinance/Stooq cannot supply it."*

Because a pure-PIT run is a near-total null result, the backtest reports **two
panels**:

| Panel | What it uses | What it can honestly say |
|---|---|---|
| **A - strict PIT** | statements truncated to periods reportable on/before `screening_date - 90d` | The real answer. Almost everything is INDETERMINATE on fundamentals; the only as-of signals are price momentum and **manually-entered** Tier-C governance/fraud facts. |
| **B - latest-vintage diagnostic** | today's restated FY22-26 statements (**look-ahead + survivorship contaminated**) | Whether the 7-pillar logic + veto pass *recognise the archetype* when data exists. An **optimistic upper bound**, NOT a claim it could have called the name early. |

**Headline numbers (all on curated, hindsight-selected sets - see 6):**

- **Multibaggers, Panel A (PIT):** recall **undefined** - 0 of 26 determinate;
  **indeterminate rate 26/26 = 100%**.
- **Multibaggers, Panel B (latest-vintage, look-ahead):** recall
  **19/26 = 73%** among determinate (26/26 determinate, 0 indeterminate).
- **Destroyers, Panel A (PIT):** rejection **7/7 = 100% among determinate**,
  but **all 7 rejections are driven by manually-entered Tier-C flags** (auditor
  resignation / promoter pledge); **0 destroyers were caught by data-derived
  signals**. Indeterminate rate **9/16 = 56%**.
- **Destroyers, Panel B (latest-vintage):** rejection **13/14 = 93% among
  determinate** (2 delisted = indeterminate); but **6 of those 13 still depend
  on the manual Tier-C auditor flag**, and **data-only** rejection is
  **~7/14 = 50%**.

Everything below unpacks these with per-name transparency and the mandatory
Section-6-of-the-plan caveats.

---

## 1. Methodology as actually run

### 1.1 Two classifiers, kept separate
Per the plan, the quality screen (recall on winners) and the veto pass
(rejection on losers) are reported **separately**; there is **no blended
"accuracy"** and **no precision / win-rate** (the sample is 100% known winners
+ 100% known losers, so precision is meaningless - plan 3).

### 1.2 Per-name "as-of" construction
For each name at its `screening_date` (interpreted as **1 January of that year**
- the most pre-run-up anchor):

1. **Fetch** statements via `provider.get_financials()` and full adjusted price
   history via yfinance (`2008-01-01 ->` now, `auto_adjust=True`).
2. **Panel A (PIT):** `src/backtest/asof.py:as_of_financials()` truncates each
   statement to only the fiscal periods ending **on/before
   `screening_date - 90 days`** (the reporting-lag buffer, plan 5.1). The
   snapshot is rebuilt from that vintage only; live `.info` valuation/momentum
   is **discarded** (it reflects today and cannot be time-travelled).
   Valuation is reconstructed from the as-of price x as-of trailing EPS where
   both exist; momentum from the as-of price series.
3. **Panel B (diagnostic):** the same name is enriched with the **full** (today)
   statement set - explicitly look-ahead - to test archetype recognition.
4. **Score** with the real `rank_multibagger` via the thin
   `src/backtest/asof.py:score_one(snap, peers)` adapter (a single name needs a
   cross-sectional panel because pillars are percentiles).
5. **Veto pass** `run_veto_pass()` applied unchanged.

### 1.3 Peer panel choice
The cross-sectional peer panel is **all 42 ground-truth names' snapshots**
(winners + losers pooled). This is the documented "use the other ground-truth
names as peers" option. Because most GICS sectors here have `< 6` members, the
sector-relative ranker falls back to whole-panel percentiles (`scoring.py`
fallback ladder). Percentiles on a 42-name curated panel are unstable and
have no base-rate meaning, so the **PASS/FAIL verdict uses absolute thresholds**
(plan 2.2 option b), with the percentile composite reported only as context.

### 1.4 Verdict rules (documented, so each call is auditable)
- **Hard veto fired (applicable)** -> FAIL (winner) / REJECTED (loser).
- Else **absolute quality gate**:
  - *Non-financials:* determinate iff >=2y ROCE history. **PASS** iff
    `ROCE(latest) >= 15%` **and** (`FCF positive-rate >= 0.6` **or**
    `cum CFO/NP >= 0.8`).
  - *Financials (banks/NBFCs):* determinate iff >=2y ROE history. **PASS** iff
    `ROE >= 14%` and 5y earnings CAGR not negative. (ROCE/Altman/Beneish/FCF
    vetoes are **suppressed for financials** - plan/spec 5; a lending book
    structurally shows negative FCF and high leverage. This filtering lives in
    the harness; `multibagger.py` is untouched.)
  - Otherwise **INDETERMINATE** (first-class outcome; never forced to PASS/FAIL).
- **Destroyers:** REJECTED if vetoed **or** (determinate and fails the gate);
  MISSED (false negative) if determinate and passes; INDETERMINATE if thin.

### 1.5 Tier-C manual inputs (governance/fraud) - fully disclosed
Free data cannot reconstruct auditor resignations, promoter pledge or fraud
historically, so the plan (7.1) allows supplying them manually from each
loser's documented `red_flag_reason`. Applied **only to destroyers**, only where
the note explicitly documents it, and always attributed as `manual`:

| Ticker | Manual flag | From the note |
|---|---|---|
| RCOM.NS | RF7 auditor/forensic | "SBI fraud tag + fund diversion" |
| RELCAPITAL.NS | RF7 auditor | "PwC auditor resignation 2019 + Grant Thornton forensic" |
| DHFL.NS | RF7 auditor/forensic | "Cobrapost alleged fraud + defaults" |
| VAKRANGEE.NS | RF7 auditor | "PwC auditor resignation 2018" |
| MANPASAND.NS | RF7 auditor | "Deloitte/Mehra Goel exit + fictitious revenue" |
| GITANJALI.NS | RF7 auditor/forensic | "PNB LoU fraud + fictitious accounts" |
| DISHTV.NS | RF6 pledge (88%) | "Essel/Zee promoter pledge" |

**These manual flags are not evidence the system can detect these autonomously.**
They are hand-fed facts; their contribution to the rejection rate is broken out
separately below.

### 1.6 Forward returns
Re-derived from the adjusted price series for both panels: buy at the first
trading day on/after the screening anchor, measured to the CSV `later_date`
(year-end) and at fixed `+3y` / `+5y` horizons, plus the latest available price.
CSV prices are treated only as sanity anchors (they are approximate and
vendor-inconsistent; e.g. Astral's CSV base disagrees with the adjusted series -
the re-derived series governs). Delisted names return no/short series - that
absence is itself survivorship evidence.

---

## 2. Multibaggers - per-name scorecard

`A` = strict PIT verdict; `B` = latest-vintage diagnostic verdict.
`fwd(later)` = realized adjusted multiple to the CSV later-date.

| Ticker | Sector | Scr. | A (PIT) | B (diag.) | B veto / gate | ROCE | Z" | fwd(later) | fwd(+5y) |
|---|---|---|---|---|---|---:|---:|---:|---:|
| TITAN | Cons.Disc | 2010 | INDET | **PASS** | ROCE38% Z6.4 | 0.38 | 6.4 | 38.0x | 5.6x |
| BAJFINANCE | Financials | 2012 | INDET | **PASS** | ROE18% g32% | - | - | 124.9x | 15.4x |
| PIDILITIND | Materials | 2010 | INDET | **PASS** | ROCE28% Z11.3 | 0.29 | 11.3 | 19.8x | 6.0x |
| ASIANPAINT | Materials | 2010 | INDET | **PASS** | ROCE24% Z10.0 | 0.24 | 10.0 | 17.1x | 4.6x |
| EICHERMOT | Cons.Disc | 2011 | INDET | **PASS** | ROCE26% Z9.4 | 0.26 | 9.4 | 25.4x | 14.5x |
| PAGEIND | Cons.Disc | 2010 | INDET | **PASS** | ROCE61% Z8.8 | 0.62 | 8.8 | 32.5x | 15.1x |
| ASTRAL | Industrials | 2015 | INDET | **PASS** | ROCE18% Z7.8 | 0.18 | 7.8 | 9.8x | 3.8x |
| APLAPOLLO | Materials | 2016 | INDET | **PASS** | ROCE28% Z6.8 | 0.28 | 6.8 | 13.9x | 6.0x |
| DEEPAKNTR | Materials | 2016 | INDET | FAIL | **RF8** perception (PE40, g-13%) | 0.11 | 7.4 | 35.5x | 14.0x |
| SRF | Materials | 2016 | INDET | FAIL | **RF8** perception (PE45, g-5%) | 0.15 | 7.3 | 9.9x | 4.6x |
| NAVINFLUOR | Materials | 2017 | INDET | **PASS** | ROCE19% Z7.8 | 0.19 | 7.8 | 8.7x | 8.8x |
| TATAELXSI | IT | 2019 | INDET | **PASS** | ROCE26% Z14.1 | 0.26 | 14.1 | 6.4x | 9.0x |
| PERSISTENT | IT | 2019 | INDET | **PASS** | ROCE29% Z9.4 | 0.29 | 9.4 | 8.2x | 12.5x |
| TCS | IT | 2010 | INDET | **PASS** | ROCE55% Z11.7 | 0.55 | 11.7 | 12.6x | 3.8x |
| AVANTIFEED | Cons.Staples | 2012 | INDET | FAIL | **RF3** Beneish M=0.28 | 0.24 | 14.5 | 112.5x | 21.6x |
| SYMPHONY | Cons.Disc | 2010 | INDET | FAIL | gate ROCE-7% (+RF9 soft) | -0.08 | 5.7 | n/a* | n/a* |
| AJANTPHARM | Health Care | 2012 | INDET | FAIL | **RF3** Beneish M=-1.75 | 0.29 | 12.5 | 38.6x | 47.0x |
| CAPLIPOINT | Health Care | 2013 | INDET | **PASS** | ROCE22% Z17.2 | 0.22 | 17.2 | n/a* | n/a* |
| RELAXO | Cons.Disc | 2012 | INDET | FAIL | **RF8** perception (PE54, g-10%) | 0.11 | 8.5 | 29.1x | 17.4x |
| BALKRISIND | Cons.Disc | 2013 | INDET | FAIL | gate ROCE14% fcf+0.5 | 0.14 | 6.5 | 6.5x | 8.4x |
| HAVELLS | Industrials | 2012 | INDET | **PASS** | ROCE22% Z9.4 | 0.22 | 9.4 | 9.2x | 4.7x |
| KAJARIACER | Industrials | 2012 | INDET | **PASS** | ROCE21% Z10.1 | 0.21 | 10.1 | 15.9x | 10.6x |
| CHOLAFIN | Financials | 2013 | INDET | **PASS** | ROE19% g24% | - | - | 4.8x | 5.0x |
| MUTHOOTFIN | Financials | 2014 | INDET | **PASS** | ROE30% g43% | - | - | 16.7x | 5.4x |
| DIXON | Industrials | 2019 | INDET | **PASS** | ROCE34% Z4.7 | 0.34 | 4.7 | 13.5x | 15.9x |
| BERGEPAINT | Materials | 2012 | INDET | **PASS** | ROCE21% Z8.5 | 0.21 | 8.5 | 26.3x | 7.2x |

`*` SYMPHONY (2010) and CAPLIPOINT (2013) - yfinance price history did not reach
their screening year, so the forward multiple is indeterminate (the CSV notes
these are the most heavily split/bonus-adjusted, hardest-to-anchor names).

**All 26 forward returns that could be computed are strongly positive**
(median realized `later` multiple ~16x), confirming the positive class.

---

## 3. Value-destroyers - per-name scorecard

| Ticker | Sector | Scr. | A (PIT) | B (diag.) | Veto / gate that fired | manual? | fwd(later) |
|---|---|---|---|---|---|---|---:|
| YESBANK | Financials | 2018 | INDET | **REJECTED** | gate ROE 7% | - | 0.06x (-94%) |
| RCOM | Comm.Svcs | 2010 | **REJECTED** | **REJECTED** | RF7(man) + RF4 Z"=-16.7 | RF7 | 0.01x (-99%) |
| SUZLON | Industrials | 2010 | INDET | **REJECTED** | RF2 CFO/NP=0.33 + RF3 Beneish | data | 0.07x (-93%) |
| RPOWER | Utilities | 2010 | INDET | **REJECTED** | gate ROCE 5% | - | 0.02x (-98%) |
| RELINFRA | Utilities | 2010 | INDET | **MISSED** | passed gate: ROCE15% Z"1.9 | - | 0.03x (-97%) |
| RELCAPITAL | Financials | 2010 | **REJECTED** | **REJECTED** | RF7(man); statements delisted | RF7 | 0.02x (-98%) |
| DHFL | Financials | 2018 | **REJECTED** | **REJECTED** | RF7(man); no data (delisted) | RF7 | n/a (delisted) |
| IDEA | Comm.Svcs | 2017 | INDET | **REJECTED** | RF3 Beneish M=-1.72 | data | 0.35x (-65%) |
| IBULHSGFIN | Financials | 2018 | INDET | INDET | no statements/price (renamed) | - | n/a (no data) |
| DISHTV | Comm.Svcs | 2017 | **REJECTED** | **REJECTED** | RF6 pledge(man) + RF4 Z"=-19.4 | RF6 | 0.22x (-78%) |
| HATHWAY | Comm.Svcs | 2017 | INDET | **REJECTED** | gate ROCE 3% | - | 0.59x (-41%) |
| VAKRANGEE | IT | 2018 | **REJECTED** | **REJECTED** | RF7(man) auditor | RF7 | 0.17x (-83%) |
| MANPASAND | Cons.Staples | 2018 | **REJECTED** | **REJECTED** | RF7(man); no data (delisted) | RF7 | 0.03x (-97%) |
| GITANJALI | Cons.Disc | 2012 | **REJECTED** | **REJECTED** | RF7(man); no data (delisted) | RF7 | 0.00x (-100%) |
| JETAIRWAYS | Industrials | 2018 | INDET | **REJECTED** | RF4 Z"=-21.2 + RF5 insolvency | data | 0.03x (-97%) |
| KFA | Industrials | 2010 | INDET | INDET | no statements (delisted 2015) | - | 0.02x (-98%, to delist) |

**All 16 losers realized catastrophic losses** where a series exists (delisted
names return nothing - the survivorship hole, made visible).

---

## 4. Aggregate metrics (with sample sizes)

### 4.1 Recall on multibaggers
| Panel | n | Determinate | Indeterminate | PASS (recall among determinate) |
|---|---:|---:|---:|---|
| **A - strict PIT** | 26 | **0** | **26 (100%)** | **undefined (0/0)** |
| **B - latest-vintage (look-ahead)** | 26 | 26 | 0 | **19/26 = 73%** |

### 4.2 Rejection on destroyers
| Panel | n | Determinate | Indeterminate | REJECTED (among determinate) | of which data-only |
|---|---:|---:|---:|---|---|
| **A - strict PIT** | 16 | 7 | 9 (56%) | **7/7 = 100%** | **0/7** (all manual Tier-C) |
| **B - latest-vintage** | 16 | 14 | 2 (12.5%) | **13/14 = 93%** | **~7/14 = 50%** (6 need manual RF7) |

### 4.3 Veto attribution (Panel B, applicable vetoes)
| Veto | Fired on destroyers | Fired on multibaggers (**false positives**) | Source |
|---|---|---|---|
| RF7 auditor/forensic | RCOM, RELCAPITAL, DHFL, VAKRANGEE, MANPASAND, GITANJALI (6) | - | **manual** |
| RF4 Altman distress `<1.1` | RCOM, DISHTV, JETAIRWAYS (3) | - | data |
| RF3 Beneish `> -1.78` | SUZLON, IDEA (2) | AVANTIFEED, AJANTPHARM (2) | data |
| RF6 promoter pledge `>50%` | DISHTV (1) | - | **manual** |
| RF2 CFO/NP `<0.5` | SUZLON (1) | - | data |
| RF5 insolvency | JETAIRWAYS (1) | - | data |
| RF8 perception-only re-rating | - | DEEPAKNTR, SRF, RELAXO (3) | data |
| RF9 working-capital trap (soft) | - | SYMPHONY (1) | data |
| gate low ROE/ROCE (no veto) | YESBANK, RPOWER, HATHWAY (3) | SYMPHONY, BALKRISIND (2) | data |

A veto that never fired here (e.g. RF1 explicit cash-burn count) is **untested,
not proven safe**.

---

## 5. Concrete examples (audit trail)

**A cleanly caught multibagger (Panel B):** **TITAN** - latest-vintage ROCE 38%,
Altman Z" 6.4, FCF positive 3/4 years, no veto -> PASS. Realized +38x to 2021.
The screen's profitability/safety logic clearly recognises a Titan-type
compounder *when it has the data*. (Same story for TCS: ROCE 55%, +12.6x.)

**A correctly-vetoed destroyer, data-only:** **SUZLON** - no manual input;
latest-vintage `cum CFO/NP = 0.33 (< 0.5)` fired RF2 and Beneish fired RF3.
Realized -93%. This is a genuine data-derived catch of the "cash-burn +
aggressive accounting" archetype. **DISHTV** is another good one: RF4 Altman
distress (data) *and* RF6 pledge (manual) both fire; realized -78%.

**A correctly-vetoed destroyer that needs the manual flag:** **VAKRANGEE** -
its latest-vintage statements actually look benign (Altman 7.3, ROCE 7%), so the
**only** thing that rejects it is the hand-fed RF7 auditor-resignation flag.
Without the manual input, the free-data screen would **miss** this classic
auditor-red-flag blow-up (it realized -83%). This is the honest limit of free
data on governance fraud.

**Notable misses:**
- **DEEPAKNTR** (a genuine +35x winner) was **FAILed** by RF8 "perception-only
  re-rating" - but only because RF8 was evaluated on **today's** rich PE (40)
  and a **recent** negative 5y earnings CAGR (post-run earnings dip). This is a
  pure look-ahead artefact: in 2016 the name was cheap and growing. RF8/RF3
  false-positives (also SRF, RELAXO, AVANTIFEED, AJANTPHARM) are the main reason
  Panel B recall is "only" 73% - and they would largely vanish with true PIT
  data.
- **RELINFRA** (a -97% destroyer) was **MISSED** in Panel B: on restated data it
  scrapes the gate (ROCE exactly 15%, positive reported FCF) with Altman in the
  grey zone (1.9, not `<1.1`). A reminder that a single-threshold gate lets
  borderline leverage/governance cases through - exactly why the plan warns the
  test says nothing about false-positive rate.

---

## 6. Present-day expectation (with humility)

Present-day screen (as-run):
```powershell
python -m src.cli research -p india_multibagger -t "present-day multibagger screen" -u NIFTY50 --no-llm --no-excel
```
Data health: OK, 50/50 fetched, avg coverage 92%, single-source (yfinance).
`input hash: 3fcedb63cd9cfb37`.

**Top-10 NIFTY50 by Multibagger Quality Score (today):**

| # | Ticker | Name | Composite | Fit | Cov |
|---:|---|---|---:|---:|---:|
| 1 | HEROMOTOCO.NS | Hero MotoCorp | 0.74 | 0.98 | 100% |
| 2 | ASIANPAINT.NS | Asian Paints | 0.65 | 0.95 | 100% |
| 3 | EICHERMOT.NS | Eicher Motors | 0.65 | 0.90 | 100% |
| 4 | TCS.NS | Tata Consultancy Services | 0.63 | 0.97 | 100% |
| 5 | NESTLEIND.NS | Nestle India | 0.62 | 0.94 | 75% |
| 6 | APOLLOHOSP.NS | Apollo Hospitals | 0.61 | 0.91 | 100% |
| 7 | TATASTEEL.NS | Tata Steel | 0.61 | 0.87 | 100% |
| 8 | CIPLA.NS | Cipla | 0.59 | 0.91 | 100% |
| 9 | BPCL.NS | Bharat Petroleum | 0.59 | 0.90 | 100% |
| 10 | SUNPHARMA.NS | Sun Pharmaceutical | 0.58 | 0.92 | 100% |

**How to read this - and how NOT to:**

- **It is recall, not precision.** The historical exercise shows the logic
  *retains* known-quality archetypes and *targets* known failure modes. It says
  **nothing** about how many *non-winners* the screen would also pass today. On
  a live universe, **most flagged names will not multi-bag.**
- **This is NIFTY50 - the wrong pond for multibaggers.** These are already-large
  compounders (Asian Paints, TCS, Nestle). Multibaggers are typically born in
  **small/mid caps** (the profile default is NIFTY500 with a small-mid market-cap
  floor). Passing large-caps mostly signals "durable quality," not "10x ahead."
- **Valuation / regime dependence.** Many sample winners re-rated from *cheap*
  starting multiples in specific regimes (2012-17 mid-cap boom, 2019-21
  China+1 / EMS / post-COVID liquidity). The same quality names today may be
  priced for perfection (the very RF8 condition that mis-fired above). Quality
  != high forward return from a rich multiple; patterns need not repeat.
- **Base-rate realism.** Multibaggers are rare in any period. Treat the screen
  as an **odds-improver and a blow-up-avoider** (the vetoes correctly rejected
  cash-burn/distress/pledge/auditor cases), **not** as a multibagger predictor.
  Do **not** convert the 73% look-ahead recall into any forward probability.

---

## 7. Caveats & why these numbers are an optimistic upper bound

Every figure above carries the plan's mandatory scaffolding. In one place:

1. **Look-ahead bias (the dominant one).** Panel B uses **today's restated**
   FY22-26 statements to judge names screened in 2010-2019. It "knows" how the
   story ended. Panel A avoids this but, precisely because it does, can
   determine **nothing** on fundamentals (100% indeterminate for winners) -
   yfinance has no pre-2022 statements. There is no free-data middle ground.
2. **Survivorship bias.** The winners are, by construction, survivors that won.
   Delisted losers (DHFL, RelCapital, Gitanjali, Manpasand, KFA, IBulls-Hsg
   renamed) return **no statements** -> INDETERMINATE, i.e. a naive live-universe
   screen would **silently never see them**. Their rejection here depends on
   manual entry, not on anything the pipeline could fetch.
3. **Shallow history.** Even where statements exist, it is ~4-5 years, not the
   5-10y the consistency operators want. Every ROCE-stability / 5y-FCF /
   5y-CAGR figure runs on a short window.
4. **Selection bias / tiny n.** 26 winners + 16 losers, hand-picked with
   hindsight. These are **archetype-coverage diagnostics**, not statistics.
   No confidence interval is meaningful at this n.
5. **Manual Tier-C contamination.** Roughly **half** of all destroyer
   rejections (all 7 in Panel A; 6 of 13 in Panel B) come from **hand-fed**
   auditor/pledge facts, not from anything the system computed. Strip those and
   free-data destroyer rejection falls to ~50%.
6. **Absolute-threshold / percentile artefacts.** The 42-name panel has no
   base-rate universe, so PASS uses fixed thresholds; the choice of 15% ROCE /
   0.6 FCF-rate / 14% ROE bars is a defensible convention, not a tuned optimum.
7. **Return/adjustment noise.** Split/bonus adjustments differ across vendors;
   re-derived multiples (used here) diverge from the CSV approximations for the
   most heavily-adjusted names.

**Standing disclosure (quote this with any number):** *These rates were
estimated on a hindsight-selected, survivorship-affected sample using restated
(non-point-in-time) free fundamentals, with roughly half of the destroyer
rejections supplied by manual governance inputs. They are an optimistic upper
bound on the screen's coherence with history; they do not estimate its
false-positive rate and do not imply a forward probability that any given pick
will multi-bag.* For a defensible forward number you need point-in-time
fundamentals + historical index membership + a full-universe walk-forward
(plan 7.2).

---

## 8. Reproducibility

- Harness: `scripts/backtest_multibagger.py`; adapter/helpers:
  `src/backtest/asof.py` (both additive; no core files changed).
- Env: `conda activate fra` (Python 3.11, yfinance 1.4.1).
- Re-run: `python -m scripts.backtest_multibagger`
- Present-day screen:
  `python -m src.cli research -p india_multibagger -t "present-day multibagger screen" -u NIFTY50 --no-llm --no-excel`
- Per-name outputs: `data/backtest_results_multibaggers.csv`,
  `data/backtest_results_destroyers.csv`, `data/backtest_results_summary.json`.
- Data depth is time-sensitive: yfinance's ~4-5y statement window slides
  forward, so the exact indeterminate counts in Panel A will stay ~100% for
  these old dates but Panel B numbers may drift as restated statements change.
