# Finance Research Agent (FRA)

A CLI-first multi-agent **investment research** workflow that ranks the best
stocks/indices to invest in for a given domain / country / world, tailored to
two configurable investor profiles:

- **India (adult, no restrictions)** - full NSE/BSE + global universe.
- **Germany (student)** - lower-risk lean (DAX/MDAX/Xetra ETFs + global), with
  Abgeltungssteuer / Sparerpauschbetrag awareness.

> **Disclaimer.** This software produces educational/research output. It is
> **not financial advice**. No real orders are placed. All numbers come from
> public free data sources and may be stale, incomplete, or wrong - verify
> before acting.

## What it does

1. Resolves the user's target (a specific ticker, or "best X in domain Y") into
   a candidate ticker universe via index constituents and sector lists.
2. Fetches fundamentals + price history through a free `DataProvider`
   abstraction (yfinance + India/Germany helpers, on-disk cached).
3. Runs a deterministic **factor engine** (Quality / Value / Momentum /
   Financial Health / Earnings Quality) and produces a percentile composite
   ranking.
4. Runs LLM analyst agents (Fundamentals / Technical / News+Sentiment / Macro)
   that *reason over* the deterministic numbers and cite evidence - they are
   forbidden from inventing numerical values.
5. Holds a bounded Bull vs Bear debate, then a Risk + Profile/Tax agent applies
   profile-specific constraints (tax efficiency, suitability for a student,
   currency).
6. The Research Manager reconciles everything and emits a ranked report
   (Markdown / optional PDF) plus a persistent memory log.

## Architecture (one-line)

`Universe -> DataProvider -> FactorEngine -> Analysts -> Bull/Bear Debate -> Risk+Profile -> Manager -> Report`

## Free data sources used

All sources below are free and require no API key.

| Layer | Source | Used for | Failure mode |
|---|---|---|---|
| Prices + fundamentals | yfinance | Primary `CompanySnapshot` for every ticker | Missing fields -> coverage drops, surfaced on report |
| Prices (cross-check) | Stooq CSV | Per-ticker `data_agreement` score | None -> single-source mode |
| Universe (IN) | NSE archives CSV | Live NIFTY 50/100/200/500 constituents | Falls back to seeded NIFTY50 |
| Universe (DE) | Wikipedia DAX page | Live DAX 40 constituents | Falls back to seeded DAX+MDAX |
| Universe (US) | Wikipedia S&P 500 page | Live S&P 500 constituents | Falls back to seeded global large-cap |
| News | GDELT 2.0 DOC API | Cross-source news headlines | Falls back to yfinance news |
| Insider trades | SEC EDGAR full-text search | Form 4 buys/sales (US tickers only) | Returns empty signal |

## New CLI features

- `--as-of YYYY-MM-DD` stamps the report and the persisted run.
- `input_hash` is a SHA-256 of the canonical inputs - rerunning on the same
  data produces the same hash (auditability).
- The Picks table shows **profile fit** (cosine similarity vs your factor
  weights), **coverage**, **after-tax expected return**, and an FX flag for
  cross-currency picks.
- A **Data health** card (OK / WARN / CRITICAL) prints under each run; the
  same card is at the top of the Markdown report and on its own Excel sheet.
- A **Factor regime** sheet shows the trailing 12-1m top-quintile minus
  bottom-quintile spread per factor, with warnings on regime drawdowns.
- New `backtest` subcommand: `python -m src.cli backtest --profile india_adult --start 2022-01-01 --top 10 --benchmark "^NSEI"` runs a quarterly-rebalance walk-forward of a price-only proxy of the composite ranker, applies the profile's transaction-cost and long-term tax rate, and writes a multi-sheet Excel workbook with equity curve, holdings log, and metrics (annualised return, Sharpe, Sortino, max drawdown).

## Quickstart

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
copy .env.example .env

# Local (free) Ollama setup
ollama pull llama3.1:8b
ollama serve

# Run an India research pass
python -m src.cli research --profile india_adult --target "best IT stocks in India" --top 10

# Run a Germany (student) research pass on a specific ticker
python -m src.cli research --profile germany_student --target SAP.DE
```

The CLI also supports an offline/deterministic mode that skips LLM calls and
returns just the factor-engine ranking + report:

```bash
python -m src.cli research --profile india_adult --target "best banks in India" --top 10 --no-llm
```

## Project structure

```
finance-research-agent/
  config/profiles/{india_adult.yaml, germany_student.yaml}
  src/
    cli.py
    graph/{orchestrator.py, state.py, conditional_logic.py}
    data/{provider.py, india.py, germany_global.py, cache.py}
    factors/{engine.py, metrics.py, scoring.py}
    agents/{universe.py, fundamentals.py, technical.py, news_sentiment.py,
            macro.py, researchers.py, risk_profile.py, manager.py}
    llm/factory.py
    report/{generator.py, templates/}
    memory/store.py
  tests/
```

## Profiles

Profile YAMLs in `config/profiles/` control:

- universe defaults (NIFTY500 / DAX+MDAX / S&P 500 / world)
- factor weights (e.g. India adult tilts a bit harder on Momentum; Germany
  student tilts harder on Quality + Financial Health)
- tax rules (rates, holding-period thresholds, annual exemptions)
- risk constraints (max position concentration, min market cap, ETF preference)
- currency

Tax rules and rates live in YAML so they can be updated without touching code.

## What it is NOT

- Not a *full* backtester. The `backtest` subcommand uses a price-only proxy
  for the composite (no point-in-time fundamentals, no survivorship adjustment,
  no factor-tilt parity). It's a directional sanity check, not a research-grade
  walk-forward.
- Not a trading bot - this v1 is research-only.
- Not an oracle - LLMs reason over deterministic factor scores; they don't
  produce price targets out of thin air.

## Credits / inspiration

- TradingAgents (Tauric Research) - LangGraph specialist-agent pattern + debate.
- ai-hedge-fund - investor-persona framing.
- FinRobot (AI4Finance) - auditable Perception/Brain/Action layering and
  report generation.
- Asness/Frazzini/Pedersen and Jegadeesh/Titman - factor model literature.
