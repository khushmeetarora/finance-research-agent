Personal multi-agent research CLI. Not a trading bot. Not financial advice. Not client/NDA code.

Deterministic scoring first. LLM agents reason over those numbers and may not invent values. No LLM? The run still finishes.

```powershell
python -m src.cli research -p india_adult -t "best IT stocks in India" -n 10 --no-llm
```

Interesting choice: bounded Bull vs Bear debate, then a Risk/Profile agent applies constraints. Full notes below.

---
# Finance Research Agent (FRA)

A CLI-first, multi-agent **investment research** workflow that ranks the best
stocks/indices to invest in for a given domain / country / world, tailored to
configurable investor profiles. All data comes from **free, no-API-key** public
sources. The pipeline is fully deterministic without an LLM, and adds LLM analyst
reasoning on top when one is available.

> **Disclaimer.** This software produces educational/research output. It is
> **not financial advice**. No real orders are placed. All numbers come from
> public free data sources and may be stale, incomplete, or wrong - verify
> before acting.

---

## Contents

- [What it does](#what-it-does)
- [Scoring versions](#scoring-versions)
- [Profiles](#profiles)
- [Branch model (dev / main)](#branch-model-dev--main)
- [Quickstart](#quickstart)
- [CLI reference](#cli-reference)
- [Free data sources](#free-data-sources)
- [Key features](#key-features)
- [Project structure](#project-structure)
- [Deep-dive docs](#deep-dive-docs)
- [What it is NOT](#what-it-is-not)
- [Credits](#credits)

---

## What it does

1. Resolves the user's target (a specific ticker, or "best X in domain Y") into
   a candidate ticker universe via index constituents and sector lists.
2. Fetches fundamentals + price history through a free `DataProvider`
   abstraction (yfinance + India/Germany helpers, on-disk cached).
3. Runs a deterministic **scoring engine** (classic 5-factor **or** the V2
   7-pillar Multibagger Quality Score) and produces a percentile composite
   ranking.
4. Runs LLM analyst agents (Fundamentals / Technical / News+Sentiment / Macro)
   that *reason over* the deterministic numbers and cite evidence - they are
   forbidden from inventing numerical values.
5. Holds a bounded Bull vs Bear debate, then a Risk + Profile/Tax agent applies
   profile-specific constraints (tax efficiency, suitability, currency).
6. The Research Manager reconciles everything and emits a ranked report
   (Markdown / optional Excel) plus a persistent memory log.

**One-line architecture:**

`Universe -> DataProvider -> ScoringEngine -> Analysts -> Bull/Bear Debate -> Risk+Profile -> Manager -> Report`

---

## Scoring versions

FRA supports two scoring engines. Pick one per run with `--mode` (or set
`scoring_mode` in the profile). The classic path is never affected by the V2 path.

### V1 - Classic 5-factor (`--mode classic`, default)

A deterministic factor engine producing a coverage-weighted percentile composite
across five factors:

| Factor | Signals |
|---|---|
| Quality | ROE, margins, ROIC proxy |
| Value | PE, PB, PS, EV/EBITDA, yields |
| Momentum | 12-1m / 6-1m price momentum |
| Financial health | D/E, current ratio, net-debt/EBITDA |
| Earnings quality | cash conversion / accruals |

Weights are set per profile (`factor_weights`) and normalized internally.

### V2 - Multibagger Quality Score (`--mode multibagger`)

An additive 7-pillar "Multibagger Quality Score" with sector-relative
normalization and a hard red-flag **veto pass**, implementing
`docs/FRA_V2_STRATEGY.md`.

| Pillar | Weight |
|---|---|
| Profitability (ROCE consistency, gross profitability) | 0.22 |
| Earnings quality (Sloan accruals, OCF/NP, true FCF) | 0.18 |
| Balance-sheet safety (Altman Z", interest coverage, leverage) | 0.15 |
| Growth & valuation (PEG within sector, earnings CAGR) | 0.15 |
| Moat / pricing power (through-cycle gross-margin) | 0.12 |
| Promoter / governance (Tier-C manual inputs; neutral by default) | 0.10 |
| Re-rating catalysts | 0.08 |

V2 also includes:

- **Forensic screens** - Beneish M-Score (earnings-manipulation) and
  Altman Z"-EM (distress), used by the veto pass. Formulas independently audited
  (`docs/FRA_V2_AUDIT.md`).
- **Red-flag veto pass** - 9 hard/soft red flags (negative FCF streaks,
  cash-flow vs profit divergence, Beneish/Altman thresholds, weak interest
  coverage, promoter pledge, auditor red flags, over-valuation, etc.).
- **Macro / regime + news overlay** (opt-in) - a point-in-time regime layer that
  tilts pillar weights and adds re-rating context. Off by default; enable with
  `factor_config.use_macro_overlay: true` in a profile. See `docs/FRA_V2_MACRO.md`.
- **Point-in-time backtest harness** - `scripts/backtest_multibagger.py` +
  `src/backtest/asof.py`, validated against a labeled historical multibagger
  dataset (`data/multibagger_dataset.csv`). See `docs/FRA_V2_BACKTEST_RESULTS.md`.
  Honest headline: with **free** data (yfinance carries only ~4-5 recent fiscal
  years) a strict point-in-time historical hit-rate is **not** achievable; V2 is
  valid for **present-day screening**, not for historical success-rate claims.

---

## Profiles

Profile YAMLs live in `config/profiles/`. List them with
`python -m src.cli profiles`.

| Profile | Market | Currency | Default mode | Notes |
|---|---|---|---|---|
| `india_adult` | India (NSE/BSE) + global | INR | classic | Full universe, no restrictions. |
| `germany_student` | Germany (DAX/MDAX/Xetra ETFs) + global | EUR | classic | Lower-risk lean; Abgeltungssteuer / Sparerpauschbetrag aware. |
| `india_multibagger` | India (NSE/BSE) | INR | multibagger | V2 7-pillar; small/mid-cap floor. |
| `global_multibagger` | US / global large caps | USD | multibagger | V2 7-pillar; empty yahoo suffix so `GOOGL`, `AAPL` reach yfinance verbatim. |

Profiles control the universe menu, factor/pillar weights, tax rules, risk
constraints, currency, and (for V2) manual governance overrides. Tax rules live
in YAML so they can be updated without touching code. See `RUN_OPTIONS.md` §5 for
every field.

---

## Branch model (dev / main)

| Branch | Role |
|---|---|
| `main` | Stable / staging. Reviewed, tested code intended to be shareable. |
| `dev` | Experimentation. New strategies, features, and iterations land here first. |

Workflow: experiment on `dev`, and once a change is verified and tests are green,
merge it into `main`. Clone or check out `dev` to collaborate on in-progress work:

```bash
git checkout dev     # experiment here
# ...work, commit...
git checkout main    # merge verified work in
git merge dev
```

---

## Quickstart

```powershell
# 1. Environment (Windows / PowerShell)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env

# 2. (Optional) local, free LLM via Ollama - the pipeline also runs fully without one
ollama pull llama3.1:8b
ollama serve

# 3. Classic 5-factor research pass (India)
python -m src.cli research -p india_adult -t "best IT stocks in India" -n 10

# 4. V2 Multibagger screen (India)
python -m src.cli research -p india_multibagger -t "best multibagger candidates" -n 15

# 5. Fully offline / deterministic (no LLM) - fastest, reproducible
python -m src.cli research -p india_adult -t "best banks in India" -n 10 --no-llm
```

No LLM configured? Every run still produces factor/pillar picks and a report -
the LLM stages silently fall back to a deterministic stub. See `OLLAMA_SETUP.md`
and `SETUP_GUIDE.md` for details.

---

## CLI reference

The CLI (`src/cli.py`, built with Typer) exposes four sub-commands. Full,
code-grounded reference of every flag, env var, and profile field is in
[`RUN_OPTIONS.md`](RUN_OPTIONS.md).

### `research` - run a research pass and write a report

```powershell
python -m src.cli research -p <profile> -t <target> [options]
```

| Option | Short | Default | Description |
|---|---|---|---|
| `--profile` | `-p` | *required* | Profile id (`india_adult`, `germany_student`, `india_multibagger`, `global_multibagger`). |
| `--target` | `-t` | *required* | Free-text goal (`"best IT stocks in India"`) or a ticker (`INFY`, `SAP.DE`, `GOOGL`). |
| `--universe` | `-u` | profile default | Override universe (`NIFTY50`, `NIFTY500`, `BSE500`, `GLOBAL_LARGE`, `DAX`, ...). |
| `--domain` | `-d` | none | Sector hint (`banking`, `IT`, `pharma`, ...). |
| `--top` | `-n` | `10` | Top-N picks to surface. |
| `--mode` | | profile's `scoring_mode` | `classic` (5-factor) or `multibagger` (7-pillar). |
| `--no-llm` | | off | Skip all LLM stages; factor/pillar engine only. |
| `--no-excel` | | off | Skip the `.xlsx` report (Markdown still written). |
| `--rounds` | | `1` | Bull/Bear debate rounds (`0` disables debate). |
| `--as-of` | | none | ISO date stamp for reproducibility (affects input hash + report stamp). |

Examples:

```powershell
# V2 multibagger, override universe + sector, more picks
python -m src.cli research -p india_multibagger -t "quality compounders" -u NIFTY500 -d pharma -n 15

# Force multibagger mode on a classic profile
python -m src.cli research -p india_adult -t "long-term compounders" --mode multibagger

# Global single-name deep dive (US ticker, verbatim to yfinance)
python -m src.cli research -p global_multibagger -t GOOGL

# Reproducible, no Excel
python -m src.cli research -p india_adult -t "best IT stocks in India" --as-of 2026-06-21 --no-excel
```

### `backtest` - price-only walk-forward proxy of the composite ranker

```powershell
python -m src.cli backtest -p <profile> [--universe U] [--start YYYY-MM-DD] [--top N] [--benchmark ^NSEI]
```

| Option | Short | Default | Description |
|---|---|---|---|
| `--profile` | `-p` | *required* | Profile to source universe + tax rate. |
| `--universe` | `-u` | profile default | Override universe. |
| `--start` | | `2020-01-01` | Backtest start date. |
| `--top` | `-n` | `10` | Top-N equal-weight rebalanced portfolio. |
| `--benchmark` | | none | Benchmark ticker (`^NSEI`, `^GDAXI`, `^GSPC`). |

```powershell
python -m src.cli backtest -p india_adult --start 2020-01-01 -n 10 --benchmark ^NSEI
```

> This is a directional price-only proxy (quarterly rebalance, no point-in-time
> fundamentals). For the V2 point-in-time multibagger event study use
> `scripts/backtest_multibagger.py` (see `docs/FRA_V2_BACKTEST_RESULTS.md`).

### `history` - list recent runs

```powershell
python -m src.cli history -n 20
```

### `profiles` - list available profiles

```powershell
python -m src.cli profiles
```

### LLM selection (environment variables, not flags)

```powershell
# OpenAI
$env:LLM_PROVIDER = "openai"; $env:LLM_MODEL = "gpt-4o-mini"; $env:OPENAI_API_KEY = "sk-..."
# Anthropic
$env:LLM_PROVIDER = "anthropic"; $env:LLM_MODEL = "claude-3-5-sonnet-20240620"; $env:ANTHROPIC_API_KEY = "sk-ant-..."
# Local Ollama (default) - raise the timeout on CPU to avoid silent fallback
$env:LLM_PROVIDER = "ollama"; $env:LLM_MODEL = "llama3.1:8b"; $env:OLLAMA_TIMEOUT = "900"
```

If a provider/SDK/key is missing or unreachable, the factory silently returns a
deterministic stub - the pipeline never crashes for lack of an LLM. See
`RUN_OPTIONS.md` §3/§6 for every env var.

---

## Free data sources

All sources are free and require no API key.

| Layer | Source | Used for | Failure mode |
|---|---|---|---|
| Prices + fundamentals | yfinance | Primary `CompanySnapshot` for every ticker | Missing fields -> coverage drops, surfaced on report |
| Prices (cross-check) | Stooq CSV | Per-ticker `data_agreement` score | None -> single-source mode |
| Universe (IN) | NSE archives CSV | Live NIFTY 50/100/200/500 constituents | Falls back to seeded NIFTY50 |
| Universe (DE) | Wikipedia DAX page | Live DAX 40 constituents | Falls back to seeded DAX+MDAX |
| Universe (US) | Wikipedia S&P 500 page | Live S&P 500 constituents | Falls back to seeded global large-cap |
| Fundamentals (IN, V2) | screener.in-style public pages | Extra statement fields (India only) | Skipped -> yfinance-only |
| Macro / regime (V2) | Free macro proxies | Regime overlay + entry context | Overlay off -> unchanged scores |
| News | GDELT 2.0 DOC API | Cross-source news headlines | Falls back to yfinance news |
| Insider trades | SEC EDGAR full-text search | Form 4 buys/sales (US tickers only) | Returns empty signal |

---

## Key features

- **Two scoring engines** - classic 5-factor and V2 7-pillar multibagger,
  switchable per run.
- **Data health card** (OK / WARN / CRITICAL) printed under each run and at the
  top of the Markdown report + a dedicated Excel sheet.
- **Profile fit** (cosine similarity vs your factor weights), **coverage**,
  **after-tax expected return**, and an FX flag for cross-currency picks in the
  Picks table.
- **Factor regime** sheet - trailing 12-1m top-minus-bottom-quintile spread per
  factor, with drawdown warnings.
- **Reproducibility** - `--as-of` stamp + a SHA-256 `input_hash` of canonical
  inputs (same data -> same hash).
- **Persistent memory** - every run logged to `.fra_memory`, queryable via
  `history`.
- **Never crashes for missing data or LLM** - graceful `None` handling and a
  deterministic stub path throughout.

---

## Project structure

```
finance-research-agent/
  config/profiles/{india_adult, germany_student, india_multibagger, global_multibagger}.yaml
  src/
    cli.py
    graph/{orchestrator.py, state.py, conditional_logic.py}
    data/{provider.py, india.py, germany_global.py, screener.py,
          macro_signals.py, news_events.py, news_gdelt.py, insiders_edgar.py, cache.py}
    factors/{engine.py, metrics.py, scoring.py, multibagger.py, forensic.py, regime.py, after_tax.py, decay.py}
    backtest/{engine.py, asof.py}
    agents/{universe.py, fundamentals.py, technical.py, news_sentiment.py,
            macro.py, quant.py, researchers.py, risk_profile.py, manager.py}
    llm/factory.py
    report/{generator.py, excel.py, templates/}
    memory/store.py
  scripts/{backtest_multibagger.py, demo_macro_regime.py}
  tools/build_multibagger_dataset.py
  data/{multibagger_dataset.csv, multibagger_ground_truth.csv, value_destroyers.csv, backtest_*}
  docs/FRA_V2_*.md
  tests/
```

---

## Deep-dive docs

| Doc | What it covers |
|---|---|
| `RUN_OPTIONS.md` | Every CLI flag, env var, and profile field (code-grounded). |
| `SETUP_GUIDE.md` / `OLLAMA_SETUP.md` | Install + local LLM setup. |
| `docs/FRA_V2_STRATEGY.md` | The 7-pillar Multibagger Quality Score spec (source of truth). |
| `docs/FRA_V2_FEASIBILITY.md` | Feasibility of the V2 approach on free data. |
| `docs/FRA_V2_AUDIT.md` | Independent adversarial audit of the V2 formulas + bias-safety. |
| `docs/FRA_V2_RESEARCH.md` | Free-data feature research + macro/news signal brief. |
| `docs/FRA_V2_DATASET.md` | The labeled historical multibagger dataset methodology. |
| `docs/FRA_V2_MACRO.md` | Macro / regime + news overlay design + wiring. |
| `docs/FRA_V2_BACKTEST_PLAN.md` / `FRA_V2_BACKTEST_RESULTS.md` | Point-in-time backtest plan + honest results. |

---

## What it is NOT

- **Not a full backtester.** The `backtest` subcommand is a price-only proxy
  (no point-in-time fundamentals, no survivorship adjustment). The V2 PIT event
  study is honest about free-data limits (see above).
- **Not a trading bot** - research-only; no orders are placed.
- **Not an oracle** - LLMs reason over deterministic scores; they don't invent
  price targets or numeric values.

---

## Credits / inspiration

- TradingAgents (Tauric Research) - LangGraph specialist-agent pattern + debate.
- ai-hedge-fund - investor-persona framing.
- FinRobot (AI4Finance) - auditable Perception/Brain/Action layering.
- Asness/Frazzini/Pedersen and Jegadeesh/Titman - factor-model literature.
- Greenblatt (Magic Formula), Piotroski (F-Score), Novy-Marx (gross
  profitability), Beneish (M-Score), Altman (Z-Score) - V2 pillar/forensic basis.
