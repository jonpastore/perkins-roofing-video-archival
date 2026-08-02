#!/usr/bin/env python3
"""Add the #436 `access` term to each branch's day model — a new config version per branch.

Without this the feature is INERT in prod. `core.estimator.derive_daily_series` reads the access
coefficient out of `daily_overhead_day_model.geometry_model[<series>].access`, and the live
pricing_configs rows do not have it: the code would ship, the fixture would ship, and every prod
quote would keep booking the same days. That is the "built, never called" failure this repo has
already had once (the F6 seam bug).

WHAT IT MEANS. `access` = 1 when `QuoteInput.access_difficult`, else 0 — a TIME feature, never a
price adder (accessibility_flat is the money field). Tim, 2026-07-27: *"if there's a back roof that
has very poor access ... you're going to work slower."*

    tile      +0.747 d      demo      +0.514 d
    metal     +0.339 d      shingle   +0.225 d

which orders by how much material has to be carried — a sign the feature is signal, not noise.

MEASURED, feature set FROZEN and coefficients + steep rule refit inside each LOO fold (n=29):

    geometry only (shipped)   MAE 0.672 d   83% of homes within a day of Tim's booked days
    + access                  MAE 0.586 d   90%
    + stories                 MAE 0.586 d   86%
    + stories + access        MAE 0.603 d   90%   (same score, worse MAE, one more feature)

⚠️ Quote the range, not the best cell. The nested estimate of the whole choose-a-feature-set
PROCEDURE is 86%; picking the winning arm of four on 29 homes is itself worth something, so the
truth for this shipped model is between 86% and 90%. Reading one number off a leaderboard computed
on all 29 homes is exactly what turned the old "93%" headline into 83%
(docs/four-way-review-2026-07-25.md F8).

⚠️ STILL SHORT of Tim's 95%, and more features will not close it: with n=29 one home is worth 3.4
points, so the binding constraint is DATA. He offered another 20 homes on the 7/27 call.

    .venv/bin/python scripts/seed_day_model_access.py                # print and exit
    .venv/bin/python scripts/seed_day_model_access.py --apply        # new version per branch
"""
from __future__ import annotations

import argparse
import copy
import sys

#: Fitted per series on Tim's 29 RoofR homes joined to the access_issue flag of his 30-home sheet
#: (scripts/refit_day_model_stories_access.py, POOL = geometry + access). Config keys, not the
#: fitter's series names — `demo` is stored as `demo_dry_in_flat`.
ACCESS_DAYS = {
    "tile": 0.746911,
    "shingle": 0.225064,
    "metal": 0.33943,
    "demo_dry_in_flat": 0.51359,
}

NOTE = (
    "#436, 2026-08-02. `access` = 1 when QuoteInput.access_difficult, else 0 — a TIME feature, "
    "never a price adder. Fitted per series on Tim's 29 RoofR homes joined to his 30-home sheet's "
    "access_issue flag. MEASURED with the feature set FROZEN and coefficients + steep rule refit "
    "inside each LOO fold: geometry only 83% of homes within a day (MAE 0.672), +access 90% "
    "(0.586). The nested estimate of the choose-a-set PROCEDURE is 86%, so the honest range for "
    "this model is 86-90%. Still short of Tim's 95%: at n=29 one home is 3.4 points, so the "
    "binding constraint is DATA, not features — he offered 20 more homes on the 7/27 call."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write a new config version per branch")
    ap.add_argument("--branches", default="", help="comma-separated; default every branch")
    args = ap.parse_args()
    only = {b.strip() for b in args.branches.split(",") if b.strip()}

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash

    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = sorted({r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()})
    for branch in branches:
        if only and branch not in only:
            print(f"{branch}: not in --branches — untouched")
            continue
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue

        cfg = copy.deepcopy(active.config)
        model = cfg.get("daily_overhead_day_model") or {}
        geom = model.get("geometry_model") or {}
        if not geom:
            # A branch with no geometry model uses the squares-only fit, where the access
            # coefficient has nowhere to live. Skip loudly rather than inventing one.
            print(f"{branch}: no geometry_model — skipped (squares-only fit)")
            continue

        touched = []
        for series, days in ACCESS_DAYS.items():
            if series in geom:
                geom[series]["access"] = round(days, 6)
                touched.append(f"{series} +{days:.3f}d")
        if not touched:
            print(f"{branch}: geometry_model has none of {sorted(ACCESS_DAYS)} — skipped")
            continue
        model["_note_access_term"] = NOTE
        cfg["daily_overhead_day_model"] = model

        if cfg == active.config:
            print(f"{branch}: already carries the access term — no new version")
            continue
        print(f"{branch}: v{active.version} -> v{active.version + 1}  " + ", ".join(touched))
        if not args.apply:
            continue
        active.is_active = False
        s.add(PricingConfig(
            branch=branch, version=active.version + 1, label=f"{active.label} + access day term",
            config=cfg, config_hash=compute_hash(cfg), is_active=True,
            created_by="seed_day_model_access.py", tenant_id=1))
        s.commit()
        print(f"  created + activated v{active.version + 1}")

    if not args.apply:
        print("\nprint-only. re-run with --apply to write a new version per branch.")


if __name__ == "__main__":
    main()
