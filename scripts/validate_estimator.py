#!/usr/bin/env python3
"""Behavioral validation for the F2 estimating engine — hermetic, no I/O side effects.

Loads the Exhibit B seed fixture directly from disk (no DB needed), instantiates the
engine with the config, runs all sloped golden inputs, and asserts totals within tolerance.

Exits 0 on PASS, 1 on FAIL. Prints PASS or FAIL <diff> for each case.

R1 behavioral validation for core/estimator.py (the non-coverage-gated I/O path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path when run directly
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.estimator import QuoteInput, estimate  # noqa: E402
from core.pricing_config import load_config  # noqa: E402

FIXTURE_PATH = ROOT / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"


def run_validation() -> int:
    """Returns 0 on full pass, 1 if any case fails."""
    raw = json.loads(FIXTURE_PATH.read_text())
    cfg = load_config(raw)

    golden_files = sorted(GOLDEN_DIR.glob("*.json"))
    if not golden_files:
        print("FAIL: no golden fixture files found in", GOLDEN_DIR)
        return 1

    all_passed = True
    for gf in golden_files:
        data = json.loads(gf.read_text())
        inp = data["input"]

        # Build QuoteInput — filter None values for optional fields
        q_kwargs = {k: v for k, v in inp.items() if v is not None}
        # Restore explicit None for optional fields that must be passed as None
        for nullable in ("specialty_tile", "county", "deck_type"):
            if nullable not in q_kwargs:
                q_kwargs[nullable] = None

        q = QuoteInput(**q_kwargs)
        result = estimate(cfg, q)

        expected = data["expected_total"]
        actual = result["project_total"]
        tol = max(data["tolerance_abs"], expected * data["tolerance_pct"])
        diff = abs(actual - expected)

        if diff <= tol:
            print(f"PASS  {gf.stem}: total={actual:.2f} (expected {expected:.2f})")
        else:
            print(f"FAIL  {gf.stem}: total={actual:.2f}, expected={expected:.2f}, diff={diff:.4f} > tol={tol:.4f}")
            all_passed = False

    if all_passed:
        print(f"\nPASS — {len(golden_files)}/5 golden fixtures (2 pending Tim OI-1) within tolerance.")
        return 0
    else:
        print(f"\nFAIL — one or more of {len(golden_files)}/5 golden fixtures out of tolerance.")
        return 1


if __name__ == "__main__":
    sys.exit(run_validation())
