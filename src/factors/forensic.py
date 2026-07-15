"""Forensic accounting scores: Beneish M-Score and Altman Z"-EM.

Pure functions over aligned statement line-item series (chronological,
oldest..latest). They take the latest period `t` and prior period `t-1`
(Beneish) or just the latest period (Altman). Everything degrades to `None`
when the required inputs are missing rather than guessing - this keeps the
multibagger variant honest about data gaps (spec sections 3.6 / 3.8).

These functions deliberately have NO dependency on the data provider so they
can be imported from both the provider (enrichment) and the factor engine
without an import cycle, and unit-tested with tiny hand-computed fixtures.
"""

from __future__ import annotations

from typing import Sequence

Number = float | int | None


def _at(series: Sequence[Number] | None, idx: int) -> float | None:
    """Fetch the idx-th element (supports negative indexing) or None."""
    if not series:
        return None
    try:
        v = series[idx]
    except (IndexError, TypeError):
        return None
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def beneish_m_score(
    *,
    revenue: Sequence[Number] | None,
    cogs: Sequence[Number] | None,
    sga: Sequence[Number] | None,
    net_income: Sequence[Number] | None,
    cfo: Sequence[Number] | None,
    receivables: Sequence[Number] | None,
    current_assets: Sequence[Number] | None,
    ppe: Sequence[Number] | None,
    total_assets: Sequence[Number] | None,
    depreciation: Sequence[Number] | None,
    current_liabilities: Sequence[Number] | None,
    long_term_debt: Sequence[Number] | None,
) -> float | None:
    """Beneish 8-variable M-score using the latest two fiscal years.

    M = -4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
            + 0.115*DEPI - 0.172*SGAI - 0.327*LVGI + 4.679*TATA

    M > -1.78 => likely earnings manipulator.

    Returns None when the core inputs (revenue, COGS, net income, CFO,
    receivables, total assets) are not available for BOTH t and t-1 - per the
    spec, when COGS is not disclosed the model is not computable and callers
    should fall back to accruals / cash-conversion signals. SGA and
    depreciation are optional: their sub-indices default to the neutral value
    1.0 when absent (they contribute ~0 net signal).
    """
    # Latest (t) and prior (t-1).
    sales_t, sales_p = _at(revenue, -1), _at(revenue, -2)
    cogs_t, cogs_p = _at(cogs, -1), _at(cogs, -2)
    ni_t = _at(net_income, -1)
    cfo_t = _at(cfo, -1)
    recv_t, recv_p = _at(receivables, -1), _at(receivables, -2)
    ca_t, ca_p = _at(current_assets, -1), _at(current_assets, -2)
    ppe_t, ppe_p = _at(ppe, -1), _at(ppe, -2)
    ta_t, ta_p = _at(total_assets, -1), _at(total_assets, -2)

    # Core requirements: without these the model cannot be computed.
    core = [sales_t, sales_p, cogs_t, cogs_p, ta_t, ta_p]
    if any(v is None or v == 0 for v in core):
        return None
    if ni_t is None or cfo_t is None:
        return None

    # DSRI - Days Sales in Receivables Index.
    dsri = _ratio(_ratio(recv_t, sales_t), _ratio(recv_p, sales_p))
    if dsri is None:
        dsri = 1.0

    # GMI - Gross Margin Index (prior GM / current GM).
    gm_t = (sales_t - cogs_t) / sales_t
    gm_p = (sales_p - cogs_p) / sales_p
    gmi = _ratio(gm_p, gm_t)
    if gmi is None:
        gmi = 1.0

    # AQI - Asset Quality Index (securities dropped; often absent).
    def _non_quality(ca, ppe_, ta):
        if ca is None or ppe_ is None or ta is None or ta == 0:
            return None
        return 1.0 - (ca + ppe_) / ta

    nq_t = _non_quality(ca_t, ppe_t, ta_t)
    nq_p = _non_quality(ca_p, ppe_p, ta_p)
    aqi = _ratio(nq_t, nq_p)
    if aqi is None:
        aqi = 1.0

    # SGI - Sales Growth Index.
    sgi = _ratio(sales_t, sales_p) or 1.0

    # DEPI - Depreciation Index.
    dep_t, dep_p = _at(depreciation, -1), _at(depreciation, -2)
    depi = 1.0
    if dep_t is not None and dep_p is not None and ppe_t is not None and ppe_p is not None:
        rate_t = _ratio(dep_t, (dep_t + ppe_t))
        rate_p = _ratio(dep_p, (dep_p + ppe_p))
        d = _ratio(rate_p, rate_t)
        if d is not None:
            depi = d

    # SGAI - SG&A Index.
    sga_t, sga_p = _at(sga, -1), _at(sga, -2)
    sgai = 1.0
    if sga_t is not None and sga_p is not None:
        s = _ratio(_ratio(sga_t, sales_t), _ratio(sga_p, sales_p))
        if s is not None:
            sgai = s

    # LVGI - Leverage Index. Lev = (Current Liab + LTD) / Total Assets.
    cl_t, cl_p = _at(current_liabilities, -1), _at(current_liabilities, -2)
    ltd_t, ltd_p = _at(long_term_debt, -1), _at(long_term_debt, -2)
    lvgi = 1.0
    lev_t = _ratio((cl_t or 0.0) + (ltd_t or 0.0), ta_t) if (cl_t is not None or ltd_t is not None) else None
    lev_p = _ratio((cl_p or 0.0) + (ltd_p or 0.0), ta_p) if (cl_p is not None or ltd_p is not None) else None
    l = _ratio(lev_t, lev_p)
    if l is not None:
        lvgi = l

    # TATA - Total Accruals to Total Assets ~ (NI - CFO) / TA_t.
    tata = (ni_t - cfo_t) / ta_t

    m = (
        -4.84
        + 0.92 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        - 0.327 * lvgi
        + 4.679 * tata
    )
    return m


def altman_z_em(
    *,
    current_assets: Sequence[Number] | None,
    current_liabilities: Sequence[Number] | None,
    total_assets: Sequence[Number] | None,
    retained_earnings: Sequence[Number] | None,
    ebit: Sequence[Number] | None,
    equity: Sequence[Number] | None,
    total_liabilities: Sequence[Number] | None,
) -> float | None:
    """Altman Z"-EM (emerging-market / non-manufacturer) score, latest period.

    Z" = 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
      X1 = (CA - CL) / TA
      X2 = Retained Earnings / TA
      X3 = EBIT / TA
      X4 = Book Equity / Total Liabilities

    Zones: > 2.6 safe, 1.1-2.6 grey, < 1.1 distress.
    Returns None when total assets are unavailable. Missing retained earnings
    is treated conservatively as 0 (penalises young high-growth names, as the
    spec notes). Not meaningful for banks/financials - callers should skip.
    """
    ta = _at(total_assets, -1)
    if ta is None or ta == 0:
        return None
    ca = _at(current_assets, -1)
    cl = _at(current_liabilities, -1)
    re = _at(retained_earnings, -1)
    e = _at(ebit, -1)
    eq = _at(equity, -1)
    tl = _at(total_liabilities, -1)

    # Need at least working capital OR EBIT to be meaningful.
    if ca is None and cl is None and e is None:
        return None

    x1 = ((ca or 0.0) - (cl or 0.0)) / ta
    x2 = (re or 0.0) / ta
    x3 = (e or 0.0) / ta
    x4 = (eq / tl) if (eq is not None and tl not in (None, 0)) else 0.0

    return 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
