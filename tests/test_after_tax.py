"""Tests for the per-pick after-tax expected return estimator."""

from __future__ import annotations

from src.config import load_profile
from src.factors.after_tax import compute_after_tax


def test_after_tax_germany_single_stock():
    profile = load_profile("germany_student")
    res = compute_after_tax(0.8, profile=profile, is_etf=False)
    assert res is not None
    # Tax rate ~ 26.375% (full Abgeltungssteuer).
    assert abs(res.tax_rate_applied - profile["tax"]["long_term_rate"]) < 1e-9
    assert res.expected_after_tax_return < res.expected_gross_return


def test_after_tax_germany_etf_applies_teilfreistellung():
    profile = load_profile("germany_student")
    rate = profile["tax"]["long_term_rate"]
    tf = profile["etf_teilfreistellung_pct"]
    res = compute_after_tax(0.8, profile=profile, is_etf=True)
    assert res is not None
    # Effective rate is roughly rate * (1 - tf).
    assert abs(res.tax_rate_applied - rate * (1 - tf)) < 1e-9
    assert any("Teilfreistellung" in n for n in res.notes)


def test_after_tax_india_uses_ltcg_rate():
    profile = load_profile("india_adult")
    res = compute_after_tax(0.7, profile=profile)
    assert res is not None
    assert abs(res.tax_rate_applied - profile["tax"]["long_term_rate"]) < 1e-9


def test_after_tax_returns_none_without_return_model():
    profile = {"country": "IN", "tax": {"long_term_rate": 0.1}}
    res = compute_after_tax(0.5, profile=profile)
    assert res is None
