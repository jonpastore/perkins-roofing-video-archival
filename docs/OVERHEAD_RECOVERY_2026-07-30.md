# Overhead: the recovery identity, run — and what it overturns

**2026-07-30.** Reproduce with `scripts/recovery_identity_jupiter.py` and
`scripts/recovery_identity_miami.py`. Nothing in pricing was changed.

The two adversarial reviews (`~/perkins-corpus/ai-reviews/`) named one test as the only
non-circular way to judge an overhead model:

    ratio = SUM(overhead charged over a period) / (branch daily burn x working days)

Under `overhead_basis="branch"` the burn cancels and it reduces to a pure day count:
**estimator-charged job-days ÷ calendar working days.** No sold price enters, so it cannot be
passed by wrong overhead plus compensating profit. It had never been run. It has now.

---

## 1. Miami is NOT priced at $1,400/day. It has charged $4,250/day since 2026-07-28.

The brief given to both reviewers said *"all three branches are `overhead_basis='branch'` with a
flat $1,400/day."* That was true until `miami` config **v27** (2026-07-28) set
`office_daily_overhead = 4250`, and **v29** is live. Both reviewers' lead finding — Miami
recovering ~1/2.9 of its office because it runs on Jupiter's number — rests on a premise that the
database contradicts. It was right on 2026-07-25; it is wrong today.

What the live configs actually quote, 30 SQ, tear-off, `overhead_mode="daily"`:

| branch | zone | roof | days | overhead | $/sq total | Miami/Jupiter accepted median |
|---|---|---|---|---|---|---|
| jupiter | FBC | 13" tile | 7.0 | $9,800 | **$1,390** | — |
| miami | HVHZ | 13" tile | 7.0 | **$29,750** | **$2,087** | $1,113 (n=21) |
| miami | HVHZ | shingle | 4.5 | $19,125 | $1,306 | $720 (n=40) |
| miami | HVHZ | metal | 6.5 | $27,625 | $2,256 | $1,263 (n=13) |

**Miami quotes now run ~80% ABOVE the prices Miami customers actually accept**, and roughly
$1,000/sq of a tile quote is overhead alone. The direction of the error reversed when v27 landed:
it is over-pricing, not under-pricing. `naples` still carries Jupiter's $1,400 — that half of the
criticism stands.

The cause is the conceptual hole Grok did identify: **the estimator charges one job the entire
branch calendar-day burn.** At Jupiter's $1,470 that is a ~13% distortion. At Miami's $4,257,
with Tim's own "4 crews/day minimum," it is ~4x.

## 2. Jupiter's day model is approximately calibrated. Ratio 1.19 (1.07 without one outlier).

19 months of ACCEPTED Jupiter work (60 contracts, 2025-01 → 2026-07), days from the shipped
geometry/squares model, against every working day in the window including the months that sold
nothing:

```
estimator-charged overhead days   465.5
calendar working days             392
ratio                             1.19        ( 1.07 excluding one 290-sq metal job )
$ charged at Tim's $1,470/day     $684,285  vs  $576,240 of burn   (+$108,045)
```

Low-slope lines (14 lines, 167 sq) have **no fitted day model**, so their days are missing and the
true ratio is higher. This is the first non-circular evidence about the model, and it says the
Jupiter shape is close: charging ~1.19 job-days per calendar day is a modest over-recovery that
repairs, callbacks and vacant days plausibly absorb.

It also settles the "1.5 crews" question empirically. 1.5 concurrent jobs would put the ratio near
1.5. Measured 1.19, and the logged headcount is 6.17 men/day, not the 8 the slogan implies. **The
log and the recovery identity agree with each other and both disagree with "1.5 crews."**

## 3. Miami's ratio is 0.5–0.7. It cannot fund its office from the work it sells.

Same test on the Miami mirror (sloped re-roofs only, so again a floor):

| year | accepted jobs | OH days charged | working days | ratio |
|---|---|---|---|---|
| 2022 | 50 | 345.5 | 252 | 1.37 |
| 2023 | 64 | 404.5 | 252 | 1.61 |
| 2024 | 26 | 129.0 | 254 | 0.51 |
| 2025 | 30 | 169.5 | 253 | 0.67 |
| 2026 | 16 | 96.0 | 145 | 0.66 |

Accepted re-roof volume fell ~60% after 2023 — the same quarter Tim says Miami started losing
money. At a 0.66 ratio the office is only 2/3 funded before any rate question is asked, and
closing that gap by raising the day rate is what produced the $2,087/sq quote in §1. **No
allocator fixes Miami**; the burn is too large for the volume it sells. That is a business
finding, not a config one.

## 4. The "sold $/sq" benchmark is Miami PROPOSALS, not Jupiter sales.

Two population defects in the numbers every model comparison was scored against, both verifiable
in the mirror and invisible to the reviewers:

- **Wrong branch.** The local Knowify mirror holds ONE tenant and it is the **Miami** company
  (8,510 projects; 83% Miami-Dade/Broward, 10% Palm Beach, and only 15 of 370 recent jobs in Palm
  Beach). Tim's **Jupiter** company is a separate tenant (30586/28403, 995 projects) reachable
  only through the Knowify MCP. Quotes built on Jupiter's config were being scored against
  Miami's prices.
- **Wrong state.** Of 3,357 roof-line contracts only **386 were ever accepted**
  (`BusinessState="Open"`, which matches invoicing 200/202 — `IsSigned` is set on just 5% of
  contracts and is not the acceptance marker). The benchmark counted the 2,839 `OutForSigning`
  proposals too. On 2024+ data those outstanding proposals sit **4–17% above** what customers
  actually accepted (metal +17%).

So "our quote is +0.8% vs the 2026 sold median" compared a Jupiter quote to a mostly-unaccepted
Miami proposal median. Withdrawn, as both reviewers said for separate reasons.

---

## What this changes about the next step

The open decision was framed as *per-day-by-roof-type vs per-man-day × crew size*. The identity
says that is the wrong first question — it moves Jupiter a few percent inside a model already
landing at 1.19, while the unallocated parallel-job divisor moves Miami by ~4x. **Define the
divisor first:**

    overhead charged per job-day = branch daily burn / concurrent jobs per day

with the divisor measured, not assumed — the recovery identity is exactly the measurement
(Jupiter 1.19; Miami's own target is Tim's 4 crews/day). Only then does the shape of the rate
table matter.

Still true and unchanged: cost and materials reproduce all four sheet quadrants at 0.0%; the four
emailed rates under-recover Tim's own $1,470 under his own 1.5-crew assumption; sheet productivity
(metal 5.5 sq/day vs an actual 8.0) is a larger error than any rate choice.

---

# 5. Per-square vs per-day, scored against the prices Tim actually charged

`scripts/compare_oh_models_vs_tim_prices.py`. 35 priced observations across 27 of Tim's 30 homes
(a home he quoted in two materials is two observations). Days are HIS, never derived, so a day
model cannot be blamed on our geometry fit. Everything except the overhead line is identical.

| model | within 5% | within 10% | median error | median abs |
|---|---|---|---|---|
| A per-square (his published $/sq table) | 13/35 | 24/35 | −2.4% | 6.4% |
| B day × flat branch $1,400 — **the live basis** | 10/35 | 16/35 | +10.3% | 10.3% |
| C day × his four per-roof-type rates | **15/35** | **29/35** | +2.2% | 6.5% |
| D day × flat branch $1,470 | 8/35 | 14/35 | +12.3% | 12.3% |

**The configuration running in production today is the worst of the four**, over-quoting by a
median 10%. Tim's four emailed rates are the best. That is a direct answer to "reproduce his
quotes," and it is independent of the sold-median benchmark that had to be withdrawn.

## Why one model is right on one job and wrong on the next

They are the same formula. Per-square is `OH = oh_per_sq × SQ`; per-day is
`OH = blended_rate × SQ / sq_per_day`. They cross at one productivity:

| roof | his $/sq OH | blended day rate | break-even | his actual median |
|---|---|---|---|---|
| tile | $185 | $861 | 4.7 sq/day | 4.3 sq/day |
| shingle | $105 | $910 | 8.7 sq/day | 7.7 sq/day |
| metal | $205 | $936 | 4.6 sq/day | 4.7 sq/day |

Below the break-even the roof is slow — cut up, steep, bad access — and the day model charges
more. Above it the roof is simple and the day model charges less. **The per-square table is the
day model evaluated at one fixed productivity**, which is exactly why it is right on ordinary
roofs and wrong on hard ones. Measured on his own jobs:

- slow, under 4 sq/day (n=7): per-square is **−16.8%** — it under-charges the hard jobs badly.
  Day-series −5.2%.
- access issue (n=7): per-square −12.6%, day-series −0.8%.
- mixed flat + sloped (n=10): per-square −9.8%, day-series +7.5%.
- 4/12 pitch (n=9): per-square **+0.1%**, and it beats the day model on 7 of 9. Day-series +7.7%.

## The switch input is PITCH, and it is the only one that beats both pure models

| rule | within 5% | within 10% | median abs |
|---|---|---|---|
| pure per-square | 13/35 | 24/35 | 6.4% |
| pure day-series | 15/35 | 29/35 | 6.5% |
| **per-square when pitch ≤ 4/12, day-series otherwise** | **18/35** | **31/35** | **4.8%** |
| per-square when no access issue | 15/35 | 28/35 | 6.0% |
| per-square when no flat section | 12/35 | 25/35 | 6.4% |

A sweep on productivity (`day-series when sq/day < T`) never beats pure day-series at any T, so
productivity is the *explanation* of the divergence but not a usable switch. Pitch is, and it is
physically sensible: **his $/sq table carries no pitch term at all**, so it can only be right
where pitch is neutral.

⚠️ n=35 across 27 homes, and pitch takes three values (4, 5, 6). The rule is fitted to this set.
The direction is the finding; the threshold needs re-checking on jobs quoted after it is chosen.

## What to ship

One model with one knob, not two models:

    OH = rate_by_roof_type(series) × days        days = SQ / sq_per_day

Set `sq_per_day` to the break-even constant above and it reproduces Tim's published $/sq table
exactly; let it move with measured complexity (geometry, pitch, access) and it becomes his time
model. Per-square stops being a second model and becomes the default productivity — one place to
adjust, which is what a seasonal or per-branch adjustment needs to hang off.
