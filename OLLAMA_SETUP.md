# Running the Finance Research Agent on Ollama (local LLM)

A code-grounded, step-by-step guide for running this pipeline against a **local
Ollama** model on this Windows machine, inside the `fra` conda env.

Everything below was read from the source. Key files:

- `src/llm/factory.py` — the provider factory (`_make_ollama`, `get_llm`, `is_stub`).
- `src/cli.py` — the `research` command and the `LLM provider=… model=…` echo.
- `.env.example` — the documented env vars and defaults.
- `requirements.txt` — confirms Ollama needs **no** Python SDK (HTTP only).

---

## TL;DR

```powershell
# 1. Install Ollama for Windows (one-time), then in a terminal:
ollama serve                 # starts the local API on http://localhost:11434
ollama pull llama3.1:8b      # pull the model this repo defaults to (~4.7 GB)

# 2. In the repo, with the fra env active:
conda activate fra
$env:LLM_PROVIDER  = "ollama"
$env:LLM_MODEL     = "llama3.1:8b"
$env:LLM_TEMPERATURE = "0"
$env:OLLAMA_HOST   = "http://localhost:11434"
$env:OLLAMA_TIMEOUT = "900"   # CPU runs need this — default 120s silently degrades the report

# 3. Run a research pass:
python -m src.cli research -p india_adult -t "best IT stocks in India"
```

> **⚠️ On CPU, set `OLLAMA_TIMEOUT=900`.** The default per-request timeout is
> **120 s**, which is too low for `llama3.1:8b` on CPU — large calls time out and
> the pipeline silently falls back to heuristics (empty Bull/Bear rounds,
> "Heuristic"/"backfilled" notes). See **Gotchas** below. GPU users can leave the
> default.

No extra `pip install` is needed — the Ollama provider talks HTTP via the
already-listed `requests` package.

---

## How the Ollama provider actually works (grounded in `src/llm/factory.py`)

`_make_ollama(model, temperature)` (lines ~167–214):

- **Transport:** plain HTTP via `requests` — there is **no `ollama` Python SDK**.
  It `POST`s to `"{OLLAMA_HOST}/api/generate"` with `"stream": false`.
- **Host:** read from `OLLAMA_HOST`, default `http://localhost:11434` (trailing
  slash stripped). So `OLLAMA_HOST` **is** supported.
- **Model:** comes from `LLM_MODEL`; the factory default (`get_llm`, line ~327)
  is **`llama3.1:8b`** — this is the tag you must `ollama pull`.
- **Temperature:** from `LLM_TEMPERATURE` (default `0`, invalid → `0.0`), sent as
  `options.temperature`.
- **Timeout:** read from `OLLAMA_TIMEOUT` (seconds) via
  `float(os.environ.get("OLLAMA_TIMEOUT", "120"))`, **default 120 s** (invalid →
  `120.0`), applied to both `complete` and `complete_json`. **On CPU this default
  is too low** — set `OLLAMA_TIMEOUT=900` (see Gotchas).
- **Structured output:** `complete_json` sends Ollama's `format` field
  (`"json"`, or the JSON schema when one is supplied).
- **Response parsing:** returns `r.json()["response"].strip()`. On any non-200
  status or exception it returns `""`.

### Important: the stub-fallback for Ollama is *per-call*, not up-front

`get_llm()` returns the `_Ollama` wrapper **as long as `requests` imports** — it
does **not** ping the server first. So even if Ollama is down, `get_llm()` does
**not** return the `_Stub`. The fallback happens at request time: each failed
call returns `""`, and the individual analyst agents then fall back to their
deterministic heuristics (you'll see per-ticker "LLM unavailable / No LLM …
available" notices in the report).

Consequence: the top-level `is_stub(get_llm())` check (used by
`src/report/generator.py` for the report's `llm_unavailable` flag) reports
**False** for Ollama whether or not Ollama is reachable. **Do not rely on it** to
confirm Ollama is being used — see the verification section below.

(For comparison: `openai`/`anthropic` fall back to the stub up-front if the SDK
is missing or the API key is unset; Ollama only falls back per-request.)

---

## Step-by-step

### (a) Install Ollama on Windows

1. Download the Windows installer from <https://ollama.com/download> (or
   `winget install Ollama.Ollama`).
2. Run it. Ollama installs a background service and the `ollama` CLI.
3. Verify in a fresh PowerShell:

```powershell
ollama --version
```

### (b) Start the Ollama service

The Windows app usually starts the server automatically on
`http://localhost:11434`. If not, or to run it in the foreground:

```powershell
ollama serve
```

Confirm the API answers:

```powershell
curl http://localhost:11434/api/tags
# or
Invoke-RestMethod http://localhost:11434/api/tags
```

### (c) Pull the default model

This repo defaults to **`llama3.1:8b`** (≈ 4.7 GB first-time download):

```powershell
ollama pull llama3.1:8b
```

To use a **different** local model, pull it and point `LLM_MODEL` at the exact
tag (the tag must match what `ollama list` shows, e.g. `qwen2.5:7b`,
`mistral:7b`, `llama3.1:70b`):

```powershell
ollama pull qwen2.5:7b
$env:LLM_MODEL = "qwen2.5:7b"
```

### (d) Set the required env vars

The repo auto-loads a `.env` at startup via `load_dotenv()`.

**Option 1 — `.env` file at the repo root** (mirrors `.env.example`):

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_TEMPERATURE=0
OLLAMA_HOST=http://localhost:11434
OLLAMA_TIMEOUT=900          # seconds; default 120 — set 900 on CPU (see Gotchas)
```

**Option 2 — inline PowerShell (current session only):**

```powershell
$env:LLM_PROVIDER    = "ollama"
$env:LLM_MODEL       = "llama3.1:8b"
$env:LLM_TEMPERATURE = "0"
$env:OLLAMA_HOST     = "http://localhost:11434"
$env:OLLAMA_TIMEOUT  = "900"   # CPU runs need this; default 120s silently degrades the report
```

> The first four have sane defaults in code (`ollama`, `llama3.1:8b`, `0`,
> `http://localhost:11434`), so on a default local setup you can skip them
> entirely — but setting them explicitly avoids surprises.
>
> **`OLLAMA_TIMEOUT` (seconds, default 120) is the exception on CPU:** the
> default is too low for `llama3.1:8b` on CPU and causes a silent fallback —
> **set it to `900`** (600–900). GPU users can leave the default. See **Gotchas**.

### (e) Install Python deps into the `fra` env

**No Ollama-specific package is required.** The provider uses `requests`, which
is already in `requirements.txt`. `requirements.txt` even notes:
`# ollama is invoked via HTTP (localhost:11434), no SDK pin required`.

Just make sure the env's deps are installed:

```powershell
conda activate fra
C:\Users\SURFACE\miniconda3\envs\fra\python.exe -m pip install -r requirements.txt
```

### (f) Run the workflow on Ollama

```powershell
conda activate fra
python -m src.cli research -p india_adult -t "best IT stocks in India"
```

Useful variants (from `RUN_OPTIONS.md` / `src/cli.py`):

```powershell
# More picks + enable a multi-round bull/bear debate (more LLM calls)
python -m src.cli research -p india_adult -t "best banks in India" -n 8 --rounds 3

# Germany profile
python -m src.cli research -p germany_student -t "DAX quality names"

# Quant-only, NO LLM at all (for contrast / fast offline run)
python -m src.cli research -p india_adult -t "best IT stocks in India" --no-llm
```

(Do **not** pass `--no-llm` when you want Ollama — that flag skips every LLM
stage entirely.)

---

## (g) Verify it's really using Ollama (not the silent fallback)

Because `is_stub()` is unreliable for Ollama (see above), use these checks:

1. **Console echo** — `src/cli.py` prints, when LLM is enabled:

   ```
   LLM provider=ollama model=llama3.1:8b
   ```

   This confirms the *configured* provider, but not that calls succeeded.

2. **Watch Ollama's own activity.** While a run is in progress:

   ```powershell
   ollama ps          # shows the model loaded/running during the pass
   ```

   You should see `llama3.1:8b` loaded. If you ran `ollama serve` in the
   foreground, you'll also see `POST /api/generate` log lines.

3. **Inspect the generated report** (written to `reports/`). This is the most
   reliable tell:
   - **Ollama working:** analyst sections contain real LLM prose/rationales, and
     you do **not** see a wall of fallback notices.
   - **Ollama NOT reached (silent fallback):** the report is peppered with lines
     like `No LLM sentiment classification available; defaulting to neutral` and
     `Macro context for … - LLM unavailable; using neutral default` (these strings
     come from `src/agents/news_sentiment.py` and `src/agents/macro.py`). The
     existing files in `reports/` were generated with no LLM and show exactly this
     pattern — use them as a reference for what "fell back" looks like.

4. **Sanity-ping the API yourself** before a run:

   ```powershell
   $body = @{ model = "llama3.1:8b"; prompt = "say hi"; stream = $false } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri "http://localhost:11434/api/generate" -Body $body -ContentType "application/json"
   ```

   A JSON object with a `response` field means the exact endpoint the agent uses
   is healthy.

---

## Gotchas

- **Empty Bull/Bear rounds or "Heuristic"/"backfilled" notes on CPU → raise
  `OLLAMA_TIMEOUT`.** The single most common CPU gotcha. **Symptoms:** a report
  with **empty Bull AND Bear debate rounds**, analyst notes reading *"Heuristic
  from factor engine"*, *"No LLM sentiment classification available"*, and theses
  marked *"Manager backfilled this entry"* — typically with **macro prose still
  present** — even though `ollama ps` shows the model loaded and the server is
  healthy. **Cause:** `OLLAMA_TIMEOUT` defaults to **120 s**, and on CPU
  `llama3.1:8b` needs longer than that for any call carrying a data payload
  (fundamentals, technical, news_sentiment, bull, bear, manager). The request
  times out, `complete()`/`complete_json()` swallows the exception and returns
  `""`, and the agent falls back to its deterministic heuristic — silently. (The
  tiny `macro` call has no data payload, so it beats the 120 s default — which is
  why macro prose survives while everything else degrades.) **Fix:** set
  **`OLLAMA_TIMEOUT=900`** (600–900 on CPU), e.g. `$env:OLLAMA_TIMEOUT="900"`, and
  re-run. A full run at `900` takes ~20 min and produces populated Bull and Bear
  rounds with real analyst rationales.
- **Model tag mismatch:** `LLM_MODEL` must equal a tag from `ollama list`. A typo
  (e.g. `llama3.1` vs `llama3.1:8b`) makes `/api/generate` return non-200 → the
  call yields `""` → silent fallback to heuristics. No crash, no obvious error.
- **Server not running / wrong host/port:** default is `http://localhost:11434`.
  If you changed Ollama's port or run it remotely, set `OLLAMA_HOST` to match
  (include the scheme, e.g. `http://127.0.0.1:11434`).
- **First-run download size:** `llama3.1:8b` is ~4.7 GB; the first `ollama pull`
  (and the first generate that loads it into memory) can take a while. The
  pipeline's per-call timeout defaults to **120 s** (`OLLAMA_TIMEOUT`) — a cold
  model load (or any CPU run) can bump against this and cause the call to fall
  back. Raise it to `900` on CPU (see the first gotcha above).
- **Silent fallback is by design:** the pipeline never errors out for a missing
  LLM; it degrades to the deterministic factor engine. Always verify via the
  report / `ollama ps`, not by assuming success because the run "worked."
- **`--no-llm` overrides everything:** it bypasses the provider entirely, so
  Ollama won't be touched even if configured.
- **Throughput:** with `--rounds N` and larger `--top N`, the number of Ollama
  calls grows (analysts + debate turns + manager). An 8B model on CPU can be
  slow; consider a smaller/faster model via `LLM_MODEL` if needed.
