"""Unit tests for the news/event keyword layer (PIT-aware, mocked GDELT).

Hermetic: no network. A fake fetch function returns fixture articles; we assert
classification, the as_of look-ahead safety gate, flags/bias, and graceful
failure when the feed raises or is empty.
"""

from __future__ import annotations

import datetime as dt

from src.data import news_events as ne


def _art(title, published, summary="", publisher="Wire"):
    return {"title": title, "summary": summary, "published": published, "publisher": publisher}


# --- date parsing ----------------------------------------------------------


def test_parse_pubdate_gdelt_compact():
    assert ne._parse_pubdate("20240115T120000Z") == dt.date(2024, 1, 15)


def test_parse_pubdate_iso_and_epoch():
    assert ne._parse_pubdate("2023-06-30") == dt.date(2023, 6, 30)
    # epoch seconds for 2021-01-01
    assert ne._parse_pubdate("1609459200") == dt.date(2021, 1, 1)


def test_parse_pubdate_bad():
    assert ne._parse_pubdate("garbage") is None
    assert ne._parse_pubdate(None) is None


# --- PIT filter ------------------------------------------------------------


def test_pit_filter_drops_future_articles():
    arts = [
        _art("old", "20200101T000000Z"),
        _art("future", "20210101T000000Z"),
    ]
    kept = ne.pit_filter_articles(arts, dt.date(2020, 6, 1))
    assert [a["title"] for a in kept] == ["old"]


def test_pit_filter_none_passes_all():
    arts = [_art("a", "20200101T000000Z"), _art("b", "bad-date")]
    assert len(ne.pit_filter_articles(arts, None)) == 2


def test_pit_filter_drops_unparseable_under_as_of():
    arts = [_art("bad", "not-a-date")]
    assert ne.pit_filter_articles(arts, dt.date(2020, 6, 1)) == []


# --- classification --------------------------------------------------------


def test_classify_article_categories():
    assert "war_geopolitics" in ne.classify_article(_art("Missile strike escalates conflict", "x"))
    assert "policy_catalyst" in ne.classify_article(_art("Govt announces PLI scheme for EMS", "x"))
    assert "earnings_upgrade" in ne.classify_article(_art("Firm bags order, profit surges", "x"))
    assert "governance_risk" in ne.classify_article(_art("Auditor resignation triggers SFIO probe", "x"))
    assert ne.classify_article(_art("A dull uneventful day", "x")) == set()


def test_classify_articles_counts_and_matches():
    arts = [
        _art("PLI scheme boost for defense", "x"),
        _art("Company wins order, earnings beat", "x"),
        _art("Nothing to see", "x"),
    ]
    res = ne.classify_articles(arts)
    assert res["policy_catalyst"]["count"] == 1
    assert res["earnings_upgrade"]["count"] == 1
    assert res["war_geopolitics"]["count"] == 0
    assert res["policy_catalyst"]["matches"][0]["title"] == "PLI scheme boost for defense"


# --- scan_company_events ---------------------------------------------------


def test_scan_company_events_bias_bullish():
    def fake_fetch(name, ticker, days=21, limit=50):
        return [
            _art("PLI scheme lifts sector", "20200101T000000Z"),
            _art("Q2 results: profit jumps, earnings beat", "20200201T000000Z"),
        ]

    res = ne.scan_company_events("Foo Ltd", "FOO.NS", as_of=dt.date(2020, 6, 1), fetch_fn=fake_fetch)
    assert res["flags"]["policy_catalyst"] is True
    assert res["flags"]["earnings_upgrade"] is True
    assert res["event_bias"] > 0
    assert res["n_articles"] == 2


def test_scan_company_events_bias_bearish():
    def fake_fetch(name, ticker, days=21, limit=50):
        return [_art("SEBI probe over fraud; auditor resignation", "20200101T000000Z")]

    res = ne.scan_company_events("Bar Ltd", "BAR.NS", as_of=dt.date(2020, 6, 1), fetch_fn=fake_fetch)
    assert res["flags"]["governance_risk"] is True
    assert res["event_bias"] < 0


def test_scan_company_events_as_of_gates_future():
    def fake_fetch(name, ticker, days=21, limit=50):
        return [
            _art("PLI scheme (old)", "20200101T000000Z"),
            _art("PLI scheme (future)", "20990101T000000Z"),
        ]

    res = ne.scan_company_events("Foo", "FOO.NS", as_of=dt.date(2020, 6, 1), fetch_fn=fake_fetch)
    assert res["n_articles"] == 1  # future dropped


def test_scan_company_events_graceful_when_feed_raises():
    def boom(*a, **k):
        raise RuntimeError("gdelt down")

    res = ne.scan_company_events("Foo", "FOO.NS", fetch_fn=boom)
    assert res["n_articles"] == 0
    assert res["event_bias"] == 0.0
    assert all(res["flags"][c] is False for c in res["flags"])


# --- scan_macro_geopolitics ------------------------------------------------


def test_scan_macro_geopolitics_elevated():
    def fake_fetch(name, ticker, days=7, limit=50):
        return [_art(f"war headline {i}", "20200101T000000Z") for i in range(50)]

    res = ne.scan_macro_geopolitics(as_of=dt.date(2020, 6, 1), days=7, limit=50, fetch_fn=fake_fetch)
    assert res["available"] is True
    assert res["conflict_volume"] >= 50
    assert res["flag_elevated"] is True


def test_scan_macro_geopolitics_quiet():
    def fake_fetch(name, ticker, days=7, limit=50):
        return []

    res = ne.scan_macro_geopolitics(fetch_fn=fake_fetch, limit=50)
    assert res["conflict_volume"] == 0
    assert res["flag_elevated"] is False
