"""Shared Pydantic state passed between graph nodes.

Lightweight - the heavy data structures (snapshots, factor reports) are
serialized via to_dict() before being placed on state, so the graph can be
checkpointed/inspected as plain JSON.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalystSignal(BaseModel):
    """Structured analyst output. Score is in [-1, 1]; rationale in plain text."""

    role: str
    ticker: str | None = None
    score: float = 0.0
    stance: Literal["bullish", "bearish", "neutral"] = "neutral"
    confidence: float = 0.5
    rationale: str = ""
    evidence: list[str] = Field(default_factory=list)


class DebateTurn(BaseModel):
    side: Literal["bull", "bear"]
    round_idx: int
    text: str


class FinalPick(BaseModel):
    ticker: str
    name: str | None = None
    composite_score: float | None = None
    rank: int
    thesis: str = ""
    key_risks: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    suggested_horizon: str | None = None
    tax_notes: list[str] = Field(default_factory=list)
    profile_fit: float | None = None
    factor_std_dev: float | None = None
    coverage: float | None = None
    expected_gross_return: float | None = None
    expected_after_tax_return: float | None = None
    is_cross_currency: bool = False
    floor_breaches: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    """The blob that flows through the graph."""

    # Inputs
    profile_id: str
    profile: dict[str, Any] = Field(default_factory=dict)
    target: str
    universe_name: str | None = None
    domain: str | None = None
    top_n: int = 10
    use_llm: bool = True
    write_excel: bool = True
    max_debate_rounds: int = 1
    as_of: str | None = None              # ISO date for reproducibility
    input_hash: str | None = None         # SHA-256 of canonical input data

    # Universe + data
    candidate_tickers: list[str] = Field(default_factory=list)
    candidate_meta: list[dict[str, Any]] = Field(default_factory=list)
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    data_health: dict[str, Any] = Field(default_factory=dict)

    # Quant output
    factor_reports: list[dict[str, Any]] = Field(default_factory=list)
    shortlist: list[str] = Field(default_factory=list)
    factor_regime: dict[str, Any] = Field(default_factory=dict)

    # Agent outputs
    analyst_signals: list[AnalystSignal] = Field(default_factory=list)
    debate: list[DebateTurn] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    tax_notes: list[str] = Field(default_factory=list)

    # Final
    picks: list[FinalPick] = Field(default_factory=list)
    report_path: str | None = None
    excel_path: str | None = None
    memory_id: str | None = None
