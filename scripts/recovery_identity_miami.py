#!/usr/bin/env python3
"""THE RECOVERY IDENTITY — the only non-circular overhead test (Grok Q3.2/Q7.1, GPT Q8).

    ratio = SUM(overhead charged across a period) / (branch daily burn x working days)

Under overhead_basis="branch" the burn cancels, so the identity reduces to a pure DAY COUNT:

    ratio = SUM(estimator job-days sold in the period) / (working days in the period)

ratio ~= 1.0  -> the allocator funds the office exactly
ratio  > 1.0  -> over-recovery (the parallel-job double count: N concurrent jobs each charged a
                 full calendar day of a burn that is incurred once)
ratio  < 1.0  -> under-recovery (the office is not paid for by the jobs sold)

It uses accounting burn + estimator-charged days only. No sold price enters, so it cannot be
passed by wrong overhead plus compensating profit.

Also prints the BRANCH COMPOSITION of the job-costing mirror, because every "sold $/sq" benchmark
used to date was drawn from it.

Usage: DB_URL=... PYTHONPATH=/home/jon/projects/perkins-roofing/video-archival \
       .venv/bin/python ~/perkins-corpus/analysis/recovery_identity.py
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import date

import numpy as np
from sqlalchemy import create_engine, text

from core.estimator import QuoteInput, derive_daily_series
from core.pricing_config import load_config

# Same extraction contract as scripts/sold_price_trend.py (Quantity = 1/100 sq, Price = cents).
QTY_SCALE, CENTS = 100.0, 100.0
MATERIALS = [
    ("barrel", r"\bbarrel\b", "barrel_tile"),
    ("tile", r"\btile\b", "13_tile"),
    ("shingle", r"\bshingle\b", "dimensional_shingle"),
    ("metal", r"\bmetal\b|standing seam", "standing_seam_metal"),
    ("tpo", r"\btpo\b", None),
    ("silicone", r"\bsilicone\b", None),
    ("coating", r"\bcoating\b", None),
]
# US federal holidays are ~10/yr; roofing crews in FL work most of them, so 8 is a conservative
# deduction. The ratio moves <4% across 0-10, so this is not load-bearing.
HOLIDAYS_PER_YEAR = 8

COUNTY = {330: "Dade/Broward", 331: "Miami-Dade", 332: "Miami-Dade", 333: "Broward",
          334: "Palm Beach", 349: "Martin/St Lucie"}


def _county(zip_code: str | None) -> str:
    z = (zip_code or "").strip()[:5]
    if not re.fullmatch(r"\d{5}", z):
        return "no zip"
    return COUNTY.get(int(z[:3]), f"other {z[:3]}xx")


def _bucket(desc: str) -> tuple[str, str | None] | None:
    for name, pat, roof_type in MATERIALS:
        if re.search(pat, desc, re.I):
            return name, roof_type
    return None


def _working_days(year: int) -> int:
    start, end = date(year, 1, 1), min(date(year + 1, 1, 1), date.today())
    if end <= start:
        return 0
    days = int(np.busday_count(start, end))
    return max(days - round(HOLIDAYS_PER_YEAR * days / 252), 0)


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='miami'")).scalar())
        contracts = {p["Id"]: p for (p,) in c.execute(text(
            "select payload from knowify_raw_records where entity='contracts' and is_present")).all()
            if p.get("Id") is not None}
        projects = {p["Id"]: p for (p,) in c.execute(text(
            "select payload from knowify_raw_records where entity='projects' and is_present")).all()
            if p.get("Id") is not None}
        clients = {p["Id"]: p for (p,) in c.execute(text(
            "select payload from knowify_raw_records where entity='clients' and is_present")).all()
            if p.get("Id") is not None}
        delivs = [p for (p,) in c.execute(text(
            "select payload from knowify_raw_records where entity='deliverables' and is_present")).all()]

    # ---- pass 1: the roof lines the benchmark is built from --------------------------------
    # contract id -> {"year": int, "lines": [(material, roof_type, squares, $/sq)]}
    jobs: dict[int, dict] = {}
    for d in delivs:
        if (d.get("UnitName") or "").strip().lower() not in ("squares", "square", "sq"):
            continue
        if d.get("IsChangeOrder"):
            continue
        qty, price = d.get("Quantity"), d.get("Price")
        if not qty or not price:
            continue
        sq, dollars = float(qty) / QTY_SCALE, float(price) / CENTS
        if sq < 5 or sq > 200 or dollars < 2000:
            continue
        hit = _bucket(d.get("Description") or "")
        if not hit:
            continue
        ct = contracts.get(d.get("ContractId"))
        created = (ct or {}).get("DateCreated")
        if not created:
            continue
        proj = projects.get(ct.get("ProjectId")) or {}
        zip_code = proj.get("Zip") or (clients.get(ct.get("ClientId")) or {}).get("Zip")
        j = jobs.setdefault(d["ContractId"], {
            "year": int(created[:4]), "lines": [], "state": ct.get("BusinessState"),
            "zip": zip_code})
        j["lines"].append((hit[0], hit[1], sq, dollars / sq))

    # BusinessState is the ACCEPTANCE marker, not IsSigned (only 5% of contracts carry the
    # e-signature flag). Proof: of the roof-line contracts in state "Open", 200 of 202 in
    # 2023-2026 were also invoiced, versus ~0 of the "OutForSigning" ones. "OutForSigning" is
    # a proposal the customer has not accepted.
    print(f"contracts carrying a per-square roof line: {len(jobs)}")
    print("  by state: " + ", ".join(
        f"{k}={v}" for k, v in Counter(j["state"] for j in jobs.values()).most_common()))
    print()
    print("ACCEPTED vs OUTSTANDING median $/sq — the benchmark used to date included both")
    print(f"{'material':10}{'accepted $/sq':>18}{'outstanding $/sq':>20}{'gap':>9}")
    for name, _, _ in MATERIALS:
        acc = [px for j in jobs.values() if j["state"] == "Open" and j["year"] >= 2024
               for m, _, _, px in j["lines"] if m == name]
        out = [px for j in jobs.values() if j["state"] == "OutForSigning" and j["year"] >= 2024
               for m, _, _, px in j["lines"] if m == name]
        if len(acc) < 3 or len(out) < 3:
            continue
        a, o = float(np.median(acc)), float(np.median(out))
        print(f"{name:10}{a:>12,.0f} n={len(acc):<4}{o:>14,.0f} n={len(out):<4}"
              f"{100 * (o / a - 1):>8.0f}%")
    print()
    # ---- branch composition of the benchmark -----------------------------------------------
    print("WHERE THE SOLD-PRICE BENCHMARK COMES FROM (county of the job / client address)")
    comp = Counter(_county(j["zip"]) for j in jobs.values())
    total = sum(comp.values())
    for name, n in comp.most_common():
        print(f"  {name:16} {n:5}  {100 * n / total:5.1f}%")
    recent = Counter(_county(j["zip"])
                     for j in jobs.values() if j["year"] >= 2025)
    print("  2025-2026 only: " + ", ".join(f"{k} {v}" for k, v in recent.most_common(5)))
    print()

    jobs = {k: v for k, v in jobs.items() if v["state"] == "Open"}
    print(f"ACCEPTED jobs used for the identity below: {len(jobs)}\n")

    # ---- pass 2: the recovery identity ------------------------------------------------------
    days_by_year: dict[int, float] = defaultdict(float)
    jobs_by_year: dict[int, int] = defaultdict(int)
    modelled = Counter()
    sq_by_year: dict[int, float] = defaultdict(float)

    for j in jobs.values():
        year, job_days, sloped_sq = j["year"], 0.0, 0.0
        for material, roof_type, sq, _ in j["lines"]:
            if roof_type is None:          # low-slope: no fitted day model exists
                modelled[f"unmodelled:{material}"] += 1
                continue
            modelled[f"modelled:{material}"] += 1
            sloped_sq += sq
            # install days only — demo is charged once per job below.
            series = derive_daily_series(cfg, QuoteInput(
                code_zone="HVHZ", slope_type="sloped", roof_type=roof_type, num_squares=sq,
                project_kind="residential", demo=False, existing_roof="none"))
            job_days += sum(s.days for s in series)
        if sloped_sq > 0:
            demo = derive_daily_series(cfg, QuoteInput(
                code_zone="HVHZ", slope_type="sloped", roof_type=j["lines"][0][1] or "13_tile",
                num_squares=sloped_sq, project_kind="residential", demo=True, existing_roof="tile"))
            install_only = derive_daily_series(cfg, QuoteInput(
                code_zone="HVHZ", slope_type="sloped", roof_type=j["lines"][0][1] or "13_tile",
                num_squares=sloped_sq, project_kind="residential", demo=False, existing_roof="none"))
            job_days += sum(s.days for s in demo) - sum(s.days for s in install_only)
        if job_days > 0:
            days_by_year[year] += job_days
            jobs_by_year[year] += 1
            sq_by_year[year] += sloped_sq

    print("line coverage:", ", ".join(f"{k}={v}" for k, v in sorted(modelled.items())))
    print()
    print("RECOVERY IDENTITY — Miami (the mirror's population), estimator days vs calendar")
    print(f"{'year':6}{'jobs':>7}{'squares':>10}{'OH days charged':>17}{'working days':>14}"
          f"{'ratio':>9}{'over/under':>13}")
    for year in sorted(days_by_year):
        wd = _working_days(year)
        if not wd:
            continue
        ratio = days_by_year[year] / wd
        print(f"{year:<6}{jobs_by_year[year]:>7}{sq_by_year[year]:>10,.0f}"
              f"{days_by_year[year]:>17,.1f}{wd:>14}{ratio:>9.2f}"
              f"{100 * (ratio - 1):>12.0f}%")
    print()
    print("ratio 1.0 = the days the estimator bills exactly fill the calendar it bills against.")
    print("Sloped re-roofs ONLY: low-slope lines have no fitted day model, and repairs/service")
    print("(no per-square line) are excluded entirely — both consume real calendar days, so the")
    print("true ratio is HIGHER than printed. This is a floor, not a point estimate.")


if __name__ == "__main__":
    main()
