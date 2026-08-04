#!/usr/bin/env python3
"""Put ALL overhead on days, per branch — Tim's 2026-08-03 request, with his own numbers.

    "Why is this still trying to use per SQ prices on the OH? It's all going to be based on
     days, so the days are what it needs to measure - not prices per SQ."   — Tim, 2026-08-03

Four changes per branch, every value his:

  1. overhead_basis  -> "branch"        one office burn x days / crews, not four activity rates
  2. office_daily_overhead              Jupiter $1,470, Miami $4,257   (2026-07-30, config had
                                        1400/4250)
  3. concurrent_crews                   Jupiter 1.5, Miami 4           (2026-07-30; UNSET today,
                                        which defaults to 1.0 and charges every job the WHOLE
                                        office day — the single biggest error in the book)
  4. a low_slope day series             so flat roofs get days like everything else, instead of
                                        silently falling back to the per-square table

THE LOW-SLOPE DAY FIT is `days = 0.389 + 0.0851 x squares`, least squares over the 9 homes in his
2026-07-27 workbook that carry BOTH "Squares (Flat)" and "Flat (days)" (R2 0.585, every residual
inside +/-0.6 days). Small, and honest about it — but it reproduces an independent document: it
predicts 2.8 days for the 28-square flat section on the Evergrene clubhouse, and his own
commercial bid sheet allocated 3.

Rates are kept for every series because the API validates series names against
`daily_overhead_rates`; under branch basis the rate itself is unused (the burn comes from
office_daily_overhead), so the low_slope entry uses his "Demo & Flat: $1,050 per day".

Prints the priced before/after and exits unless --apply. Reversible: a new config VERSION is
created and the old one deactivated, so reactivating the previous row rolls it back.

Usage: DB_URL=… PYTHONPATH=. .venv/bin/python scripts/seed_overhead_by_days.py [--apply]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics as st
from dataclasses import fields

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.pricing_config import load_config

# Tim, 2026-07-30 12:31.
BRANCH = {
    "jupiter": {"office_daily_overhead": 1470.0, "concurrent_crews": 1.5},
    "naples":  {"office_daily_overhead": 1470.0, "concurrent_crews": 1.5},
    "miami":   {"office_daily_overhead": 4257.0, "concurrent_crews": 4.0},
}
LOW_SLOPE_FIT = {"setup": 0.389, "rate": 0.0851}
LOW_SLOPE_RATE = 1050.0          # "Demo & Flat: $1,050 per day", 2026-07-24
LOW_SLOPE_SERIES = "low_slope"

_QI = {f.name for f in fields(QuoteInput)}


def _new_config(cfg: dict, branch: str) -> dict:
    out = copy.deepcopy(cfg)
    out["overhead_basis"] = "branch"
    out.update(BRANCH[branch])

    model = out.setdefault("daily_overhead_day_model", {})
    model.setdefault("series", {})[LOW_SLOPE_SERIES] = dict(LOW_SLOPE_FIT)
    # Which series the FLAT half of a mixed roof books against (core.estimator.derive_daily_series).
    model["flat_series"] = {"series": LOW_SLOPE_SERIES}
    # And the mapping that lets a PURE low-slope quote derive days at all.
    ls_keys = [k for k in (out.get("low_slope", {}).get("base_cost_lm", {}).get("HVHZ") or {})
               if not k.startswith("_")]
    mapping = model.setdefault("install_series_by_roof_type", {})
    for k in ls_keys:
        mapping[k] = LOW_SLOPE_SERIES
    out.setdefault("daily_overhead_rates", {})[LOW_SLOPE_SERIES] = LOW_SLOPE_RATE
    return out


def _quote(raw: dict) -> QuoteInput:
    kw = {k: v for k, v in raw.items() if k in _QI and v is not None}
    kw["daily_series"] = [DailyOverheadSeries(series=s["series"], days=s["days"])
                          for s in (raw.get("daily_series") or [])]
    return QuoteInput(**kw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write + activate a new config version")
    args = ap.parse_args()

    eng = create_engine(os.environ["DB_URL"])
    s = Session(eng)
    s.execute(text("set app.tenant_id='1'"))
    from app.models import PricingConfig
    from core.pricing_config import compute_hash

    rows = s.execute(text("select id, branch, input_json from estimates order by id")).all()

    for branch in ("jupiter", "miami", "naples"):
        active = s.query(PricingConfig).filter(
            PricingConfig.branch == branch, PricingConfig.is_active == True).one()  # noqa: E712
        old = active.config if isinstance(active.config, dict) else json.loads(active.config)
        new = _new_config(old, branch)
        cfg_old, cfg_new = load_config(old), load_config(new)

        deltas, moved = [], 0
        for _id, b, raw in rows:
            if b != branch:
                continue
            try:
                q = _quote(raw if isinstance(raw, dict) else json.loads(raw))
                a = estimate(cfg_old, q)["project_total"]
                z = estimate(cfg_new, q)["project_total"]
            except Exception:                                # noqa: BLE001
                continue
            if a:
                deltas.append((z - a) / a)
                moved += (abs(z - a) > 0.5)
        med = f"{100*st.median(deltas):+.1f}%" if deltas else "n/a"
        rng = (f"{100*min(deltas):+.1f}% .. {100*max(deltas):+.1f}%") if deltas else ""
        print(f"{branch:8} v{active.version} -> basis=branch, daily=${BRANCH[branch]['office_daily_overhead']:,.0f}, "
              f"crews={BRANCH[branch]['concurrent_crews']}")
        print(f"         {len(deltas)} estimates repriced, {moved} moved   median {med}   range {rng}")

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        row = PricingConfig(
            branch=branch, version=active.version + 1,
            label="overhead by days per branch (Tim 2026-07-30/08-03)",
            config=new, config_hash=compute_hash(new),
            is_active=True, created_by="seed_overhead_by_days.py", tenant_id=1,
        )
        s.add(row)
        s.flush()
        print(f"         created + activated v{row.version} (id={row.id})")

    if args.apply:
        s.commit()
        print("\napplied.")
    else:
        s.rollback()
        print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
