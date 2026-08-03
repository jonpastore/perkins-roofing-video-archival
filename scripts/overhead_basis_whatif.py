#!/usr/bin/env python3
"""Priced before/after for the two open overhead decisions, replayed over REAL estimates.

The two decisions, both answered by Tim on 2026-07-30 and neither applied:

  (1) `concurrent_crews` is unset on all three branches, so it defaults to 1.0 and every job
      carries a FULL office day. Tim: "My assumption is to have 1.5 crews on any given day",
      "Miami needs to have 4 crews on any given day". Applies to `overhead_basis='branch'` ONLY.

  (2) `overhead_basis` is 'series' on jupiter and naples (Tim's four per-activity day rates) and
      'branch' on miami (one office burn / crews). Tim: "The numbers I provided you are what I use
      for Jupiter and what any franchisee should use for their branch."

Also carried: `office_daily_overhead` is 1400/4250 in config against the 1470/4257 Tim stated on
2026-07-30.

METHOD. Every stored estimate's `input_json` is a full QuoteInput, so each is re-priced through
the real engine under each scenario — no model of the engine, the engine itself. Scenarios differ
ONLY in the keys above; every other config value is the branch's live active config, so a delta
here is attributable to the decision and nothing else.

⚠️ `concurrent_crews` moves nothing under 'series' basis — the per-series rates are already
per-crew-day numbers, so dividing them again would discount the same split twice. That is why
scenario 2 shows jupiter/naples unchanged: it is correct, not a bug in this script.

Usage: DB_URL=… PYTHONPATH=. .venv/bin/python scripts/overhead_basis_whatif.py
"""
from __future__ import annotations

import json
import os
import statistics as st
from collections import defaultdict
from dataclasses import fields

from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.pricing_config import load_config

# Tim, 2026-07-30 12:31. Jupiter 1.5 is his "assumption"; Miami 4 is a REQUIREMENT he states
# ("Miami needs to have 4 crews ... otherwise that branch is losing money") — a capacity target,
# not a measurement, which is why concurrent_crews() is documented to be set from measured
# concurrency. Both are priced here so the difference is visible rather than argued.
TIM_CREWS = {"jupiter": 1.5, "miami": 4.0, "naples": 1.5}
TIM_DAILY = {"jupiter": 1470.0, "miami": 4257.0, "naples": 1470.0}
# scripts/recovery_identity_jupiter.py measures Jupiter at ~1.2 charged job-days per working day,
# and that EXCLUDES repairs and low-slope, so it is a floor.
MEASURED_CREWS = {"jupiter": 1.2, "miami": 4.0, "naples": 1.2}

_QI_FIELDS = {f.name for f in fields(QuoteInput)}


def _quote_input(raw: dict) -> QuoteInput:
    """QuoteInput from a stored input_json. The row also carries API-level keys (discounts,
    commission_basis, override_*) that the engine takes elsewhere; filtering by dataclass field
    keeps this honest rather than silently dropping something the engine would have used."""
    kw = {k: v for k, v in raw.items() if k in _QI_FIELDS and v is not None}
    kw["daily_series"] = [DailyOverheadSeries(series=s["series"], days=s["days"])
                          for s in (raw.get("daily_series") or [])]
    return QuoteInput(**kw)


def _variant(base: dict, *, basis: str | None, crews: float | None, daily: float | None) -> dict:
    cfg = dict(base)
    if basis:
        cfg["overhead_basis"] = basis
    if crews is not None:
        cfg["concurrent_crews"] = crews
    if daily is not None:
        cfg["office_daily_overhead"] = daily
    return cfg


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        live = {b: (j if isinstance(j, dict) else json.loads(j)) for b, j in c.execute(text(
            "select branch, config from pricing_configs where is_active")).all()}
        rows = c.execute(text(
            "select id, branch, input_json from estimates order by id")).all()

    scenarios = {
        "1 today (as deployed)":
            lambda b: live[b],
        "2 + Tim's crews (1.5/4)":
            lambda b: _variant(live[b], basis=None, crews=TIM_CREWS[b], daily=None),
        "3 branch basis + Tim's crews + his daily":
            lambda b: _variant(live[b], basis="branch", crews=TIM_CREWS[b], daily=TIM_DAILY[b]),
        "4 branch basis + MEASURED crews (J 1.2)":
            lambda b: _variant(live[b], basis="branch", crews=MEASURED_CREWS[b], daily=TIM_DAILY[b]),
    }
    configs = {name: {b: load_config(fn(b)) for b in live} for name, fn in scenarios.items()}

    totals: dict[str, dict[str, list]] = {n: defaultdict(list) for n in scenarios}
    failures: dict[str, int] = defaultdict(int)
    for est_id, branch, raw in rows:
        if branch not in live:
            continue
        try:
            q = _quote_input(raw if isinstance(raw, dict) else json.loads(raw))
        except Exception:                                   # noqa: BLE001
            failures["input"] += 1
            continue
        priced = {}
        for name in scenarios:
            try:
                priced[name] = estimate(configs[name][branch], q)["project_total"]
            except Exception:                               # noqa: BLE001
                break
        if len(priced) != len(scenarios):
            failures[branch] += 1
            continue
        for name, tot in priced.items():
            totals[name][branch].append((est_id, tot))

    print(f"replayed {sum(len(v) for v in totals['1 today (as deployed)'].values())} of {len(rows)} "
          f"stored estimates; skipped {sum(failures.values())} "
          f"({dict(failures) or 'none'})\n")

    base_name = "1 today (as deployed)"
    for branch in sorted(live):
        base = dict(totals[base_name][branch])
        if not base:
            continue
        print(f"=== {branch}  (n={len(base)}, live basis={live[branch].get('overhead_basis')}, "
              f"concurrent_crews={live[branch].get('concurrent_crews')}) ===")
        print(f"    {'scenario':42} {'median $':>11} {'vs today':>10} {'min':>9} {'max':>9}")
        for name in scenarios:
            vals = dict(totals[name][branch])
            meds = st.median(list(vals.values()))
            deltas = [(vals[k] - base[k]) / base[k] for k in base if base[k]]
            arrow = "" if name == base_name else f"{100*st.median(deltas):+.1f}%"
            lo = f"{100*min(deltas):+.1f}%" if deltas and name != base_name else ""
            hi = f"{100*max(deltas):+.1f}%" if deltas and name != base_name else ""
            print(f"    {name:42} {meds:>11,.0f} {arrow:>10} {lo:>9} {hi:>9}")
        print()


if __name__ == "__main__":
    main()
