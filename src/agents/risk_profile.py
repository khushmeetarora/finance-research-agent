"""Risk + investor-profile/tax agent.

Deterministic-first: applies profile risk constraints (concentration, max
volatility) and tax notes from the profile YAML. The output is a list of
risk_notes + tax_notes attached to state, and per-pick tax_notes added by
the manager later.
"""

from __future__ import annotations

from ..graph.state import AgentState


def _format_currency(amount: float, currency: str) -> str:
    if currency == "INR":
        # Use lakh / crore formatting.
        if amount >= 1e7:
            return f"Rs {amount/1e7:.2f} cr"
        if amount >= 1e5:
            return f"Rs {amount/1e5:.2f} L"
        return f"Rs {amount:,.0f}"
    if currency == "EUR":
        return f"EUR {amount:,.0f}"
    return f"{currency} {amount:,.0f}"


def run(state: AgentState) -> AgentState:
    profile = state.profile
    constraints = profile.get("risk_constraints", {}) or {}
    tax = profile.get("tax", {}) or {}
    currency = profile.get("currency", "")
    country = profile.get("country", "").upper()

    notes: list[str] = []
    max_pos = constraints.get("max_single_position_pct")
    if max_pos:
        notes.append(
            f"Position concentration cap: {max_pos*100:.0f}% per name."
        )
    if constraints.get("prefer_etf"):
        notes.append("Profile prefers diversified ETFs alongside single names.")
    max_vol = constraints.get("max_volatility_annualized")
    if max_vol:
        notes.append(
            f"Names with annualized volatility > {max_vol*100:.0f}% were filtered out."
        )

    state.risk_notes.extend(notes)

    # Tax notes - copied verbatim from profile so they live in YAML.
    tax_notes: list[str] = []
    for n in tax.get("notes") or []:
        tax_notes.append(n)

    if country == "IN":
        st = tax.get("short_term_rate", 0)
        lt = tax.get("long_term_rate", 0)
        thr = tax.get("short_term_threshold_days", 365)
        exempt = tax.get("long_term_annual_exemption_inr", 0)
        tax_notes.append(
            f"India equity tax: STCG {st*100:.1f}% (held <= {thr}d), "
            f"LTCG {lt*100:.2f}% above {_format_currency(exempt, 'INR')}/FY."
        )
    elif country == "DE":
        rate = tax.get("long_term_rate", 0)
        exempt = tax.get("long_term_annual_exemption_eur", 0)
        tax_notes.append(
            f"Germany Abgeltungssteuer: flat {rate*100:.3f}% on capital income "
            f"above Sparerpauschbetrag {_format_currency(exempt, 'EUR')}/yr."
        )

    state.tax_notes.extend(tax_notes)
    return state
