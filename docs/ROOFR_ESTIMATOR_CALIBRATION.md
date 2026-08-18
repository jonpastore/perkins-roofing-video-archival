# Estimator vs sold PROTECTOR lines (honest harness)

This is **not** a claim that we reprint Tim's Knowify PDFs. Those PDFs live in
`~/perkins-corpus/` (mostly Roofr *measurement* reports). The one real Knowify
proposal in `golden-proposals/` is Josh's 30 SQ tile test roof at **$33,000**.

The 7/25 and 7/26 "worked examples" PDFs are **engine output we generated**, not
Tim's sold book. They disagree with each other on the same house when the weekly
floor basis flips. Do not call them golden.

Exhibit-B JSON fixtures (`tests/fixtures/golden/28sq_*.json`, `41_5sq_*.json`)
are **closed-loop unit tests** of the per-square table. They pass
`overhead_mode=per_sq` explicitly. They are not sold jobs.

## What the harness actually does

`tests/test_roofr_calibration.py` (rewritten 2026-08-15):

- Roofr **pitched / flat** split, not `total_sqft` billed as one sloped system
- `demo=True` (every sold PROTECTOR tears off)
- `overhead_mode=daily` — Tim, 2026-08-03: overhead is days; per-sq is a guide
- compares engine `project_total` to the **sum of PROTECTOR / flat / 3-ply lines**
  (copper, paint, gutters, named discounts stripped)

Tolerance is **±15%**. That is the remaining method gap (catalog specials, waste,
unmodeled extras), not a 100% calibration.

Butterworth is mixed (8.28 pitched + 15.51 flat). Pricing it as 23.79 SQ of tile
against the sold *flat* line of $28,320 was a false 100%.

Palmer (3-story) and Malooley (waste / second structure / 76 SQ) are exercised
for "still prices", not for a ratio.

Person and Meharg have no Roofr row.

## Josh 30 SQ

`knowify_jon_test_roof_2026-08-08.pdf` (2026-07-08): PROTECTOR tile, 30 SQ,
**$33,000** ($1,100/sq catalog). The engine cost-up is ~$35,450–$35,700. The
catalog number is what he charged; `package_options()` still layers adders on
the engine total. Closing that last gap is a product call (catalog as headline
vs engine as headline), not a missing formula.
