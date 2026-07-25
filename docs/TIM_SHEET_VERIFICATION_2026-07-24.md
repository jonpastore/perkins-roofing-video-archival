# Verified against Tim's live calculator (2026-07-24)

Source: Tim's own sloped calculator, read read-only via the DWD service account
(`1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig`, tabs `FBC (Palm / Lee / St. Lucie)` and
`OH Metrics`). Not a copy — his live sheet.

## Every config number matches his sheet exactly

| Item | Tim's FBC tab | Our config | |
|---|---:|---:|:--|
| Base 13" tile | $770 | $770 | ✅ |
| Base barrel tile | $1,435 | $1,435 | ✅ |
| Base 3-tab shingle | $395 | $395 | ✅ |
| Base dimensional shingle | $420 | $420 | ✅ |
| Base standing seam metal | $750 | $750 | ✅ |
| OH shingle | $105 | $105 | ✅ |
| OH 13" tile | $185 | $185 | ✅ |
| OH barrel tile | $350 | $350 | ✅ |
| OH standing seam | $205 | $205 | ✅ |
| Profit sliding scale | 1sq $400 · 2-4 $200 · 5-7 $160 · 8-14 $140 · 15-20 $120 · 20-29 $110 · 30+ $100 | identical | ✅ |
| Roof cuts low/med/high | $0 / $25 / $50 | same | ✅ |
| 2 stories | $50 | same | ✅ |
| Tile pointing | $200 | same | ✅ |
| PM incentive | <20sq $50 · 20-50 $100 · >50 $250 | same | ✅ |
| Delivery/plywood/vents | $650 | $650 | ✅ |
| New bonus values | $1,350 | $1,350 | ✅ |
| Permit processing | $500 | $500 | ✅ |
| Tile dumpster | $300 | $300 | ✅ |
| Santa Fe Clay "S" upgrade | $160 | $160 | ✅ |

**The estimator engine reproduces Tim's method.** His tab is the same cost-up build:
base + OH + sliding-scale profit + adders + fixed costs, and his worked example shows
`TOTAL PER SQ $595 → 57.5 SQ → PROJECT TOTAL $36,713`, `PROFIT % 13.45`, `PROFIT/OH % 29.41` —
the same shape and the same floors our engine enforces.

## There is NO size-tiered sell-price table in his sheet

Nothing in Tim's calculator publishes a flat `$/sq` per tier. His price *is* the cost-up build,
and job size enters only through the profit sliding scale and the spread of fixed costs. So the
earlier idea of "tier the labor" has no counterpart in his model — and the flat catalog
`$1,100/sq` in `core/perkins_packages.py` is **not from his calculator at all**.

## The OH Metrics tab settles the two-overhead-modes question

His overhead is **production-rate driven**: a daily crew cost divided by squares-per-day per task.

- Daily OH basis by crew size: 9 men $460/day · 12 men $345 · 15 men $275
- Squares per day per task: tile removal 45 · tile demo+dry-in 25 · 13" tile install 8 ·
  barrel tile install 4 · metal install 5.5 · shingle install 25 · SA underlayment 50
- Rolled up: 13" tile re-roof OH $362 (9 men) / $271 (12) / $216 (15); shingle $147/$110/$88;
  metal $343/$257/$205; barrel tile $475. FBC at 13 men: tile $272 · barrel $366 · shingle $118 ·
  metal $315.

**`days = SQ ÷ squares_per_day` — pure rate, no fixed setup term.** That makes his OH per square
*constant* with job size, which is exactly why a flat per-square OH is correct in his framework.

This invalidates the fitted `days = setup + rate × SQ` model in
`docs/ROOFR_OVERHEAD_TIERS.md`: the setup constant is what made by-days diverge from per-square
(higher on small jobs, lower on big ones). The fix is to drop the setup term and derive days from
his production rates, which reproduces the per-square OH the config already carries — the two
modes then agree by construction instead of needing a reconciliation.

⛔ Still needs Tim: which **crew-size column** each branch should price from (9/12/15 men, or the
FBC 11/14/18 variant). The config's current values sit between his columns.

## Two real defects this exposes

1. **Barrel tile is quoted below cost through `/proposal-gen`.** `core/proposal_gen.py` prices by
   SYSTEM via `sell_price_per_sq("tile", tier)` = **$1,100/sq**, and `_ROOF_TYPE_SYSTEM` maps BOTH
   `13_tile` and `barrel_tile` to `tile`. Tim's barrel tile base cost alone is **$1,435/sq** before
   any overhead or profit. Any barrel tile proposal built on the catalog price loses money on every
   square. The estimator path is unaffected — `package_options()` uses the engine total — so this is
   specifically the catalog/`proposal_gen` path.
2. **The catalog and the engine disagree by construction.** A flat `$/sq` cannot equal a cost-up
   build across job sizes: engine 13" tile runs $1,420/sq at 10 SQ down to $1,129/sq at 100 SQ
   against a flat $1,100. Josh's $33,000 sale of a 30 SQ tile job (engine: $35,700) is that gap.
   Either the catalog becomes size-banded, or it is treated as a marketing anchor and the engine
   remains the quoted price with any difference booked as an explicit discount.

## Evidence base is thin — one proposal

Only ONE real Perkins proposal has been run through our system: Josh's "Jon test roof"
(`~/perkins-corpus/golden-proposals/knowify_jon_test_roof_2026-07-08.pdf`, 30 SQ tile PROTECTOR,
$33,000). The other six PDFs in that folder are RoofR *measurement* reports, not proposals. Every
conclusion about matching Tim's numbers rests on n=1 plus his calculator; the 8 "JOB SOLD" packages
from the July 10-11 emails should be pulled and run before treating the tier question as settled.
