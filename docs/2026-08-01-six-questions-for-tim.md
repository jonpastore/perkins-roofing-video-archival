# Six questions for Tim — Evergrene / multi-building bids

**Status: DRAFT, not sent.** `EMAIL_SEND_MODE=test` in prod, and Jon sends anything client-facing.

Every one of these was checked against the corpus first — all 77 sheet comments, the low-slope
comments, both branch catalogs, the golden proposals, and Tim's 7/30 and 7/31 emails. **Zero hits**
for each. He has never stated any of them, which is the test for asking rather than defaulting.

Q1 is now blocking someone else too: on the Workflow Notes thread (7/31) Chris asked whether the
software will bid jobs with Tim's calculator, and wants a permitting agent.

---

## Suggested email

**Subject:** Evergrene — six pricing questions I can't answer from your sheets

Tim,

We've taught the estimator to price a multi-building job as one bid instead of nine separate
ones, using your Evergrene spreadsheet as the reference. It now lands within about 2% of your
number ($390,230 against your $381,288, profit $30,790 against $30,363).

Six things I could not work out from the sheet, and I'd rather ask than guess. Each one moves
real money.

**1. Permits — one per structure, or one per site?**
On Evergrene, Palm Beach might issue one permit for the whole site or one per building. The
difference on that job alone is between $500 and about $9,000. We default to one per site today.

**2. "New Bonus Values" ($1,350) — per mobilisation, or per roof completed?**
If the crew is on site once but finishes nine roofs, does that line get charged once or nine
times? I read it as back-end crew money and defaulted it to once per site.

**3. Is commission paid on General Conditions?**
This is the biggest of the six — roughly $8,000–$16,000 on Evergrene by itself. General
Conditions is site cost rather than roof scope, so I don't know whether it's commissionable.

**4. Is the General Conditions markup always 1.15, or set per bid?**
Your Evergrene sheet uses (22,800 + 9,000) × 1.15 = $36,570. Is 1.15 the standing number?

**5. What are the bare +4,250 and +2,550 on the Evergrene sheet?**
Cells K33 and K35. They're unlabelled and nothing else on the sheet references them, so I've
left them out rather than guess at what they cover.

**6. On a multi-building job, does the proposal need each building's own address?**
Two of the Evergrene gates are on different roads. For the website you told us town/city/HOA is
right, but a proposal is a contract document and I'd guess that's a different answer.

**One more, on day rates.** On Evergrene you billed demo at $885/day and metal install at
$735/day. Our config carries $1,050 and $850 — tile install matches yours exactly at $745. Are
commercial rates different from residential, or have those numbers moved since the 7/24 sheet?
I haven't changed anything; I'd rather have it from you.

Thanks,
Jon

---

## Why each is not defaultable

| # | If we guess wrong | Where it bites |
|---|---|---|
| 1 | $500–$9,000 per bid | `permit_count`, default 1 |
| 2 | $1,350 × (n−1) | `new_bonus_values` in `DEFAULT_ONCE_PER_PROJECT` |
| 3 | **$8–16k on Evergrene alone** | commission base — no code path either way yet |
| 4 | scales all site cost | `bid_projects.general_conditions_markup`, default 1.0 |
| 5 | $6,800 unexplained | omitted from the fixture on purpose |
| 6 | contract validity, not money | proposal renderer (slice 3) |
| + | ours 15% high on metal, 19% high on demo | `daily_overhead_rates` — do NOT change without him |

## Do not pre-empt

Tim's 7/30 "town/city/HOA" answer was about **public marketing pages**. It does not answer Q6 —
a proposal is a contract document. Do not collapse the two.
