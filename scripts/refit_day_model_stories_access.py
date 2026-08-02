"""#436 — does Stories / Pitch / Accessibility improve the day model? Honest answer: yes, a little.

Tim, 2026-07-27 call: "you might see variances ... not just based on cuts, but also on how many
stories the roof is. Or if there's a back roof that has very poor access ... and then the pitch
also. So like a six on 12 pitch on a two story is going to be slower ... if you fall off, you're
toast. So you're going to work slower." He wants 95%+ on overhead accuracy; the shipped model is
83% within a day out-of-sample.

Joins Tim's 30-home sheet (stories, access_issue, and his ACTUAL quoted prices) onto the 29 RoofR
geometry homes by normalised address — 29 of 30 match, the miss being 1141 Vintner, whose RoofR PDF
we have never had. Pitch is already in the RoofR data and already drives the steep-roof rule.

RESULT, 2026-07-28, with the feature set AND the steep rule both chosen inside each fold:

    shipped (geometry only)      MAE 0.672 d    83% within a day
    + stories / + access         MAE 0.638 d    86% within a day     <- honest
    squares only (sanity floor)  MAE 1.034 d    69%

⚠️ A flat leaderboard over feature sets scored 90% for "+ accessibility". That number is NOT real:
choosing the arm by reading a table computed on all 29 homes is exactly the in-sample selection
that turned the old "93%" headline into 83% (docs/four-way-review-2026-07-25.md F8). Nesting the
choice costs 4 points. 86% is the number to quote.

What IS solid: no fold chose geometry-only. All 29 picked a set containing stories and/or access,
so the features genuinely carry signal rather than winning by noise on one home.

Still short of Tim's 95%. With n=29, one home is worth 3.4 points, so the binding constraint is
data, not features — he offered another 20 homes on the same call and that is the cheapest next
move. Worst residuals: 213 Isle Verde Way (2.0 d), then 314 5th St, 16285 115th Ave N and
1081 Fairview Lane at 1.5 d.

Usage: PYTHONPATH=. DB_URL=... .venv/bin/python scripts/refit_day_model_stories_access.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

import scripts.honest_day_model_cv as H
from scripts.fit_days_from_roofr import load

TIM30 = "/home/jon/perkins-corpus/tim30_with_actual_prices.json"
BASE = ["squares", "hips", "valleys", "ridges", "rakes", "wall_flash", "eaves"]
CANDIDATES = [BASE, BASE + ["stories"], BASE + ["access"], BASE + ["stories", "access"]]
_SUFFIXES = (r"\b(drive|dr|road|rd|street|st|lane|ln|court|ct|circle|cir|terrace|ter|place|pl"
             r"|avenue|ave|way|north|n|south|s|east|e|west|w)\b")


def norm(addr):
    """Normalise an address enough to join two spellings of the same house."""
    a = re.sub(r"[^a-z0-9 ]", " ", (addr or "").lower())
    return re.sub(r"\s+", " ", re.sub(_SUFFIXES, " ", a)).strip()


def joined_homes():
    """RoofR geometry homes, annotated with Tim's stories and access flag."""
    homes = load()
    tim = {norm(t["address"]): t for t in json.load(open(TIM30))}
    for h in homes:
        t = tim.get(norm(h.get("address")))
        if t:
            h["stories"] = float(t.get("stories") or 1)
            h["access"] = 1.0 if t.get("access_issue") else 0.0
    return homes


def usable_pairs(homes):
    return [(h, H.EXISTING_TO_SERIES[h["existing"]]) for h in homes
            if h.get("existing") in H.EXISTING_TO_SERIES
            and h.get(H.EXISTING_TO_SERIES[h["existing"]])
            and h.get("demo") and "stories" in h]


def best_pool_on(train, subset):
    """Choose the feature set AND the steep rule using training homes only."""
    best = None
    for pool in CANDIDATES:
        H.POOL = pool
        rule = H.choose_rule(train, subset)
        betas = {s: H.fit_series(train, s) for s in ("tile", "shingle", "metal")}
        demo = H.fit_series(train, "demo")
        errs = [H.predict(betas[s], demo, h, *rule) - H.tim_total(h, s)
                for h, s in subset if h in train]
        mae, w1, _ = H.score(errs)
        key = (-w1, mae, len(pool))
        if best is None or key < best[0]:
            best = (key, pool, rule)
    return best[1], best[2]


def frozen_scores():
    """Score each candidate with the FEATURE SET FROZEN across folds.

    The 86% headline is the score of a PROCEDURE that re-chooses the feature set per fold, and the
    folds disagree (access 14, stories 8, both 7). Shipping one fixed set and quoting 86% would be
    the same in-sample selection that turned "93%" into 83% — one level up. This is the number a
    SHIPPED model may claim: set fixed, coefficients and steep rule still refit per fold.
    """
    homes = joined_homes()
    usable = usable_pairs(homes)
    print(f"\nFROZEN feature set (coefficients + steep rule still refit per fold), n={len(usable)}")
    rows = []
    for pool in CANDIDATES:
        errors = []
        for home, series in usable:
            train = [x for x in homes if x is not home and "stories" in x]
            subset = [(a, b) for a, b in usable if a is not home]
            H.POOL = pool
            rule = H.choose_rule(train, subset)
            errors.append(H.predict(H.fit_series(train, series), H.fit_series(train, "demo"),
                                    home, *rule) - H.tim_total(home, series))
        mae, w1, wh = H.score(errors)
        label = "+".join(pool[len(BASE):]) or "geometry only (shipped)"
        rows.append((w1, mae, label))
        print(f"   {label:<28} MAE {mae:.3f} d | within 1 day {w1:.0f}% | within 0.5 {wh:.0f}%")
    best = max(rows)
    print(f"\n   BEST FROZEN: {best[2]} at {best[0]:.0f}% within a day")
    return best


def main():
    if "--frozen" in sys.argv:
        frozen_scores()
        return
    homes = joined_homes()
    usable = usable_pairs(homes)
    errors, chosen = [], []
    for home, series in usable:
        train = [x for x in homes if x is not home and "stories" in x]
        subset = [(a, b) for a, b in usable if a is not home]
        pool, rule = best_pool_on(train, subset)
        chosen.append(tuple(pool[len(BASE):]) or ("geometry only",))
        H.POOL = pool
        errors.append(H.predict(H.fit_series(train, series), H.fit_series(train, "demo"),
                                home, *rule) - H.tim_total(home, series))

    mae, within_day, within_half = H.score(errors)
    print(f"\nHONEST (feature set AND steep rule chosen inside each fold), n={len(errors)}")
    print(f"   MAE {mae:.3f} days | within 1 day {within_day:.0f}% "
          f"| within 0.5 day {within_half:.0f}%")
    print(f"\n   feature set picked per fold: {Counter(chosen).most_common()}")
    worst = sorted(((abs(e), h["address"]) for e, (h, _) in zip(errors, usable)), reverse=True)
    print("   worst residuals: " + ", ".join(f"{a} ({d:.1f} d)" for d, a in worst[:4]))


if __name__ == "__main__":
    main()
