"""Persistent memory log.

Per TradingAgents-style memory: after each run we append a compact JSON
record (target, profile, picks, factor weights, report path, timestamp) so
later runs - and the user reviewing history - can see what was previously
recommended.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

from ..config import memory_dir
from ..graph.state import AgentState


def _index_path() -> Path:
    return memory_dir() / "index.jsonl"


def persist_run(state: AgentState) -> AgentState:
    rec_id = str(uuid.uuid4())[:8]
    record = {
        "id": rec_id,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "profile_id": state.profile_id,
        "target": state.target,
        "universe": state.universe_name or state.profile.get("universe", {}).get("default"),
        "top_n": state.top_n,
        "use_llm": state.use_llm,
        "candidate_count": len(state.candidate_tickers),
        "picks": [
            {
                "rank": p.rank,
                "ticker": p.ticker,
                "name": p.name,
                "composite_score": p.composite_score,
                "confidence": p.confidence,
                "thesis": p.thesis[:240],
            }
            for p in state.picks
        ],
        "report_path": state.report_path,
        "excel_path": state.excel_path,
        "as_of": state.as_of,
        "input_hash": state.input_hash,
        "data_health_severity": (state.data_health or {}).get("severity"),
        "avg_coverage": (state.data_health or {}).get("avg_coverage"),
        "avg_agreement": (state.data_health or {}).get("avg_agreement"),
        "factor_regime": (state.factor_regime or {}).get("factor_returns") or {},
    }
    with _index_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    state.memory_id = rec_id
    return state


def list_runs(limit: int = 20) -> list[dict]:
    path = _index_path()
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:][::-1]
