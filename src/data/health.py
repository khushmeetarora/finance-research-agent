"""DataHealthCard: a per-run summary of how trustworthy the input data is.

We compute coverage (fraction of metrics populated), dropout list (tickers
that failed to fetch), and average cross-source agreement. The card is
surfaced prominently in both the Markdown and Excel reports so the user
cannot miss when a run was based on degraded data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .provider import CompanySnapshot


# Numeric fields we expect on every snapshot - used to compute coverage.
_NUMERIC_FIELDS: tuple[str, ...] = (
    "market_cap",
    "price",
    "pe_trailing",
    "pb",
    "ps",
    "ev_to_ebitda",
    "earnings_yield",
    "fcf_yield",
    "dividend_yield",
    "roe",
    "roic",
    "gross_margin",
    "operating_margin",
    "profit_margin",
    "debt_to_equity",
    "net_debt_to_ebitda",
    "current_ratio",
    "cash_conversion",
    "revenue_growth",
    "earnings_growth",
    "momentum_12_1",
    "momentum_6_1",
    "volatility_annualized",
)


@dataclass
class DataHealthCard:
    requested: int = 0
    fetched: int = 0
    failed: int = 0
    avg_coverage: float = 0.0
    avg_agreement: float | None = None
    dropouts: list[str] = field(default_factory=list)
    low_agreement: list[tuple[str, float]] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    severity: str = "ok"  # "ok" | "warn" | "critical"
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "fetched": self.fetched,
            "failed": self.failed,
            "avg_coverage": self.avg_coverage,
            "avg_agreement": self.avg_agreement,
            "dropouts": list(self.dropouts),
            "low_agreement": [list(t) for t in self.low_agreement],
            "sources_used": list(self.sources_used),
            "severity": self.severity,
            "messages": list(self.messages),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "DataHealthCard":
        if not d:
            return cls()
        c = cls()
        c.requested = int(d.get("requested", 0))
        c.fetched = int(d.get("fetched", 0))
        c.failed = int(d.get("failed", 0))
        c.avg_coverage = float(d.get("avg_coverage", 0.0))
        c.avg_agreement = d.get("avg_agreement")
        c.dropouts = list(d.get("dropouts") or [])
        c.low_agreement = [tuple(t) for t in (d.get("low_agreement") or [])]
        c.sources_used = list(d.get("sources_used") or [])
        c.severity = str(d.get("severity") or "ok")
        c.messages = list(d.get("messages") or [])
        return c


def _coverage_of(snap: CompanySnapshot) -> float:
    present = sum(1 for f in _NUMERIC_FIELDS if getattr(snap, f, None) is not None)
    return present / len(_NUMERIC_FIELDS) if _NUMERIC_FIELDS else 0.0


def coverage_of(snap: CompanySnapshot) -> float:
    """Public per-snapshot coverage (0..1)."""
    return _coverage_of(snap)


# Tier-A + Tier-B fields the multibagger variant relies on. Used as the
# coverage denominator for the multibagger scoring mode so a name with no
# statement enrichment is (correctly) shrunk toward the median.
_MULTIBAGGER_FIELDS: tuple[str, ...] = _NUMERIC_FIELDS + (
    "roce",
    "gross_profitability",
    "accruals_ratio",
    "interest_coverage",
    "fcf",
    "fcf_posrate",
    "ocf_to_np_multiyear",
    "beneish_m",
    "altman_z",
    "peg",
    "earnings_cagr",
    "capex_intensity",
    "asset_turnover",
    "dso",
    "dio",
    "dpo",
    "ccc",
)


def multibagger_coverage_of(snap: CompanySnapshot) -> float:
    """Per-snapshot coverage across Tier-A + Tier-B multibagger fields (0..1)."""
    present = sum(1 for f in _MULTIBAGGER_FIELDS if getattr(snap, f, None) is not None)
    return present / len(_MULTIBAGGER_FIELDS) if _MULTIBAGGER_FIELDS else 0.0


def build_card(
    requested_tickers: Iterable[str],
    snapshots: Iterable[CompanySnapshot],
    *,
    coverage_warn: float = 0.5,
    coverage_critical: float = 0.3,
    agreement_warn: float = 0.95,
    agreement_critical: float = 0.85,
) -> DataHealthCard:
    requested = list(requested_tickers)
    snaps = list(snapshots)
    fetched_tickers = {s.ticker for s in snaps if s.fetch_status != "failed"}
    failed_tickers = [t for t in requested if t not in fetched_tickers]

    coverages = [_coverage_of(s) for s in snaps]
    agreements = [s.data_agreement for s in snaps if s.data_agreement is not None]
    sources_used: set[str] = set()
    for s in snaps:
        for src in s.data_sources:
            sources_used.add(src)

    avg_cov = sum(coverages) / len(coverages) if coverages else 0.0
    avg_agreement = (
        sum(agreements) / len(agreements) if agreements else None
    )
    low_agreement: list[tuple[str, float]] = sorted(
        [
            (s.ticker, s.data_agreement)
            for s in snaps
            if s.data_agreement is not None and s.data_agreement < agreement_warn
        ],
        key=lambda x: x[1],
    )

    severity = "ok"
    messages: list[str] = []

    if requested:
        fetch_rate = len(fetched_tickers) / len(requested)
    else:
        fetch_rate = 1.0

    if fetch_rate < 0.5:
        severity = "critical"
        messages.append(
            f"Only {len(fetched_tickers)}/{len(requested)} tickers fetched "
            f"({fetch_rate*100:.0f}%) - rankings are unreliable on this small sample."
        )
    elif fetch_rate < 0.8:
        severity = "warn" if severity != "critical" else severity
        messages.append(
            f"{len(failed_tickers)} ticker(s) failed to fetch: "
            f"{', '.join(failed_tickers[:8])}"
            + (" ..." if len(failed_tickers) > 8 else "")
        )

    if avg_cov < coverage_critical:
        severity = "critical"
        messages.append(
            f"Average data coverage {avg_cov*100:.0f}% is critically low. "
            "Composite scores are heavily diluted."
        )
    elif avg_cov < coverage_warn:
        if severity == "ok":
            severity = "warn"
        messages.append(
            f"Average data coverage {avg_cov*100:.0f}% is below the comfort "
            f"threshold ({coverage_warn*100:.0f}%)."
        )

    if avg_agreement is not None and avg_agreement < agreement_critical:
        severity = "critical"
        messages.append(
            f"Average price agreement between yfinance and Stooq is "
            f"{avg_agreement*100:.0f}% - data sources disagree materially."
        )
    elif avg_agreement is not None and avg_agreement < agreement_warn:
        if severity == "ok":
            severity = "warn"
        messages.append(
            f"Some tickers show low cross-source price agreement: "
            + ", ".join(f"{t}={a*100:.0f}%" for t, a in low_agreement[:5])
        )

    if not messages:
        messages.append(
            f"OK: {len(fetched_tickers)}/{len(requested)} tickers, "
            f"avg coverage {avg_cov*100:.0f}%, "
            + (
                f"avg agreement {avg_agreement*100:.0f}%."
                if avg_agreement is not None
                else "single-source mode."
            )
        )

    card = DataHealthCard(
        requested=len(requested),
        fetched=len(fetched_tickers),
        failed=len(failed_tickers),
        avg_coverage=avg_cov,
        avg_agreement=avg_agreement,
        dropouts=failed_tickers,
        low_agreement=low_agreement,
        sources_used=sorted(sources_used),
        severity=severity,
        messages=messages,
    )
    return card
