# Estimator v2 — Tim's feedback (2026-07-10, deferred to next work block)

Tim wants two changes to the estimating engine. Both change the COMPOSITION, not just
values. NOTE (tension): this is a different overhead methodology than the Exhibit B sheet
we verified today (per-square OH). Tim's day-based OH is his real-world mental model —
treat this as the estimator-v2 model; keep the per-sq path or migrate, decide at build.

## 1. Daily overhead (replaces/augments per-square OH)

Overhead is charged PER DAY per work series, then divided across the job's squares.

Daily rates:
- Demo / Dry-in / Flat roof: **$1,050/day**
- Tile install: **$745/day**
- Metal install: **$850/day**
- Shingle install: **$700/day**

UI: the estimator enters **number of days per series, to the half-day** (0.5 increments).
A job can have multiple series (e.g. demo + install of a different material).

OH_total = Σ (days_series × rate_series)
per_square_OH = OH_total / num_squares

Worked example (Tim's): 40 SQ shingle→metal, cut up:
- Demo: 2 days × $1,050 = $2,100
- Metal: 5 days × $850 = $4,250
- OH_total = $6,350 → $6,350 / 40 = **$158.75/sq**

## 2. Absolute-dollar profit (alongside the % sliding scale)

Percentage is fine, but Tim wants to enter a **total profit dollar amount** for the job.
His rule of thumb: **≥ $2,500 per week the crew is on-site**, and **≥ $2,500 minimum per
job regardless of size** (a small 8 SQ / 1.5-day re-roof still carries full liability, so
it must clear the same floor).

Same example: 7 days of work on the 40 SQ metal roof → he'd charge **≥ $5,000 profit**
(it ties up ~2 weeks of scheduling window after inspections), not whatever the sliding
scale yields.

Design: profit MODE selector — (a) sliding scale (existing), or (b) flat dollar entry —
with guidance/validation surfacing the weekly-minimum ($2,500 × on-site-weeks, derived
from total series days) and the $2,500 absolute-per-job floor. Show the implied
$/week so Tim can sanity-check.

## Build notes
- New config: daily_overhead_rates (per series) + a profit_mode field; both tenant-editable
  via the versioned pricing-config flow (like all other rates).
- Engine: a day-based OH path + a flat-dollar profit path; keep both selectable so the
  Exhibit B per-sq/scale model still works for existing golden files.
- UI (Estimator.tsx): per-series day inputs (0.5 step) + profit-mode toggle + live
  $/week readout.
- TDD; validate against Tim's two worked examples as golden cases; R1 core 100%.
- Ties to #318/#324 — reconcile with the 5× golden proposals when they arrive.
