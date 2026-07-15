"""Tests for the structured-output LLM helper."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm.factory import complete_validated, grade_rationale


class _Sig(BaseModel):
    ticker: str
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class _ScriptedLLM:
    """Returns the next scripted JSON string for each call."""

    def __init__(self, scripts: list[str]):
        self._scripts = list(scripts)
        self.calls = 0

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        return self._scripts.pop(0) if self._scripts else ""

    def complete_json(
        self, prompt: str, system: str | None = None, schema: dict | None = None
    ) -> str:
        return self.complete(prompt, system=system)


def test_complete_validated_succeeds_first_try():
    llm = _ScriptedLLM(['{"ticker":"A","score":0.5,"confidence":0.8}'])
    out = complete_validated(llm, "?", system=None, pydantic_model=_Sig)
    assert out is not None
    assert out.ticker == "A"
    assert llm.calls == 1


def test_complete_validated_retries_on_invalid():
    llm = _ScriptedLLM([
        '{"ticker":"A","score":7,"confidence":0.8}',  # invalid (score > 1)
        '{"ticker":"A","score":0.5,"confidence":0.8}',  # valid
    ])
    out = complete_validated(llm, "?", system=None, pydantic_model=_Sig)
    assert out is not None
    assert llm.calls == 2


def test_complete_validated_returns_none_after_all_retries():
    llm = _ScriptedLLM([
        '{"ticker":"A","score":7,"confidence":0.8}',
        '{"bogus":"output"}',
    ])
    out = complete_validated(llm, "?", system=None, pydantic_model=_Sig)
    assert out is None


def test_grade_rationale_grounded_metric():
    """1.0 if rationale cites an actual metric, 0.75 if it has *some* number,
    0.5 if no numbers / empty."""
    metrics = {"roe": 0.25, "pe": 18.0}
    grounded = "ROE of 25 is excellent and the P/E of 18 is reasonable."
    has_some_digit = "Trading at 12 times something - looks fine."
    no_digits = "Solid fundamentals overall."
    assert grade_rationale(grounded, metrics) == 1.0
    assert grade_rationale(has_some_digit, metrics) == 0.75
    assert grade_rationale(no_digits, metrics) == 0.5
    assert grade_rationale("", metrics) == 0.5
