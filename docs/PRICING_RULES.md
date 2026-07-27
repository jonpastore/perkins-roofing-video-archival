# Perkins Roofing — how a price is built

**Every rule below is Tim's, and every one names where it came from** — a cell on the live
calculator, a comment behind that cell, a line in an email, or a moment on a recorded call. Nothing
here is a DeGenito assumption. Where something *is* still an assumption it is marked **OPEN** and
says so.

Last updated 2026-07-27. Source of truth for the numbers: `infra/fixtures/pricing_config_exhibit_b.json`
(git) and the active `pricing_configs` row per branch (prod). This document explains the rules; the
config carries the values.

---

## 1. The order a re-roof is priced in

```
  Base cost (labour + materials)      squares × base $/sq       ← from the cut calculator
+ Overhead                            Σ (days × daily rate)     ← from TIME, not squares
+ Profit                              sliding scale, then floor
+ Demo                                squares × demo $/sq
+ Fixed fees                          delivery, bonus, permit, dumpsters, PM incentive
= PROJECT TOTAL
```

Two things make this Perkins' method rather than a generic roofing calculator: **overhead comes from
days**, and **days come from the roof's geometry**, not its size.

> "you have two houses that are both 30 squares but one got towers and all kinds of crazy shit going
> on and one could just be like this up and over — this one is going to take two days and then the
> one with all the crazy shit going on could take five or six days … that's why it's very important
> to do things based on time." — Tim, Zoom 2026-07-17 [10:12]

---

## 2. Base cost — the cut calculator

Roofers who price per square "are stupid, because you're not accounting for how many cuts are
actually on the roof" (Tim, 7/17 [37:54]). The base cost is therefore computed from the RoofR
measurements, not from squares alone.

| input | rounding | source |
|---|---|---|
| eaves, hips + ridges, rakes, wall flashings | up to nearest **10 ft** | materials come in 10-ft pieces (7/17 [00:10]) |
| valleys | up to nearest **50 ft** | `cuts_calc.rounding` |

Components: drip metal + SA V strips, valley metal, field tiles and mortar, hip/ridge/rake tiles and
H&R metal, eave closure metal, tile delivery, plus a fixed per-square amount.

- **Fixed per square:** Palm Beach / FBC **$519**. Miami / HVHZ is **OPEN** — the tile calculator
  carries an "HVHZ Upgrade — $100 per SQ" line, but whether Miami is simply $519 + $100 or its own
  number has not been confirmed.
- **Tile brands** (field cost / rake per tile, live Custom Tile Calc): Eagle $147.59 / $4.82 ·
  Crown $143.19 / $4.30 · West Lake $145.71 / $4.50 · Verea Spanish "S" $297.04 / $5.78 ·
  Verea Caribbean $230.00 / $13.98 · Other-Custom $310.00 / $45.00.
- The same cut calculator is reused for shingle and metal by applying **the same percentage
  difference** it produces on tile (7/17 [05:33]).

**Barrel tile is blocked from the published per-square sheet.** The guide has 13" tile at $770/sq
base against barrel at $1,435, so one blended "tile" price quotes barrel under water. Sold barrel
jobs run near $3,000/sq, which agrees.

---

## 3. Overhead — from days

Tim's daily rates, sent by email **2026-07-10** and repeated **2026-07-24**:

| series | rate per day |
|---|--:|
| Demo / dry-in / flat roof | **$1,050** |
| Tile install | **$745** |
| Metal install | **$850** |
| Shingle install | **$700** |

His own worked example, verbatim from the 7/10 email:

```
40 SQ shingle to metal roof that's cut up
Demo:   2 days   $1,050 × 2 = $2,100
Metal:  5 days   $850   × 5 = $4,250
Total OH = $6,350 / 40 sq = $158.75 per SQ
```

Overhead is entered **to the half day** per series, which is why the estimator rounds derived days
to 0.5 with a 0.5-day floor.

Overhead is the office's daily cost of being open, spread over the days a job runs. His OH Basis
rows reduce to about **$4,140/day for Miami** (9×$460, 12×$345, 15×$275) and **$1,400/day for
Jupiter** (4×$345, 7×$200, 10×$140).

- **Naples carries zero overhead.** "Miami's overhead is more than Jupiter's and Naples has zero
  overhead right now" (7/17 [40:20]).
- **OPEN:** which crew-size column each office actually prices from, and Miami's true daily figure.
  The daily rates above arrived with 30 Palm Beach homes, so they are Jupiter's. Scaling Miami by
  office cost produced $1,393/sq on a 30-square tile roof against his published $270/sq overhead
  (≈$1,240), so the scaling was backed out and Miami left as it was.

### Days from geometry

Days are fitted per series from the RoofR report — squares, hips, ridges, valleys, rakes, wall
flashings, eaves — with all slope coefficients forced non-negative, so more geometry can never mean
less time.

**Steep-roof rule:** a predominant pitch of **6/12 or steeper adds half a day** to the install
series, once per job. This is a threshold rule, not a fitted coefficient. It survives honest
cross-validation: re-derived from the training fold alone it was selected in **27 of 29 folds** and
never switched off (`scripts/honest_day_model_cv.py`).

**Accuracy against Tim's own day figures, measured out-of-sample** (rule selection nested inside the
CV loop, so the model is never graded on a house it was fitted on):

| | MAE | within 1 day | within ½ day |
|---|--:|--:|--:|
| geometry model | **0.67 d** | **83%** | 59% |
| guessing every job at the 7-day average | 2.29 d | 34% | 21% |

Scored in-sample the same model reads 93% / 0.52 d. **83% is the number to quote.**

**Known ceiling:** no roof in the 30 is 7/12 or steeper, so the band where Tim's own sheet says cost
jumps has no calibration. And access is invisible to a RoofR report — see §8.

---

## 4. Profit — sliding scale, then the weekly floor

### 4a. Sliding scale (per square, by job size)

| squares | $/sq |
|---|--:|
| 1 | 400 |
| 2–4 | 200 |
| 5–7 | 160 |
| 8–14 | 140 |
| 15–20 | 120 |
| 20–29 | 110 |
| 30+ | 100 |

Band edges are **inclusive of the lower bound**: a 7-square job earns $160, not $140.
**OPEN:** the sheet lists 20 in two bands (15–20 and 20–29). We pay **$120**, the better of the two
for Perkins.

### 4b. The weekly profit floor — $2,500 per on-site week

> "I generally like to make **$2,500 min. per week the crew will be on-site**…. Even though the total
> is 7 days of work, on a 40 SQ metal roof, I would charge closer to **$5,000 at a min. for profit**,
> because it's still taking up **2 weeks of work in window after inspections**. A smaller roof that
> might be 8 squares and take 1.5 days, I would still want to make at least **$2,500** on, because a
> re-roof of any size is not worth the liability."
> — Tim, email 2026-07-10, "Re: Requested documents"

```
on_site_weeks   = max(1, ceil(total_days / 5))        ← 5-day work week
weekly_floor    = on_site_weeks × $2,500
profit          = max(sliding_scale_profit, weekly_floor)
```

Both halves of his example reproduce exactly:

| his example | days | weeks | floor |
|---|--:|--:|--:|
| 40 SQ metal, cut up | 7.0 | 2 | **$5,000** |
| 8 SQ, small | 1.5 | 1 | **$2,500** |

A one-day job is still one week — "if it's one day it still counts as one week and I'm still gonna
charge $2,500 minimum on re-roofs" (7/17 [08:52]).

Across his own 29 homes this lifts **20 of 29** above the sliding scale and raises the set by
**+$28,655 (+2.6%)**. On-site weeks run 1 (10 homes), 2 (17), 3 (1), 4 (1).

The floor never overrides an operator who prices deliberately — a typed flat profit or a per-square
override is left alone.

**OPEN — what counts as a week.** His rationale is *"in window after inspections"*, which is calendar
occupancy rather than crew-days. We currently count **crew days ÷ 5**. If a job has a long inspection
gap in the middle, counting schedule time end to end would give a higher number.

**OPEN — the "four grand".** On 7/17 [08:15], about a 6-square roof, he said "I'm not gonna do this
job unless I make at least $2,500 — unless I make at least four grand." His written position is
$2,500 at any size, so $4,000 is treated as thinking aloud until confirmed.

### 4c. Margin floors

Minimum profit **13%**, minimum profit + overhead **33%** (7/17 [07:03]). Advisory badges, they do
not move the price.

---

## 5. Demo

| | Palm Beach / FBC | Miami / HVHZ |
|---|--:|--:|
| Tile demo | $30/sq | $40/sq |
| Metal demo | $45/sq | $60/sq |

Demo days are driven mainly by **eaves**, which is why a quote missing `eaves_lf` falls back to the
squares-only fit rather than silently returning ~1.1 days.

**OPEN — demo per material.** Tile tear-off costs far more than shingle: "$65 a square" hauling
against "$30" (7/17 [13:28], [13:56]). His sheet has a single Demo column, so we cannot split it yet.
Logging tile vs shingle tear-off separately would give demo its own formula per material.

---

## 6. Fixed fees, per job

| line | amount | note |
|---|--:|---|
| Delivery + 2 sheets plywood + vents | $650 | |
| New bonus values | $1,350 | wind-mit report, pressure clean, protection, urethane on wall flashings |
| Permit processing | $500 | permit runner |
| Tile dumpsters | $300 each | FBC every 30 sq, HVHZ more than 15 sq — **OPEN**, the tile calculator says every 17.5 sq for both |
| PM incentive | see below | |

**PM incentive is keyed differently in each zone** — this is the defect that had a 35-square Palm
Beach residential job charging $50:

- **Miami / HVHZ** — by **project kind only**: Residential $150, Commercial $300, at any size.
- **Palm Beach / FBC** — by **size only**: under 20 sq $50, 20–50 sq $100, over 50 sq $250, applying
  to residential *and* commercial.

**OPEN:** the newer sloped calculator restructures the fixed fees entirely — delivery $200 + decking
and vents $350 + permit and PM bonus $550. If that sheet is live, every quote changes.

---

## 7. Adders

| adder | value | source |
|---|--:|---|
| 7/12+ pitch, tile | **$305/sq**, both zones | two cell comments build to $305 twice (Demo L $70 + Tile L $70 + M $40 + OH $90–95 + P $30–35). Sits in the **overhead** block, not base cost |
| WinterGuard | **$135/sq** | comment build-up M $60 + L $25 + OH $32 + P $18, on two sheets |
| Secondary water barrier, ridge vents $9.79/LF, penetrations $75 each | per config | |
| Stucco metal | **$9 per LF** | his subs quote "+$1–2 per LF stucco", so the "$9 per 10 LF" wording elsewhere is a typo |
| Roof cuts (access) | Low $0 / Medium $25 / High $50 per sq | identical in both zones |
| Roof height 3–5 storeys | +$1,200 flat | "min. add $1,200 delivery and trash chute". 6+ needs a crane → manual review |
| HVHZ upgrade | +$100/sq | tile calculator |
| Specialty tile upgrades | Santa Fe Clay "S" $160, Verea "S" $195, Verea Caribbean "S" $120 | |

⚠️ A 7/12+ tile roof pays for steepness **twice** — once in the $305 adder (whose own build-up
includes overhead) and once through the extra half day. The estimator warns
`steepness_counted_twice` when both fire.

---

## 8. What the measurements cannot see

Two cost drivers are invisible to a RoofR report, and Tim prices both by hand today.

**Access.** On 7/17 [02:28] he added **$45 under "roof cuts"** on 1141 Vintner because a delivery
truck cannot reach the rear roof: *"you got to hand load all that shit."* 210 Lone Pine is the clean
case — 9 facets, the simplest geometry in the set, yet he books 8 days on a tight tract lot with
neighbours close on both sides, heavy canopy behind and pool cages. 233 Hampton has 17 facets, is
geometrically busier, sits on open water, and the model hits his day count exactly.

**Height and harnessing.** Three storeys or a highly visible slope means harnesses all day, and his
subs go from **$160/sq to $250/sq** (7/17 [03:39]). Cranes likewise.

**OPEN:** whether access should become an explicit input (none / hand-load / crane) rather than
something the model tries to infer.

---

## 9. Mixed sloped + flat roofs

**36% of Perkins roofs are mixed.** Nine of Tim's thirty homes have a flat section — 70 squares in
total, including 17 squares on 451 South Juno Lane, a third of that roof.

A roof with both is **one job**: whole-job items (profit band, the weekly floor, fixed fees, PM
incentive) run on **combined** squares; the flat section contributes only its own per-area lines.

**OPEN:** the flat section defaults to **Polyglass SAP** — what all three of his mixed proposals sold
— and a 32.5 + 17 roof bands as a **49.5-square** job for profit.

---

## 10. Repairs

Priced off time and crew size, not squares: "how many guys, how many days, and then what materials
do I need" (7/20 [39:23]).

| | rate |
|---|--:|
| One man, one day | **$1,185** |
| Two men, one day | **$1,435** |

**OPEN:** a $1,400 two-man figure appears on the same call immediately after Tim says "I don't know
what you're using, Josh, for your overhead and labor and gas, but that's my numbers" — so it is
probably Josh's Miami rate, and repair rates may be per person the way commission is. Tim also
undertook to send a fixed repair price list by email; it has not arrived.

---

## 11. Commission

**Set per salesperson, not per branch or zone.**

> "mostly net … unless it's like outside so like it just varies by the salesperson." — Tim, 7/20 [03:49]

Two tabs on the newest sheet with an identical price grid read 15% (Marco) and 7.5% (Josh), which
settles it: a rate that differs between identically-zoned tabs is not a function of zone. The earlier
"Miami 15% / Jupiter 10%" reading was wrong — **no Jupiter tab carries a commission cell at all**.

**OPEN:** each person's rate, and confirmation the percentage is of **profit** ("mostly net") rather
than of the contract. Until then the engine pays 10% on Miami sloped jobs.

---

## 12. Commercial — a different animal

Evergrene and Miramar price almost nothing the way the residential calculator does.

- **General conditions** — green fence, telehandler, full-time PM — are charged **once for the whole
  site**, not per building. Evergrene is nine buildings; quoting each as its own job would charge the
  $650 delivery, $1,350 bonus and $500 permit nine times.
- Miramar states a **5-day work week** twice ("8-10 weeks — 5 days per week", "12 weeks — 5 days per
  week"), which is the corroboration for §4b.
- **OPEN:** is commercial profit always a percentage of cost (Miramar shows 14% and 15%)? Is the PM a
  daily rate ($450 / $300 / $225 across two sheets)? Is "8 SQ walls" a straight parapet-area
  conversion? And we have no project container, so site costs and the floor repeat per building.

---

## 13. Still open — the short list

1. **Plywood deck replacement on a flat roof, per square.** The only item that blocks a quote
   outright. Material is known (5/8" CDX ≈ $99/sq after tax and waste); labour and overhead are not.
2. **Which calculator is live** — the newer sloped sheet moves 7/12, WinterGuard, the tile base and
   the whole fixed-fee block.
3. What counts as an on-site week (§4b), and whether $4,000 is a small-job walk-away.
4. The 20-square profit band (§4a) and the tile dumpster threshold (§6).
5. Miami's daily overhead and crew-size column (§3); the Miami cut-calculator fixed cost (§2).
6. Per-person commission rates (§11); per-person repair rates (§10).
7. Small coating jobs under 25 squares, and whether the 2024 silicone insurance increase reached the
   headline prices — the note sits on two cells reading $445 and $485.
8. Commercial structure (§12).

---

## 14. Provenance rules we hold ourselves to

1. **The LIVE sheet is the source** — not the "NEW" one, not a "Copy of".
2. **Within the live sheet, a comment beats the headline cell**, because the comment shows the
   build-up. This is how 7/12 became $305 and WinterGuard $135.
3. **A number Tim wrote in an email or said on a recorded call outranks our inference.** Two rules in
   this document were wrong because nobody had searched his mailbox.
4. **Where nothing says, we say OPEN** and quote the better-of-two for Perkins in the meantime.
5. **A config change is four places** — the fixture, prod, the tests, and any seeder that could
   replay an old value.
