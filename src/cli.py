"""Finance Research Agent CLI."""

from __future__ import annotations

import os
import sys
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .config import load_profile
from .graph.orchestrator import run as run_graph
from .graph.state import AgentState
from .memory.store import list_runs


load_dotenv()
app = typer.Typer(
    add_completion=False,
    help="Finance Research Agent (FRA) - research-only multi-agent stock screener.",
)
console = Console()


@app.command()
def research(
    profile: str = typer.Option(..., "--profile", "-p", help="Profile id (e.g. india_adult, germany_student)."),
    target: str = typer.Option(..., "--target", "-t", help="Free-text target: a ticker, or e.g. 'best IT stocks in India'."),
    universe: Optional[str] = typer.Option(None, "--universe", "-u", help="Override universe (e.g. NIFTY50, DAX, GLOBAL_LARGE)."),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain/sector hint (e.g. banking, IT, pharma)."),
    top: int = typer.Option(10, "--top", "-n", help="Top-N picks to surface."),
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Scoring mode override: 'classic' (5-factor) or 'multibagger' "
        "(7-pillar Multibagger Quality Score). Defaults to the profile's "
        "scoring_mode (or 'classic').",
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM stages; use factor engine only."),
    no_excel: bool = typer.Option(False, "--no-excel", help="Skip writing the .xlsx report."),
    rounds: int = typer.Option(1, "--rounds", help="Bull/Bear debate rounds when LLM is enabled."),
    as_of: Optional[str] = typer.Option(
        None,
        "--as-of",
        help="ISO date (YYYY-MM-DD) for reproducibility. "
        "Currently affects the input hash and report stamp; data fetch is best-effort live.",
    ),
):
    """Run a research pass and write a Markdown report."""
    try:
        profile_data = load_profile(profile)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    # CLI --mode overrides the profile's scoring_mode (additive; leaves the
    # on-disk profile untouched).
    if mode:
        profile_data = {**profile_data, "scoring_mode": mode.lower()}

    state = AgentState(
        profile_id=profile,
        profile=profile_data,
        target=target,
        universe_name=universe,
        domain=domain,
        top_n=top,
        use_llm=not no_llm,
        write_excel=not no_excel,
        max_debate_rounds=max(0, rounds),
        as_of=as_of,
    )

    console.rule("[bold]Finance Research Agent[/bold]")
    console.print(
        f"profile=[cyan]{profile}[/cyan]  target=[cyan]{target!r}[/cyan]  "
        f"universe=[cyan]{universe or profile_data.get('universe', {}).get('default')}[/cyan]  "
        f"mode=[cyan]{profile_data.get('scoring_mode', 'classic')}[/cyan]  "
        f"top={top}  use_llm={not no_llm}  rounds={rounds}"
    )

    if not no_llm:
        provider = os.environ.get("LLM_PROVIDER", "ollama")
        model = os.environ.get("LLM_MODEL", "llama3.1:8b")
        console.print(f"[dim]LLM provider={provider} model={model}[/dim]")

    state = run_graph(state)

    _print_summary(state)

    if state.input_hash:
        console.print(f"input hash:      [dim]{state.input_hash}[/dim]")
    if state.report_path:
        console.print(f"\nMarkdown report: [green]{state.report_path}[/green]")
    if state.excel_path:
        console.print(f"Excel report:    [green]{state.excel_path}[/green]")
    _print_data_health(state)


@app.command(name="history")
def history(limit: int = typer.Option(20, "--limit", "-n", help="Max records.")):
    """Show recent research runs."""
    runs = list_runs(limit=limit)
    if not runs:
        console.print("[dim](no past runs)[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("when")
    table.add_column("profile")
    table.add_column("target")
    table.add_column("top picks")
    table.add_column("hash")
    table.add_column("health")
    table.add_column("md")
    table.add_column("xlsx")
    for r in runs:
        picks = ", ".join(p["ticker"] for p in (r.get("picks") or [])[:5])
        table.add_row(
            r.get("ts", ""),
            r.get("profile_id", ""),
            r.get("target", ""),
            picks,
            (r.get("input_hash") or "")[:8],
            r.get("data_health_severity", "") or "",
            r.get("report_path", "") or "",
            r.get("excel_path", "") or "",
        )
    console.print(table)


@app.command()
def backtest(
    profile: str = typer.Option(..., "--profile", "-p", help="Profile id."),
    universe: Optional[str] = typer.Option(None, "--universe", "-u", help="Override universe."),
    start: str = typer.Option("2020-01-01", "--start", help="Start date (YYYY-MM-DD)."),
    top: int = typer.Option(10, "--top", "-n", help="Top-N rebalanced equal-weight portfolio."),
    benchmark: Optional[str] = typer.Option(
        None, "--benchmark", help="Optional benchmark ticker (e.g. ^NSEI, ^GDAXI, ^GSPC)."
    ),
):
    """Run a price-only proxy walk-forward backtest of the composite ranker."""
    try:
        profile_data = load_profile(profile)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    from .agents.universe import _candidate_pool  # type: ignore
    from .backtest.engine import BacktestConfig, run_backtest
    from .config import reports_dir

    rows = _candidate_pool(profile_data, universe)
    suffix = (profile_data.get("universe") or {}).get("yahoo_suffix", "")
    tickers = [f"{r[0]}{suffix}" for r in rows]
    console.print(
        f"[bold]Backtest[/bold] profile={profile} tickers={len(tickers)} "
        f"start={start} top={top} benchmark={benchmark or '-'}"
    )

    cfg = BacktestConfig(
        profile_id=profile,
        profile=profile_data,
        tickers=tickers,
        start=start,
        top_n=top,
        transaction_cost_bps=float(
            (profile_data.get("return_model") or {}).get("transaction_cost_bps", 15)
        ),
        benchmark=benchmark,
    )
    res = run_backtest(cfg)

    out_path = (
        reports_dir() / f"backtest_{profile}_{start}_top{top}.xlsx"
    )
    res.to_excel(str(out_path))

    table = Table(title="Backtest metrics", show_header=True, header_style="bold")
    table.add_column("metric")
    table.add_column("value")
    for k, v in res.metrics.items():
        table.add_row(str(k), str(v))
    console.print(table)
    if res.notes:
        console.print("[bold]Notes[/bold]")
        for n in res.notes:
            console.print(f"  - {n}")
    console.print(f"\nBacktest workbook: [green]{out_path}[/green]")


@app.command()
def profiles():
    """List available investor profiles."""
    from .config import PROFILES_DIR
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        console.print(f"- {p.stem}")


def _print_data_health(state: AgentState) -> None:
    h = state.data_health or {}
    if not h:
        return
    sev = h.get("severity") or "ok"
    color = {"ok": "green", "warn": "yellow", "critical": "red"}.get(sev, "white")
    avg_a = h.get("avg_agreement")
    agreement_str = "-" if avg_a is None else f"{avg_a*100:.0f}%"
    sources = ",".join(h.get("sources_used") or [])
    console.print(
        f"\n[bold]Data health[/bold]: [{color}]{sev.upper()}[/{color}]  "
        f"fetched {h.get('fetched')}/{h.get('requested')}  "
        f"avg coverage {h.get('avg_coverage', 0)*100:.0f}%  "
        f"agreement {agreement_str}  "
        f"sources={sources}"
    )
    for msg in (h.get("messages") or [])[:3]:
        console.print(f"  - {msg}")


def _print_summary(state: AgentState) -> None:
    if not state.picks:
        console.print("[yellow]No picks produced.[/yellow]")
        return
    table = Table(title="Top picks", show_header=True, header_style="bold")
    table.add_column("rank", justify="right")
    table.add_column("ticker")
    table.add_column("name")
    table.add_column("composite", justify="right")
    table.add_column("fit", justify="right")
    table.add_column("cov", justify="right")
    table.add_column("after-tax", justify="right")
    table.add_column("conf", justify="right")
    for p in state.picks:
        table.add_row(
            str(p.rank),
            p.ticker + (" *" if p.is_cross_currency else ""),
            (p.name or "")[:30],
            f"{p.composite_score:.2f}" if p.composite_score is not None else "-",
            f"{p.profile_fit:.2f}" if p.profile_fit is not None else "-",
            f"{(p.coverage or 0)*100:.0f}%",
            f"{p.expected_after_tax_return*100:+.1f}%"
            if p.expected_after_tax_return is not None
            else "-",
            f"{p.confidence:.2f}",
        )
    console.print(table)
    if any(p.is_cross_currency for p in state.picks):
        console.print(
            "[dim]* indicates a cross-currency pick (FX exposure vs your profile currency)[/dim]"
        )


def main():
    app()


if __name__ == "__main__":
    main()
