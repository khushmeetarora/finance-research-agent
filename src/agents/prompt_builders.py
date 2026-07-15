"""
Prompt Builders - All LLM prompt generation for the research agents.

Centralizes the system/user prompt construction that used to live inline in
each analyst (`fundamentals`, `technical`, `news_sentiment`, `macro`,
`researchers`, `manager`). Keeping every prompt in one module makes the
"interpret the numbers, never invent them" guardrails easy to audit and keeps
the agent modules focused on data prep + signal parsing.

Each builder is prefixed by the agent it serves so names never collide:
  - generate_fundamentals_*  -> from agents.fundamentals
  - generate_technical_*     -> from agents.technical
  - generate_news_*          -> from agents.news_sentiment
  - generate_macro_*         -> from agents.macro
  - generate_researcher_*    -> from agents.researchers (bull/bear debate)
  - generate_manager_*       -> from agents.manager

Conventions (mirrors the canonical sample):
  - Builders return a single ready-to-send prompt `str`.
  - Tabular/record inputs are serialized internally with `json.dumps(...)`.
  - System prompts are exposed as module-level constants so callers pass them
    straight to `LLM.complete(prompt, system=...)`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ======================================================================
# Shared system prompts + schema fragments
# ======================================================================

ANALYST_SYSTEM_PROMPT: str = (
    "You are a meticulous buy-side equity analyst. Your job is to INTERPRET the "
    "numbers you are given - never to produce them.\n"
    "Operate under these non-negotiable rules:\n"
    "1. NEVER invent, estimate, or extrapolate a numerical value. Reference ONLY "
    "numbers that appear in the provided data; if a metric is missing, say so "
    "instead of guessing.\n"
    "2. Tie every claim to a specific metric from the data, naming the metric and "
    "its value.\n"
    "3. Keep each rationale tight: 2-4 sentences, no filler.\n"
    "4. Respond with JSON that matches the requested schema EXACTLY - identical "
    "keys, and no prose before or after the JSON."
)

MACRO_SYSTEM_PROMPT: str = (
    "You are a cautious macro strategist. You describe the prevailing environment "
    "in neutral, factual terms and explicitly avoid forecasting or predicting "
    "market moves."
)

RESEARCHER_SYSTEM_PROMPT: str = (
    "You are a disciplined sell-side research analyst in a structured bull-vs-bear "
    "debate. Argue your assigned side persuasively, but stay strictly grounded in "
    "the supplied data and never fabricate numbers."
)

# Shared JSON shape for the per-ticker analyst signal arrays
# (fundamentals / technical / news_sentiment).
SIGNAL_ARRAY_SCHEMA: str = (
    '{"signals": [{"ticker": "...", "score": -1..1, "stance": "bullish|bearish|neutral",'
    ' "confidence": 0..1, "rationale": "...", "evidence": ["..."]}]}'
)


# ======================================================================
# Fundamentals analyst prompts (from agents.fundamentals)
# ======================================================================

def generate_fundamentals_prompt(items: list[dict[str, Any]]) -> str:
    """
    Builds the user prompt for the fundamentals analyst.

    Purpose:
        Asks the LLM to judge Quality, Value, Financial Health and Earnings
        Quality per shortlisted ticker using ONLY the supplied numbers, folding
        in the optional `insider_signal` (US tickers) qualitatively.

    Args:
        items: list[dict] — Per-ticker context blobs (snapshot metrics + factor
            scores, optionally an "insider_signal" entry) to ground the review.

    Returns:
        str: The full user prompt, ending with the JSON schema and a "DATA:"
        block containing the serialized items.

    Side effects / Errors:
        None. Serializes items via json.dumps(default=str).
    """
    payload = json.dumps(items, default=str)
    return (
        "ROLE: Fundamentals analyst reviewing a shortlist of companies.\n\n"
        "TASK: For each ticker in the DATA block, assess four dimensions strictly "
        "from the numbers provided:\n"
        "  1. Quality\n"
        "  2. Value\n"
        "  3. Financial Health\n"
        "  4. Earnings Quality\n\n"
        "HOW TO REASON (per ticker):\n"
        "  - Read the snapshot metrics and factor scores, then weigh which "
        "dimensions look strongest and weakest.\n"
        "  - If an `insider_signal` entry is present (US tickers only), fold it in "
        "qualitatively as a secondary input; ignore it when it is absent.\n"
        "  - Express the net view as `stance`, a `score` in [-1, 1] reflecting the "
        "balance of evidence, and a `confidence` in [0, 1] reflecting how complete "
        "the data is.\n\n"
        "GUARDRAIL: Interpret ONLY the supplied numbers. Do NOT invent, round, or "
        "assume any value that is not in the DATA block; name the metric behind "
        "each judgement in `rationale` and `evidence`.\n\n"
        "OUTPUT: Respond with JSON only, matching this schema exactly:\n"
        + SIGNAL_ARRAY_SCHEMA
        + "\n\nDATA:\n"
        + payload
    )


# ======================================================================
# Technical analyst prompts (from agents.technical)
# ======================================================================

def generate_technical_prompt(metrics: list[dict[str, Any]]) -> str:
    """
    Builds the user prompt for the technical analyst.

    Purpose:
        Asks the LLM to judge trend strength and risk from 12-1 month momentum
        (excluding the most recent month) and annualized volatility, using ONLY
        the supplied numbers.

    Args:
        metrics: list[dict] — Reduced per-ticker records carrying ticker, name,
            sector and a "metrics" dict (momentum_12_1, volatility_annualized).

    Returns:
        str: The full user prompt, ending with the JSON schema and a "DATA:"
        block containing the serialized metrics.

    Side effects / Errors:
        None. Serializes metrics via json.dumps(default=str).
    """
    payload = json.dumps(metrics, default=str)
    return (
        "ROLE: Technical analyst judging trend and risk.\n\n"
        "TASK: For each ticker in the DATA block, assess trend strength and risk "
        "from exactly two inputs:\n"
        "  1. `momentum_12_1` - 12-1 month price momentum (trailing 12 months, "
        "excluding the most recent month).\n"
        "  2. `volatility_annualized` - annualized volatility (risk).\n\n"
        "HOW TO REASON (per ticker):\n"
        "  - Treat stronger positive momentum as bullish and negative momentum as "
        "bearish; treat higher volatility as a reason to temper conviction.\n"
        "  - Express the net view as `stance`, a `score` in [-1, 1], and a "
        "`confidence` in [0, 1].\n\n"
        "GUARDRAIL: Use ONLY the two supplied numbers per ticker. Do NOT infer or "
        "fabricate prices, returns, or any metric that is not provided; reference "
        "the actual momentum and volatility values in `rationale` and `evidence`.\n\n"
        "OUTPUT: Respond with JSON only, matching this schema exactly:\n"
        + SIGNAL_ARRAY_SCHEMA
        + "\n\nDATA:\n"
        + payload
    )


# ======================================================================
# News + sentiment analyst prompts (from agents.news_sentiment)
# ======================================================================

def generate_news_sentiment_prompt(bundles: list[dict[str, Any]]) -> str:
    """
    Builds the user prompt for the news + sentiment analyst.

    Purpose:
        Asks the LLM to classify the aggregate short-term sentiment toward each
        ticker from its headlines, staying conservative (neutral / low
        confidence) when headlines are mixed or sparse.

    Args:
        bundles: list[dict] — Per-ticker headline bundles (ticker, name,
            sources, headlines[]) to classify.

    Returns:
        str: The full user prompt, ending with the JSON schema and a "DATA:"
        block containing the serialized bundles.

    Side effects / Errors:
        None. Serializes bundles via json.dumps(default=str).
    """
    return (
        "ROLE: News & sentiment analyst.\n\n"
        "TASK: For each ticker in the DATA block, classify the AGGREGATE short-term "
        "sentiment implied by its headlines.\n\n"
        "HOW TO REASON (per ticker):\n"
        "  - Read all of the ticker's headlines together and weigh the overall tone "
        "rather than reacting to any single headline.\n"
        "  - Map the net tone to `stance` and a `score` in [-1, 1], with a "
        "`confidence` in [0, 1].\n\n"
        "EDGE CASES: Be conservative. If the headlines are mixed, ambiguous, sparse, "
        "or not clearly about the company, return `neutral` with low `confidence`.\n\n"
        "GUARDRAIL: Base your read ONLY on the supplied headlines. Do NOT invent "
        "news, price moves, or figures; quote or paraphrase the relevant headlines "
        "in `evidence`.\n\n"
        "OUTPUT: Respond with JSON only, matching this schema exactly:\n"
        + SIGNAL_ARRAY_SCHEMA
        + "\n\nDATA:\n"
        + json.dumps(bundles, default=str)
    )


# ======================================================================
# Macro overlay analyst prompts (from agents.macro)
# ======================================================================

def generate_macro_prompt(country: str, currency: str) -> str:
    """
    Builds the user prompt for the macro overlay analyst.

    Purpose:
        Requests 2-3 sentences of neutral, non-predictive macro context for an
        equity investor in a given country/reporting currency.

    Args:
        country: str — Investor's country of residence (from the profile).
        currency: str — Reporting currency (from the profile).

    Returns:
        str: The full user prompt, ending with the single-signal JSON schema.

    Side effects / Errors:
        None.
    """
    return (
        "ROLE: Macro strategist writing a brief context note for an equity investor "
        f"based in {country} (portfolio reported in {currency}).\n\n"
        "TASK: Write 2-3 sentences of neutral macro context, covering three things:\n"
        "  1. The prevailing interest-rate environment signals.\n"
        f"  2. Currency considerations relevant to a {currency} investor.\n"
        f"  3. One sector-level theme commonly discussed for {country} today.\n\n"
        "CONSTRAINTS: Stay neutral and factual. Do NOT predict markets, set price "
        "targets, or forecast returns - summarize the established context only.\n\n"
        "OUTPUT: Respond with JSON only, matching this schema exactly (put the 2-3 "
        "sentences in `rationale`, and a directional macro tilt in [-1, 1] in "
        "`score`):\n"
        '{"score": -1..1, "rationale": "...", "evidence": ["..."]}'
    )


# ======================================================================
# Bull/Bear researcher debate prompts (from agents.researchers)
# ======================================================================

def generate_researcher_prompt(
    side: str,
    payload: list[dict[str, Any]],
    round_idx: int,
    history_text: str,
) -> str:
    """
    Builds the user prompt for one side of the bull/bear researcher debate.

    Purpose:
        Asks the assigned researcher to write a focused case (5-8 sentences) on
        the 2-3 most compelling/concerning tickers, referencing specific metrics
        and never inventing numbers, given prior debate history.

    Args:
        side: str — Debate side, "bull" or "bear" (case-insensitive); anything
            other than "bull" is treated as the bear side.
        payload: list[dict] — Per-ticker signal/factor summaries to argue over.
        round_idx: int — Zero-based round index (rendered as Round round_idx + 1).
        history_text: str — Pre-formatted transcript of prior debate turns, or a
            placeholder such as "(no prior turns)".

    Returns:
        str: The full user prompt, with "PRIOR DEBATE:" and "DATA:" blocks.

    Side effects / Errors:
        None. Serializes payload via json.dumps(default=str).
    """
    role = "BULL" if side == "bull" else "BEAR"
    stance_word = "bullish" if role == "BULL" else "bearish"
    return (
        f"ROLE: You are the {role} researcher in a structured debate. This is "
        f"Round {round_idx + 1}.\n\n"
        f"TASK: Build the strongest honest {stance_word} case, then deliver it as a "
        "focused argument of 5-8 sentences.\n\n"
        "HOW TO PROCEED:\n"
        "  1. Read every analyst signal and factor score in the DATA block, plus "
        "the PRIOR DEBATE.\n"
        f"  2. Pick the 2-3 tickers that most support your {stance_word} thesis and "
        "concentrate your argument on them.\n"
        "  3. Back each point by referencing specific metrics and signals by value; "
        "where relevant, rebut the opposing side's earlier claims.\n\n"
        "GUARDRAIL: Argue your side, but stay grounded in the data. Do NOT invent "
        "numbers, prices, or facts that are not present below.\n\n"
        "FORMAT: Reply in prose (no JSON).\n\n"
        f"PRIOR DEBATE:\n{history_text}\n\nDATA:\n{json.dumps(payload, default=str)}"
    )


# ======================================================================
# Research Manager prompts (from agents.manager)
# ======================================================================

def generate_manager_prompt(
    items: list[dict[str, Any]],
    debate_text: str,
    top_n: int,
) -> str:
    """
    Builds the user prompt for the Research Manager reconciliation step.

    Purpose:
        Asks the manager to reconcile factor-engine scores, analyst signals and
        the bull/bear debate into a ranked top-N list, each with a metric-cited
        thesis (no invented numbers), key risks and a suggested holding horizon.

    Args:
        items: list[dict] — Shortlist context (snapshot metrics + factor scores +
            attached analyst signals).
        debate_text: str — Pre-formatted bull/bear debate transcript, or a
            placeholder such as "(no debate)".
        top_n: int — Number of picks the ranked list should contain.

    Returns:
        str: The full user prompt, with "SHORTLIST + SIGNALS:" and "DEBATE:"
        blocks plus the picks JSON schema.

    Side effects / Errors:
        None. Serializes items via json.dumps(default=str).
    """
    schema = (
        '{"picks": [{"ticker": "...", "rank": 1, "thesis": "...", '
        '"key_risks": ["..."], "confidence": 0..1, "suggested_horizon": "..."}]}'
    )
    return (
        "ROLE: Research Manager making the final call.\n\n"
        "TASK: Reconcile three inputs - the factor-engine scores, the analyst "
        "signals, and the bull/bear debate - into a single ranked list of the "
        f"top {top_n} picks.\n\n"
        "HOW TO REASON:\n"
        "  1. Weigh the quantitative factor scores against the analysts' signals "
        "and the strongest points from the debate; resolve disagreements "
        "explicitly rather than averaging blindly.\n"
        f"  2. Select and rank the best {top_n} tickers (rank 1 = highest "
        "conviction).\n"
        "  3. For each pick, write a 2-3 sentence `thesis` that cites concrete "
        "metrics, list 2-3 `key_risks`, set a `confidence` in [0, 1], and give a "
        "`suggested_horizon`.\n\n"
        "GUARDRAIL: Cite ONLY metrics present in the inputs below. Do NOT invent "
        "numbers, price targets, or facts.\n\n"
        "OUTPUT: Respond with JSON only, matching this schema exactly:\n"
        + schema
        + "\n\nSHORTLIST + SIGNALS:\n"
        + json.dumps(items, default=str)
        + "\n\nDEBATE:\n"
        + debate_text
    )
