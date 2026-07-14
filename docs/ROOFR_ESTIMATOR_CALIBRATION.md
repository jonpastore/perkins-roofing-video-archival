# Estimator calibration vs Roofr golden measurements + sold proposals

Roofr is the source of truth for measurements. This calibration feeds the **Roofr
squares** from `roofr_baseline.json` (extracted from Tim's golden attachments) into the
cost-plus estimator using the **production-active pricing config** (branch `miami`, hash
`dc8775b6…`, snapshotted at `tests/fixtures/golden/roofr_calibration/active_pricing_config.json`)
and compares the estimator's PROTECTOR base to Tim's sold PROTECTOR base line.

## Results (residential, standard slope, 1-story assumption)

| Job | System | Roofr SQ | Est. base | Sold base | Est/Sold |
|-----|--------|---------:|----------:|----------:|---------:|
| Butterworth | tile | 23.79 | $28,186 | $28,320 | 100% |
| Thompson | metal | 35.48 | $39,981 | $39,985 | 100% |
| Mazzeo | tile | 37.05 | $42,238 | $43,938 | 96% |
| Allen | shingle | 34.58 | $24,163 | $22,840 | 106% |
| Palmer* | metal | 25.86 | $30,091 | $38,380 | 78% |
| Malooley* | tile | 64.28 | $71,265 | $94,460 | 75% |

`*` Excluded from the tight-tolerance regression assertion — Tim's sold price carried a
documented surcharge the base estimate does not model:
- **Palmer** — 3-story + 6/12 slope surcharge.
- **Malooley** — 76 SQ premium (Mediterranean) tile job.

Two golden proposals (Person, Meharg) have no Roofr baseline extracted, so they are not in
the calibration set.

## Interpretation

For standard-slope / standard-height single-system jobs, the cost-plus estimator, fed Roofr
squares, reproduces Tim's sold PROTECTOR base within ~±6% — strong evidence the pricing
config and per-square build-up are calibrated to real sold work. The two outliers are
explained by documented surcharges/premium tiers, not model error.

## What this validates vs. not

- Validated: estimator base $/project for standard jobs ≈ Tim's sold base.
- Not yet modeled automatically: 3-story/steep-slope surcharge, large-job premium tiers,
  gutters/accessory LF lines, discounts — these are the sold-total deltas above the base.

## Reproduce

- Regression test: `tests/test_roofr_calibration.py` (pins standard jobs within 10%).
- Measurement import (prod): `scripts/import_roofr_golden_measurements.py --cloud-sql-connector --apply`
  creates `provider="roofr_fixture"` measurements linked to golden customers/properties.
