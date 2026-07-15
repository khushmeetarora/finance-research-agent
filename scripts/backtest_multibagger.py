"""Phase 4 - GENUINE point-in-time (PIT) event-study backtest of the V2
multibagger screen, powered by the deep free fundamentals source (screener.in).

What changed vs the Phase-3 harness (docs/FRA_V2_BACKTEST_RESULTS.md, "as-run"):
  * The Phase-3 run proved that yfinance's ~4-5y statement window makes ~100% of
    pre-2022 screening dates INDETERMINATE under a strict PIT reading. This
    harness swaps in ``src/data/screener.py`` (~10-12y annual statements) behind
    ``DataProvider.get_financials(as_of=...)`` so pre-run fundamentals are
    actually reconstructable for the more recent cohorts, and reports how many of
    the 136 labelled names screener rescued into DETERMINACY vs the yfinance
    baseline (~0).
  * It scores the FULL labelled dataset (data/multibagger_dataset.csv, 136 rows)
    - winners AND controls/destroyers together - so precision / lift over the
    (curated) base rate can be estimated, not just recall.
  * Ranking uses a POINT-IN-TIME PEER PANEL (audit H-1): each name is ranked only
    against CONTEMPORANEOUS dataset peers (same screening-year cohort) built with
    pre-as_of values, never against today's survivors. (Free data cannot supply
    true historical small/mid-cap index membership, so the dataset cohort is used
    as the contemporaneous panel, with the caveat documented in the results doc.)

Honesty guardrails (unchanged in spirit from the Phase-3 plan sec 6):
  * screener statements are RESTATED (latest-vintage), not as-first-reported, so
    every determinate figure is a "restated-vintage upper bound" even after the
    90-day reporting-lag gate.
  * the dataset is hindsight-selected and survivorship-affected; the base rate
    here is NOT a market base rate. Metrics are archetype diagnostics + a curated
    lift, never a forward probability.

Macro/regime overlay A/B (docs/FRA_V2_MACRO.md, additive + opt-in):
  At EACH name's own PIT as-of date the harness computes a regime from the
  free macro/market series (PIT-gated, no lookahead) and scores the cohort BOTH
  without and with the overlay, so the delta is measurable. The overlay is a
  compositing tilt + a bounded re-rating-pillar boost + advisory context; it
  never changes the veto/quality-gate verdict, so overlay-off reproduces the
  prior (Phase 5) numbers byte-for-byte. News is omitted (GDELT is forward-only
  PIT; see FRA_V2_MACRO.md 5).

Outputs (machine-readable, under data/):
  data/backtest_pit_results.csv             (per-name PIT scorecard == overlay OFF)
  data/backtest_pit_summary.json            (aggregate metrics   == overlay OFF)
  data/backtest_pit_results_overlay_off.csv / _overlay_on.csv
  data/backtest_pit_summary_overlay_off.json / _overlay_on.json
  data/backtest_pit_ab_summary.json         (A/B delta + honest read)

Re-run:  conda run -n fra python -m scripts.backtest_multibagger
Flags:   --limit N   (dev: only first N names)
         --no-screener (yfinance-only baseline, for the determinacy contrast)
         --no-overlay  (skip the regime overlay A/B; overlay-off only)
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from collections import defaultdict
from pathlib import Path

from src.backtest.asof import (
    as_of_financials,
    build_asof_snapshot,
    usable_period_count,
)
from src.data.provider import CompanySnapshot, DataProvider
from src.data import macro_signals as _ms
from src.factors.multibagger import rank_multibagger
from src.factors.regime import build_scorer_overlay, compute_regime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PRICE_CACHE = DATA / "_price_cache"

WINNER_LABELS = {"multibagger_strong", "multibagger"}
STRONG_LABELS = {"multibagger_strong"}

# Tier-C manual governance/fraud facts (free data cannot reconstruct these
# historically). Applied ONLY to the documented destroyers, always attributed as
# "manual" so they are never mistaken for autonomous detection. Verbatim from
# data/value_destroyers.csv red_flag_reason. (Same set as the Phase-3 harness.)
MANUAL_TIER_C: dict[str, dict] = {
    "RCOM.NS": {"auditor_red_flag": True},
    "RELCAPITAL.NS": {"auditor_red_flag": True},
    "DHFL.NS": {"auditor_red_flag": True},
    "VAKRANGEE.NS": {"auditor_red_flag": True},
    "MANPASAND.NS": {"auditor_red_flag": True},
    "GITANJALI.NS": {"auditor_red_flag": True},
    "DISHTV.NS": {"promoter_pledge_pct": 88.0},
}

FINANCIAL_NA_VETOES = ("RF1", "RF2", "RF3", "RF4", "RF5")


# --------------------------------------------------------------------------
# Price cache (offline, adjusted) - reused from the dataset builder.
# --------------------------------------------------------------------------
def load_price_series(yahoo_symbol: str) -> list[tuple[_dt.date, float]]:
    path = PRICE_CACHE / f"{yahoo_symbol}.csv"
    if not path.exists():
        return []
    rows: list[tuple[_dt.date, float]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if len(r) < 2:
                continue
            try:
                d = _dt.datetime.strptime(r[0], "%Y-%m-%d").date()
                c = float(r[1])
            except (ValueError, TypeError):
                continue
            if c > 0:
                rows.append((d, c))
    return rows


def price_on_or_before(series, target: _dt.date):
    best = None
    for d, c in series:
        if d <= target:
            best = c
        else:
            break
    return best


def momentum_as_of(series, asof: _dt.date):
    closes = [c for d, c in series if d <= asof]
    m12 = m6 = None
    if len(closes) >= 252 + 21:
        past, recent = closes[-(252 + 21)], closes[-21]
        if past > 0:
            m12 = recent / past - 1.0
    if len(closes) >= 126 + 21:
        past6, recent = closes[-(126 + 21)], closes[-21]
        if past6 > 0:
            m6 = recent / past6 - 1.0
    return m12, m6


# --------------------------------------------------------------------------
# Verdict logic (absolute quality gate; identical thresholds to Phase 3 so the
# two runs are comparable). Percentile composite is reported as context.
# --------------------------------------------------------------------------
def quality_gate(snap: CompanySnapshot) -> tuple[bool, bool, list[str]]:
    notes: list[str] = []
    if snap.is_financial:
        roe = snap.roe_series[-1] if snap.roe_series else snap.roe
        if roe is None or len(snap.roe_series) < 2:
            return False, False, ["financial: insufficient ROE history"]
        roe_ok = roe >= 0.14
        growth_ok = snap.earnings_cagr is None or snap.earnings_cagr > 0
        notes.append(f"ROE={roe:.2f}({'ok' if roe_ok else 'lo'})")
        return True, bool(roe_ok and growth_ok), notes
    if snap.roce is None or len(snap.roce_series) < 2:
        return False, False, ["non-fin: insufficient ROCE history"]
    roce_ok = snap.roce >= 0.15
    notes.append(f"ROCE={snap.roce:.2f}({'ok' if roce_ok else 'lo'})")
    fcf_ok = snap.fcf_posrate is not None and snap.fcf_posrate >= 0.6
    cash_ok = snap.ocf_to_np_multiyear is not None and snap.ocf_to_np_multiyear >= 0.8
    if snap.fcf_posrate is not None:
        notes.append(f"fcf+={snap.fcf_posrate:.2f}")
    if snap.ocf_to_np_multiyear is not None:
        notes.append(f"CFO/NP={snap.ocf_to_np_multiyear:.2f}")
    return True, bool(roce_ok and (fcf_ok or cash_ok)), notes


def applicable_vetoes(snap, report) -> list[str]:
    vetoes = list(report.vetoes) if report is not None else []
    if snap.is_financial:
        vetoes = [v for v in vetoes if not any(v.startswith(c) for c in FINANCIAL_NA_VETOES)]
    return vetoes


def classify(snap, report) -> tuple[str, str]:
    """PASS/FAIL/INDETERMINATE. PASS == the screen would surface it (no veto,
    clears the absolute quality gate)."""
    vetoes = applicable_vetoes(snap, report)
    if vetoes:
        return "FAIL", "vetoed: " + "; ".join(vetoes)
    determinate, passed, notes = quality_gate(snap)
    if not determinate:
        return "INDETERMINATE", "; ".join(notes)
    return ("PASS" if passed else "FAIL"), "; ".join(notes)


# --------------------------------------------------------------------------
# Dataset load + PIT snapshot construction.
# --------------------------------------------------------------------------
def load_dataset() -> list[dict]:
    with open(DATA / "multibagger_dataset.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_pit_snapshot(dp, row, asof, series, *, prefer_deep):
    """Return (snap, fin_gated, source). Purely offline except the (cached)
    screener fetch inside get_financials."""
    sym = row["yahoo_symbol"].strip()
    fin = dp.get_financials(sym, as_of=asof, prefer_deep=prefer_deep)
    source = fin.get("source", "yfinance")
    asof_price = price_on_or_before(series, asof)
    asof_eps = None
    eps = (fin.get("income", {}) or {}).get("Diluted EPS") or (
        fin.get("income", {}) or {}
    ).get("Basic EPS")
    if eps:
        for v in reversed(eps):
            if v is not None:
                asof_eps = v
                break
    m12, m6 = momentum_as_of(series, asof)
    manual = MANUAL_TIER_C.get(sym)
    base = CompanySnapshot(ticker=sym, name=row.get("company"), sector=row.get("sector"))
    snap = build_asof_snapshot(
        base, fin, asof_price=asof_price, asof_eps=asof_eps,
        momentum_12_1=m12, momentum_6_1=m6, manual=manual,
    )
    return snap, fin, source


# --------------------------------------------------------------------------
# Main run.
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="dev: only first N rows")
    ap.add_argument("--no-screener", action="store_true",
                    help="yfinance-only baseline (determinacy contrast)")
    ap.add_argument("--no-overlay", action="store_true",
                    help="skip the macro/regime overlay A/B (overlay-off only)")
    args = ap.parse_args()

    prefer_deep = not args.no_screener
    dp = DataProvider(use_stooq=False)
    rows = load_dataset()
    if args.limit:
        rows = rows[: args.limit]

    print(f"Building PIT snapshots for {len(rows)} labelled names "
          f"(deep source: {'screener.in' if prefer_deep else 'OFF (yfinance only)'}) ...",
          flush=True)

    prepared = []
    for i, row in enumerate(rows, 1):
        sym = row["yahoo_symbol"].strip()
        try:
            asof = _dt.date.fromisoformat(row["entry_date"].strip())
        except ValueError:
            asof = _dt.date(int(row["entry_date"][:4]), 1, 1)
        series = load_price_series(sym)
        print(f"  [{i}/{len(rows)}] {sym} @ {asof} ...", flush=True)
        try:
            snap, fin, source = build_pit_snapshot(dp, row, asof, series, prefer_deep=prefer_deep)
        except Exception as e:  # never let one name kill the run
            print(f"      ! error {e}", flush=True)
            snap = CompanySnapshot(ticker=sym, name=row.get("company"), sector=row.get("sector"))
            fin, source = {"status": "failed"}, "error"
        # yfinance-only baseline determinacy for the contrast headline. screener
        # strictly dominates yfinance in statement depth, so we only need to probe
        # yfinance where screener made the name determinate (to confirm the
        # rescue was real); elsewhere yfinance cannot do better than screener.
        yf_periods = 0
        det_screener = usable_period_count(fin) >= 2
        if det_screener and not args.no_screener:
            try:
                yf_fin = dp.get_financials(sym, as_of=asof, prefer_deep=False)
                yf_periods = usable_period_count(yf_fin)
            except Exception:
                yf_periods = 0
        prepared.append(dict(
            row=row, sym=sym, asof=asof, snap=snap, fin=fin, source=source,
            usable_periods=usable_period_count(fin), yf_periods=yf_periods,
            cohort=asof.year,
        ))

    # ---- PIT macro/regime overlays (opt-in A/B). Computed at EACH name's OWN
    # as-of date (no lookahead: compute_regime PIT-gates every macro/market
    # series through as_of_series with its publication lag). News is
    # deliberately omitted here (GDELT's shared feed is forward-only PIT; see
    # docs/FRA_V2_MACRO.md 5), so the boost is the fully-reproducible easing +
    # sector-tailwind component. Regimes are cached per (as_of, sector). ----
    if not args.no_overlay:
        provider = _ms.default_series_provider()
        reg_cache: dict[tuple, dict] = {}
        for it in prepared:
            asof, sector = it["asof"], it["row"].get("sector")
            key = (asof.isoformat(), sector or "")
            if key not in reg_cache:
                try:
                    reg = compute_regime(asof, sector=sector, series_provider=provider)
                    reg_cache[key] = build_scorer_overlay(reg)
                except Exception as e:
                    print(f"      ! regime error {asof} {sector}: {e}", flush=True)
                    reg_cache[key] = None
            it["overlay"] = reg_cache[key]
        n_active = sum(
            1 for it in prepared
            if it.get("overlay") and it["overlay"].get("regime_label") not in (None, "unknown")
        )
        print(f"Regime overlays computed for {len(reg_cache)} (as_of,sector) keys; "
              f"{n_active}/{len(prepared)} names have a non-unknown regime.", flush=True)

    # ---- A/B: rank BOTH without and with the regime overlay so the delta is
    # measurable. Overlay-off reproduces the prior (Phase 5) numbers exactly. ----
    assign_reports(prepared, use_overlay=False, key="report_off")
    if not args.no_overlay:
        assign_reports(prepared, use_overlay=True, key="report_on")

    results_off = [build_result_row(it, it.get("report_off")) for it in prepared]
    _write_csv(DATA / "backtest_pit_results.csv", results_off)
    _write_csv(DATA / "backtest_pit_results_overlay_off.csv", results_off)
    summary_off = aggregate(results_off)
    with open(DATA / "backtest_pit_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_off, f, indent=2)
    with open(DATA / "backtest_pit_summary_overlay_off.json", "w", encoding="utf-8") as f:
        json.dump(summary_off, f, indent=2)

    print("\n============ PIT SUMMARY (overlay OFF) ============")
    print(json.dumps(summary_off, indent=2))

    if not args.no_overlay:
        results_on = [
            build_result_row(it, it.get("report_on"), overlay=it.get("overlay"))
            for it in prepared
        ]
        _write_csv(DATA / "backtest_pit_results_overlay_on.csv", results_on)
        summary_on = aggregate(results_on)
        with open(DATA / "backtest_pit_summary_overlay_on.json", "w", encoding="utf-8") as f:
            json.dump(summary_on, f, indent=2)
        ab = ab_delta(summary_off, summary_on, results_off, results_on)
        with open(DATA / "backtest_pit_ab_summary.json", "w", encoding="utf-8") as f:
            json.dump(ab, f, indent=2)
        print("\n============ PIT SUMMARY (overlay ON) ============")
        print(json.dumps(summary_on, indent=2))
        print("\n================ A/B DELTA ================")
        print(json.dumps(ab, indent=2))
        print("\nWrote:\n  data/backtest_pit_results.csv (== overlay_off)"
              "\n  data/backtest_pit_results_overlay_off.csv"
              "\n  data/backtest_pit_results_overlay_on.csv"
              "\n  data/backtest_pit_summary.json (== overlay_off)"
              "\n  data/backtest_pit_summary_overlay_off.json"
              "\n  data/backtest_pit_summary_overlay_on.json"
              "\n  data/backtest_pit_ab_summary.json")
    else:
        print("\nWrote:\n  data/backtest_pit_results.csv\n  data/backtest_pit_summary.json"
              " (overlay A/B skipped: --no-overlay)")
    return 0


def assign_reports(prepared: list[dict], *, use_overlay: bool, key: str) -> None:
    """Rank each name only against same-cohort peers (PIT peer panel) and stash
    its FactorReport under ``it[key]``. With ``use_overlay`` the per-name macro
    overlay (``it['overlay']``) is threaded via ``overlay_by_ticker``; the
    cross-sectional percentiles are identical to the off run (overlay only
    re-weights the composite + boosts the re-rating pillar + annotates context),
    so overlay-off is byte-for-byte the prior behaviour."""
    by_cohort: dict[int, list] = defaultdict(list)
    for item in prepared:
        by_cohort[item["cohort"]].append(item)
    for cohort, items in by_cohort.items():
        snaps = [it["snap"] for it in items]
        ov_by_ticker = None
        if use_overlay:
            ov_by_ticker = {
                it["sym"]: it["overlay"] for it in items if it.get("overlay")
            }
        cohort_reports = rank_multibagger(
            snaps, sector_relative=True, apply_vetoes=True,
            overlay_by_ticker=ov_by_ticker,
        )
        # rank_multibagger sorts; map back by ticker (unique within a cohort row
        # set - Titan appears twice across cohorts but not the same year).
        rep_by_ticker: dict[str, list] = defaultdict(list)
        for r in cohort_reports:
            rep_by_ticker[r.ticker].append(r)
        for it in items:
            lst = rep_by_ticker.get(it["sym"])
            it[key] = lst.pop(0) if lst else None


def build_result_row(it: dict, rep, *, overlay: dict | None = None) -> dict:
    """One per-name result row. ``overlay`` (on-run only) adds regime attribution
    columns; verdict/vetoes are unchanged by the overlay (context, never a kill)."""
    row, snap = it["row"], it["snap"]
    label = row.get("label", "")
    is_winner = label in WINNER_LABELS
    verdict, detail = classify(snap, rep)
    det, _passed, _ = quality_gate(snap)
    vetoes = applicable_vetoes(snap, rep)
    ctx = (rep.regime_context if rep is not None else {}) or {}
    out = {
        "ticker": it["sym"],
        "company": row.get("company", ""),
        "sector": row.get("sector", ""),
        "entry_date": row.get("entry_date", ""),
        "cohort": it["cohort"],
        "label": label,
        "is_winner": is_winner,
        "peak_mult_5y": row.get("peak_mult_5y", ""),
        "mult_5y": row.get("mult_5y", ""),
        "source": it["source"],
        "usable_periods_screener": it["usable_periods"],
        "usable_periods_yfinance": it["yf_periods"],
        "determinate": det,
        "rescued_by_screener": bool(det and it["yf_periods"] < 2),
        "verdict": verdict,
        "composite": round(rep.composite_score, 4) if rep and rep.composite_score is not None else None,
        "vetoes": "; ".join(vetoes),
        "soft_flags": "; ".join(rep.soft_flags) if rep else "",
        "is_financial": snap.is_financial,
        "roce": round(snap.roce, 3) if snap.roce is not None else None,
        "roe_latest": round(snap.roe_series[-1], 3) if snap.roe_series else None,
        "altman_z": round(snap.altman_z, 2) if snap.altman_z is not None else None,
        "fcf_posrate": snap.fcf_posrate,
        "ocf_np": round(snap.ocf_to_np_multiyear, 2) if snap.ocf_to_np_multiyear is not None else None,
        "earnings_cagr": round(snap.earnings_cagr, 3) if snap.earnings_cagr is not None else None,
        "detail": detail,
    }
    if overlay is not None:
        out["regime_label"] = overlay.get("regime_label")
        out["rerating_boost"] = round(float(overlay.get("rerating_boost", 0.0) or 0.0), 4)
        out["regime_cautions"] = ";".join(ctx.get("cautions", []) or [])
    return out


def ab_delta(summary_off: dict, summary_on: dict, results_off: list[dict],
             results_on: list[dict]) -> dict:
    """Compact A/B comparison: which verdict-level metrics are (by design)
    unchanged, and how the composite ranking moved."""
    so = summary_off["separation_on_determinate"]
    sn = summary_on["separation_on_determinate"]
    off_by = {r["ticker"] + "|" + str(r["cohort"]): r for r in results_off}
    verdict_changes = 0
    composite_changes = 0
    for r in results_on:
        k = r["ticker"] + "|" + str(r["cohort"])
        o = off_by.get(k)
        if o is None:
            continue
        if o["verdict"] != r["verdict"]:
            verdict_changes += 1
        if (o["composite"] or 0) != (r["composite"] or 0):
            composite_changes += 1
    return {
        "determinacy_unchanged": (
            summary_off["determinacy"]["determinate_screener"]
            == summary_on["determinacy"]["determinate_screener"]
        ),
        "verdict_changes_off_to_on": verdict_changes,
        "composite_changes_off_to_on": composite_changes,
        "separation_off": {
            "base_rate": so["curated_base_rate"], "precision": so["screen_precision"],
            "recall": so["screen_recall"], "lift": so["lift_over_base_rate"],
            "control_rejection": so["control_rejection_rate"],
        },
        "separation_on": {
            "base_rate": sn["curated_base_rate"], "precision": sn["screen_precision"],
            "recall": sn["screen_recall"], "lift": sn["lift_over_base_rate"],
            "control_rejection": sn["control_rejection_rate"],
        },
        "quintile_hit_rates_off": [b["hit_rate"] for b in summary_off["composite_quintile_hit_rates"]],
        "quintile_hit_rates_on": [b["hit_rate"] for b in summary_on["composite_quintile_hit_rates"]],
        "note": (
            "The screen VERDICT (PASS/FAIL) is a veto + absolute-quality-gate "
            "decision that does NOT read the composite, and the overlay is "
            "context/tilt only (never a veto), so base-rate / precision / recall "
            "/ lift / control-rejection are unchanged BY DESIGN. The overlay can "
            "only move the composite-based quintile ordering (and add advisory "
            "regime context). Honest read: on this tiny determinate sample the "
            "overlay does not change any verdict; treat quintile shifts as noise "
            "at n<=51, not evidence of edge."
        ),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _rate(num, den):
    return round(num / den, 3) if den else None


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    determinate = [r for r in results if r["determinate"]]
    indet = [r for r in results if not r["determinate"]]
    winners = [r for r in results if r["is_winner"]]
    det_winners = [r for r in determinate if r["is_winner"]]
    det_losers = [r for r in determinate if not r["is_winner"]]

    # Determinacy rescue (screener vs yfinance).
    rescued = [r for r in results if r["rescued_by_screener"]]
    yf_determinate = [r for r in results if r["usable_periods_yfinance"] >= 2]

    # Verdict-based classifier on the DETERMINATE set.
    flagged = [r for r in determinate if r["verdict"] == "PASS"]
    flagged_winners = [r for r in flagged if r["is_winner"]]
    base_rate = _rate(len(det_winners), len(determinate))
    precision = _rate(len(flagged_winners), len(flagged))
    recall = _rate(len(flagged_winners), len(det_winners))
    lift = round(precision / base_rate, 2) if (precision and base_rate) else None

    # Destroyer/control rejection: of determinate non-winners, how many the
    # screen correctly did NOT pass (FAIL, incl. vetoed).
    rejected_losers = [r for r in det_losers if r["verdict"] == "FAIL"]

    # Decile (quintile - n is small) hit-rates on composite among determinate.
    scored = [r for r in determinate if r["composite"] is not None]
    scored.sort(key=lambda r: r["composite"], reverse=True)
    buckets = _quantile_hit_rates(scored, q=5)

    # Veto attribution: which veto fired on winners (false pos) vs losers.
    veto_attr: dict[str, dict] = defaultdict(lambda: {"losers": 0, "winners": 0})
    for r in determinate:
        for v in [x.strip() for x in r["vetoes"].split(";") if x.strip()]:
            code = v.split()[0]
            veto_attr[code]["winners" if r["is_winner"] else "losers"] += 1

    return {
        "n_total": n,
        "counts_by_label": _count_by(results, "label"),
        "determinacy": {
            "determinate_screener": len(determinate),
            "indeterminate_screener": len(indet),
            "determinate_rate": _rate(len(determinate), n),
            "determinate_yfinance_baseline": len(yf_determinate),
            "rescued_by_screener": len(rescued),
            "note": (
                "screener.in rescued names into PIT-determinacy that yfinance's "
                "~4-5y window could not; determinacy is bounded to ~entry-year "
                ">=2017 because screener free depth reaches ~FY2015 for March-end "
                "filers."
            ),
        },
        "separation_on_determinate": {
            "n_determinate": len(determinate),
            "n_winners_determinate": len(det_winners),
            "curated_base_rate": base_rate,
            "screen_precision": precision,
            "screen_recall": recall,
            "lift_over_base_rate": lift,
            "flagged": len(flagged),
            "flagged_winners": len(flagged_winners),
            "control_rejection_rate": _rate(len(rejected_losers), len(det_losers)),
            "n_controls_determinate": len(det_losers),
        },
        "composite_quintile_hit_rates": buckets,
        "veto_attribution_determinate": {k: dict(v) for k, v in sorted(veto_attr.items())},
        "caveats": [
            "Hindsight-selected, survivorship-affected dataset: the base rate is "
            "NOT a market base rate; precision/lift are curated-set diagnostics.",
            "screener statements are restated (latest-vintage), not "
            "as-first-reported: a restated-vintage upper bound even after the "
            "90-day reporting-lag gate.",
            "PIT peer panel = same-year dataset cohort (free data lacks true "
            "historical small/mid-cap index membership).",
            "Do NOT convert recall/precision here into a forward probability.",
        ],
    }


def _count_by(rows, key):
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        out[str(r[key])] += 1
    return dict(sorted(out.items()))


def _quantile_hit_rates(scored, q=5):
    if not scored:
        return []
    out = []
    n = len(scored)
    size = max(1, n // q)
    for i in range(0, n, size):
        chunk = scored[i : i + size]
        if not chunk:
            continue
        wins = sum(1 for r in chunk if r["is_winner"])
        out.append({
            "quantile_from_top": len(out) + 1,
            "n": len(chunk),
            "winners": wins,
            "hit_rate": _rate(wins, len(chunk)),
            "composite_range": [round(chunk[-1]["composite"], 3), round(chunk[0]["composite"], 3)],
        })
    return out


if __name__ == "__main__":
    sys.exit(main())
