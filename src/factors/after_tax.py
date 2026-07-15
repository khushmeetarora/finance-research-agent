"""Per-pick after-tax expected return estimator.

This is intentionally simple. It takes the deterministic composite score and
translates it to an expected gross return using a profile-specific base rate
plus a slope, then subtracts trading costs and capital-gains tax with the
profile's holding-period and exemption rules.

It is *not* a forecast - it's a structured comparison aid so the Picks sheet
can compare picks on a consistent after-tax basis instead of just composite
scores. The user must understand the assumptions baked into base_annual_return
and composite_to_return_slope (set in profile YAML).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AfterTaxRow:
    expected_gross_return: float
    transaction_cost: float
    tax_rate_applied: float
    expected_after_tax_return: float
    holding_horizon_days: int
    notes: list[str]


def compute_after_tax(
    composite_score: float | None,
    *,
    profile: dict[str, Any],
    is_etf: bool = False,
) -> AfterTaxRow | None:
    """Estimate after-tax annualised return for a pick.

    Returns None if the profile lacks a return_model section.
    """
    rm = (profile or {}).get("return_model") or {}
    if not rm:
        return None

    base = float(rm.get("base_annual_return", 0.08))
    slope = float(rm.get("composite_to_return_slope", 0.03))
    cost_bps = float(rm.get("transaction_cost_bps", 15))

    composite = composite_score if composite_score is not None else 0.5
    gross = base + slope * (composite - 0.5) * 2.0  # composite 0->-slope, 1->+slope

    cost = cost_bps / 10000.0  # annualised: 1x cost (assume hold > 1y)

    tax = (profile or {}).get("tax") or {}
    country = (profile or {}).get("country", "").upper()
    notes: list[str] = []

    horizon_days = 365
    if country == "IN":
        # Use LTCG (>= 1 year) by default for the after-tax model; STCG hits
        # only if you trade short-term, which violates the profile preference.
        rate = float(tax.get("long_term_rate", 0.125))
        exempt = float(tax.get("long_term_annual_exemption_inr", 0))
        notes.append(
            f"Assuming LTCG eligibility ({tax.get('long_term_rate', 0)*100:.2f}%); "
            f"first {exempt:,.0f} INR/yr exempt."
        )
        # For a single-pick estimate we ignore the exemption (it's portfolio-level).
        tax_rate = rate
    elif country == "DE":
        rate = float(tax.get("long_term_rate", 0.26375))
        if is_etf:
            tf = float((profile or {}).get("etf_teilfreistellung_pct", 0.30))
            tax_rate = rate * (1.0 - tf)
            notes.append(
                f"ETF: applying {tf*100:.0f}% Teilfreistellung -> "
                f"effective tax {tax_rate*100:.2f}%."
            )
        else:
            tax_rate = rate
            notes.append(
                f"Single stock: full Abgeltungssteuer {rate*100:.3f}% "
                "(no Teilfreistellung)."
            )
    else:
        tax_rate = float(tax.get("long_term_rate", 0.20))

    # We tax only the *positive* component of gross return; if the model's
    # gross is negative (composite very low) we don't add a fictitious tax credit.
    taxable = max(0.0, gross - cost)
    after_tax = (gross - cost) - tax_rate * taxable

    return AfterTaxRow(
        expected_gross_return=gross,
        transaction_cost=cost,
        tax_rate_applied=tax_rate,
        expected_after_tax_return=after_tax,
        holding_horizon_days=horizon_days,
        notes=notes,
    )
