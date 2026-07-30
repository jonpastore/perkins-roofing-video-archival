#!/usr/bin/env python3
"""Does ONE day model with a constant productivity reproduce Tim's per-square table?

Testing the claim "per-square is just the day model at a fixed sq/day, so ship one model with one
knob." Three checks, in order of how much they matter:

  1. ALGEBRA — if days are proportional to squares (days = SQ / p, no intercept), the day model
     collapses to a constant $/sq and CAN be made to equal his table exactly. Verified per job.
  2. THE SHIPPED MODEL — our derive_daily_series is `setup + rate x SQ`, i.e. it has an
     INTERCEPT, and the geometry variant adds cut-length terms. Neither is proportional, so the
     implied $/sq is a function of job size. Measured across 10-80 SQ.
  3. WHAT IT BUYS — a day model tuned to reproduce the per-square table reproduces the per-square
     table's ERRORS against Tim's charged prices, exactly. Measured on the 35 priced jobs.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/prove_persq_day_equivalence.py
"""
from __future__ import annotations

import json
import os
import statistics as st
from pathlib import Path

from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, derive_daily_series, estimate
from core.pricing_config import load_config

PRICES = Path.home() / "perkins-corpus/tim30_with_actual_prices.json"
MATERIALS = {"tile": ("13_tile", "tile"), "shingle": ("dimensional_shingle", "shingle"),
             "metal": ("standing_seam_metal", "metal")}


def _oh(result: dict) -> float:
    return next(li["amount"] for li in result["line_items_detail"] if li["key"] == "overhead")


def _half(x: float) -> float:
    """The half-day grid DailyOverheadSeries enforces."""
    return max(0.5, round(x * 2) / 2)


def _flat_days() -> dict[str, float]:
    """Tim's 'Flat (days) - if existing' column, so the day counts match the other scripts."""
    import openpyxl
    xlsx = Path.home() / "perkins-corpus/roofr-attachments" / (
        "2026-07-24__Re_TIME_LEARNING_Overhead_for_AI_Systems__"
        "Residential_OH_Calculator_SLOPED_ONLY_.xlsx")
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Sheet1"]
    return {str(r[0]).strip().lower(): float(r[11] or 0)
            for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]}


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar())
    rates = cfg.daily_overhead_rates()
    # Every day model below must run on the SERIES basis — the live config is basis="branch" with
    # a flat $1,400/day, which is a different model and would silently mislabel the results.
    cfg_series = load_config({**cfg.raw, "overhead_basis": "series"})
    homes = json.loads(PRICES.read_text())
    flat_days = _flat_days()

    print("=" * 78)
    print("1. ALGEBRA — days proportional to squares")
    print("=" * 78)
    print("   OH = 1050 x demo_days + rate x install_days,  demo_days = SQ/p_d, install = SQ/p_i")
    print("      => OH = SQ x (1050/p_d + rate/p_i)   which IS a constant $/sq. Solve for p_i")
    print("      holding p_d at his own median demo productivity:\n")
    solved = {}
    for mat, (roof_type, series) in MATERIALS.items():
        oh_sq = float(cfg.sloped_overhead("FBC", roof_type))
        rate = float(rates[series])
        # his own median demo productivity on the homes that carry this material
        p_d = st.median([float(h["sloped_sq"]) / float(h["demo"]) for h in homes
                         if h.get(f"price_{mat}") and h.get("demo")])
        residual = oh_sq - 1050.0 / p_d
        if residual <= 0:
            print(f"   {mat:8} demo alone at {p_d:.1f} sq/day already exceeds his ${oh_sq:.0f}/sq"
                  f" — no p_i exists")
            continue
        p_i = rate / residual
        solved[mat] = (p_d, p_i)
        print(f"   {mat:8} ${oh_sq:>5.0f}/sq = 1050/{p_d:.2f} + {rate:.0f}/{p_i:.2f}"
              f"   -> install {p_i:.2f} sq/day")
    print("\n   check on every priced job (SQ x k vs his table, both in dollars):")
    worst = 0.0
    for mat, (roof_type, series) in MATERIALS.items():
        if mat not in solved:
            continue
        p_d, p_i = solved[mat]
        oh_sq = float(cfg.sloped_overhead("FBC", roof_type))
        for h in homes:
            if not h.get(f"price_{mat}"):
                continue
            sq = float(h["sloped_sq"])
            day_oh = 1050.0 * (sq / p_d) + float(rates[series]) * (sq / p_i)
            worst = max(worst, abs(day_oh / (oh_sq * sq) - 1))
    print(f"   worst deviation across all priced jobs: {100 * worst:.4f}%"
          f"   -> the collapse is EXACT, as algebra requires")

    print()
    print("=" * 78)
    print("2. THE SHIPPED DAY MODEL IS NOT PROPORTIONAL — it has an intercept")
    print("=" * 78)
    model = cfg.daily_overhead_day_model()
    print("   fits:", json.dumps(model.get("series")))
    print("   so days = setup + rate x SQ, and OH/sq = (setup x r)/SQ + r x rate is a CURVE.\n")
    print(f"   {'roof':10}" + "".join(f"{s:>9} SQ" for s in (10, 20, 30, 45, 60, 80)) +
          f"{'his table':>12}{'spread':>9}")
    for mat, (roof_type, _series) in MATERIALS.items():
        oh_sq = float(cfg.sloped_overhead("FBC", roof_type))
        cells, vals = [], []
        for sq in (10, 20, 30, 45, 60, 80):
            q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type=roof_type,
                           num_squares=float(sq), project_kind="residential", demo=True,
                           existing_roof="tile", overhead_mode="daily",
                           daily_series=derive_daily_series(cfg_series, QuoteInput(
                               code_zone="FBC", slope_type="sloped", roof_type=roof_type,
                               num_squares=float(sq), project_kind="residential", demo=True,
                               existing_roof="tile")))
            per_sq = _oh(estimate(cfg_series, q)) / sq
            vals.append(per_sq)
            cells.append(f"{per_sq:>12,.0f}")
        print(f"   {mat:10}" + "".join(cells) + f"{oh_sq:>12,.0f}"
              f"{100 * (max(vals) / min(vals) - 1):>8.0f}%")
    print("\n   A single constant $/sq cannot equal that curve at more than one size. The claim")
    print("   'set sq_per_day and it reproduces his table exactly' holds ONLY if the intercepts")
    print("   are dropped — which is a different day model from the one that ships.")

    print()
    print("=" * 78)
    print("2b. AND DAYS ARE QUANTISED TO THE HALF DAY")
    print("=" * 78)
    print("   DailyOverheadSeries rejects anything that is not a multiple of 0.5, so SQ/p cannot")
    print("   even be EXPRESSED unless it lands on a half day. Rounding it re-breaks the collapse:")
    print(f"\n   {'roof':10}{'SQ':>6}{'exact days':>12}{'rounded':>9}{'$/sq rounded':>14}"
          f"{'his table':>11}{'error':>9}")
    for mat, (roof_type, series) in MATERIALS.items():
        if mat not in solved:
            continue
        p_d, p_i = solved[mat]
        oh_sq = float(cfg.sloped_overhead("FBC", roof_type))
        for sq in (17.0, 25.0, 35.0, 52.0):
            exact = sq / p_d + sq / p_i
            dd, di = _half(sq / p_d), _half(sq / p_i)
            got = (1050.0 * dd + float(rates[series]) * di) / sq
            print(f"   {mat:10}{sq:>6.0f}{exact:>12.2f}{dd + di:>9.1f}{got:>14,.0f}"
                  f"{oh_sq:>11,.0f}{100 * (got / oh_sq - 1):>8.1f}%")

    print()
    print("=" * 78)
    print("3. WHAT THE UNIFICATION BUYS — nothing, by construction")
    print("=" * 78)
    rows = []
    for h in homes:
        sq = float(h["sloped_sq"])
        for mat, (roof_type, series) in MATERIALS.items():
            charged = h.get(f"price_{mat}")
            if not charged or not h.get(mat) or mat not in solved:
                continue
            p_d, p_i = solved[mat]
            fd = flat_days.get(str(h["address"]).strip().lower(), 0.0)
            base = dict(code_zone="FBC", county="palm_beach", slope_type="sloped",
                        roof_type=roof_type, num_squares=sq, flat_squares=float(h["flat_sq"] or 0),
                        project_kind="residential", demo=True, existing_roof=h["existing"],
                        roof_height={1: "1_story", 2: "2_stories", 3: "3_5_stories"}.get(
                            int(h.get("stories") or 1), "1_story"),
                        pitch_primary=float(h["pitch"]) if h.get("pitch") else None,
                        pitch_7_12=bool(h.get("pitch") and float(h["pitch"]) >= 7))
            a = estimate(cfg, QuoteInput(**base, overhead_mode="per_sq"))
            # the "one model" tuned to reproduce his table: days = SQ/p, no intercept
            unified = estimate(cfg_series, QuoteInput(**base, overhead_mode="daily", daily_series=[
                DailyOverheadSeries(series="demo_dry_in_flat", days=_half(sq / p_d)),
                DailyOverheadSeries(series=series, days=_half(sq / p_i))]))
            # his OWN days — the time model
            tim = estimate(cfg_series, QuoteInput(**base, overhead_mode="daily", daily_series=[
                DailyOverheadSeries(series="demo_dry_in_flat", days=_half(float(h["demo"]) + fd)),
                DailyOverheadSeries(series=series, days=_half(float(h[mat])))]))
            rows.append({
                "sq_per_day": sq / (float(h["demo"]) + float(h[mat])),
                "per_sq": a["project_total"] / float(charged) - 1,
                "unified": unified["project_total"] / float(charged) - 1,
                "tim_days": tim["project_total"] / float(charged) - 1,
            })

    def line(label: str, key: str, subset=None) -> None:
        e = [r[key] for r in (subset if subset is not None else rows)]
        print(f"   {label:<34}{sum(1 for x in e if abs(x) <= 0.05):>3}/{len(e):<4}within 5%"
              f"   median {100 * st.median(e):>+6.1f}%   median abs "
              f"{100 * st.median([abs(x) for x in e]):>5.1f}%")

    print(f"   {len(rows)} priced jobs\n")
    line("A per-square (his table)", "per_sq")
    line("U 'one model' at constant sq/day", "unified")
    line("C day model on HIS days", "tim_days")
    slow = [r for r in rows if r["sq_per_day"] < 4]
    print(f"\n   the {len(slow)} slow jobs (<4 sq/day) — the ones per-square gets wrong:")
    line("A per-square", "per_sq", slow)
    line("U 'one model'", "unified", slow)
    line("C day model on HIS days", "tim_days", slow)
    print("\n   The unified model tracks per-square, not the time model, because a constant")
    print("   productivity IS the per-square assumption. Making days vary with the job is what")
    print("   makes the day model different — and then it is a second model, not one knob.")


if __name__ == "__main__":
    main()
