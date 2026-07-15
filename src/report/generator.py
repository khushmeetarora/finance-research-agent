"""Markdown report generator.

Renders the final AgentState into a Markdown report under ./reports/. PDF
rendering is intentionally optional (we don't want a hard wkhtmltopdf
dependency) - markdown -> HTML is provided as a convenience.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import reports_dir
from ..graph.state import AgentState
from ..llm.factory import get_llm, is_stub
from .excel import generate_excel_report


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _fmt(v):
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip())
    return text.strip("-")[:60] or "report"


def generate_report(state: AgentState) -> AgentState:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(disabled_extensions=("md", "j2")),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.globals["fmt"] = _fmt
    template = env.get_template("report.md.j2")

    top_n = state.top_n
    scoring_mode = (state.profile.get("scoring_mode") or "classic").lower()
    factor_table = []
    for rep in state.factor_reports[:top_n]:
        factor_table.append(
            {
                "ticker": rep["ticker"],
                "name": rep.get("name"),
                "composite_score": rep.get("composite_score"),
                "factor_scores": rep.get("factor_scores", {}),
            }
        )

    # Multibagger scorecard: pillar scores + consistency stats + red flags.
    multibagger_scorecard = []
    if scoring_mode == "multibagger":
        for rep in state.factor_reports[:top_n]:
            multibagger_scorecard.append(
                {
                    "ticker": rep["ticker"],
                    "name": rep.get("name"),
                    "composite_score": rep.get("composite_score"),
                    "pillar_scores": rep.get("pillar_scores", {}),
                    "consistency_stats": rep.get("consistency_stats", {}),
                    "vetoes": rep.get("vetoes", []),
                    "soft_flags": rep.get("soft_flags", []),
                }
            )

    md = template.render(
        profile_id=state.profile_id,
        profile_display=state.profile.get("display_name") or state.profile_id,
        profile_country=state.profile.get("country") or "",
        target=state.target,
        universe_name=state.universe_name,
        candidate_count=len(state.candidate_tickers),
        top_n=top_n,
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        as_of=state.as_of,
        input_hash=state.input_hash,
        picks=state.picks,
        factor_table=factor_table,
        analyst_signals=state.analyst_signals,
        debate=state.debate,
        risk_notes=state.risk_notes,
        tax_notes=state.tax_notes,
        factor_weights=state.profile.get("factor_weights", {}),
        pillar_weights=state.profile.get("pillar_weights", {}),
        scoring_mode=scoring_mode,
        multibagger_scorecard=multibagger_scorecard,
        data_health=state.data_health,
        factor_regime=state.factor_regime,
        llm_unavailable=is_stub(get_llm()),
    )

    folder = reports_dir()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"{stamp}-{state.profile_id}-{_slug(state.target)}.md"
    out_path = folder / fname
    out_path.write_text(md, encoding="utf-8")
    state.report_path = str(out_path)

    if state.write_excel:
        try:
            xlsx_path = generate_excel_report(state)
            state.excel_path = str(xlsx_path)
        except Exception as e:
            # Don't fail the whole pipeline if openpyxl/xlsx writing breaks.
            state.excel_path = None
            state.risk_notes.append(f"Excel report generation failed: {e}")

    return state
