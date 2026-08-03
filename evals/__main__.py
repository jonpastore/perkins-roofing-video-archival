"""CLI: `python -m evals run [suite ...] [--check] [--write-baseline]`.

`run` prints a scorecard. `--check` additionally compares every gated metric against
evals/baseline.json and exits 1 on a regression — that exit code is the CI gate.

Why a floor rather than an exact match: the datasets are frozen, so scores ARE deterministic to
the bit and equality would be enforceable — but a gate that fires on an improvement gets switched
off. A floor fails on bad news only.

Why the default tolerance is 0.0 and not a slack band: there is no noise to absorb. A 0.02 band
was tried first and it let BOTH fusion legs of `core.retrieval.rank` be deleted outright without
failing — removing the Content-Graph boost moves recall@4 by 0.0166 and removing the lexical
boost by the same, which is under any slack worth writing down. A tolerance sized for noise that
does not exist is just a hole in the gate. `--tolerance` remains for a deliberate, argued
exception.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .scoring import GATED, SUITES

BASELINE = Path(__file__).parent / "baseline.json"


def _scorecard(name: str, scores: dict) -> None:
    print(f"\n=== {name} ===")
    for key, value in scores.items():
        if isinstance(value, float):
            print(f"  {key:<24} {value:.4f}" if key != "n" else f"  {key:<24} {int(value)}")
        else:
            print(f"  {key:<24} {value}")


def _check(name: str, scores: dict, baseline: dict, tolerance: float) -> list[str]:
    """Regressions in `name`, as printable lines. A metric missing from the baseline is a
    failure, not a pass: a new gated metric with no recorded floor is ungated, and an ungated
    metric reads exactly like a passing one."""
    failures = []
    want = baseline.get(name)
    if want is None:
        return [f"{name}: no baseline recorded — run `python -m evals run --all --write-baseline`"]
    # Both directions. Iterating only the scores would let a metric that VANISHES from a suite
    # pass — nothing to compare, so nothing to fail, and the scorecard just gets shorter. A
    # metric that stopped being computed is the loudest regression there is.
    for key in sorted({k for k in scores if k in GATED} | set(want)):
        floor, value = want.get(key), scores.get(key)
        if floor is None:
            failures.append(f"{name}.{key}: no baseline floor for a gated metric")
        elif value is None:
            failures.append(f"{name}.{key}: baseline records a floor but the suite no longer "
                            f"reports this metric")
        elif value < floor - tolerance:
            failures.append(f"{name}.{key}: {value:.4f} < {floor:.4f} - {tolerance} (REGRESSION)")
    return failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evals")
    p.add_argument("command", choices=["run", "refresh"])
    # No `choices=`: with nargs="*" argparse validates the DEFAULT against choices too, so an
    # empty default (meaning "all") is rejected before main() ever runs.
    p.add_argument("suites", nargs="*", default=[], help=f"one of {', '.join(SUITES)}")
    p.add_argument("--all", action="store_true", help="every suite")
    p.add_argument("--check", action="store_true", help="fail on regression vs baseline.json")
    p.add_argument("--write-baseline", action="store_true", help="record current scores as the floor")
    p.add_argument("--tolerance", type=float, default=0.0)
    args = p.parse_args(argv)

    if args.command == "refresh":
        from .refresh import run
        run()
        return 0

    unknown = [s for s in args.suites if s not in SUITES]
    if unknown:
        p.error(f"unknown suite(s) {unknown} — choose from {', '.join(SUITES)}")
    names = list(SUITES) if (args.all or not args.suites) else args.suites
    results = {n: SUITES[n]() for n in names}
    for name in names:
        _scorecard(name, results[name])

    if args.write_baseline:
        current = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        # Truncate, never round-to-nearest. round(0.116666, 4) = 0.1167, which is ABOVE the score
        # it was taken from — with a zero tolerance that fails the gate on the very tree that
        # wrote it. Rounding down keeps the file readable and the floor honest.
        current.update({n: {k: math.floor(v * 10_000) / 10_000 for k, v in s.items()
                            if k in GATED} for n, s in results.items()})
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written: {BASELINE}")
        return 0

    if args.check:
        baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        failures = [f for n in names for f in _check(n, results[n], baseline, args.tolerance)]
        if failures:
            print("\nEVAL GATE FAILED:")
            for f in failures:
                print("  " + f)
            return 1
        print("\neval gate: OK (no gated metric below baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
