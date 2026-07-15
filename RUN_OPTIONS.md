# Finance Research Agent — Run Options Reference

A complete, code-grounded reference of **every option you can tweak** when running
this pipeline. Everything below was read directly from the source; where an
"expected" knob does **not** exist, it is called out explicitly.

The CLI is built with [Typer]. The entry point is `src/cli.py` and there are
**four sub-commands**: `research`, `backtest`, `history`, and `profiles`.

> Invoke it however your project is wired up. Common forms (PowerShell):
>
> ```powershell
> python -m src.cli research --profile india_adult --target "best IT stocks in India"
> # or, if an entry point named `fra` is installed:
> fra research --profile india_adult --target "best IT stocks in India"
> ```
>
> The examples below use `python -m src.cli`. Substitute your launcher as needed.

---

## 1. Quick-start command examples

All knobs that matter live on the `research` command plus a handful of
environment variables (for model selection). Copy-paste these PowerShell
snippets.

### Default run (offline-safe, uses local Ollama if available)

```powershell
python -m src.cli research -p india_adult -t "best IT stocks in India"
```

If no LLM is reachable, the pipeline still produces factor-engine picks (it
silently falls back to a deterministic stub). See `src/llm/factory.py`.

### Quant-only / fully offline (no LLM at all, fastest, deterministic)

```powershell
python -m src.cli research -p germany_student -t "DAX quality names" --no-llm
```

`--no-llm` skips all analyst + debate + manager-LLM stages and synthesizes picks
straight from the factor engine (`src/graph/orchestrator.py`,
`src/agents/manager.py:run_quant_only`).

### Choose a specific model — OpenAI

```powershell
$env:LLM_PROVIDER = "openai"
$env:LLM_MODEL    = "gpt-4o-mini"
$env:OPENAI_API_KEY = "sk-..."
$env:LLM_TEMPERATURE = "0"
python -m src.cli research -p india_adult -t "best banks in India" -n 8
```

### Choose a specific model — Anthropic

```powershell
$env:LLM_PROVIDER = "anthropic"
$env:LLM_MODEL    = "claude-3-5-sonnet-20240620"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m src.cli research -p india_adult -t "pharma leaders"
```

### Choose a specific model — local Ollama (default provider)

```powershell
$env:LLM_PROVIDER = "ollama"
$env:LLM_MODEL    = "llama3.1:8b"
$env:OLLAMA_HOST  = "http://localhost:11434"
$env:OLLAMA_TIMEOUT = "900"   # raise from the 120s default for CPU Ollama (avoids silent fallback)
python -m src.cli research -p germany_student -t "EURO_STOXX_50 dividend payers"
```

### Multi-round bull/bear debate

```powershell
$env:LLM_PROVIDER = "openai"; $env:LLM_MODEL = "gpt-4o-mini"; $env:OPENAI_API_KEY = "sk-..."
python -m src.cli research -p india_adult -t "best IT stocks in India" --rounds 3
```

`--rounds 0` disables the debate stage entirely (analysts + manager still run).
See `src/graph/orchestrator.py` and `src/agents/researchers.py`.

### Override the universe, narrow by sector, and surface more picks

```powershell
python -m src.cli research -p india_adult -t "large caps" -u NIFTY50 -d IT -n 15
```

### Single-ticker deep dive (target that "looks like a ticker")

```powershell
python -m src.cli research -p germany_student -t SAP.DE
```

### Reproducible stamp + skip the Excel workbook

```powershell
python -m src.cli research -p india_adult -t "best IT stocks in India" --as-of 2026-06-21 --no-excel
```

### Backtest the deterministic composite (price-only proxy)

```powershell
python -m src.cli backtest -p india_adult --start 2020-01-01 -n 10 --benchmark ^NSEI
```

### List profiles / view recent runs

```powershell
python -m src.cli profiles
python -m src.cli history -n 20
```

---

## 2. CLI flags

### `research` — run a research pass and write a Markdown (+ Excel) report
Source: `src/cli.py` (the `research` command).

| Option | Short | Type | Default | Allowed / examples | Description |
|---|---|---|---|---|---|
| `--profile` | `-p` | str | **required** | `india_adult`, `germany_student` (any file in `config/profiles/*.yaml`) | Investor profile id. Selects currency, tax rules, factor weights, universe, risk constraints. |
| `--target` | `-t` | str | **required** | `"best IT stocks in India"`, `INFY`, `SAP.DE` | Free-text goal. If it "looks like a ticker" it triggers single-name research; otherwise sector keywords route the universe (`src/agents/universe.py`). |
| `--universe` | `-u` | str | `None` → profile default | `NIFTY50`, `NIFTY500`, `BSE500`, `GLOBAL_LARGE`, `DAX`, `DAX_PLUS_MDAX`, `EURO_STOXX_50` | Override the candidate index. Allowed values come from the profile's `universe.available`. |
| `--domain` | `-d` | str | `None` | `banking`, `IT`, `pharma`, `energy`, … | Sector hint that further narrows the pool via keyword matching (`_SECTOR_KEYWORDS` in `src/agents/universe.py`). |
| `--top` | `-n` | int | `10` | any positive int | Top-N picks to surface. Also the shortlist size fed to the LLM stages (`src/agents/quant.py`). |
| `--no-llm` | — | flag | `False` | present / absent | Skip all LLM stages; use the factor engine only. Maps to `use_llm = not no_llm` (`src/graph/conditional_logic.py`). |
| `--no-excel` | — | flag | `False` | present / absent | Skip writing the `.xlsx` report (Markdown still written). |
| `--rounds` | — | int | `1` | `0`+ (negatives clamped to 0 via `max(0, rounds)`) | Number of bull/bear debate rounds when LLM is enabled. `0` disables debate. |
| `--as-of` | — | str | `None` | ISO date `YYYY-MM-DD` | Reproducibility stamp. **Affects only the input hash and report stamp** — data fetch is still best-effort live (per the help text). |

### `backtest` — price-only walk-forward backtest of the composite ranker
Source: `src/cli.py` (the `backtest` command) + `src/backtest/engine.py`.

| Option | Short | Type | Default | Allowed / examples | Description |
|---|---|---|---|---|---|
| `--profile` | `-p` | str | **required** | profile id | Profile to source the ticker universe and tax rate from. |
| `--universe` | `-u` | str | `None` → profile default | same as research | Override the universe. |
| `--start` | — | str | `2020-01-01` | `YYYY-MM-DD` | Backtest start date. |
| `--top` | `-n` | int | `10` | positive int | Top-N equal-weight rebalanced portfolio. |
| `--benchmark` | — | str | `None` | `^NSEI`, `^GDAXI`, `^GSPC` | Optional benchmark ticker plotted alongside the equity curve. |

The backtest's transaction cost is **not** a CLI flag — it is read from the
profile's `return_model.transaction_cost_bps` (default 15). Rebalancing is
quarterly and hardcoded; the scoring proxy (12-1m + 6-1m momentum − vol) is also
hardcoded in `src/backtest/engine.py`.

### `history` — list recent runs
Source: `src/cli.py` + `src/memory/store.py`.

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--limit` | `-n` | int | `20` | Max records to show from the on-disk memory store (`.fra_memory`). |

### `profiles` — list available profiles
Source: `src/cli.py`. **No options.** Prints the stem of each
`config/profiles/*.yaml`.

---

## 3. Models & LLM settings

All model selection is done with **environment variables** (read in
`src/llm/factory.py` and echoed in `src/cli.py`), not CLI flags. The
`.env.example` file is loaded automatically via `load_dotenv()`.

### Providers & how to select a model

| Provider (`LLM_PROVIDER`) | Selected model (`LLM_MODEL`) examples | Required key / host | Notes |
|---|---|---|---|
| `ollama` *(default)* | `llama3.1:8b` *(default)*, any local model tag | `OLLAMA_HOST` (default `http://localhost:11434`) | Local, no API key. Calls `POST /api/generate`. |
| `openai` | `gpt-4o-mini`, `gpt-4o`, etc. | `OPENAI_API_KEY` | Uses chat completions; supports JSON / json_schema response formats. |
| `anthropic` | `claude-3-5-sonnet-20240620`, etc. | `ANTHROPIC_API_KEY` | `max_tokens` hardcoded to **1024**. Structured output emulated via tool-use. |
| `cursor_io` | *(model name ignored)* | `CURSOR_LLM_DIR` (default `./llm_cache`) | File-IO provider: dumps each prompt to `prompts/<sha>.txt`, reads answers from `responses/<sha>.json`. For two-pass "use the Cursor chat as the analyst" workflows. **Not listed in `.env.example`** but fully supported. |
| *(anything else / unreachable / SDK missing)* | — | — | Falls back to a deterministic **`_Stub`** that returns `{}`; analysts then synthesize from factor scores. The pipeline never crashes for lack of an LLM. |

> Important: even with `LLM_PROVIDER=openai/anthropic/ollama`, if the SDK isn't
> installed or the key/host is missing/unreachable, the factory **silently
> returns the stub**. There is no hard error — check the console line
> `LLM provider=… model=…` and your report's "LLM unavailable" notices.

### Model parameters

| Env var | Type | Default | Applies to | Description |
|---|---|---|---|---|
| `LLM_PROVIDER` | str | `ollama` | all | Which backend to use (`openai` / `anthropic` / `ollama` / `cursor_io`). Lower-cased. |
| `LLM_MODEL` | str | `llama3.1:8b` | openai, anthropic, ollama | Provider-specific model name. Ignored by `cursor_io` and the stub. |
| `LLM_TEMPERATURE` | float | `0` | openai, anthropic, ollama | Sampling temperature. Invalid values fall back to `0.0`. Keep at `0` for determinism. |

There is **no** configurable `max_tokens`, `top_p`, `seed`, or per-agent model
override exposed. `max_tokens=1024` is hardcoded for Anthropic only; OpenAI and
Ollama use provider defaults. The Ollama per-request network timeout **is**
configurable via `OLLAMA_TIMEOUT` (seconds, default 120) — see §6. **Raise it to
`900` for CPU Ollama runs**, otherwise large LLM calls time out and the pipeline
silently falls back to heuristics (empty debate, "backfilled" theses).

### Forcing modes

- **AI / full mode:** default when an LLM is reachable and the shortlist is
  non-empty (`should_run_llm` in `src/graph/conditional_logic.py`).
- **Quant-only / offline:** pass `--no-llm`, **or** simply have no reachable
  LLM (the stub path still produces factor-based picks). The skip is also
  triggered automatically if the shortlist comes back empty.

---

## 4. Debate settings (bull vs bear)

Source: `src/agents/researchers.py`, `src/graph/orchestrator.py`,
`src/graph/state.py`.

| Knob | Where | Type | Default | Description |
|---|---|---|---|---|
| `--rounds` | CLI (`research`) → `AgentState.max_debate_rounds` | int | `1` | Number of debate rounds. Each round appends **one bull turn + one bear turn** to `state.debate`. |
| Disable debate | `--rounds 0` | — | — | With 0 rounds the loop body never executes; analysts + manager still run. |
| Disable via no-LLM | `--no-llm` | flag | — | The entire LLM branch (including debate) is skipped. |

**What is NOT configurable (grounded in the code):**

- **Verbosity / length:** hardcoded prompt asks for "5–8 sentences" covering
  "2–3 tickers." No flag or env var.
- **Number of debaters / sides:** always exactly bull and bear; not extensible
  via config.
- **Debate only over the shortlist:** it iterates the top-N shortlist
  (`--top`), so `--top` indirectly affects how many names are debated.
- There is **no** separate "enable_debate" boolean, "debate depth," or
  "consensus threshold" setting — round count is the only lever.

The Research Manager (`src/agents/manager.py:run`) then reconciles the factor
scores + analyst signals + the full debate transcript into the final ranked
picks. Its prompt length caps (e.g. thesis ≤ 1200 chars, ≤ 5 risks) are
hardcoded, not configurable.

---

## 5. Profile fields reference

Profiles are YAML files in `config/profiles/`. Add a new one by dropping
`config/profiles/<id>.yaml` and selecting it with `-p <id>`
(`src/config.py:load_profile`). Below is every tunable field, taken from
`india_adult.yaml` and `germany_student.yaml`.

### Top-level identity

| Field | Type | Example | Meaning |
|---|---|---|---|
| `profile_id` | str | `india_adult` | Profile id (should match filename). |
| `display_name` | str | `"India - Adult (no restrictions)"` | Human label. |
| `country` | str | `IN` / `DE` | Drives constraint logic, tax branch, suggested horizon (`src/agents/quant.py`, `manager.py`, `after_tax.py`). |
| `currency` | str | `INR` / `EUR` | Cross-currency flagging vs each stock's native currency (`quant.py`). |
| `locale` | str | `en_IN` | Informational. |

### `universe`

| Field | Type | Example | Meaning |
|---|---|---|---|
| `default` | str | `NIFTY500` / `DAX_PLUS_MDAX` | Universe used when `--universe` is omitted. |
| `available` | list | `[NIFTY50, NIFTY500, BSE500, GLOBAL_LARGE]` | The menu of valid `--universe` values for this profile. |
| `yahoo_suffix` | str | `.NS` / `.DE` | Appended to bare symbols for yfinance (`universe.py:_add_yahoo_suffix`). |
| `alt_yahoo_suffix` | str | `.BO` / `.F` | Documented fallback exchange suffix. |

> Note: the seed lists only fully populate NIFTY50 (India) and DAX (Germany);
> broader indices fall back to those seeds unless the live fetcher succeeds
> (`src/data/universe_live.py`, `india.py`, `germany_global.py`). Live sources:
> NSE archive CSVs and Wikipedia tables (DAX / S&P 500), cached 24 h.

### `factor_weights`
Five factors; values are normalized to sum to 1 internally
(`src/factors/engine.py:_normalize_weights`).

| Field | Type | India default | Germany default | Meaning |
|---|---|---|---|---|
| `quality` | float | 0.30 | 0.35 | Weight on quality metrics (ROE, margins, ROIC proxy). |
| `value` | float | 0.25 | 0.20 | Weight on valuation (PE, PB, PS, EV/EBITDA, yields). |
| `momentum` | float | 0.25 | 0.15 | Weight on 12-1m / 6-1m price momentum. |
| `financial_health` | float | 0.12 | 0.20 | Weight on leverage/liquidity (D/E, current ratio, net-debt/EBITDA). |
| `earnings_quality` | float | 0.08 | 0.10 | Weight on cash conversion / accruals. |

### `factor_config`

| Field | Type | Default (code) | Meaning |
|---|---|---|---|
| `per_factor_floor` | float | `None` (no floor) | Any factor score below this is **flagged** (not rejected) as a `floor_breach`. India 0.20, Germany 0.25. |
| `coverage_weight_floor` | float | `0.4` | Minimum data-coverage weight; sparse-data picks have their composite shrunk toward the universe median 0.5. India 0.4, Germany 0.5. |
| `orthogonalize_eq` | bool | `false` | If true, residualize Earnings Quality against Quality before compositing (de-correlation). Off in both shipped profiles. |

### `return_model` (after-tax estimator + backtest cost)
Source: `src/factors/after_tax.py`, used by the Picks sheet and the backtest.

| Field | Type | India / Germany | Meaning |
|---|---|---|---|
| `base_annual_return` | float | 0.10 / 0.07 | Baseline expected gross annual return (equity-premium proxy). |
| `composite_to_return_slope` | float | 0.04 / 0.03 | How much a composite of 1.0 adds over base (composite 0→−slope, 1→+slope). |
| `transaction_cost_bps` | float | 15 / 20 | Round-trip frictional cost (bps). Also the **backtest** rebalance cost. |

### `risk_constraints`
Applied in `src/agents/quant.py:_passes_constraints` (filters the candidate pool;
falls back to all snapshots if filtering empties the pool).

| Field | Type | Example | Meaning |
|---|---|---|---|
| `min_market_cap_inr_crore` | float | 1000 | (IN) Drop names below this market cap (crore). |
| `min_market_cap_eur_million` | float | 2000 | (DE / non-IN) Drop names below this market cap (millions, FX-naive). |
| `max_single_position_pct` | float | 0.10 / 0.05 | Documented concentration cap (advisory; not enforced in ranking). |
| `prefer_etf` | bool | false / true | Advisory lean toward ETFs (surfaced in prompts; no auto-ETF classification yet). |
| `max_volatility_annualized` | float | 0.60 / 0.40 | Drop names whose annualized vol exceeds this. |

### `tax`
Used by `manager.py` (per-pick notes), `after_tax.py`, and the backtest year-end
tax. Fields vary by country.

| Field | Type | India | Germany | Meaning |
|---|---|---|---|---|
| `short_term_threshold_days` | int | 365 | 0 | Holding-period split for STCG vs LTCG (0 = no split). |
| `short_term_rate` | float | 0.20 | 0.26375 | Short-term capital-gains rate. |
| `long_term_rate` | float | 0.125 | 0.26375 | Long-term rate; drives after-tax model + backtest tax. |
| `long_term_annual_exemption_inr` / `_eur` | float | 125000 | 1000 | Annual exemption (portfolio-level; ignored in single-pick estimate). |
| `prefer_long_term_holding` | bool | true | false | Nudges the suggested holding horizon. |
| `notes` | list[str] | … | … | Free-text caveats rendered in the report. |

### Germany-only extra

| Field | Type | Default | Meaning |
|---|---|---|---|
| `etf_teilfreistellung_pct` | float | 0.30 | 30% of equity-fund/ETF gains tax-exempt. Applied in `after_tax.py` **only if** a pick is flagged `is_etf` (a future feature — currently no auto-classification). |

### `llm`

| Field | Type | Meaning |
|---|---|---|
| `prompt_locale_hints` | list[str] | Locale/market hints injected into prompts (currency conventions, exchange tickers, beginner suitability). |

---

## 6. Environment variables

Every `os.environ` / `os.getenv` usage in the codebase (plus `.env.example`).
Loaded via `load_dotenv()` in `src/cli.py`.

| Variable | Type | Default | Used in | Purpose |
|---|---|---|---|---|
| `LLM_PROVIDER` | str | `ollama` | `llm/factory.py`, `cli.py` | LLM backend: `openai` / `anthropic` / `ollama` / `cursor_io`. |
| `LLM_MODEL` | str | `llama3.1:8b` | `llm/factory.py`, `cli.py` | Provider-specific model name. |
| `LLM_TEMPERATURE` | float | `0` | `llm/factory.py` | Sampling temperature (invalid → 0.0). |
| `OPENAI_API_KEY` | str | *(empty)* | `llm/factory.py` | Required for the OpenAI provider; if missing, OpenAI returns `None` → stub. |
| `ANTHROPIC_API_KEY` | str | *(empty)* | `llm/factory.py` | Required for the Anthropic provider. |
| `OLLAMA_HOST` | str | `http://localhost:11434` | `llm/factory.py` | Local Ollama endpoint. |
| `OLLAMA_TIMEOUT` | float | `120` | `llm/factory.py` | Per-request HTTP timeout in **seconds** for the Ollama provider (invalid → `120.0`). **Raise to `900` (600–900) for CPU Ollama runs** — the `120` default times out large LLM calls (fundamentals/technical/news/bull/bear/manager); the timeout is swallowed and the call returns `""`, so the pipeline silently falls back to heuristics. GPU users can leave the default. |
| `CURSOR_LLM_DIR` | str | `./llm_cache` | `llm/factory.py` | Prompt/response directory for the `cursor_io` provider. |
| `FRA_CACHE_DIR` | str | `./.fra_cache` | `config.py` | Override the on-disk data cache directory. |
| `EDGAR_USER_AGENT` | str | `fra-finance-research-agent contact@example.com` | `data/insiders_edgar.py` | Polite User-Agent for SEC EDGAR (US insider Form 4 fetch). Set to your "name email" per EDGAR policy. |

Not configurable via env: memory dir (`.fra_memory`) and reports dir (`reports/`)
are fixed in `src/config.py`.

---

## 7. Other tunables (and hardcoded values worth knowing)

### Data provider / sources
Source: `src/data/provider.py`.

| Item | Value | Configurable? |
|---|---|---|
| Primary source | yfinance | No (swap by code). |
| Secondary cross-check | Stooq latest close (`use_stooq=True`) | Constructor arg only; **not exposed** on the CLI. |
| News sources | GDELT 2.0 DOC API, fallback to yfinance news | No flag; GDELT preferred, yfinance fills gaps (`agents/news_sentiment.py`, `data/news_gdelt.py`). |
| Insider data | SEC EDGAR Form 4 (US tickers only) | Via `EDGAR_USER_AGENT` only. |
| Polite request sleep | `polite_sleep_s=0.0` | Constructor arg only; not exposed. |

### Caching (on-disk, TTL-based)
Source: `src/data/cache.py` + TTL constants in providers. Only the **location**
is configurable (`FRA_CACHE_DIR`); the TTLs are hardcoded:

| Namespace | TTL | File |
|---|---|---|
| Quotes | 15 min | `provider.py` |
| Daily history | 6 h | `provider.py` |
| Fundamentals (`info`) | 24 h | `provider.py` |
| News (yfinance) | 30 min | `provider.py` |
| News (GDELT) | 30 min | `news_gdelt.py` |
| Universe constituents (live) | 24 h | `universe_live.py` |
| EDGAR filings | 6 h | `insiders_edgar.py` |

To force a fresh fetch, delete the relevant subfolder under `.fra_cache/` (or
point `FRA_CACHE_DIR` somewhere empty). There is **no** `--no-cache` flag.

### Factor engine internals
Source: `src/factors/engine.py`. Tuned via the profile (`factor_weights`,
`factor_config`) — see §5. The composite is coverage-weighted and shrunk toward
the universe median; `factor_std_dev` and `profile_fit` (cosine similarity to the
weight vector) are reported but not user-tunable.

### Factor decay / regime warnings
Source: `src/factors/decay.py`. Computes top-minus-bottom quintile 12-1m spread
per factor; warns when a factor's spread < **−0.02** (hardcoded threshold). Not
configurable.

### Universe / shortlist size
- Candidate universe: profile `universe.default` or `--universe`.
- Shortlist + final picks size: `--top` (default 10). This also bounds how many
  names hit the LLM stages and the debate.

### Output / reports
- Markdown report: always written to `reports/` (`src/report/generator.py`).
- Excel workbook: written unless `--no-excel` (`src/report/excel.py`).
- Backtest workbook: `reports/backtest_<profile>_<start>_top<N>.xlsx`.
- File naming and output directory are not configurable via flags.

### Randomness / reproducibility
- No RNG seed setting; determinism comes from `LLM_TEMPERATURE=0` plus the
  deterministic factor engine.
- `--as-of` and the SHA-256 `input_hash` (`src/agents/quant.py:_input_hash`)
  give a verifiable stamp of the inputs, but do **not** pin historical data.

### Rate limits
- No explicit rate-limit/backoff configuration. Politeness comes from caching,
  the optional `polite_sleep_s` (code-only), and request timeouts (Ollama via
  `OLLAMA_TIMEOUT`, default 120 s — raise to 900 on CPU, see §6; 8–10 s HTTP
  fetches are hardcoded).

---

## Summary of what's tunable vs. fixed

- **Tunable per run (CLI):** profile, target, universe, domain/sector, top-N,
  no-LLM toggle, no-Excel toggle, debate rounds, as-of date; plus backtest
  start/benchmark.
- **Tunable via env:** LLM provider, model, temperature, provider keys, Ollama
  host, cursor_io dir, cache dir, EDGAR user-agent.
- **Tunable via profile YAML:** factor weights, factor floors/coverage,
  orthogonalization, after-tax return model, transaction cost, risk constraints,
  tax rules, ETF Teilfreistellung, universe menu, locale prompt hints.
- **Fixed in code (not exposed):** max_tokens/top_p/seed, debate verbosity & side
  count, cache TTLs, rebalance frequency, decay warning threshold, data-source
  selection, report file naming, polite-sleep, Stooq toggle.
