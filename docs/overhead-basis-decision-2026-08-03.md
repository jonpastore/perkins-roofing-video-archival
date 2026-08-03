# Overhead basis + concurrent_crews — priced before/after

**2026-08-03.** Two decisions Tim answered on 2026-07-30 that were never applied. Both are money
on live quotes. Reproduce:

```bash
DB_URL=… PYTHONPATH=. .venv/bin/python scripts/overhead_basis_whatif.py    # what it MOVES
DB_URL=… PYTHONPATH=. .venv/bin/python scripts/overhead_basis_backtest.py  # what is RIGHT
```

## Where things stand

| key | jupiter | miami | naples | Tim, 2026-07-30 |
|---|---|---|---|---|
| `overhead_basis` | series | **branch** | series | — |
| `office_daily_overhead` | 1400 | 4250 | 1400 | **1,470 / 4,257** |
| `concurrent_crews` | **unset** | **unset** | **unset** | **1.5 / 4** |

`concurrent_crews` unset defaults to **1.0** — every job carries a full office day. It applies to
`overhead_basis='branch'` **only**; under `series` the per-activity rates are already per-crew-day
numbers and dividing them again would discount the same split twice.

## 1. What each change MOVES — 96 of 101 real stored estimates, re-priced through the engine

Median change vs today. Scenarios differ only in the keys above; every other value is the live config.

| scenario | jupiter (n=60) | miami (n=34) | naples (n=2) |
|---|---|---|---|
| today | — | — | — |
| + Tim's crews (1.5 / 4) | +0.0% | **−35.4%** (min −46.2%) | +0.0% |
| branch basis + his crews + his daily | +1.1% | −35.3% | +2.3% |
| branch basis + measured crews (J 1.2) | +5.4% | −35.3% | +6.9% |

Jupiter/naples show +0.0% for the crews row because they are on `series`, where the key does
nothing. **Miami is the whole story: it is on branch basis with crews unset, so every job is
charged the full $4,250 office day.**

*(5 miami estimates excluded — ids 27–31, all `roof_type='tpo_adhered'` stored with
`slope_type='sloped'`, which today's config cannot price. Created 7/21–7/23 under configs 21/24,
$10,150 each, **none reached a proposal**. Latent data defect, no customer exposure.)*

## 2. Which is RIGHT — scored against what Tim actually charged

His 2026-07-27 workbook carries his own day counts **and** his actual price per home, so each
scenario is scored on 35 real priced cases using **his** days (never our day model — an error in
days would otherwise be scored as an error in the basis).

| scenario | median err | within 5% | within 10% | median abs err |
|---|---|---|---|---|
| **1 today — series (his 4 rates)** | **+1.0%** | **17/35** | **27/35** | **5.2%** |
| 2 branch basis, crews 1.5 (his) | +2.1% | 14/35 | 26/35 | 5.5% |
| 3 branch basis, crews 1.2 (measured) | +5.8% | 12/35 | 22/35 | 7.2% |
| 4 branch basis, crews **1.0** — *what Miami runs today* | +10.9% | 8/35 | 15/35 | **10.9%** |

⚠️ Palm Beach / Martin / St Lucie homes only, so FBC and Jupiter's rates. This scores the
**jupiter/naples** question. It cannot score Miami, which has its own burn and no comparable price
log.

## What the numbers say

**Miami — change it.** `crews = 1.0` is the worst-scoring configuration in the only place we can
measure it (15/35 within 10%, systematically **+10.9%** high), and Miami is running exactly that
on 34 live estimates in 30 days. This is not a preference call; it is the one setting the evidence
condemns. Tim's `4` is a capacity target, not a measurement — so the number is his to confirm, but
`1.0` is demonstrably not it.

**Jupiter / naples — leave on `series`.** Flipping to branch basis costs about a point of accuracy
(27/35 → 26/35, 5.2% → 5.5% median abs) — a tie within noise on n=35, so there is no accuracy case
for churning it. They are **already day-based**: `series` is Tim's own four per-day rates
(tile 745 / metal 850 / shingle 700 / demo & flat 1050), just per activity instead of per branch.

**`office_daily_overhead` 1400 → 1470** matters only under branch basis, so today it changes
nothing on jupiter/naples. Miami's 4250 → 4257 is +0.16%.

**It will not fix Tim's headline complaint.** He wrote *"only 2/3 of jobs are even within 10%"*.
At best we reach 27/35 = 77%, and the basis moves that by one job. The residual is **days and
complexity**, not the overhead basis — which is what his own *"suggested pricing and a suggested
# of days that can be edited within the cell"* asks for.

## Not addressed here

The low-slope install-days model. Note that **9 of Tim's homes carry both flat squares and flat
days**, so the data the `SLOPED ONLY` filename implies is missing partly exists — enough to
scope a fit, not enough to trust one at n=9.
