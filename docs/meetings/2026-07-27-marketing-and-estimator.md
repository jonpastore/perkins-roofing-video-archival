# Meeting 2026-07-27 — answers, action items, and the plan

Source: `~/Documents/Zoom/2026-07-27 14.10.24 Perkins Marketing/audio1697003957.m4a`, 69 min,
transcribed locally on litellm `whisper-turbo` (7 × 10-min chunks, $0). Present: Jon, Tim, Josh,
Marco, Vlad; Chris joined late. Timestamps below are chunk-relative (±10 min).

**Tim also sent an updated sheet at 20:22** —
`Residential OH Calculator (SLOPED ONLY) (1).xlsx`. It is the single most useful artefact we have
had: the same 30 homes plus **Stories**, **Sloped Pitch**, **Accessibility Issue (Y/N)** and — for
the first time — **his ACTUAL quoted prices** on 27 of them.

⚠️ Excel ate the pitch column as dates: `4/12` is stored as `2026-04-12`. The month is the rise.
Parse it as `date.month`, never as a number.

---

## 1. What the meeting answered

### 1a. The work week — CONFIRMED, and it gives us Miami's overhead

> "Five, Monday through Friday. We do work Saturdays sometimes, but we don't count those as work
> days. The way we count work days is **20 days per month**. Our monthly fixed overhead — for my
> branch is like **28 grand**, for their branch is like **85 grand** — and we just divide that by 20."

- **5-day week confirmed.** What we shipped today is right.
- **Jupiter: $28,000 / 20 = $1,400/day** — exactly our `office_daily_overhead`. ✓
- **Miami: $85,000 / 20 = $4,250/day** — this answers the open Miami question. We had inferred
  ~$4,140 from his OH-basis rows; his own figure is **$4,250**.
- Naples still unstated.

### 1b. The profit floor — CONFIRMED per week

> "If it was an eight day job, you want a minimum of $5,000 margin built in regardless, right?"
> — "Yeah, pretty much. $4,500, $5,000 … if it's a week and a half we can discount that a little.
> But the minimum should be $2,500. Even if we're doing a six square house and it only takes one
> day, we want to make $2,500, because it's not worth the liability — any insurance claim is a
> $5,000 deductible right off the bat."

Today's change stands. **And the $4,000 question is closed: it is $2,500 at any size.**

### 1c. ⚠️ Kill the per-square profit scale — this is a real change

> "That profit thing per square is an old thing I used to use before I really nailed it down. That's
> more like a loose table … **I should probably not consider that. Let's not have duplicate
> mechanisms.** I would just eliminate it for simplification … **$2,500 minimum and then use the
> sliding scale to figure out your percent**, whatever you want to charge."

Profit becomes **an operator-set percentage with a $2,500 floor**. The band table
(1 sq $400 … 30+ $100) goes. That also makes the "20 squares — $120 or $110?" question moot.

### 1d. Accuracy target, and what drives the misses

> "We really need to get probably closer to **95 or higher** on the overhead for accuracy … variances
> are not just cuts. **How many stories.** A back roof with poor access. Pitch — a 6/12 on a two
> story is slower than a 6/12 on a one story, because if you fall off a two story you're toast, so
> you work slower."

He accepted the 83% figure without pushback and named the three variables he thinks are missing —
all three are now columns in the new sheet.

### 1e. Customer must not see back-end lines

> "The **PM incentive is not something the customer ever needs to see** … we usually don't want to
> show them any of the back-end stuff."

⚠️ **Defect in what we shipped today.** Customer mode folds base + overhead + profit but still
prints `PM Incentive $100` as its own row. It has to fold too.

### 1f. Repairs

- Priced on **days × crew size + materials**, as built.
- **A repair quote currently returns cost with no profit** — he spotted it live: 1 day, 1 man,
  $500 materials printed **$1,685** ($1,185 + $500). "That's the cost, though. That's without
  profit." **Needs the profit slider.**
- **Minimum $500 service-call charge; minimum profit $250** on a repair.
- **Maintenance prices exactly like a repair** — relabel to "Repair / Maintenance", one path, no
  third tab. (Josh wanted a separate button; Tim and Jon overruled on "less is more".)

### 1g. Tiers and scope

- Good = Protector, Better = Preferred, Best = Premium — **plus Coastal as a fourth tier** when the
  property is in the salt/brackish zone, driven by the salinity tool (which is built but untested).
- **Scrape TIM's Knowify catalog, not Josh's** — "I update my catalog all the time, way more than
  Josh does." Tim to supply his login.

---

## 2. His actual prices — our first real validation

21 homes have a like-for-like actual price. Engine vs his number, flat sections included:

| profit floor | median | mean | within 5% | within 10% |
|---|--:|--:|--:|--:|
| **weekly (shipped today)** | **+1.0%** | +2.8% | **12/21** | **18/21** |
| flat $2,500 (yesterday) | −0.1% | +0.5% | 10/21 | 17/21 |

**Today's change improved the fit against his real prices**, which is the outcome that matters —
the earlier 2.6% uplift was not us drifting away from him.

Worst remaining: 15739 136th Terrace N **+$7,670**, 13020 152nd Rd **+$5,785** (both we quote HIGH),
1081 Fairview **−$5,714**, 451 South Juno **−$5,290** (both metal, we quote LOW).

---

## 3. Still unanswered from the email we sent

Six of thirteen closed. Still open, in his court:

1. **Flat-roof plywood deck replacement $/sq** — still the only thing that blocks a quote.
2. **Which calculator is live** — he sent a new *homes* sheet, not a new price book.
3. Tile dumpster threshold (15 / 30 / 17.5).
4. Commission — per-person rates, and % of profit or contract.
5. Repair day rates — is $1,400 Josh's Miami number?
6. Silicone $445/$515/$645 vs +$25/coat.
7. Coating under 25 squares with tear-off.
8. Stucco metal $9/LF vs $9/10LF.
9. Naples overhead — is zero still right?
10. Commercial: multi-building general conditions, profit as % of cost, PM daily rate, parapet.
11. 7/12+ roofs — none in the thirty; he offered to send more houses.
12. 1141 Vintner's RoofR PDF (facet count).

---

## 4. Plan — ranked by money and by what he is waiting on

**A. Profit model rework** (his explicit instruction, changes every quote)
- Replace the per-square band table with **operator percentage + $2,500 floor**.
- Keep `profit_scale` readable for old proposals; new quotes use the percentage.
- Default percentage TBC — his sheet's realised margins can back it out.

**B. Fold PM incentive (and any back-end line) into the customer view** — one-line fix to
`_CUSTOMER_FOLDED_KEYS`, plus a test that no `pm_incentive`/internal key survives customer mode.

**C. Repair profit** — add the slider, `$250` minimum profit, `$500` minimum charge; relabel
"Repair / Maintenance".

**D. Seed Miami $4,250/day** (`office_daily_overhead`), from his own arithmetic. Leave the
rate-scaling question alone — it was reverted for good reason.

**E. Feed stories / pitch / accessibility into the day model.** All three now exist as data.
Add the **accessibility checkbox** to the estimator UI — he asked for it explicitly, and it is the
one thing AI cannot infer from a RoofR report. Re-fit and re-measure against his 27 actual prices;
target ≥95%.

**F. Coastal as a fourth tier**, gated on the salinity tool. Test that tool first — it was never
verified after the WordPress-plugin conversion.

**G. Scrape Tim's Knowify catalog** for scope templates once he sends the login.

---

## 5. Non-estimator action items

| owner | item |
|---|---|
| Tim / Marco / Chris | review + approve all 11 workflow message bodies (meeting tomorrow) |
| Jon | re-invite everyone to crm.degenito.ai, add Maria as a user (needs her email + mobile) |
| Jon / Vlad | confirm 10DLC approval with Twilio |
| — | messaging must **not** be signed "Tim" — an invented assistant persona instead, because customers try to reach Tim directly and he can't answer |
| Jon / Vlad | two A/B ad creatives: brand/service vs metal-specific; AI-avatar testimonials sourced from real Google reviews but not verbatim, with a disclosure |
| Marco | send the Crypt Keepers' proposal + scope of work; Merchant login |
| Jon | set a GCP budget ($200/mo) with 50/80/90/95% alerts; move billing off Jon's Amex (Marie has the card) |
| Jon | article image prompt → prefer drone / exterior frames, not garage stills |
| Jon | meeting with Wendy/Crypt Keepers before the full article run |

**Commercial context:** they are paying the Crypt Keepers just under **$2,000/month** for website
hosting, two blog articles and a CompanyCam→Google photo sync that Merchant already does. Tim wants
it unwound without a confrontation. Jon to review their scope and quote a replacement.

---

## 6. Not in scope of the estimator, but said on the record

Ads should sell the audience, not the engineering: "most of them are price conscious, how fast you
can get there, and why you're the best." Metal is the growth line and gets its own campaign.
