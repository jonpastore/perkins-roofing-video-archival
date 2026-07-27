#!/usr/bin/env python3
"""Score the day model with RULE SELECTION nested inside cross-validation.

`docs/four-way-review-2026-07-25.md` F8 — still unrefuted — says the "93% within a day" headline is
in-sample: the feature elimination AND the >=6/12 steep-roof rule were both chosen by re-scoring the
same 29 homes, so the number measures fit, not forecast. The review named the missing test and
nobody ran it. This runs it.

Four scorings of the SAME metric (derived total days vs Tim's own total days, per home):

  1. in-sample              — what the email currently quotes.
  2. LOO, coefficients only — refit betas per fold, steep rule frozen as shipped. Still optimistic:
                              the rule was picked on all 29.
  3. LOO, rule nested       — refit betas AND re-choose the steep rule (threshold x days grid) on
                              the 28 training homes each fold. This is the honest number.
  4. constant baseline      — predict every job at the training mean. Guards against a headline
                              that rides on low variance rather than on the model.

Usage: PYTHONPATH=. DB_URL=... .venv/bin/python scripts/honest_day_model_cv.py
"""
from __future__ import annotations

import numpy as np

from scripts.fit_days_from_roofr import fit_nonneg, load

# Feature pool offered to backward elimination, matching the shipped geometry_model terms.
POOL = ["squares", "hips", "valleys", "ridges", "rakes", "wall_flash", "eaves"]
INSTALL_FOR = {"tile": "tile", "shingle": "shingle", "metal": "metal"}
# Tim logs one Demo column; the like-for-like install series comes from the existing roof.
EXISTING_TO_SERIES = {"tile": "tile", "shingle": "shingle", "metal": "metal"}
# Grid the steep-roof rule is chosen from. (threshold 99 = rule off.)
RULE_GRID = [(99, 0.0)] + [(t, d) for t in (5, 6, 7) for d in (0.5, 1.0)]


def half(x: float) -> float:
    """Half-day resolution with a 0.5-day floor — the estimator's own rounding."""
    return max(0.5, round(float(x) * 2) / 2)


def _design(homes: list[dict]) -> np.ndarray:
    return np.column_stack([np.ones(len(homes))] + [[h[c] for h in homes] for c in POOL])


def fit_series(homes: list[dict], target: str) -> np.ndarray:
    """Backward-eliminated non-negative fit — the same selection the shipped model used."""
    rows = [h for h in homes if h.get(target)]
    if len(rows) < 4:
        return np.zeros(len(POOL) + 1)
    return fit_nonneg(_design(rows), np.array([h[target] for h in rows], float))


def predict(beta_install: np.ndarray, beta_demo: np.ndarray, home: dict,
            threshold: float, adder: float) -> float:
    """Total crew-days for one home: demo + like-for-like install, steep adder on install only."""
    x = np.array([1.0] + [home[c] for c in POOL], float)
    install = half(x @ beta_install)
    if home.get("pitch") and float(home["pitch"]) >= threshold:
        install = half(install + adder)
    return install + half(x @ beta_demo)


def tim_total(home: dict, series: str) -> float:
    return float(home.get("demo") or 0.0) + float(home.get(series) or 0.0)


def score(errors: list[float]) -> tuple[float, float, float]:
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    w1 = 100 * sum(1 for e in errors if abs(e) <= 1.0) / n
    wh = 100 * sum(1 for e in errors if abs(e) <= 0.5) / n
    return mae, w1, wh


def choose_rule(train: list[dict], usable: list[tuple[dict, str]]) -> tuple[float, float]:
    """Pick (threshold, adder) that maximises '% within one day' on the TRAINING homes only.

    Ties broken on MAE, then on the smaller adder, so 'rule off' wins a genuine tie. This mirrors
    how the shipped rule was chosen — the point of the test is that the choosing happens on
    training data, not on the home being scored.
    """
    betas = {s: fit_series(train, s) for s in ("tile", "shingle", "metal")}
    demo = fit_series(train, "demo")
    best = None
    for thr, add in RULE_GRID:
        errs = [predict(betas[s], demo, h, thr, add) - tim_total(h, s)
                for h, s in usable if h in train]
        if not errs:
            continue
        mae, w1, _ = score(errs)
        key = (-w1, mae, add)
        if best is None or key < best[0]:
            best = (key, (thr, add))
    return best[1] if best else (99, 0.0)


def main() -> None:
    homes = load()
    usable = [(h, EXISTING_TO_SERIES[h["existing"]]) for h in homes
              if h.get("existing") in EXISTING_TO_SERIES and h.get(EXISTING_TO_SERIES[h["existing"]])
              and h.get("demo")]
    n = len(usable)
    print(f"\n{n} homes with a like-for-like day figure from Tim\n")

    shipped_thr, shipped_add = 6, 0.5

    # 1. in-sample, shipped rule
    betas = {s: fit_series(homes, s) for s in ("tile", "shingle", "metal")}
    demo_all = fit_series(homes, "demo")
    e_in = [predict(betas[s], demo_all, h, shipped_thr, shipped_add) - tim_total(h, s)
            for h, s in usable]

    # 2. LOO over coefficients, shipped rule frozen
    e_loo = []
    for h, s in usable:
        train = [x for x in homes if x is not h]
        e_loo.append(predict(fit_series(train, s), fit_series(train, "demo"),
                             h, shipped_thr, shipped_add) - tim_total(h, s))

    # 3. LOO with the rule re-chosen on the training fold
    e_nested, picks = [], []
    for h, s in usable:
        train = [x for x in homes if x is not h]
        thr, add = choose_rule(train, [(a, b) for a, b in usable if a is not h])
        picks.append((thr, add))
        e_nested.append(predict(fit_series(train, s), fit_series(train, "demo"),
                                h, thr, add) - tim_total(h, s))

    # 4. constant baseline: training-fold mean total days
    e_base = []
    for h, s in usable:
        others = [tim_total(a, b) for a, b in usable if a is not h]
        e_base.append(half(sum(others) / len(others)) - tim_total(h, s))

    print(f"{'scoring':<40}{'MAE (days)':>12}{'within 1.0d':>13}{'within 0.5d':>13}")
    print("-" * 78)
    for label, errs in (("1. in-sample (what the email quotes)", e_in),
                        ("2. LOO, coefficients only", e_loo),
                        ("3. LOO, steep rule nested  <-- honest", e_nested),
                        ("4. constant baseline (training mean)", e_base)):
        mae, w1, wh = score(errs)
        print(f"{label:<40}{mae:>12.2f}{w1:>12.0f}%{wh:>12.0f}%")

    agree = sum(1 for p in picks if p == (shipped_thr, shipped_add))
    print(f"\nSteep rule re-chosen per fold: shipped (>=6/12, +0.5d) selected in {agree}/{n} folds.")
    off = sum(1 for p in picks if p[0] == 99)
    print(f"  rule switched OFF entirely in {off}/{n} folds; distinct choices: {sorted(set(picks))}")
    bias_in, bias_nested = sum(e_in) / n, sum(e_nested) / n
    print(f"\nBias (ours - Tim): in-sample {bias_in:+.2f} d, honest {bias_nested:+.2f} d")


def selftest() -> None:
    """The one thing that must not break: no fold may see the home it is scoring.

    A leak here would quietly turn every 'honest' number back into an in-sample one — the exact
    defect this script exists to detect — and it would still print plausible output.
    """
    homes = [{"squares": 10.0 + i, "hips": 5.0 * i, "valleys": 0.0, "ridges": 2.0 * i,
              "rakes": 1.0, "wall_flash": 0.0, "eaves": 100.0 + i, "pitch": 4 + (i % 4),
              "existing": "tile", "tile": 1.0 + 0.1 * i, "demo": 2.0} for i in range(12)]
    for h in homes:
        train = [x for x in homes if x is not h]
        assert h not in train and len(train) == len(homes) - 1
        # A fold's rule choice must not depend on the held-out home either.
        usable = [(a, "tile") for a in homes if a is not h]
        assert all(a is not h for a, _ in usable)
        choose_rule(train, usable)
    assert half(0.1) == 0.5 and half(2.26) == 2.5 and half(2.24) == 2.0
    beta = np.zeros(len(POOL) + 1)
    beta[0] = 3.0
    # Steep adder fires at/above the threshold and only there.
    flat = dict(homes[0], pitch=4)
    steep = dict(homes[0], pitch=6)
    assert predict(beta, beta, flat, 6, 0.5) == 6.0
    assert predict(beta, beta, steep, 6, 0.5) == 6.5
    print("selftest ok")


if __name__ == "__main__":
    import sys

    selftest() if "--selftest" in sys.argv else main()
