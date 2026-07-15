"""News + sentiment analyst.

Pulls recent news headlines for each shortlisted ticker via the DataProvider
and asks the LLM to classify the dominant sentiment. With no LLM available,
the analyst issues a low-confidence neutral signal.
"""

from __future__ import annotations

from ..data.news_gdelt import get_news_gdelt
from ..data.provider import DataProvider
from ..graph.state import AgentState, AnalystSignal
from ..llm.factory import get_llm, parse_json
from . import _common
from .prompt_builders import (
    ANALYST_SYSTEM_PROMPT,
    generate_news_sentiment_prompt,
)


def _neutral_signal(ticker: str, headlines: list[dict]) -> AnalystSignal:
    titles = [h.get("title") for h in headlines if h.get("title")][:3]
    return AnalystSignal(
        role="news_sentiment",
        ticker=ticker,
        score=0.0,
        stance="neutral",
        confidence=0.2,
        rationale="No LLM sentiment classification available; defaulting to neutral.",
        evidence=titles,
    )


def run(state: AgentState) -> AgentState:
    if not state.shortlist:
        return state
    provider = DataProvider()
    llm = get_llm()
    items = _common.shortlist_context(state)

    bundles = []
    for ctx in items:
        # Prefer GDELT for diversity / cross-source corroboration; fall back to
        # yfinance news if GDELT returns nothing.
        sources_used: list[str] = []
        news = get_news_gdelt(ctx.get("name"), ctx["ticker"], limit=8)
        if news:
            sources_used.append("gdelt")
        if len(news) < 4:
            yf_news = provider.get_news(ctx["ticker"], limit=8)
            if yf_news:
                sources_used.append("yfinance")
            # Combine with dedup by title.
            seen_titles = {(n.get("title") or "").strip().lower() for n in news}
            for n in yf_news:
                title = (n.get("title") or "").strip().lower()
                if title and title not in seen_titles:
                    news.append(n)
                    seen_titles.add(title)
        bundles.append(
            {
                "ticker": ctx["ticker"],
                "name": ctx["name"],
                "sources": sources_used,
                "headlines": [
                    {
                        "title": n.get("title"),
                        "publisher": n.get("publisher"),
                    }
                    for n in news
                    if n.get("title")
                ][:8],
            }
        )

    user = generate_news_sentiment_prompt(bundles)
    out = llm.complete(user, system=ANALYST_SYSTEM_PROMPT)
    parsed = parse_json(out) or {}

    by_ticker = {}
    for sig in parsed.get("signals") or []:
        try:
            t = sig.get("ticker")
            if not t:
                continue
            by_ticker[t] = AnalystSignal(
                role="news_sentiment",
                ticker=t,
                score=float(sig.get("score", 0.0) or 0.0),
                stance=sig.get("stance", "neutral"),
                confidence=float(sig.get("confidence", 0.5) or 0.5),
                rationale=str(sig.get("rationale", ""))[:600],
                evidence=[str(e)[:200] for e in (sig.get("evidence") or [])][:6],
            )
        except Exception:
            continue

    for bundle in bundles:
        state.analyst_signals.append(
            by_ticker.get(bundle["ticker"])
            or _neutral_signal(bundle["ticker"], bundle["headlines"])
        )
    return state
