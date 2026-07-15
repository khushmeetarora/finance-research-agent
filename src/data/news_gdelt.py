"""GDELT 2.0 DOC API news feed (free, no API key required).

Reference: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

We perform a query-by-name and return a list of {title, publisher, link,
published, summary} dicts shaped exactly like DataProvider.get_news so the
analyst agents are source-agnostic.

Failure modes are deliberately quiet: any exception or non-200 returns []
so the news_sentiment agent can fall back to yfinance news.
"""

from __future__ import annotations

import json as _json
import urllib.parse
from typing import Iterable

from . import cache


_TTL = 60 * 30  # 30 minutes
_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


def _query_for(name_or_ticker: str) -> str:
    name = name_or_ticker.strip()
    if not name:
        return ""
    # GDELT requires phrase in quotes for multi-word, plain otherwise.
    if " " in name or "&" in name:
        return f'"{name}"'
    return name


def _normalize(records: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    for r in records:
        out.append(
            {
                "title": r.get("title"),
                "publisher": r.get("domain") or r.get("source") or r.get("sourcename"),
                "link": r.get("url"),
                "published": r.get("seendate") or r.get("published"),
                "summary": r.get("title"),  # GDELT doesn't ship a summary field
            }
        )
    return out


def get_news_gdelt(
    company_name: str | None,
    ticker: str,
    *,
    limit: int = 10,
    days: int = 21,
) -> list[dict]:
    """Query GDELT for recent English-language coverage. Returns [] on failure."""
    name = (company_name or ticker).strip()
    if not name:
        return []
    cache_key = f"{name}|{days}|{limit}"
    cached = cache.get("news_gdelt", cache_key, _TTL)
    if cached is not None:
        return cached[:limit]

    try:
        import requests  # type: ignore

        params = {
            "query": _query_for(name) + " sourcelang:eng",
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(min(limit, 50)),
            "timespan": f"{days}d",
            "sort": "DateDesc",
        }
        url = f"{_BASE}?{urllib.parse.urlencode(params)}"
        r = requests.get(url, timeout=10, headers={"User-Agent": "fra/0.1"})
        if r.status_code != 200 or not r.text:
            cache.put("news_gdelt", cache_key, [])
            return []
        body = r.text.strip()
        try:
            data = r.json()
        except Exception:
            try:
                data = _json.loads(body)
            except Exception:
                cache.put("news_gdelt", cache_key, [])
                return []
        articles = data.get("articles") or data.get("artlist") or []
        if not isinstance(articles, list):
            cache.put("news_gdelt", cache_key, [])
            return []
        normalized = _normalize(articles)
        cache.put("news_gdelt", cache_key, normalized)
        return normalized[:limit]
    except Exception:
        cache.put("news_gdelt", cache_key, [])
        return []
