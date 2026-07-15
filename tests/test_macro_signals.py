"""Unit tests for the free macro-signals layer (PIT transforms + parsing).

Hermetic: no live network. The pure transform functions are exercised directly
with fixture series; the FRED CSV parser is tested on a literal CSV string.
"""

from __future__ import annotations

import datetime as dt

from src.data import macro_signals as ms


def _daily_series(start: str, values: list[float]) -> list[dict]:
    d0 = dt.date.fromisoformat(start)
    out = []
    for i, v in enumerate(values):
        out.append({"date": (d0 + dt.timedelta(days=i)).isoformat(), "value": v})
    return out


def _monthly_series(start_year: int, months: int, base: float, step: float) -> list[dict]:
    out = []
    y, m = start_year, 1
    for i in range(months):
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": base + step * i})
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


# --- FRED CSV parsing ------------------------------------------------------


def test_parse_fred_csv_skips_missing_and_sorts():
    csv_text = (
        "DATE,DGS10\n"
        "2020-01-01,.\n"          # missing -> skipped
        "2020-01-03,1.90\n"
        "2020-01-02,1.88\n"       # out of order -> sorted
        "2020-01-04,not_a_number\n"  # unparseable -> skipped
    )
    series = ms._parse_fred_csv(csv_text)
    assert [p["date"] for p in series] == ["2020-01-02", "2020-01-03"]
    assert series[0]["value"] == 1.88
    assert series[-1]["value"] == 1.90


def test_parse_fred_csv_observation_date_header():
    csv_text = "observation_date,INDCPIALLMINMEI\n2021-06-01,160.2\n"
    series = ms._parse_fred_csv(csv_text)
    assert series == [{"date": "2021-06-01", "value": 160.2}]


# --- as_of_series (the PIT gate) ------------------------------------------


def test_as_of_series_drops_future_points_no_lag():
    s = _daily_series("2020-01-01", [10, 11, 12, 13, 14])  # Jan 1..5
    gated = ms.as_of_series(s, dt.date(2020, 1, 3), publication_lag_days=0)
    assert [p["date"] for p in gated] == ["2020-01-01", "2020-01-02", "2020-01-03"]


def test_as_of_series_respects_publication_lag():
    # CPI stamped for period-end but released ~21 days later.
    s = [{"date": "2020-06-30", "value": 100.0}, {"date": "2020-07-31", "value": 101.0}]
    # as_of 2020-07-15: the 2020-06-30 print is knowable (30 Jun + 21d = 21 Jul?
    # 30 Jun + 21 = 21 Jul > 15 Jul) -> NOT yet knowable with lag=21.
    gated = ms.as_of_series(s, dt.date(2020, 7, 15), publication_lag_days=21)
    assert gated == []
    # With as_of 2020-07-25 the June print (knowable 21 Jul) is admissible.
    gated2 = ms.as_of_series(s, dt.date(2020, 7, 25), publication_lag_days=21)
    assert [p["date"] for p in gated2] == ["2020-06-30"]


def test_as_of_series_empty_and_none():
    assert ms.as_of_series(None, dt.date(2020, 1, 1)) == []
    assert ms.as_of_series([], dt.date(2020, 1, 1)) == []


# --- momentum / delta / vol / zscore / percentile -------------------------


def test_momentum_date_based():
    s = _daily_series("2020-01-01", [float(x) for x in range(100, 100 + 40)])
    # latest date is day+39 (value 139); ~20 days before -> value 119.
    mom = ms.momentum(s, 20)
    assert mom is not None
    assert abs(mom - (139 - 119) / 119) < 1e-9


def test_delta_level_change():
    s = _monthly_series(2019, 24, base=6.0, step=-0.1)  # rate falling 0.1/mo
    d = ms.delta(s, 365)
    assert d is not None
    assert d < 0  # rates fell over the year (easing)


def test_annualized_vol_positive_and_none_paths():
    s = _daily_series("2020-01-01", [100, 101, 99, 102, 98, 103, 97])
    v = ms.annualized_vol(s, window_points=6)
    assert v is not None and v > 0
    assert ms.annualized_vol([{"date": "2020-01-01", "value": 100.0}], 6) is None


def test_percentile_rank_extremes():
    rising = _daily_series("2020-01-01", [float(x) for x in range(1, 60)])
    assert ms.percentile_rank(rising, 50) == 1.0  # latest is the max
    falling = _daily_series("2020-01-01", [float(x) for x in range(60, 1, -1)])
    pr = ms.percentile_rank(falling, 50)
    assert pr is not None and pr < 0.1  # latest is the min


def test_zscore_zero_when_flat():
    flat = _daily_series("2020-01-01", [5.0] * 10)
    assert ms.zscore(flat, 10) == 0.0


# --- config loading --------------------------------------------------------


def test_load_macro_config_defaults_when_missing(tmp_path):
    cfg = ms.load_macro_config(path=tmp_path / "does_not_exist.yaml")
    assert cfg["fred"]["india_repo_rate"]["id"] == "INTDSRINM193N"
    assert "thresholds" in cfg and "lookbacks" in cfg


def test_default_series_provider_uses_injected_fetchers(monkeypatch):
    monkeypatch.setattr(ms, "fetch_fred_series", lambda sid, **k: [{"date": "2020-01-01", "value": 1.0}])
    monkeypatch.setattr(ms, "fetch_yahoo_series", lambda tkr, **k: [{"date": "2020-01-02", "value": 2.0}])
    provider = ms.default_series_provider()
    assert provider("india_repo_rate")[0]["value"] == 1.0
    assert provider("india_vix")[0]["value"] == 2.0
    assert provider("unknown_name") == []


def test_publication_lag_and_source_label():
    cfg = ms.load_macro_config()
    assert ms.publication_lag("india_cpi", cfg) == 21
    assert ms.publication_lag("india_vix", cfg) == 0
    assert ms.publication_lag("nonexistent", cfg) == 0
    assert ms.source_label("india_cpi", cfg).startswith("FRED:")
    assert ms.source_label("india_vix", cfg).startswith("yfinance:")


def test_fetch_fred_series_graceful_on_network_error(monkeypatch):
    # Force requests.get to raise; expect [] and a cached empty result.
    import src.data.macro_signals as m

    def _boom(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setitem(__import__("sys").modules, "requests", type("R", (), {"get": staticmethod(_boom)}))
    out = m.fetch_fred_series("DGS10")
    assert out == []
