# FRA V2 — Macro / Regime + News/Event Overlay (free-data, PIT-safe)

> **Status:** Additive, self-contained layer. **The integration API described in
> §4 is now WIRED** into the scorer (`src/factors/multibagger.rank_multibagger`),
> the PIT backtest (`scripts/backtest_multibagger.py`, A/B), and (opt-in) the live
> path (`src/agents/quant.py`). The wiring is **additive and opt-in**: with no
> regime/overlay supplied every path is byte-for-byte identical to the
> pre-overlay behaviour, so the classic 5-factor mode, the live multibagger
> default, and all prior tests are unchanged. See §4 (marked *IMPLEMENTED*) for
> exactly how it is applied and how it stays a no-op by default.
>
> **Primary spec:** `docs/FRA_V2_RESEARCH.md` §4 (macro/geopolitical/news signals
> with free proxies + PIT-safe encoding) and §7 step 5. Companion guardrails:
> `docs/FRA_V2_STRATEGY.md` §2.7 (re-rating catalysts) and §7 (anti-naive-ranking).
> Measured A/B value of the overlay: `docs/FRA_V2_BACKTEST_RESULTS.md` **Phase 6**.

---

## 0. What this layer is (and is not)

The repo had **no regime layer**: the `macro` agent emits a single narrative
paragraph and consumes no per-ticker macro numbers (`src/agents/macro.py`). This
layer fills that gap with a small set of **free, no-key** macro/market series and
a **news/event keyword** layer, encoded so that a read for any historical
`as_of` uses **only data that was knowable on/before that date** (no look-ahead).

It is deliberately a **gate/tilt/context** layer, **kept out of the per-name
fundamental score** to avoid double-counting (`FRA_V2_RESEARCH.md` §4, and the
"screens, not verdicts" guardrail `FRA_V2_STRATEGY.md` §7.5). Nothing here vetoes
a stock; it produces context a later wiring step can overlay.

### New files

| File | Purpose |
|---|---|
| `config/macro.yaml` | Free-source registry (FRED ids / yahoo tickers), publication lags, thresholds, lookbacks. Overridable; module has built-in defaults if absent. |
| `src/data/macro_signals.py` | Fetch (FRED no-key CSV + yfinance), on-disk cache, graceful failure, and the **pure PIT transforms** (`as_of_series`, `momentum`, `delta`, `annualized_vol`, `zscore`, `percentile_rank`). |
| `src/factors/regime.py` | Regime classification (rates/inflation/crude/FX/risk/equity/credit + optional sector tailwind) + the **unwired integration API**. |
| `src/data/news_events.py` | News/event keyword layer over the existing free GDELT feed (`src/data/news_gdelt.py`), PIT-gated. |
| `tests/test_macro_signals.py`, `tests/test_regime.py`, `tests/test_news_events.py` | Hermetic unit tests (no network). |
| `scripts/demo_macro_regime.py` | Runnable demo (offline synthetic by default; `--live` for real free data). |

---

## 1. Signals implemented, with their free sources

All sources are free and require **no API key**. FRED via the public
`fredgraph.csv?id=<ID>` CSV endpoint; market series via `yfinance` (already a
repo dependency).

| Regime signal | Free proxy / source | Encoding | Flags produced |
|---|---|---|---|
| **Rate regime** | India policy/discount rate — FRED `INTDSRINM193N` (monthly) | Δlevel over ~12m (`delta`); ±0.25pp band | `regime∈{easing,tightening,neutral}`, `flag_rates_rising` |
| **Inflation regime** | India CPI — FRED `INDCPIALLMINMEI` (monthly) | YoY (`momentum` 365d) vs RBI 6% band; short-window annualised for direction | `regime∈{hot,moderate,cool}`, `flag_above_band`, `flag_rising` |
| **Crude regime** | Brent `BZ=F` (fallback WTI `CL=F`), yfinance | 20d momentum; ±10% spike/crash | `flag_spike`, `flag_crash` |
| **FX regime** | USD/INR `INR=X`, yfinance | 20d momentum (up = INR depreciation) + annualised vol | `flag_inr_depreciating`, `flag_inr_appreciating`, `flag_fx_stress` |
| **Risk regime** | India VIX `^INDIAVIX`, yfinance | ~2y percentile of latest; >80% risk-off, <30% risk-on | `regime∈{risk_off,risk_on,neutral}`, `flag_risk_off`, `flag_risk_on` |
| **Equity trend** | Nifty 50 `^NSEI`, yfinance | ~1y momentum | `flag_uptrend`, `flag_downtrend` |
| **Credit / curve (proxy)** | FRED `BAA10Y` (credit spread), `DGS10`/`DGS2` (US curve) | spread level + ~3m change; 10y−2y slope | `flag_credit_widening`, `flag_curve_inverted` |
| **Sector tailwind** (optional) | derived from the flags above | transparent per-sector rule map → tilt in `[-1,1]` | e.g. IT/pharma + on INR depreciation; Energy + on crude spike; Financials − on credit widening |

**News / event signals** (`news_events.py`, over free GDELT DOC API):

| Category | Example triggers | Direction |
|---|---|---|
| `war_geopolitics` | war, conflict, missile, sanctions, Strait of Hormuz | regime-level risk-off proxy |
| `policy_catalyst` | PLI, import/customs duty, China+1, privatization, budget, tariff | bullish re-rating catalyst (R4) |
| `earnings_upgrade` | beats estimates, profit surges, rating upgrade, order win | bullish |
| `governance_risk` | auditor resignation, SFIO, forensic audit, fraud, pledge, NCLT | bearish flag-for-review |

Plus a market-level `scan_macro_geopolitics()` that sums GDELT conflict-theme
volume as a coarse risk-off proxy.

---

## 2. How PIT / `as_of` correctness is enforced

The whole layer is built around one gate, `macro_signals.as_of_series`:

```python
def as_of_series(series, as_of, publication_lag_days=0):
    # keep a point stamped period-end D only when D + publication_lag_days <= as_of
```

1. **Fetch is separated from PIT filtering.** Fetchers return the *full* series;
   the regime layer always passes it through `as_of_series` with the series'
   configured `publication_lag_days` **before** computing any statistic. So a
   read for `as_of` can never see an observation released after `as_of`.
2. **Publication lags are explicit** (`config/macro.yaml`). A data point dated
   period-end `D` is only *knowable* on `D + lag`. Examples: CPI ≈ 21 days
   (released ~12th of the next month), repo ≈ 7 days (MPC decision date), daily
   market series 0–1 day. This mirrors the "encode each signal using the value
   **published/known** on the decision date" golden rule in `FRA_V2_RESEARCH.md` §4.
3. **All statistics are date-based, not index-based** (`momentum`, `delta`),
   so mixing monthly (CPI/repo) and daily (VIX/FX/crude) series is safe and the
   lookback window is honoured in calendar time.
4. **Injectable series provider.** `compute_regime(..., series_provider=...)`
   takes a `name -> full_series` callable, so tests feed fixture series and never
   hit the network — the PIT gate is exercised directly (see
   `test_regime.py::test_as_of_gating_hides_future_points` and
   `::test_publication_lag_blocks_unreleased_cpi`).
5. **News is PIT-gated too.** `news_events.pit_filter_articles(articles, as_of)`
   drops any article published after `as_of` (unparseable dates dropped under a
   historical `as_of`, conservative). See the honesty caveat in §5.

This is consistent with the existing statement-level PIT gate
(`src/backtest/asof.as_of_financials`, the `−90d` reporting-lag rule): the macro
layer applies the *same philosophy* to macro/news, with per-series lags.

---

## 3. Regime definitions (thresholds)

Defaults (overridable in `config/macro.yaml`):

- **Rates:** `easing` if Δrepo ≤ −0.25pp over 12m; `tightening` if ≥ +0.25pp; else `neutral`.
- **Inflation:** `hot` if CPI YoY ≥ 6% (RBI upper band); `cool` if ≤ 3%; else `moderate`. `flag_rising` compares an annualised short window (≈120d) to YoY.
- **Crude:** `flag_spike` if +20d momentum ≥ +10%; `flag_crash` if ≤ −10%.
- **FX (USD/INR):** `flag_inr_depreciating` if +20d momentum ≥ +2%; `flag_fx_stress` if annualised 20d vol ≥ 8% **or** |momentum| ≥ 2%.
- **Risk (VIX):** `risk_off` if latest is ≥ 80th percentile of ~2y; `risk_on` if ≤ 30th; else `neutral`.
- **Equity:** `flag_uptrend`/`flag_downtrend` from sign of ~1y Nifty momentum.
- **Composite:** a conservative vote — unknown signals do not vote; `risk_on`
  requires affirmative low-VIX/uptrend and no active stress; VIX carries double
  weight. Fully-offline / all-missing input → `label="unknown"` (safe no-op).

---

## 4. Integration design — **IMPLEMENTED** (how the overlay is wired)

The overlay is exposed as three **pure** functions in `regime.py`, bundled by a
new pure builder `regime.build_scorer_overlay(regime, events=None)` into a plain
dict:

```python
{
  "pillar_tilts":   {pillar: multiplicative factor, ...},   # §4.1
  "rerating_boost": float in [0, 0.10],                     # §4.3
  "entry_context":  {tighten_vetoes, cautions[...], ...},   # §4.2 (advisory)
  "regime_label":   "risk_on|risk_off|neutral|unknown",
  "as_of": ..., "sector": ...,
}
```

`rank_multibagger` gained two **keyword-only, default-`None`** parameters:
`overlay=<dict>` (one overlay for the whole panel) and
`overlay_by_ticker=<{ticker: dict}>` (per-name, used by the PIT backtest where
each name's regime is at its own as-of). **When both are `None` the function is
a strict no-op** — the composite, sort, vetoes and every field are byte-for-byte
what they were before, which is why the classic mode, the live default, and all
prior tests are unchanged. The scorer applies the overlay at the **compositing
stage only** and imports nothing from `regime.py` (it consumes a plain dict), so
it stays pure and unit-testable. The three pieces map to:

- **§4.1 tilt** → multiplies the pillar **weights** per name, then
  `_normalize_weights` re-sums to 1 (a pure tilt of the *existing* weights).
- **§4.3 boost** → added to the `rerating_catalysts` pillar **score**, clamped to
  `[0, 1]`.
- **§4.2 context** → stored on the new `FactorReport.regime_context` field
  (advisory; the veto pass `run_veto_pass` is **never** consulted or changed —
  context, never a silent kill).

**PIT backtest wiring (`scripts/backtest_multibagger.py`).** At each name's own
`entry_date` the harness computes `compute_regime(as_of, sector=…)` (PIT-gated,
no look-ahead), builds the overlay, and runs the cohort ranking **twice** — once
with `overlay_by_ticker=None` (A) and once with the per-name overlays (B) — so
the delta is measurable. Overlay-off (A) reproduces the prior Phase-5 numbers
exactly. News is intentionally omitted in the backtest (GDELT's shared feed is
forward-only PIT, §5), so the boost is the reproducible easing + sector-tailwind
component. Disable with `--no-overlay`.

**Live wiring (`src/agents/quant.py`).** Behind a profile flag
`factor_config.use_macro_overlay` (**default `false`**). When true and
`scoring_mode=multibagger`, a single market-level regime is computed at the
profile `as_of` (or today) and passed as `overlay=…`; any failure or offline run
degrades to `None`/no-op. Default-off means the live path is unchanged.

### 4.0 Original design notes (retained)

The intended integration point is
`src/factors/multibagger.rank_multibagger(..., pillar_weights=...)` and its veto
pass `run_veto_pass(...)`.

### 4.1 Regime tilt on the 7-pillar composite — `regime_pillar_tilts(regime)`

Returns a multiplicative factor (~`[1−s, 1+s]`, default `s=0.15`) for **every**
pillar in `DEFAULT_PILLAR_WEIGHTS`. Intended wiring (documented, not executed):

```python
from src.factors.multibagger import DEFAULT_PILLAR_WEIGHTS, rank_multibagger
from src.factors.regime import compute_regime, regime_pillar_tilts

reg   = compute_regime(as_of, sector=sector)          # PIT-safe
tilts = regime_pillar_tilts(reg)
w     = {p: DEFAULT_PILLAR_WEIGHTS[p] * tilts[p] for p in DEFAULT_PILLAR_WEIGHTS}
reports = rank_multibagger(snaps, pillar_weights=w)   # engine re-normalises to 1
```

Logic (from `FRA_V2_RESEARCH.md` §4 "profile tilts"):
- **easing / risk-on** → up-weight `growth_valuation` + `rerating_catalysts`, slightly down-weight `balance_sheet_safety`.
- **tightening / risk-off / FX-stress** → up-weight `balance_sheet_safety` + `earnings_quality`, down-weight `rerating_catalysts`; a flight-to-quality nudge to `profitability`.
- **all-unknown** → all factors `1.0` (a no-op), so an offline run is safe.

Because the engine's `_normalize_weights` re-sums to 1, this is a pure *tilt*, not
a re-weighting of magnitudes — it never changes the pillar set or the veto logic.

### 4.2 Veto-context / entry filter — `regime_entry_context(regime)`

Returns advisory flags (`tighten_vetoes`, `avoid_new_rich_multiples`,
`prefer_balance_sheet_safety`, `cautions[]`) for a **downstream entry filter**,
e.g. de-emphasise initiating rich-multiple names in a risk-off tape with
persistent FX stress. This is **context, never a silent kill** — consistent with
`FRA_V2_STRATEGY.md` §7.5. A wiring step could, for instance, lower the borderline
acceptance threshold or annotate the report when `tighten_vetoes` is set, without
adding new hard vetoes.

### 4.3 Re-rating-catalyst booster — `rerating_catalyst_boost(regime, events)`

A small bounded booster in `[0, 0.10]` for the R3/R4 leg of the
`rerating_catalysts` pillar, combining easing rates + a positive sector tailwind
+ policy-catalyst news hits (from `news_events.scan_company_events`). Intended to
be **added** to the R4 catalyst signal during wiring (R4 is Tier-C per §2.7), and
to remain a *proxy for review* given the news caveats in §5.

### 4.4 Why the overlay stays a clean, separable API (still true post-wiring)

The overlay is still a set of **pure functions + a plain-dict payload**; the
scorer consumes the dict and imports nothing from `regime.py`. This (a) keeps the
tilt/boost/context unit-testable in isolation, (b) matches the research brief's
instruction to use macro as a **gate/tilt outside the per-name fundamental
score** (the boost touches only R3/R4, the tilt only re-weights, the context
only annotates), and (c) means the wiring is exactly the documented one-liner:
compute `reg` at the as-of rebalance, `build_scorer_overlay(reg)`, and pass it to
`rank_multibagger(..., overlay=…)`. The measured value of the overlay on the
determinate PIT slice is reported honestly in
`docs/FRA_V2_BACKTEST_RESULTS.md` Phase 6.

---

## 5. Honest limits — what free macro/news data can and cannot support

- **News PIT is only *approximately* enforceable via the shared feed.**
  `get_news_gdelt` uses a `timespan` query relative to *now*, so it is naturally
  PIT for forward/near-real-time use only. For a historical `as_of` this layer
  applies a strict **publish-date safety gate** (`pit_filter_articles`), but a
  *true* historical event scan needs a date-bounded GDELT query
  (`startdatetime`/`enddatetime`) which the shared feed does not expose. This is
  documented and intentionally left for a later step to keep the change additive.
- **Keyword classification is noisy** (English-only headlines; false positives
  like "no fraud found"). These are **flags for review / soft tilts**, never
  silent vetoes (Tier-C, `FRA_V2_STRATEGY.md` §7.6).
- **Credit/curve is a *global proxy*.** A free, programmatic India AAA-vs-GSec
  spread is not reliably available; we use FRED BAA-10Y + the US 10y-2y slope,
  which co-move with — but are not identical to — India credit conditions.
- **FII/DII flows are not included** here. Free JSON exists (Mr. Chartist /
  NSE), but evening figures are provisional and revised next morning; adding it
  cleanly (with a 1-day lag) is a good follow-up but out of this layer's scope.
- **Macro is a regime gate/tilt, not alpha per name.** Consistent with the
  research brief, it is deliberately kept out of the fundamental composite.
- **Sector tailwind is a transparent heuristic**, not a fitted model — a small,
  auditable rule map, easy to override.

---

## 6. Runnable demo

Offline (deterministic synthetic series, **no network** — good for CI/docs):

```bash
conda run -n fra python scripts/demo_macro_regime.py
```

Live (real free FRED + yfinance; degrades gracefully per unavailable series):

```bash
conda run -n fra python scripts/demo_macro_regime.py --live --sector "Information Technology"
```

Illustrative offline output for two historical dates (an *easing / risk-on* tape
in mid-2019 vs a *risk-off crisis* tape at end-Q1 2020), abbreviated:

```
=== Regime @ 2019-06-30  (sector=Information Technology) ===
  composite : risk_on  (on=3 off=0 drivers=['vix_low', 'nifty_uptrend'])
  rates     : {'regime': 'easing', 'flag_rates_rising': False}
  risk      : {'regime': 'risk_on', 'flag_risk_off': False, 'flag_risk_on': True}
  equity    : {'flag_uptrend': True}
  pillar_tilts : {"growth_valuation": 1.15, "rerating_catalysts": 1.15, "balance_sheet_safety": 0.925, ...}
  entry_context: {'tighten_vetoes': False, 'cautions': []}

=== Regime @ 2020-03-31  (sector=Information Technology) ===
  composite : risk_off  (on=0 off=5 drivers=['vix_high', 'nifty_downtrend', 'fx_stress', 'crude_spike'])
  fx        : {'flag_inr_depreciating': True, 'flag_fx_stress': True}
  risk      : {'regime': 'risk_off', 'flag_risk_off': True}
  sector_tw : tilt=+1.00 reasons=['fx.flag_inr_depreciating:+']   # INR-weak tailwind for IT exporters
  entry_context: {'tighten_vetoes': True, 'cautions': ['risk_off_tape', 'fx_stress', 'crude_spike']}
```

The `as_of` gate is observable: the Mar-2020 VIX/crude/FX blow-off does **not**
leak into the 2019-06-30 read even though the same series objects contain the
later points.

---

## 7. Testing

Hermetic unit tests (no live network) cover:

- **Macro parsing / transforms** (`test_macro_signals.py`): FRED CSV parsing
  (missing `.`, unsorted, bad rows), `as_of_series` gating with/without lags,
  `momentum`/`delta`/`annualized_vol`/`zscore`/`percentile_rank`, config
  defaults, and graceful network-error failure.
- **Regime classification + PIT gating** (`test_regime.py`): easing/tightening,
  risk-on/off from VIX percentile, crude spike, INR depreciation, `as_of` hides
  future points, publication-lag blocks an unreleased CPI print, graceful
  failure when series are missing or the provider raises, sector tailwinds, and
  the integration API (bounded tilts covering all pillars, no mutation of
  `DEFAULT_PILLAR_WEIGHTS`, entry context, bounded booster).
- **News/event layer** (`test_news_events.py`): date parsing, PIT filter,
  keyword classification, per-company bias, `as_of` gating, and graceful failure
  when the feed raises.
- **Scorer wiring** (`test_macro_overlay_wiring.py`, added with the integration):
  no-op invariance (`overlay=None` == no-op unknown-regime overlay; empty
  `regime_context`), tilt math (a rerating-dominant tilt collapses
  `raw_composite` onto the rerating pillar; `DEFAULT_PILLAR_WEIGHTS` never
  mutated), boost math (added to the pillar score, clamped to `[0,1]`), the
  overlay never adds/removes a veto (a distressed name stays RF4-vetoed; a clean
  name is not killed by a risk-off `tighten_vetoes` context), per-name
  `overlay_by_ticker` application, and PIT correctness of the in-backtest regime
  (a post-as_of VIX spike does not flip the regime to risk-off).

Run just this layer + the wiring:

```bash
conda run -n fra python -m pytest tests/test_macro_signals.py tests/test_regime.py tests/test_news_events.py tests/test_macro_overlay_wiring.py -q
```
