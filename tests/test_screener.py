"""Tests for the screener.in deep-history fundamentals source + PIT gating.

All tests are hermetic (no network): the parser is exercised with a compact
synthetic HTML fixture, and network is either monkeypatched or disabled.
"""

from __future__ import annotations

import datetime as dt

from src.data import screener


# A compact screener-shaped page: exact period-ends via data-date-key, comma
# thousands, a negative value, ratio (%) rows that must be ignored, a trailing
# non-dated "TTM" column that must be dropped, and a short (missing-cell) row.
FIXTURE_HTML = """
<html><body>
<section id="profit-loss"><table class="data-table">
<thead><tr>
  <th class="text"></th>
  <th class="" data-date-key="2015-03-31">Mar 2015</th>
  <th class="" data-date-key="2016-03-31">Mar 2016</th>
  <th class="" data-date-key="2017-03-31">Mar 2017</th>
  <th class="">TTM</th>
</tr></thead>
<tbody>
  <tr><td class="text"><button class="button-plain">Sales&nbsp;<span>+</span></button></td>
      <td>1,000</td><td>1,200</td><td>1,500</td><td>1,600</td></tr>
  <tr><td class="text">Operating Profit</td><td>200</td><td>250</td><td>300</td><td>320</td></tr>
  <tr><td class="text">OPM %</td><td>20%</td><td>21%</td><td>20%</td><td>20%</td></tr>
  <tr><td class="text">Other Income&nbsp;+</td><td>10</td><td>12</td><td>15</td><td>16</td></tr>
  <tr><td class="text">Interest</td><td>5</td><td>6</td><td>7</td><td>7</td></tr>
  <tr><td class="text">Depreciation</td><td>20</td><td>25</td><td>30</td><td>32</td></tr>
  <tr><td class="text">Net Profit&nbsp;+</td><td>120</td><td>150</td><td>180</td><td>190</td></tr>
  <tr><td class="text">EPS in Rs</td><td>1.20</td><td>1.50</td><td>1.80</td><td>1.90</td></tr>
</tbody></table></section>

<section id="balance-sheet"><table class="data-table">
<thead><tr>
  <th class="text"></th>
  <th data-date-key="2015-03-31">Mar 2015</th>
  <th data-date-key="2016-03-31">Mar 2016</th>
  <th data-date-key="2017-03-31">Mar 2017</th>
</tr></thead>
<tbody>
  <tr><td class="text">Equity Capital</td><td>50</td><td>50</td><td>50</td></tr>
  <tr><td class="text">Reserves</td><td>450</td><td>550</td><td>680</td></tr>
  <tr><td class="text">Borrowings&nbsp;+</td><td>100</td><td>90</td><td>80</td></tr>
  <tr><td class="text">Other Liabilities&nbsp;+</td><td>200</td><td>210</td><td>240</td></tr>
  <tr><td class="text">Total Liabilities</td><td>800</td><td>900</td><td>1,050</td></tr>
  <tr><td class="text">Fixed Assets&nbsp;+</td><td>300</td><td>330</td><td>360</td></tr>
  <tr><td class="text">Total Assets</td><td>800</td><td>900</td><td>1,050</td></tr>
</tbody></table></section>

<section id="cash-flow"><table class="data-table">
<thead><tr>
  <th class="text"></th>
  <th data-date-key="2015-03-31">Mar 2015</th>
  <th data-date-key="2016-03-31">Mar 2016</th>
  <th data-date-key="2017-03-31">Mar 2017</th>
</tr></thead>
<tbody>
  <tr><td class="text">Cash from Operating Activity&nbsp;+</td><td>150</td><td>180</td><td>210</td></tr>
  <tr><td class="text">Free Cash Flow</td><td>100</td><td>130</td><td>160</td></tr>
</tbody></table></section>
</body></html>
"""


def test_symbol_mapping():
    assert screener.screener_symbol("TITAN.NS") == "TITAN"
    assert screener.screener_symbol("500114.BO") == "500114"
    assert screener.screener_symbol("infy") == "INFY"


def test_parse_periods_and_drops_ttm():
    fin = screener.parse_statements_html(FIXTURE_HTML)
    assert fin["status"] == "ok"
    # The trailing non-dated "TTM" column is dropped from the P&L.
    assert fin["income_periods"] == ["2015-03-31", "2016-03-31", "2017-03-31"]
    assert fin["balance_periods"] == ["2015-03-31", "2016-03-31", "2017-03-31"]
    assert fin["cashflow_periods"] == ["2015-03-31", "2016-03-31", "2017-03-31"]


def test_parse_income_lines_and_derived_ebit():
    fin = screener.parse_statements_html(FIXTURE_HTML)
    inc = fin["income"]
    assert inc["Total Revenue"] == [1000.0, 1200.0, 1500.0]
    # Operating Income = Operating Profit - Depreciation (spec sec 3.2 / M-1)
    assert inc["Operating Income"] == [180.0, 225.0, 270.0]
    # EBIT = Operating Profit - Depreciation + Other Income
    assert inc["EBIT"] == [190.0, 237.0, 285.0]
    assert inc["Net Income"] == [120.0, 150.0, 180.0]
    assert inc["Diluted EPS"] == [1.20, 1.50, 1.80]
    # ratio (%) rows are never emitted as raw statement lines
    assert "opm%" not in {k.lower() for k in inc}


def test_parse_balance_capital_employed_convention():
    fin = screener.parse_statements_html(FIXTURE_HTML)
    bal = fin["balance"]
    assert bal["Total Assets"] == [800.0, 900.0, 1050.0]
    # Current Liabilities := "Other Liabilities" so that TA - CL == Equity + Debt.
    assert bal["Current Liabilities"] == [200.0, 210.0, 240.0]
    assert bal["Stockholders Equity"] == [500.0, 600.0, 730.0]
    assert bal["Total Debt"] == [100.0, 90.0, 80.0]
    for ta, cl, eq, debt in zip(
        bal["Total Assets"], bal["Current Liabilities"],
        bal["Stockholders Equity"], bal["Total Debt"],
    ):
        assert abs((ta - cl) - (eq + debt)) < 1e-6  # capital employed identity


def test_parse_cashflow_capex_reproduces_fcf():
    fin = screener.parse_statements_html(FIXTURE_HTML)
    cf = fin["cashflow"]
    assert cf["Operating Cash Flow"] == [150.0, 180.0, 210.0]
    # Capex synthesised as -(CFO - FCF) so CFO - |capex| == screener FCF.
    assert cf["Capital Expenditure"] == [-50.0, -50.0, -50.0]


def test_enrichment_from_screener_is_determinate():
    from src.data.provider import CompanySnapshot, enrich_snapshot_with_financials

    fin = screener.parse_statements_html(FIXTURE_HTML)
    snap = CompanySnapshot(ticker="X.NS", sector="Consumer")
    enrich_snapshot_with_financials(snap, fin)
    assert len(snap.roce_series) == 3
    # ROCE = (OP-Dep) / (TA - CL); first year 180/600 = 0.30
    assert abs(snap.roce_series[0] - 0.30) < 1e-6
    assert snap.fcf_posrate == 1.0
    # cum(CFO)/cum(NP) = 540/450 = 1.2
    assert abs(snap.ocf_to_np_multiyear - 1.2) < 1e-6


def test_empty_html_fails_gracefully():
    fin = screener.parse_statements_html("")
    assert fin["status"] == "failed"
    assert fin["income"] == {}


def test_get_screener_financials_uses_fetch(monkeypatch):
    monkeypatch.setattr(screener, "_fetch_html", lambda sym, variant: FIXTURE_HTML)
    fin = screener.get_screener_financials("TITAN.NS", use_cache=False)
    assert fin["status"] == "ok"
    assert fin["source"] == "screener_consolidated"
    assert fin["income"]["Total Revenue"] == [1000.0, 1200.0, 1500.0]


def test_get_screener_financials_no_network_returns_failed():
    fin = screener.get_screener_financials("NOPE.NS", use_cache=False, allow_network=False)
    assert fin["status"] == "failed"


# ---------------------------------------------------------------------------
# Parsing robustness: accounting negatives, unicode minus, extra aliases
# ---------------------------------------------------------------------------

# A page using alternate row labels (Revenue from Operations / Profit for the
# year / Net Cash Flow from Operating Activities / Total Borrowings), an
# accounting-style negative "(120)" and a unicode-minus value.
ALIAS_HTML = """
<html><body>
<section id="profit-loss"><table>
<thead><tr>
  <th class="text"></th>
  <th data-date-key="2018-03-31">Mar 2018</th>
  <th data-date-key="2019-03-31">Mar 2019</th>
  <th data-date-key="2020-03-31">Mar 2020</th>
</tr></thead>
<tbody>
  <tr><td class="text">Revenue from Operations</td><td>1,000</td><td>1,200</td><td>1,500</td></tr>
  <tr><td class="text">Operating Profit</td><td>200</td><td>250</td><td>300</td></tr>
  <tr><td class="text">Depreciation</td><td>20</td><td>25</td><td>30</td></tr>
  <tr><td class="text">Profit for the year</td><td>120</td><td>(120)</td><td>&#8722;30</td></tr>
</tbody></table></section>
<section id="balance-sheet"><table>
<thead><tr>
  <th class="text"></th>
  <th data-date-key="2018-03-31">Mar 2018</th>
  <th data-date-key="2019-03-31">Mar 2019</th>
  <th data-date-key="2020-03-31">Mar 2020</th>
</tr></thead>
<tbody>
  <tr><td class="text">Equity Share Capital</td><td>50</td><td>50</td><td>50</td></tr>
  <tr><td class="text">Reserves and Surplus</td><td>450</td><td>550</td><td>680</td></tr>
  <tr><td class="text">Total Borrowings</td><td>100</td><td>90</td><td>80</td></tr>
  <tr><td class="text">Total Assets</td><td>800</td><td>900</td><td>1,050</td></tr>
</tbody></table></section>
<section id="cash-flow"><table>
<thead><tr>
  <th class="text"></th>
  <th data-date-key="2018-03-31">Mar 2018</th>
  <th data-date-key="2019-03-31">Mar 2019</th>
  <th data-date-key="2020-03-31">Mar 2020</th>
</tr></thead>
<tbody>
  <tr><td class="text">Net Cash Flow from Operating Activities</td><td>150</td><td>180</td><td>210</td></tr>
  <tr><td class="text">Free Cash Flow</td><td>100</td><td>130</td><td>160</td></tr>
</tbody></table></section>
</body></html>
"""


def test_num_parentheses_and_unicode_minus():
    assert screener._num("(1,234)") == -1234.0
    assert screener._num("\u2212250") == -250.0   # unicode MINUS SIGN
    assert screener._num("\u201350") == -50.0     # en-dash used as a sign
    assert screener._num("(50%)") is None          # ratio rows still ignored
    assert screener._num("1,000") == 1000.0


def test_parse_alternate_aliases_and_negatives():
    fin = screener.parse_statements_html(ALIAS_HTML)
    inc = fin["income"]
    bal = fin["balance"]
    cf = fin["cashflow"]
    assert inc["Total Revenue"] == [1000.0, 1200.0, 1500.0]
    # "Profit for the year" recognised; accounting/unicode negatives parsed.
    assert inc["Net Income"] == [120.0, -120.0, -30.0]
    # "Total Borrowings" -> Total Debt; "Equity Share Capital"+"Reserves and Surplus".
    assert bal["Total Debt"] == [100.0, 90.0, 80.0]
    assert bal["Stockholders Equity"] == [500.0, 600.0, 730.0]
    # "Net Cash Flow from Operating Activities" recognised.
    assert cf["Operating Cash Flow"] == [150.0, 180.0, 210.0]


def test_best_of_variants_prefers_deeper_history(monkeypatch):
    # Consolidated is SHALLOW (2 yrs); standalone is DEEP (3 yrs). The best-of
    # rule must keep the deeper standalone rather than the first (consolidated).
    shallow = """
<section id="profit-loss"><table><thead><tr><th class="text"></th>
<th data-date-key="2019-03-31">Mar 2019</th>
<th data-date-key="2020-03-31">Mar 2020</th></tr></thead>
<tbody><tr><td class="text">Sales</td><td>10</td><td>12</td></tr></tbody></table></section>
"""

    def fake_fetch(sym, variant):
        return shallow if variant == "consolidated/" else ALIAS_HTML

    monkeypatch.setattr(screener, "_fetch_html", fake_fetch)
    fin = screener.get_screener_financials("X.NS", use_cache=False)
    assert fin["source"] == "screener_standalone"
    assert fin["income_periods"] == ["2018-03-31", "2019-03-31", "2020-03-31"]


# ---------------------------------------------------------------------------
# Local human-curated free-source fallback (pre-FY2015 hook; empty by default)
# ---------------------------------------------------------------------------


def test_local_financials_absent_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(screener, "_LOCAL_DIR", tmp_path)
    fin = screener.get_local_financials("SOMETHING.NS")
    assert fin["status"] == "failed"
    assert fin["source"] == "local_absent"


def test_local_financials_loads_and_normalizes(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setattr(screener, "_LOCAL_DIR", tmp_path)
    periods = ["2012-03-31", "2013-03-31", "2014-03-31"]
    (tmp_path / "LEGACY.json").write_text(_json.dumps({
        "income": {"Total Revenue": [100, 120, 140], "Net Income": ["12", 15, None]},
        "balance": {"Total Assets": [200, 220, 240]},
        "cashflow": {"Operating Cash Flow": [15, 18, 22]},
        "income_periods": periods,
        "balance_periods": periods,
        "cashflow_periods": periods,
    }), encoding="utf-8")
    fin = screener.get_local_financials("LEGACY.NS")
    assert fin["status"] == "ok"
    assert fin["source"] == "local_manual"
    assert fin["income"]["Total Revenue"] == [100.0, 120.0, 140.0]
    assert fin["income"]["Net Income"] == [12.0, 15.0, None]  # coerced / None kept
