#!/usr/bin/env python3
"""PER-SQUARE vs PER-DAY overhead, scored against the prices Tim actually charged.

Jon, 2026-07-30: "some jobs are accurate at the cost per sq and some jobs are accurate at the
cost per day ... show how many are accurate under both models and what the divergence is to make
one model accurate and another not. maybe we can identify inputs of when we should switch."

Ground truth: `~/perkins-corpus/tim30_with_actual_prices.json` — Tim's 30 homes (TIME LEARNING
email, 2026-07-24) with his own day estimates AND the price he charged, per material. A home can
carry two or three priced options (he quoted tile and metal on the same roof), and each priced
option is one observation.

Four models, identical in every other input (profit_mode="scale", the API default), so the ONLY
thing that moves is the overhead line:

  A  per_sq        Tim's published $/sq overhead table (config sloped_overhead[zone][roof_type]).
                   Already verified to reproduce all four sheet quadrants at 0.0%, so this is a
                   test of the MODEL, not of the numbers in it.
  B  day-branch    his days x the branch's flat daily burn (the live basis, $1,400/day)
  C  day-series    his days x his four emailed per-day-by-roof-type rates
                   (tile 745 / shingle 700 / metal 850 / demo-dry-in-flat 1,050)
  D  day-branch@1470  same as B at the $1,470/day he stated on 2026-07-30

Days come from TIM'S OWN columns, never derived, so a day-model error cannot be blamed on our
geometry fit. Flat squares are quoted with the roof and their flat days are charged to the
demo/dry-in/flat series, because his charged price covers the whole roof.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/compare_oh_models_vs_tim_prices.py
"""
from __future__ import annotations

import json
import os
import statistics as st
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import openpyxl
from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.pricing_config import load_config

PRICES = Path.home() / "perkins-corpus/tim30_with_actual_prices.json"
XLSX = Path.home() / "perkins-corpus/roofr-attachments" / (
    "2026-07-24__Re_TIME_LEARNING_Overhead_for_AI_Systems__Residential_OH_Calculator_SLOPED_ONLY_.xlsx")

MATERIALS = {                       # json key -> (roof_type, day column, install series)
    "tile": ("13_tile", "tile", "tile"),
    "shingle": ("dimensional_shingle", "shingle", "shingle"),
    "metal": ("standing_seam_metal", "metal", "metal"),
}
STORIES = {1: "1_story", 2: "2_stories", 3: "3_5_stories"}
ACCURATE = 0.05                     # |quote/charged - 1| within 5% = "accurate"


def _flat_days() -> dict[str, float]:
    """Tim's 'Flat (days) - if existing' column, which the json extract dropped."""
    ws = openpyxl.load_workbook(XLSX, data_only=True)["Sheet1"]
    out = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r and r[0]:
            out[str(r[0]).strip().lower()] = float(r[11] or 0)
    return out


def _half(x: float) -> float:
    return max(0.5, round(x * 2) / 2)


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar())

    homes = json.loads(PRICES.read_text())
    flat_days = _flat_days()
    series_rates = cfg.daily_overhead_rates()

    rows = []
    for h in homes:
        sq, flat_sq = float(h["sloped_sq"]), float(h["flat_sq"] or 0)
        if sq <= 0:
            continue
        fd = flat_days.get(str(h["address"]).strip().lower(), 0.0)
        for mat, (roof_type, day_col, install) in MATERIALS.items():
            charged = h.get(f"price_{mat}")
            if not charged or not h.get(day_col):
                continue
            days = {"demo_dry_in_flat": _half(float(h["demo"]) + fd),
                    install: _half(float(h[day_col]))}
            base = QuoteInput(
                code_zone="FBC", county="palm_beach", slope_type="sloped", roof_type=roof_type,
                num_squares=sq, flat_squares=flat_sq, project_kind="residential",
                demo=True, existing_roof=h["existing"],
                roof_height=STORIES.get(int(h.get("stories") or 1), "1_story"),
                pitch_primary=float(h["pitch"]) if h.get("pitch") else None,
                pitch_7_12=bool(h.get("pitch") and float(h["pitch"]) >= 7),
            )
            ds = [DailyOverheadSeries(series=k, days=v) for k, v in days.items() if v]
            total_days = sum(v for v in days.values())

            quotes = {"A per_sq": estimate(cfg, replace(base, overhead_mode="per_sq"))}
            # B/D: flat branch burn. C: his four per-day-by-roof-type rates. E/F/G: the model his
            # OWN Jupiter tab uses — (office / men) x crew size — with his tab's crew sizes (3 on
            # every install, 5 on demo/dry-in) and three readings of the per-man-day number:
            #   $200 = 1,400/7, the basis printed on his tab
            #   $210 = 1,470/7, his current stated burn over the same 7 men
            #   $238 = 1,470/6.17, his current burn over his LOGGED average headcount
            # The engine reads the basis off the config, so swap it per model rather than
            # hand-rolling the arithmetic.
            def _crew_rates(per_man: float) -> dict:
                return {"tile": 3 * per_man, "shingle": 3 * per_man, "metal": 3 * per_man,
                        "demo_dry_in_flat": 5 * per_man}
            for label, patch in (
                ("B day-branch", {"overhead_basis": "branch", "office_daily_overhead": 1400}),
                ("C day-series", {"overhead_basis": "series"}),
                ("D day-1470", {"overhead_basis": "branch", "office_daily_overhead": 1470}),
                ("E crew@200", {"overhead_basis": "series",
                                "daily_overhead_rates": _crew_rates(200.0)}),
                ("F crew@210", {"overhead_basis": "series",
                                "daily_overhead_rates": _crew_rates(210.0)}),
                ("G crew@238", {"overhead_basis": "series",
                                "daily_overhead_rates": _crew_rates(238.25)}),
            ):
                cfg_v = load_config({**cfg.raw, **patch})
                quotes[label] = estimate(cfg_v, replace(base, overhead_mode="daily", daily_series=ds))

            rows.append({
                "address": h["address"], "mat": mat, "sq": sq, "flat_sq": flat_sq,
                "pitch": h.get("pitch"), "stories": h.get("stories"),
                "access": bool(h.get("access_issue")), "days": total_days,
                "sq_per_day": sq / total_days if total_days else 0,
                "charged": float(charged),
                "err": {k: v["project_total"] / float(charged) - 1 for k, v in quotes.items()},
                "oh": {k: next(li["amount"] for li in v["line_items_detail"] if li["key"] == "overhead")
                       for k, v in quotes.items()},
            })

    models = ["A per_sq", "B day-branch", "C day-series", "D day-1470",
              "E crew@200", "F crew@210", "G crew@238"]
    print(f"{len(rows)} priced observations across {len({r['address'] for r in rows})} homes"
          f"   (his four rates: {series_rates})\n")

    hdr = f"{'address':<24}{'mat':<8}{'SQ':>6}{'days':>6}{'charged':>10}" + \
          "".join(f"{m:>14}" for m in models) + "   winner"
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(rows, key=lambda r: (r["mat"], r["sq"])):
        best = min(models, key=lambda m: abs(r["err"][m]))
        print(f"{r['address'][:23]:<24}{r['mat']:<8}{r['sq']:>6.1f}{r['days']:>6.1f}"
              f"{r['charged']:>10,.0f}" +
              "".join(f"{100 * r['err'][m]:>13.1f}%" for m in models) +
              f"   {best}")

    print("-" * len(hdr))
    print("\nACCURACY (|quote - charged| as a share of charged)")
    print(f"{'model':14}{'within 5%':>11}{'within 10%':>12}{'median err':>12}"
          f"{'median |err|':>14}{'worst':>9}")
    for m in models:
        e = [r["err"][m] for r in rows]
        print(f"{m:14}{sum(1 for x in e if abs(x) <= ACCURATE):>8}/{len(e):<3}"
              f"{sum(1 for x in e if abs(x) <= 0.10):>9}/{len(e):<3}"
              f"{100 * st.median(e):>11.1f}%{100 * st.median([abs(x) for x in e]):>13.1f}%"
              f"{100 * max(e, key=abs):>8.0f}%")

    print("\nWHERE EACH MODEL WINS  (winner = smallest |error| on that job)")
    def tabulate(name: str, key) -> None:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            buckets[key(r)].append(r)
        print(f"\n  by {name}")
        for b in sorted(buckets):
            grp = buckets[b]
            wins = defaultdict(int)
            for r in grp:
                wins[min(models, key=lambda m: abs(r["err"][m]))] += 1
            per_sq_err = st.median([r["err"]["A per_sq"] for r in grp])
            day_err = st.median([r["err"]["C day-series"] for r in grp])
            print(f"    {b:<18} n={len(grp):<3} per_sq {100 * per_sq_err:>+6.1f}%   "
                  f"day-series {100 * day_err:>+6.1f}%   wins: " +
                  ", ".join(f"{k.split()[0]}={v}" for k, v in sorted(wins.items())))

    tabulate("roof type", lambda r: r["mat"])
    tabulate("size", lambda r: "<20 SQ" if r["sq"] < 20 else ("20-35 SQ" if r["sq"] <= 35 else ">35 SQ"))
    tabulate("productivity", lambda r: (
        "slow <4 sq/day" if r["sq_per_day"] < 4 else
        ("4-6 sq/day" if r["sq_per_day"] < 6 else "fast >=6 sq/day")))
    tabulate("has flat section", lambda r: "flat + sloped" if r["flat_sq"] else "sloped only")
    tabulate("pitch", lambda r: f"{int(r['pitch'] or 0)}/12")
    tabulate("stories", lambda r: f"{int(r['stories'] or 1)} story")
    tabulate("access", lambda r: "access issue" if r["access"] else "normal access")

    # The divergence itself: per_sq minus day, in dollars of overhead, against what predicts it.
    print("\nDIVERGENCE  per_sq overhead minus day-series overhead, per job")
    div = [r["oh"]["A per_sq"] - r["oh"]["C day-series"] for r in rows]
    print(f"  median ${st.median(div):>+9,.0f}   range ${min(div):+,.0f} .. ${max(div):+,.0f}")
    print("\nThe two models are the SAME formula. per_sq is OH = oh_per_sq x SQ; the day model is")
    print("OH = blended_rate x SQ / sq_per_day, where blended_rate mixes the demo rate ($1,050)")
    print("with the install rate over that job's day split. They cross where")
    print("     sq_per_day  ==  blended_rate / oh_per_sq   <-- the BREAK-EVEN productivity")
    print("Below it the roof is slow (cut up, steep, bad access) and the day model charges more;")
    print("above it the roof is simple and the day model charges less. That crossing IS the rule.\n")
    print(f"{'roof':10}{'$/sq OH':>9}{'blended rate':>14}{'break-even':>12}{'his actual':>12}"
          f"{'  -> day model is'}")
    for mat, (roof_type, _, _install) in MATERIALS.items():
        grp = [r for r in rows if r["mat"] == mat]
        if not grp:
            continue
        oh_sq = cfg.sloped_overhead("FBC", roof_type)
        blended = st.median([r["oh"]["C day-series"] / r["days"] for r in grp])
        breakeven = blended / oh_sq
        actual = st.median([r["sq_per_day"] for r in grp])
        print(f"{mat:10}{oh_sq:>9,.0f}{blended:>14,.0f}{breakeven:>10.1f}/d{actual:>10.1f}/d"
              f"  {'DEARER' if actual < breakeven else 'cheaper'} than per_sq at his median job")

    # A switch rule is only worth shipping if it beats both pure models. Sweep the one input the
    # tables point at (jobs slower than X sq/day go to the day model) and score the hybrid.
    print("\nSWITCH RULE — 'day-series when sq/day < T, per_sq otherwise'")
    print(f"{'T (sq/day)':>12}{'within 5%':>11}{'within 10%':>12}{'median |err|':>14}")
    best_pure5 = max(sum(1 for r in rows if abs(r["err"][m]) <= ACCURATE) for m in models)
    for t in (0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 99):
        errs = [r["err"]["C day-series"] if r["sq_per_day"] < t else r["err"]["A per_sq"]
                for r in rows]
        print(f"{t:>12}{sum(1 for e in errs if abs(e) <= ACCURATE):>8}/{len(errs):<3}"
              f"{sum(1 for e in errs if abs(e) <= 0.10):>9}/{len(errs):<3}"
              f"{100 * st.median([abs(e) for e in errs]):>13.1f}%")
    print(f"  (T=0 is pure per_sq, T=99 is pure day-series; best PURE model hits "
          f"{best_pure5}/{len(rows)} within 5%)")

    # The per-job winner tables point at complexity flags, not just productivity. Test those too:
    # if none of them beats pure day-series, there is nothing to switch ON and the answer is one
    # model with one knob.
    print("\n  other candidate rules (per_sq when the roof is SIMPLE, day-series otherwise)")
    RULES = {
        "simple = pitch<=4/12": lambda r: (r["pitch"] or 0) <= 4,
        "simple = no access issue": lambda r: not r["access"],
        "simple = no flat section": lambda r: not r["flat_sq"],
        "simple = all three": lambda r: (r["pitch"] or 0) <= 4 and not r["access"] and not r["flat_sq"],
    }
    for name, is_simple in RULES.items():
        errs = [r["err"]["A per_sq"] if is_simple(r) else r["err"]["C day-series"] for r in rows]
        print(f"    {name:<26}{sum(1 for e in errs if abs(e) <= ACCURATE):>4}/{len(errs):<4}"
              f"within 5%   {sum(1 for e in errs if abs(e) <= 0.10):>3}/{len(errs):<4}within 10%"
              f"   median |err| {100 * st.median([abs(e) for e in errs]):.1f}%")
    print("  n=35 over 27 homes: a threshold picked off this table is FITTED to it. Treat the")
    print("  direction as the finding and re-check any T on jobs quoted after it is chosen.")


if __name__ == "__main__":
    main()
