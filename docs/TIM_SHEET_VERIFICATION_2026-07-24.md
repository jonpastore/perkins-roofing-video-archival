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
*constant* with job size, which is why a flat per-square OH is coherent in his framework.

⚠️ **But do not conclude from this tab that the setup term is wrong** — see §3 of the 30-home
appendix below, which tests both shapes against his own 30 estimates. Dropping the setup term makes
shingle *worse than predicting the mean* (R² −0.10 vs 0.378). The OH Metrics tab describes his
crew **planning** rates; his per-home estimates carry a real fixed setup component. Keep
`days = setup + rate × SQ` (`docs/ROOFR_OVERHEAD_TIERS.md`).

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

---

# All 30 of Tim's homes run through the estimator (2026-07-24)

`scripts/validate_against_tim_30_homes.py` — reads the 30 rows of
`Residential OH Calculator (SLOPED ONLY).xlsx` (existing roof, sloped squares, and Tim's own day
estimate for demo + each material), quotes each like-for-like (tile→tile, shingle→shingle,
metal→metal) at FBC / jupiter, and compares three prices per home.

## 1. The catalog under-quotes Tim's own build on 30 out of 30 homes

| Roof type | n | mean catalog − engine | worst |
|---|--:|--:|--:|
| 13" tile | 16 | **−$82/sq** | −$129/sq |
| dimensional shingle | 11 | **−$57/sq** | −$150/sq |
| standing seam metal | 3 | **−$73/sq** | −$98/sq |
| **all** | **30** | **−$72/sq** | −$150/sq |

Not one home priced at or above the engine. So the flat catalog is not merely a barrel-tile
problem — it is **systematically below Tim's guide on every system**, worst on small jobs (16.5 SQ
shingle: −$150/sq). On a 35 SQ tile job that is ~$2,900 of margin per roof.

## 2. Per-square OH and Tim's ACTUAL days agree to ~1%

Mean $/sq across the 30: **engine (per-square OH) $1,009 · engine fed Tim's own days $1,019**.
A 1% difference in aggregate (individual homes vary ±$50/sq). Our configured per-square overhead
therefore reproduces Tim's real day estimates on realistic FBC jobs — the alarming divergence
measured in `OVERHEAD_MODE_RECONCILIATION.md` is confined to **barrel tile** (whose $350/sq
per-square OH is the outlier) and to very small jobs, not to the mode choice itself.

## 3. Correction: Tim's day data does NOT support a pure production-rate model

Least squares over his 30 homes, `setup + rate×SQ` vs `rate-only` (his OH Metrics shape):

| Series | setup + rate×SQ | R² | rate-only | R² |
|---|---|--:|---|--:|
| demo | 1.31 + 0.0436/SQ | **0.371** | 0.0752/SQ (13.3 SQ/day) | 0.157 |
| tile | 0.45 + 0.1291/SQ | **0.700** | 0.1400/SQ (7.1 SQ/day) | 0.694 |
| shingle | 1.06 + 0.0237/SQ | **0.378** | 0.0492/SQ (20.3 SQ/day) | **−0.102** |
| metal | 0.59 + 0.1056/SQ | **0.661** | 0.1198/SQ (8.4 SQ/day) | 0.648 |

The fixed setup term is **real** for demo and shingle — dropping it makes shingle worse than
predicting the mean (R² −0.10). For tile and metal both forms fit equally well, and rate-only
tile lands at 7.1 SQ/day against the 8 SQ/day in his OH Metrics tab, so the two are consistent
there. Conclusion: keep `days = setup + rate×SQ` (it fits his own numbers as well or better
everywhere); the OH Metrics tab describes his *planning* rates, not the shape of his estimates.

## What to do about the money bug

`core/proposal_gen.py` now refuses to price a **tile** full price from the catalog and demands an
explicit estimator-derived `unit_price` (`requires_engine_price()`); the route already maps that
to a 422 with the reason. Upgrade adders still price off the catalog, correctly — an upgrade is a
flat per-square material swap.

Tile is fenced because its spread is $665/sq. Shingle and metal are left catalog-priceable to
avoid breaking the live endpoint, but the table above shows they under-quote too (−$57 and −$73/sq
mean), so the same treatment should follow once callers reliably pass engine prices. **Decision for
Tim/Jon: retire the flat catalog as a price entirely and quote from the engine, or re-issue it as a
size-banded table.**
