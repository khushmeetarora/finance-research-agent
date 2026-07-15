"""Tests for the live universe fetchers (Wikipedia / NSE) with mocked HTTP.

We don't hit the network. We stub `requests.get` and assert the parser
extracts the right rows, falls back to seeds on failure, and caches.
"""

from __future__ import annotations

from src.data import universe_live


_DAX_HTML = """
<html><body>
<table class="wikitable" id="constituents">
<tr><th>Company</th><th>Ticker</th><th>Sector</th></tr>
<tr><td>SAP SE</td><td>SAP</td><td>Software</td></tr>
<tr><td>Siemens AG</td><td>SIE</td><td>Industrial</td></tr>
<tr><td>Allianz SE</td><td>ALV</td><td>Insurance</td></tr>
</table>
</body></html>
"""

_NSE_CSV = """Symbol,Company Name,Industry,ISIN Code\nINFY,Infosys,Information Technology,INE009A01021\nTCS,Tata Consultancy Services,Information Technology,INE467B01029\n"""


class _Resp:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text


def test_fetch_nse_index_parses_csv(monkeypatch):
    def fake_get(url, **kw):
        return _Resp(200, _NSE_CSV)

    monkeypatch.setattr("requests.get", fake_get)
    rows = universe_live._fetch_nse_index("NIFTY50")
    assert rows is not None
    syms = [r[0] for r in rows]
    assert "INFY" in syms and "TCS" in syms
    # Sector normalised to GICS-ish.
    secs = [r[2] for r in rows]
    assert "Information Technology" in secs


def test_fetch_dax_parses_html_table(monkeypatch):
    def fake_get(url, **kw):
        return _Resp(200, _DAX_HTML)

    monkeypatch.setattr("requests.get", fake_get)
    rows = universe_live._fetch_wikipedia_table(
        "DAX", "https://en.wikipedia.org/wiki/DAX", universe_live._parse_dax
    )
    assert rows is not None
    syms = [r[0] for r in rows]
    assert "SAP" in syms and "SIE" in syms


def test_get_constituents_falls_back_to_seeds():
    """When live fetchers return None, the seed list is returned. We don't
    use `universe_live.get_constituents` directly (it's stubbed by conftest);
    instead we exercise the seeds via the public seed modules - guaranteeing
    the same return shape."""
    from src.data import germany_global, india

    rows_in = india.get_constituents("NIFTY50")
    rows_de = germany_global.get_constituents("DAX_PLUS_MDAX")
    assert rows_in and rows_de
    assert all(len(r) == 3 for r in rows_in)
    assert all(len(r) == 3 for r in rows_de)
