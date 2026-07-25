# DRAFT — not sent. Email to Tim Kanak (tim@perkinsroofing.net)

> **This is a draft for Jon's review.** Nothing has been sent. Outbound mail is still gated to
> `EMAIL_SEND_MODE=test`, so it could not go out accidentally even if triggered.
> Sources for every number: `scripts/tim_quote_breakdown.py`, `docs/TIM_SHEET_VERIFICATION_2026-07-24.md`,
> `docs/ROOFR_OVERHEAD_TIERS.md`.

**Subject:** Your 30 homes are in the estimator — 93% within a day of your numbers. Two questions on the quotes.

Tim,

Your time-learning spreadsheet did exactly what you said it would. All 30 homes are in the
estimator and it now prices overhead the way you described on the call — off how long the job
takes, driven by how cut-up and how steep the roof is, not just its size. Your line is what fixed
it: *two 30-square houses, one is two days and one with towers is five or six.* My first attempt
predicted days from square footage alone, which can't tell those two houses apart. Yours can, so
now ours does.

Against your own day figures on 29 of the 30 homes:

- **93% land within one day of your number**, 66% within half a day
- average miss: **0.5 days**
- overhead comes out within **$3** of yours on the average home

For contrast, predicting from square footage alone was nowhere close: tile 0.54 vs 0.83 accuracy,
metal 0.48 vs 0.88.

---

## How we get to a number — the whole calculation

No black box. Here is every step for one of your own homes.

**918 Mil Creek Drive** — 35 squares, tile over tile. From its RoofR report: 336ft of eaves,
158 hips, 95 ridges, 75 valleys, 10 rakes, 34 wall flashing, 4/12 pitch.

**Step 1 — days, from the roof's geometry.** One formula per phase, fitted to your 30 homes:

```
tile install = 0.55 + 0.032×squares + 0.0135×hips + 0.0130×ridges
                    + 0.0107×rakes  + 0.0007×valleys + 0.0014×wall flashing
demo         = 1.11 + 0.0060×eaves + 0.0010×rakes
plus 0.5 install days when predominant pitch is 6/12 or steeper
```

918 Mil Creek: tile = 0.55 + 1.12 + 2.13 + 1.24 + 0.11 + 0.05 + 0.05 = 5.24 → **5.0 days**.
Demo = 1.11 + 2.01 + 0.01 = 3.14 → **3.0 days**. Total **8.0 days**. You said **8.0**.

**Step 2 — days become overhead** at your daily numbers (tile $745, demo/flat $1,050, metal $850,
shingle $700): `5.0 × 745 + 3.0 × 1,050 = $6,875` — $196.43 a square. Your own 8 days give the
same figure.

**Step 3 — the rest is your sheet, unchanged:**

```
Base cost (L&M)          35 × $770.00  = $26,950
Overhead (from days)     35 × $196.43  = $ 6,875
Profit (sliding scale)   35 × $100.00  = $ 3,500
Tile demo                35 × $ 40.00  = $ 1,400
Delivery / plywood / vents             = $   650
Bonus values                           = $ 1,350
Permit processing                      = $   500
Tile dumpsters (two at 35 sq)          = $   600
PM incentive                           = $    50
                                 TOTAL   $41,875
```

I checked every one of those inputs against your live FBC tab and they match: base costs,
overheads, the profit sliding scale, roof cuts, height, pointing, and the fixed items. The
estimator isn't inventing a pricing model — it's running yours.

---

## Question 1: our quote comes out higher than your published sheet on all 29 homes

This is the one I most need your read on. Same 918 Mil Creek job, priced off our published
per-square sheet, comes to **$38,500** — **$3,375 less than your own build says it costs**.

Across all 29 homes the published sheet came out low on **every single one**, averaging **$2,554**
a roof:

| Roof type | homes | published sheet vs your build |
|---|--:|--:|
| 13" tile | 16 | −$82 a square |
| dimensional shingle | 11 | −$57 a square |
| standing seam metal | 3 | −$73 a square |

Worst case is a small shingle job at −$150 a square. I don't think your build is wrong — I think
the published sheet is stale. **Which one should win when they disagree?** Until you say, we quote
from the build, and I've blocked one case outright: barrel tile. Our published tile price is a
single number for all tile, but your guide has 13" tile at $770/sq base against barrel at $1,435,
so quoting barrel from it is under water before overhead or profit.

## Question 2: where our days differ from yours, and why

Four homes are still 1.5 days apart, and three of them are informative:

| Home | Roof | SQ | cut LF | pitch | Your days | Ours |
|---|---|--:|--:|---|--:|--:|
| 1913 Flower Drive | tile | 35.0 | 355 | 5/12 | 9.5 | 8.0 |
| 1081 Fairview Lane | metal | 41.5 | 442 | 5/12 | 10.5 | 9.0 |
| 210 Lone Pine Dr | tile | 36.0 | 221 | 6/12 | 8.0 | 7.0 |
| 503 Xanadu Place | metal | 26.0 | 262 | 6/12 | 7.0 | 6.0 |

**1913 Flower Drive is the one that proves the point.** Compare it with 918 Mil Creek: both tile,
both **35.0 squares**, 355 vs 371 feet of cuts, same everything on paper. You called Mil Creek
**8 days** and Flower Drive **9.5**. Nothing in either RoofR report tells them apart — so that
1.5 days is your judgement, and it's the ceiling on how accurate this can ever get from
measurements alone. **What's different about Flower Drive?**

I did find one thing the measurements *do* explain. Your extra time tracks pitch: across the 29
homes we over-call by 0.3 days on 4/12 roofs, land dead on at 5/12, and under-call by 0.6 days at
6/12. So steep roofs now add half a day. Your own sheet says the same thing on the material side —
your 7/12 comment breaks out `OH = $90`. None of your 30 homes are 7/12 or steeper though, so we
have no calibration at all in the steepest band.

**The other thing I suspect is access**, because you raised it on the call — the hand-load fee when
a rear roof can't be reached. 210 Lone Pine is the cleanest example: 9 facets, the *simplest* tile
geometry in the whole set, and yet you book 8 days. Its satellite shot shows a tight tract lot,
neighbours close on both sides, heavy canopy along the back, pool cages behind. Compare 233 Hampton
— 17 facets, geometrically busier, but on an open lakefront lot with a wide driveway — and we hit
your number exactly. **Access is nowhere in a RoofR report**, so we can't see it unless you tell us.

## Which brings me to the notes column

On the call you offered exactly the fix: *"a notes column that says why you think… so that it's
creating like the framing of the logic and how you're coming up with it, then we can turn that…
it's like a word problem being turned into an algebra equation."*

The sheet you sent has days for all four materials on every house — you kept that promise. What's
missing is the why, and the why is now the single biggest thing standing between 93% and better. A
short phrase per row does it: "towers", "no rear access, hand load", "steep, harness all day",
"two-story front only", "pool cage to protect".

Two smaller data asks while you're in there:
- **1141 Vintner Blvd** is the one home with no RoofR report in what came through. Send it and the
  model covers all 30.
- **A few 7/12+ roofs**, if you have them. We have zero, and your own sheet says that's where cost
  jumps.

---

## Still open on pricing — 9 config values we can't fill without you

I resolved everything your sheet actually answers. These are the ones it doesn't:

1. **PM incentive** — your sheet reads size-only (<20 $50 / 20–50 $100 / >50 $250) but ours is
   keyed by residential-vs-commercial as well, with no residential figure above 20 squares. So the
   35-square residential job above took $50 where your sheet says $100. Does it vary by
   residential vs commercial at all?
2. **Sloped-HVHZ commission** — 10% like sloped, or 15% like low-slope?
3. **3–5 storey and 6+ (crane) adders** — blank in your sheet too, so I can't infer them.
4. **Verea Spanish "S", Verea Caribbean and custom tile field-tile costs** — blank, so those brands
   can't be priced.
5. **HVHZ cut-calculator fixed cost per square** — we have the FBC figure ($519), not the HVHZ one.
6. **Generic plywood deck-replacement adder** for low-slope.
7. **Sliding-scale boundary rule** — does a job landing exactly on 20 squares take the 20–29 rate
   or the 15–20 one?
8. **Tile dumpster boundary** — does hitting the threshold square itself trigger the next dumpster?
9. **Which crew size each branch prices from** — your OH Metrics tab has 9 men $460/day, 12 men
   $345, 15 men $275, and our numbers sit between them. Your comments mention "busy, 16+ guys" and
   "huge job" variants too. Miami, Jupiter and Naples presumably aren't the same.

Plus, from your 7/17 gutter list: now that downspouts are itemised separately, should the gutter
per-foot price come down, and where do hangers and the $14.70 upgraded downspout land? Copper
K-style at $50 and $70 wasn't on your sheet — confirm or correct.

And one for later: you mentioned demoing tile costs far more than shingle ($65/sq hauling vs $30).
Your sheet has a single Demo column so we can't split it yet. If you log tile vs shingle tear-off
separately going forward, demo gets its own formula per material.

## Everything else we finished since yesterday

- Your gutter price list is live and priced per branch — styles, two-story uplift, elbows, leaf
  guard, leaderheads, removal, and the under-100' add.
- Repair quoting is live at your $1,185 one-man / $1,435 two-man day rates. (It was configured on
  paper but not actually switched on for any branch — fixed.)
- The lumber schedule is a one-click optional attachment on proposals.
- Josh's PERKINS PROTECTOR scope is a reusable template — sales loads it, edits it, saves their own
  versions instead of retyping.
- Your contractor license (CCC1331944) now prints on proposals. It was missing entirely, which is a
  Florida requirement.
- Proposals rebuilt so page one is the decision page: options, price, signature. The old ones read
  as a wall of text.
- Terms & conditions and the contract FAQ are both optional sections now, on by default, with 25
  approved FAQ answers drawn from your actual T&C.
- The article library is at 375 pieces, all cross-linked, with every metal article live.

Jon
