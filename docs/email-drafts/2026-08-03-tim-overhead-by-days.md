# Draft to Tim — overhead is now on days, and here is where we are still off

**Status:** draft for Jon. Numbers verified against the live configs and Tim's own 2026-07-27
workbook on 2026-08-03. Do not send until the config is applied and deployed.

---

## The problem list (internal — not for the email)

| # | Problem | Effect | Status |
|---|---|---|---|
| 1 | `concurrent_crews` unset on all 3 branches → defaults to 1.0, so **every job was charged the whole office day** | Miami quotes ~35% high; 34 live estimates in 30 days | **fixed** — 1.5 Jupiter/Naples, 4 Miami |
| 2 | `overhead_basis` was `series` on Jupiter/Naples (four activity rates), `branch` on Miami — two different methods | inconsistent between branches | **fixed** — all three on `branch` |
| 3 | `office_daily_overhead` was 1400/4250 against Tim's stated 1470/4257 | Jupiter −$70/day, Miami −$7/day | **fixed** |
| 4 | **Low-slope had no day model at all** — every flat roof silently fell back to the per-square table | flat roofs were the one thing NOT on days | **fixed** — day fit added |
| 5 | A mixed roof booked the **sloped** days and none of the flat | 36% of the sold book under-quoted the flat crew's time | **fixed** — flat section books its own days |
| 6 | A quote that asked for days and fell back to per-square **said nothing** | indistinguishable from one that worked | **fixed** — warns now |
| 7 | Our **day estimate** is the remaining error | 23/35 vs 27/35 within 10% | **open — needs Tim** |
| 8 | Estimates 27–31 (`tpo_adhered` saved as `slope_type='sloped'`) cannot be re-priced | none reached a proposal | open, no exposure |

**The headline:** #1–#6 are ours and are fixed. **#7 is the one that actually explains his
complaint**, and it is not about overhead at all.

---

## Draft email

Tim,

Done — overhead is now on days, per branch, everywhere. Your numbers, not ours:

    Jupiter / Naples    $1,470 a day    1.5 crews sharing it
    Miami               $4,257 a day    4 crews sharing it

**What was wrong, and it was ours.** We had the daily numbers but never set the crew split, so
the tool was charging **one job the entire office day**. On a Miami job that is $4,257 landing on
one roof instead of $1,064. Miami quotes were coming out about **35% high** — a 30-square HVHZ
tile roof priced at **$2,087 a square** when it should be **$1,343**. Jupiter was on your four
activity rates so it barely moves (+1%).

**Flat roofs were the other gap.** Everything sloped was on days; flat was still on a per-square
table, and a roof with both a sloped and a flat section only counted the sloped days. Both fixed.
The flat day count comes from your own 9 homes that list flat squares and flat days —
**about 8.5 squares a day**. Sanity check: that predicts 2.8 days for the 28-square flat section
at the Evergrene clubhouse, and your own bid sheet booked 3.

---

**Now the part you asked about: "only 2/3 of jobs are within 10%."**

You are right, and we can now say exactly where it comes from. Same 35 jobs from your sheet,
same prices you charged, the only difference is **who counts the days**:

    Days from YOUR sheet     within 10% on 27 of 35   (77%)
    Days from OUR estimate   within 10% on 23 of 35   (66%)   <- your two-thirds

**The overhead method is not the problem. The day count is.** When we use your days we are within
10% on three jobs in four. When we guess the days ourselves we drop to two in three — and that
drop is the whole gap you are seeing. Changing how overhead is calculated moves this by one job.

The reason is simple: overhead is a day rate, so being one day off on a five-day job is a 20%
error on the overhead no matter how good the rate is. We cannot see access, a cut-up roof, or a
tight lot from square footage alone.

**So we are doing what you asked** — the tool will show a **suggested price and a suggested
number of days, and both stay editable**. You or the estimator change the days, the price follows.
Guidelines, not guardrails.

Two things that would close the rest of it:

1. **RoofR reports on the jobs you price.** Your day counts track cuts, pitch and stories far
   better than squares do — with the cut measurements our day estimate gets materially closer.
2. **Tell us when you override the days and why** (access, two-story, a back slope the truck
   cannot reach). Every one of those we learn is a job that stops being off by a day.

One open question, since your commercial sheets do it and our tool does not yet: on Evergrene you
split the day rate by phase — $1,175 a day for demo and temp, $765 for tapered and base. Do you
want that phase split on residential too, or is one branch day rate right there?

Jon
