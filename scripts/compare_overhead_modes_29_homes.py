#!/usr/bin/env python3
"""What the overhead-mode default flip actually does to Tim's 29 homes.

`overhead_mode` now defaults to "daily" (Tim: "that's how we get the overhead is based on time
... this is just a guide", Zoom 2026-07-17 [09:46]). With no days typed, the engine derives them
from the roof's geometry. So the live quote path changes from column A to column B below, and
column C is the ground truth we are trying to reproduce.

  A  per_sq        — the old default; the per-square OH column Tim calls a guide
  B  daily/derived — the NEW default; days fitted from RoofR cut geometry
  C  daily/Tim     — days taken from Tim's own spreadsheet

B vs C is the honest accuracy number. A vs B is the repricing this flip causes.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/compare_overhead_modes_29_homes.py
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.pricing_config import load_config

ROOF_BY_EXISTING = {
    "tile": ("13_tile", "tile"),
    "shingle": ("dimensional_shingle", "shingle"),
    "metal": ("standing_seam_metal", "metal"),
}


def _load_config_for(branch: str):
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        row = c.execute(text(
            "select config from pricing_configs where is_active and branch=:b"
        ), {"b": branch}).scalar()
    return load_config(row)


def _measurements():
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        rows = c.execute(text(
            "select id, address, total_sq, eaves_lf, hips_lf, ridges_lf, valleys_lf, rakes_lf,"
            " wall_flashings_lf, pitch_primary, raw_payload"
            " from measurements where provider='roofr' order by address"
        )).mappings().all()
    return [dict(r) for r in rows]


def _tim_days(meas):
    """address -> Tim's own day estimates, already stored on the measurement row."""
    return {
        str(m["address"]).strip().lower(): ((m.get("raw_payload") or {}).get("tim_days") or {})
        for m in meas
    }


def main() -> None:
    cfg = _load_config_for("jupiter")
    meas = _measurements()
    tim = _tim_days(meas)

    def base_q(m, roof_type, **kw):
        return QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type=roof_type,
            num_squares=float(m["total_sq"]), project_kind="residential",
            demo=True, existing_roof=(m.get("raw_payload") or {}).get("existing") or "tile",
            eaves_lf=float(m["eaves_lf"] or 0), hips_lf=float(m["hips_lf"] or 0),
            ridges_lf=float(m["ridges_lf"] or 0), valleys_lf=float(m["valleys_lf"] or 0),
            rakes_lf=float(m["rakes_lf"] or 0),
            wall_flashings_lf=float(m["wall_flashings_lf"] or 0),
            pitch_primary=float(m["pitch_primary"] or 0) or None,
            **kw,
        )

    print(f"{'address':26} {'SQ':>6} {'A per_sq':>10} {'B derived':>10} {'C Tim days':>11} "
          f"{'B-A':>8} {'B-C':>8} {'days B':>7} {'days C':>7}")
    print("-" * 104)
    rows = []
    for m in meas:
        rp = m.get("raw_payload") or {}
        existing = (rp.get("existing") or rp.get("existing_roof") or "tile").lower()
        if existing not in ROOF_BY_EXISTING:
            continue
        roof_type, series = ROOF_BY_EXISTING[existing]
        td = tim.get(str(m["address"]).strip().lower())
        if not td or td.get("demo") is None or td.get(series) is None:
            continue

        a = estimate(cfg, base_q(m, roof_type, overhead_mode="per_sq"))
        b = estimate(cfg, base_q(m, roof_type, overhead_mode="daily"))
        c = estimate(cfg, base_q(m, roof_type, overhead_mode="daily", daily_series=[
            DailyOverheadSeries(series="demo_dry_in_flat", days=float(td["demo"])),
            DailyOverheadSeries(series=series, days=float(td[series])),
        ]))
        days_b = sum(s["days"] for s in (b.get("daily_series") or []))
        days_c = float(td["demo"]) + float(td[series])
        rows.append((m["address"], float(m["total_sq"]), a["project_total"],
                     b["project_total"], c["project_total"], days_b, days_c))
        print(f"{str(m['address'])[:26]:26} {float(m['total_sq']):6.1f} "
              f"{a['project_total']:10,.0f} {b['project_total']:10,.0f} {c['project_total']:11,.0f} "
              f"{b['project_total']-a['project_total']:8,.0f} "
              f"{b['project_total']-c['project_total']:8,.0f} {days_b:7.1f} {days_c:7.1f}")

    if not rows:
        print("no homes matched — check measurements table and Tim's sheet headers")
        return

    n = len(rows)
    d_ba = [r[3] - r[2] for r in rows]
    d_bc = [r[3] - r[4] for r in rows]
    d_days = [r[5] - r[6] for r in rows]
    within1 = sum(1 for d in d_days if abs(d) <= 1.0)
    within_half = sum(1 for d in d_days if abs(d) <= 0.5)
    print("-" * 104)
    print(f"n = {n} homes")
    print(f"  B-A  repricing from the default flip : mean {sum(d_ba)/n:+,.0f}  "
          f"min {min(d_ba):+,.0f}  max {max(d_ba):+,.0f}  total {sum(d_ba):+,.0f}")
    print(f"  B-C  derived days vs Tim's own days  : mean {sum(d_bc)/n:+,.0f}  "
          f"min {min(d_bc):+,.0f}  max {max(d_bc):+,.0f}")
    print(f"  days derived vs Tim: mean abs {sum(abs(d) for d in d_days)/n:.2f} d, "
          f"within 1.0d {within1}/{n} ({100*within1/n:.0f}%), "
          f"within 0.5d {within_half}/{n} ({100*within_half/n:.0f}%)")
    # A constant-days baseline: does geometry beat "just use the average"?
    mean_days = sum(r[6] for r in rows) / n
    base_within1 = sum(1 for r in rows if abs(mean_days - r[6]) <= 1.0)
    print(f"  BASELINE (predict every job at the mean {mean_days:.1f} days): "
          f"within 1.0d {base_within1}/{n} ({100*base_within1/n:.0f}%)  "
          f"<- geometry must beat this to be worth anything")


if __name__ == "__main__":
    main()
