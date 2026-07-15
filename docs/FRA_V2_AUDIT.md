# FRA V2 — Independent Adversarial Audit of the Multibagger Scoring Variant (Phase 2)

> **Scope:** correctness and bias-safety of the newly-implemented "Multibagger Quality Score" variant.
> **Method:** static reading of source, hand-recomputation of formula fixtures against authoritative
> definitions, full `pytest` run, and a live numerical spot-check on two real tickers (INFY.NS, TITAN.NS).
> **Constraint:** no source code was modified. This document is read-only findings + recommended fixes.
> **Auditor stance:** skeptical — assume nothing is correct until verified.

---

## TOP-LINE VERDICT

**The scoring *mathematics* is largely correct and genuinely well-tested for LIVE, as-of-today use.**
The forensic formulas (Beneish, Altman), the pillar weights, the veto thresholds, and the core Tier-B
extractors (ROCE, accruals, true FCF, gross profitability, working-capital days, PEG) all match the
spec and standard definitions, and I was able to reproduce the test fixtures by hand.

**However, the implementation is NOT point-in-time safe, and it is NOT trustworthy as a basis for any
historical success-rate / backtest claim about the multibagger strategy.** There is no mechanism
anywhere to score a *past* date without leaking future and restated information. Every fundamental
input is fetched "as of now": the annual statements returned by `get_financials()` include fiscal
periods that postdate any historical scoring date (verified live — INFY returns FY2026 today), the
valuation/quality/momentum fields come from yfinance's current-only TTM `info` dict, and the
percentile/sector ranks are computed against **today's surviving universe**. If a Phase-3 fundamental
backtest reuses `get_snapshot_enriched()` / `get_financials()` to score history, the resulting
"success rate" will be materially inflated by look-ahead and survivorship bias.

Good news: the **existing** backtest (`src/backtest/engine.py`) is a deliberate price-only proxy that
explicitly does **not** consume any of these fundamentals (it says so on its Summary sheet), so there is
no *active* leak in shipped code today. The risk is entirely forward-looking: the moment someone wires
the multibagger fundamentals into a walk-forward test, the numbers will lie.

**Must-fix before basing any success-rate claim on this:** implement real point-in-time data
plumbing (an `as_of` that actually gates statement periods and valuation), or state loudly that all
multibagger performance evidence must be **out-of-sample forward** only. See C-1 / H-1.

**Trust rating**
- As a *live, today* screening tool: **trustworthy** (with the Medium fidelity caveats below).
- As a basis for *historical backtest / success-rate* claims: **not trustworthy** as-is.

---

## Verification summary (what passed)

| Check | Result |
|---|---|
| Beneish M-Score: 8 indices, `-4.84` intercept, all 8 coefficients, `M > -1.78` threshold | **Correct.** Hand-recompute of the "clean" fixture = **-2.476** (test asserts `-2.476 ± 0.02`). Sign of TATA coefficient (+4.679) and LVGI/SGAI (negative) all correct. |
| Altman Z''-EM: `3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4`, zones 2.6 / 1.1 | **Correct.** Hand-recompute of fixtures = **7.467** (safe) and **0.713** (distress); enrichment fixture = **7.0788**. All match. |
| ROCE = EBIT / (Total Assets − Current Liabilities); ROIC proxy fallback | Formula shape correct; **numerator deviates from spec** — see **M-1**. |
| Sloan accruals = (NI − CFO) / Total Assets, low = better | **Correct** (sign inverted via `_neg` for ranking). Spot-check INFY = -0.044. |
| True FCF = CFO − Capex, posrate, neg-years | **Correct** (`o - abs(cx)`; yfinance capex is negative). |
| Gross profitability = (Rev − COGS) / Total Assets (Novy-Marx) | **Correct** (prefers explicit Gross Profit line). |
| Working-capital days DSO/DIO/DPO (365·item/denominator, COGS for DIO/DPO) | **Correct.** |
| PEG = PE_trailing / (100·g5), guard g5 ≤ 0, suppress cyclicals | **Correct** for the decimal-g convention; **g5 estimation is fragile** — see M-2. |
| Consistency operator (mean / stability = −cv / slope) | **Faithful adaptation** — see note below. |
| 7 pillar weights (0.22/0.18/0.15/0.15/0.12/0.10/0.08) | **Exact match** to spec §4, in both `DEFAULT_PILLAR_WEIGHTS` and the profile YAML. |
| 9 red-flag vetoes | Thresholds faithful; **minor deviations** in RF5 / RF8 / RF1 — see L-tier. |
| Governance pillar → neutral 0.5 when Tier-C absent; unreliable insider proxy excluded | **Confirmed** (see "Positive confirmations"). |
| `pytest` | **65 passed in ~15s** (`conda run -n fra python -m pytest -q`). |
| Classic-mode regression | **Intact** — all V2 code is additive and gated on `scoring_mode == "multibagger"`; `FactorReport` fields are optional with classic defaults. |

**Consistency operator note.** Spec §3.1 defines
`consistency_score = mean_pct − 0.5·cv_pct + 0.25·slope_pct`. The code instead exposes three signals
(`*_level`, `*_stability = −cv`, `*_trend = slope`) with member weights 1.0 / 0.5 / 0.25 and takes a
*normalized* weighted average of their percentiles. Because `stability = −cv`, its percentile ≈
`1 − cv_pct`, so the implemented pillar term equals `(mean_pct − 0.5·cv_pct + 0.25·slope_pct + 0.5) / 1.75`
— an **affine, monotone transform** of the spec expression. Rankings are preserved; this is an
acceptable and documented reformulation, not a bug. `series_cv` uses sample stdev (n−1), returns `None`
on mean = 0, and `series_slope` requires ≥3 points — all sensible edge-case handling.

---

## Findings, ranked by severity

### CRITICAL

#### C-1. No point-in-time safety — fundamentals leak future & restated data; any historical backtest will be optimistically biased
**What I checked.** `DataProvider.get_financials()`, `get_snapshot()`, `get_snapshot_enriched()`,
`enrich_snapshot_with_financials()`, `agents/quant.py`, and whether `AgentState.as_of` gates anything.

**Evidence.**
- `get_financials(ticker)` has **no `as_of` parameter**. It calls `yf.Ticker(...).income_stmt/.balance_sheet/.cashflow`
  and returns whatever yfinance serves **today**, ordered oldest→latest. Live proof: today (2026-07-09)
  INFY returns income periods `['2022-03-31', … , '2026-03-31']`. Scoring a hypothetical date in, say,
  2023 would therefore feed the model FY2024/25/26 statements — **direct future-period leak.**
- The statements are the **latest restated** figures, not as-originally-reported at the historical date
  (restatement leak).
- `get_snapshot()` populates PE, market cap, price, ROE, ROA, margins, `earnings_yield`, `fcf_yield`,
  and `beta` from yfinance's `info` dict, which is **TTM / current-only** with no history. `peg` combines
  today's `pe_trailing` with a CAGR taken over statements that end today — **both legs are current.**
  `momentum_12_1` / `momentum_6_1` come from 2y of price history up to today.
- `AgentState.as_of` exists and is folded into the reproducibility `input_hash`, but it is **never passed
  to the provider** — it does not gate any data fetch. So "as-of" is cosmetic for scoring purposes.
- There is no as-originally-reported / vendored PIT source anywhere in `src/data`.

**Impact.** Any Phase-3 walk-forward test that scores past rebalance dates using these functions will
"know" future earnings, future FCF, future distress outcomes, and current valuations — inflating hit
rates, CAGR, and Sharpe. Success-rate claims derived that way are not defensible.

**Recommended fix.**
1. Add an `as_of: date | None` to `get_financials()`/`get_snapshot()` and **drop every statement period
   whose period-end > `as_of`** and shift each period-end forward by a realistic reporting lag
   (~60–90 days) before it becomes "known".
2. Replace `info`-based TTM valuation/quality with values reconstructable at `as_of` (e.g. price at
   `as_of` ÷ trailing EPS from statements known at `as_of`), or explicitly mark those signals unusable
   in backtest mode.
3. Until (1)/(2) exist, **hard-gate backtest mode** to reject fundamental scoring, and document that
   multibagger performance evidence must be **forward, out-of-sample** only.

---

### HIGH

#### H-1. Percentile/sector ranks use a forward-looking, survivorship-selected peer panel
**What I checked.** `rank_multibagger()` → `scoring.sector_percentile_ranks()` and how `quant.py`
assembles `candidate_tickers` / `pool`.

**Evidence.** Percentiles (global and sector-relative) are computed **across the current candidate
pool**, which is today's index membership scored with today's data. The backtest module itself notes
"Single starting universe (the profile's seed/live constituents) — no historical re-membership
tracking" and "No survivorship adjustment; delisted names are silently dropped." A name's percentile in
2020 would thus be computed against firms that are known survivors in 2026, and against their 2026
fundamentals.

**Impact.** Even with a perfect PIT data feed, ranking against a today-selected, survivor-only peer set
biases historical ranks upward for eventual winners and understates competition. Compounds C-1.

**Recommended fix.** For any historical evaluation, build the peer panel from **point-in-time index
constituents** at each rebalance and rank each name only against contemporaneous peers with
contemporaneous (PIT) values.

---

### MEDIUM

#### M-1. ROCE / "operating margin" numerator uses yfinance **"EBIT"** (includes non-operating & interest income), not the spec's operating income
**What I checked.** `enrich_snapshot_with_financials()` line-item selection vs spec §3.2
("`ROCE = EBIT / Capital Employed`  # EBIT = operating income").

**Evidence.** `ebit = _pick(inc, n_inc, "EBIT", "Operating Income", …)` — the alias **"EBIT" is tried
first**. Live INFY income statement contains *both* rows:
`EBIT = [.., 4160, 4402, 4496, 4553]` vs `Operating Income = [.., 3825, 3849, 4077, 4089]`.
yfinance "EBIT" ≈ pretax income + interest expense, so it **includes treasury/other income**. Result:
`snap.roce` latest = **0.417** using "EBIT" vs **0.374** if operating income were used (~11% inflation).
The same `ebit` series feeds `operating_margin_series` (so a field *labelled* "operating margin" is
actually EBIT-margin), `_margin_capture` (M2), `interest_coverage`, and Altman X3.

**Impact.** Profitability is the **highest-weighted pillar (0.22)**. Using a numerator that includes
non-operating income systematically rewards cash-rich / high-other-income names — precisely the kind of
low-quality "earnings" the strategy is meant to discount. `operating_margin_series` is also mislabeled.
(Note: this is *defensible* as a textbook ROCE definition; the real issue is the **inconsistency with the
written spec** and the mislabeling.)

**Recommended fix.** Either (a) reorder aliases to prefer `"Operating Income"` / `"Total Operating
Income As Reported"` to honor the spec, or (b) update spec §3.2 to state ROCE uses reported EBIT and
rename `operating_margin_series` → `ebit_margin_series`. Pick one and make code, labels, and spec agree.

#### M-2. `earnings_cagr` (drives PEG V2 and RF8) uses raw first→last endpoints, contrary to spec V1
**What I checked.** `_cagr()` in `enrich_snapshot_with_financials`.

**Evidence.** `_cagr` takes `(last/first)^(1/yrs) − 1` on the filtered series endpoints. Spec V1
explicitly says "prefer normalized/median-year to blunt base effects." A single depressed or inflated
base year swings the CAGR (and hence PEG and the RF8 veto) sharply. Also, the two series-building lines
(`revenue_series = [x for x in revenue if x is not None]`, same for NI) **collapse interior `None`s**,
so a mid-series gap silently shortens `yrs` and misdates the endpoints.

**Impact.** PEG (a full member of the 0.15 growth/valuation pillar) and the RF8 perception-veto can be
noisy/wrong for names with a lumpy base year. Medium because it is one signal among many and guarded by
`g5 > 0`.

**Recommended fix.** Use a regression-based or median-anchored growth estimate; keep positional
alignment (don't drop interior `None`s before computing CAGR).

#### M-3. Unit tests pin correctness on synthetic fixtures only — they don't guard the two issues above
**What I checked.** `tests/test_multibagger.py` (all 65 tests pass).

**Evidence.** The tests are genuinely good at *numerical* pinning: Beneish/Altman/consistency/veto
fixtures are hand-computed and asserted to real numbers (not just "runs without error"), and the
sector-fallback and governance-neutral behaviors are checked. **But**: (i) no test exercises the
`_pick` alias priority, so the EBIT-vs-operating-income choice (M-1) is unpinned; (ii) no test asserts
any point-in-time / `as_of` behavior (there is none to assert); (iii) the enrichment fixture uses a
single line named `"Operating Income"` with no competing `"EBIT"` row, so it happens to sidestep M-1
entirely and gives false comfort. The forensic fixtures also never test cross-statement period-count
mismatch (see L-4).

**Recommended fix.** Add a fixture containing both `"EBIT"` and `"Operating Income"` rows and assert the
intended one is used; add an `as_of` regression test once C-1 is addressed; add a Beneish test with
income/balance/cashflow of differing lengths.

---

### LOW

- **L-1. RF5 proxy mismatch.** Spec RF5 = "interest coverage < 1.5 **and rising net-debt/EBITDA** over
  3y". Code uses `debt_rising` = *gross* total debt higher at end vs start of window. Rising gross debt
  ≠ rising net-debt/EBITDA (ignores cash build and EBITDA growth). Recommend computing a net-debt/EBITDA
  trend.
- **L-2. RF8 simplification.** Spec RF8 requires "PE up ≫ EPS over 3–5y **and** PE > 40 with g5 ≤ 0".
  Code only checks `pe_trailing > 40 and earnings_cagr ≤ 0`; the "PE re-rated far beyond EPS" leg is
  dropped. Directionally the binding condition, but not the full rule.
- **L-3. RF1 / RF2 edge gaps.** RF1 fires on `fcf_neg_years ≥ 3` without enforcing the "of last 5 years"
  window or the "early-stage growth exception". RF2's alternative clause ("CFO/NI < 0.5 for 3
  consecutive years") is not implemented, and `ocf_to_np_multiyear` is only set when cumulative NI > 0,
  so a cumulatively loss-making firm can never trip RF2 (it would rely on Altman/others instead).
- **L-4. Beneish cross-statement alignment.** `beneish_m_score` aligns income/balance/cashflow purely by
  negative index (`-1`, `-2`), not by matching period-end dates. If the three statements return
  different period *counts*, the prior-year (t−1) terms (DSRI, GMI, AQI, LVGI, SGAI, DEPI) can be pulled
  from mismatched fiscal years. In practice yfinance returns the same periods for all three, so this is
  latent, not observed. Recommend date-aligning before indexing.
- **L-5. `earnings_yield` signal = 1/PE, not spec's EBIT/EV (V5).** Documented Tier-A fallback; it is a
  weaker Greenblatt leg (ignores capital structure). Fine as a proxy, worth noting.

---

## Positive confirmations (things that are correctly done)

- **Beneish coefficients / intercept / threshold are exactly right**, including the correct signs
  (`−0.172·SGAI`, `−0.327·LVGI`, `+4.679·TATA`) and the `M > −1.78` manipulator rule. Hand recompute of
  the clean fixture = −2.476; the high-accrual fixture (NI ≫ CFO) correctly pushes M above −1.78.
- **Altman Z''-EM coefficients and zones are exactly right**; `X4 = equity/total-liabilities`, missing
  RE treated conservatively as 0, and financials correctly skipped.
- **Pillar weights match the spec §4 table exactly** and are re-normalized to sum 1.
- **Governance/Tier-C handling is honest.** The `promoter_governance` pillar defaults to neutral **0.5**
  when no manual pledge/holding-trend data is present; the known-unreliable `heldPercentInsiders`
  proxy is extracted into `SIGNAL_EXTRACTORS` but is **not referenced by any pillar in `PILLARS`**, so it
  genuinely does not contribute to any score (verified — the claim in the module comment holds). Tier-C
  manual overrides are never fabricated; RF6/RF7 stay live only when a human supplies them.
- **Graceful degradation everywhere:** every derived field is `None`/empty when inputs are missing;
  vetoes never fire on missing data; ROCE/gross-profitability/Altman are skipped for financials
  (`is_financial` detection by sector keyword). Spot-check: INFY's `DIO` correctly returned `None`
  (no inventory line for an IT firm).
- **True FCF, accruals, gross profitability, and working-capital day formulas are correct** and
  reproduced sensible live values (INFY FCF positive every year, accruals −0.044, ROCE ~37–42%;
  TITAN DIO ~222 days as expected for jewelry, `ocf_to_np` 0.535 just above the RF2 0.5 line).
- **Classic path is untouched**: multibagger enrichment and ranking are gated behind
  `scoring_mode == "multibagger"`; `FactorReport`'s new fields are optional with classic defaults;
  the full 65-test suite passes.

---

## Numerical spot-check (live, 2026-07-09)

| Field | INFY.NS | TITAN.NS | Sanity |
|---|---|---|---|
| financials status / periods | ok / 5 (FY22–FY26) | ok / 4 (FY23–FY26) | OK |
| ROCE (latest / via_proxy) | 0.417 / False | 0.384 / False | High, plausible; **inflated by EBIT choice — M-1** |
| Gross profitability | 0.370 | 0.280 | OK |
| Accruals ratio | −0.044 | −0.009 | Low/negative = cash-backed, OK |
| FCF posrate / neg years | 1.0 / 0 | 0.75 / 1 | OK (Titan one negative year) |
| OCF/NP (multiyear) | 1.14 | 0.535 | OK; Titan borderline vs RF2 0.5 |
| Beneish M | −2.73 | −2.29 | Both < −1.78 (clean), OK |
| Altman Z''-EM | 11.49 | 6.39 | Both safe (> 2.6), OK |
| earnings_cagr / PEG | 0.041 / 3.43 | 0.160 / 4.96 | PEG rich because low g / high PE — arithmetic consistent (**endpoint-CAGR fragility, M-2**) |
| Interest coverage | 96.9 | 6.76 | OK |

The `20/(100·cagr)` PEG identity, the `(NI−CFO)/TA` accruals, and the Altman/Beneish outputs all
reconcile with the raw statement lines pulled in the same run.

---

## Bottom line for decision-makers

- Ship it as a **live screening mode** — the math is sound and the guardrails (neutral governance, veto
  pass, graceful degradation, coverage-shrink) are well built.
- Do **not** publish or rely on any historical "success rate" for the multibagger strategy computed with
  the current data path. Fix **C-1** (point-in-time gating) and **H-1** (PIT peer panel / survivorship)
  first, and reconcile **M-1** so the headline profitability pillar matches the written spec.

---

## Fixes applied (Phase-2 remediation changelog)

> Appended after the read-only audit above. This section records the concrete code
> fixes made to resolve the Medium/Low findings, plus the consistency-operator
> recommendation. **C-1 and H-1 (point-in-time / survivorship) are NOT addressed here**
> — they remain open and the "forward, out-of-sample only" caveat stands. Classic
> 5-factor mode is untouched (all changes are gated on `scoring_mode == "multibagger"`
> or on optional statement-derived fields); full suite: **82 passed**.

Files changed: `src/data/provider.py`, `src/factors/multibagger.py`, `tests/test_multibagger.py`.

- **M-1 (ROCE numerator) — RESOLVED.** `enrich_snapshot_with_financials` now keeps two
  distinct income extractions: `operating_income` (prefers `"Operating Income"` /
  `"Total Operating Income As Reported"`, falls back to `"EBIT"`) drives **ROCE** and the
  **operating-margin series** per spec §3.2 ("EBIT = operating income"), while the original
  `ebit` (prefers `"EBIT"`) still drives **interest coverage** and **Altman X3**. The
  `operating_margin_series` is now a genuine operating margin. New test
  `test_enrich_roce_uses_operating_income_not_ebit` supplies BOTH rows and asserts ROCE uses
  operating income (0.24, not 0.40) — closing the M-3 fixture gap.

- **M-2 (robust growth) — RESOLVED.** `_cagr` (raw first→last endpoint) replaced by
  `_robust_growth`, a log-linear OLS slope (`exp(slope) − 1`) over the series indexed by
  period position. Interior `None`/non-positive values are skipped but keep their time slot,
  so a mid-series gap no longer misdates the endpoints. The `g5 > 0` guard for PEG is kept.
  Tests: `test_robust_growth_tames_lumpy_base_year`,
  `test_robust_growth_keeps_positional_alignment_through_none`,
  `test_enrich_earnings_cagr_is_robust_estimate`.

- **Consistency level leg — RESOLVED.** `roce_level` / `roe_level` extractors now rank the
  multi-year **mean** of the series (`series_mean`) rather than the latest TTM value, honoring
  "consistency > peak" (§3.1 / §7.1), with a fallback to the latest value when the series is
  too short (< 2 points). Test `test_roce_level_uses_series_mean_not_latest`.

- **RF5 (veto) — RESOLVED.** The gross `debt_rising` proxy is replaced by a rising
  **net-debt/EBITDA** trend (`net_debt = total_debt − cash`, `EBITDA = EBIT + depreciation`)
  computed over the window in enrichment (`net_debt_ebitda_rising`), combined with interest
  coverage < 1.5. `debt_rising` is retained as a coarse signal only. Tests:
  `test_veto_rf5_net_debt_ebitda_rising`, `test_veto_rf5_not_fired_on_gross_debt_alone`,
  `test_enrich_net_debt_ebitda_trend_computed`.

- **RF8 (veto) — RESOLVED (with a documented spec deviation).** Added the "PE re-rated far
  beyond EPS" leg, approximated from a multi-year **price CAGR** vs the **earnings CAGR**
  (`_pe_rerated_beyond_eps`): PE multiple expansion ≈ `(1+price_cagr)/(1+g5) − 1`, flagged
  when ≥ ~50% while earnings are roughly flat. `price_cagr` is populated best-effort in
  `get_snapshot_enriched` from 5y price history (a clean PE history is unavailable from free
  data). **Deviation:** the spec joins the two legs with AND; because leg (b) is only an
  approximation and often uncomputable on free data, the binding leg (PE > 40 & g5 ≤ 0) stays
  sufficient on its own and a clearly-computed leg (b) reinforces/extends it. Noted in a code
  comment. Tests: `test_veto_rf8_binding_leg_still_fires`,
  `test_veto_rf8_price_rerated_beyond_eps`, `test_no_rf8_when_price_tracks_eps`.

- **RF1 (veto) — RESOLVED.** Now counts FCF < 0 within the **trailing 5-year window**
  (`fcf_series[-5:]`), requiring ≥ 3, rather than over all history. Tests:
  `test_veto_rf1_only_counts_last_5_years`, `test_veto_rf1_fires_within_last_5_years`.

- **RF2 (veto) — RESOLVED.** Added the alternative clause **"CFO/NI < 0.5 for 3 consecutive
  years"** (`cfo_np_below_half_streak`) and handling for the **cumulative-NI ≤ 0** case
  (`cum_np_nonpositive`): a persistently loss-making firm now trips RF2 even though the
  cum(CFO)/cum(NP) ratio is left `None` (meaningless with non-positive cumulative earnings).
  Tests: `test_veto_rf2_consecutive_low_cfo_ni`, `test_veto_rf2_cumulative_losses`,
  `test_enrich_cumulative_losses_sets_rf2_flag`, `test_enrich_cfo_ni_streak_computed`.

- **L-4 (Beneish/enrichment date alignment) — NOT DONE (left as noted).** Cross-statement
  date-alignment before positional indexing was deemed higher-risk than the other fixes
  (touches the forensic call path and its hand-computed fixtures); in practice yfinance returns
  matching periods for all three statements, so it stays latent. Left for a follow-up.

- **C-1 / H-1 (point-in-time & survivorship) — OUT OF SCOPE, STILL OPEN.** No look-ahead
  gating or PIT peer panel was added; multibagger performance evidence must remain forward,
  out-of-sample only.
