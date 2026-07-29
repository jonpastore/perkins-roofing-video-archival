# 2026-07-29 — Tim / Marco / Josh: how overhead lands in the price

To: tim@perkinsroofing.net
Cc: marco@perkinsroofing.net, josh@perkinsroofing.net
Subject: One question about the $1,400/day before I set it

**Supersedes the 2026-07-28 draft** (`2026-07-28-tim-overhead-and-pricing.md`), which was
never sent. That draft's headline — "your last 21 jobs show almost no margin, median −0.4%" —
**does not reproduce** on the current pricing config, and its framing of the gap as a margin
squeeze was an overhead-allocation artifact. See "What changed and why" below.

---

Tim,

Short one. The estimator now prices exactly the way you described it: **materials and labor,
plus overhead, plus margin — and margin is the only thing that moves in a negotiation.** That
part is built and I'm not asking about it.

I need one thing settled about the overhead number itself.

**The question: is $1,400/day charged to each job, or split across the jobs running that day?**

$28,000/month ÷ 20 = $1,400/day is the whole Jupiter office for a day. Annualized that's
$336,000, and $1,400 × 250 working days = $350,000. So charging $1,400/day to a job recovers
the office exactly right **when one job is running** — and over-recovers it as soon as two
crews are out.

From your own invoiced work, Jupiter ran roughly **1 to 1.7 jobs' worth of on-site days per
working day in 2025**, and **1.5 to 4.3 in 2024**. So in a year like 2025 the flat $1,400 is
about right. In a year like 2024 the same rule collects the office two to four times over.

Both answers are defensible — it depends whether you mean "no job leaves the yard without
carrying a full day of the office" (a floor, deliberately conservative) or "the office costs
$28k a month and the month's work has to cover it" (an allocation). **I just need to know
which one you mean**, because they price the same job differently.

**What the 21 homes actually show.** I re-ran the homes you sent through the estimator on our
current numbers:

| overhead model | our quote vs what you charged | margin left in your price after materials, labor and OH |
|---|--:|--:|
| flat $1,400/day | **+8.5%** median | **+4.2%** median (range −15% to +35%) |
| your 7/24 per-day rates ($745 tile / $700 shingle / $850 metal / $1,050 demo) | **−1.3%** median | **+13.0%** median |

Your per-day rates reproduce your actual pricing almost exactly — 14 of 21 within 10%. That
isn't a coincidence: those rates are close to the office burn divided across the crews you
actually have out, which is the same thing as the allocation answer above.

Under flat $1,400/day, 13 of the 21 land under your own $2,500-per-on-site-week minimum. After
paying that floor, your prices support about **$1,080/day** of overhead (median).

**One thing worth seeing, separately from the above.** Sliced by year, your sold prices per
square:

| | 2020 | 2024 | 2026 |
|---|--:|--:|--:|
| tile | $1,036 | $1,426 | $1,100 |
| metal | $1,263 | $1,697 | $1,255 |
| shingle | $591 | $757 | $689 |

Down sharply from 2024 — but 2024 was the spike. Against 2020 tile is up 6% and metal is flat,
while the April 2026 material list is up ~8% on last year (TU Plus $105.20 → $113.90, MTS
$105.20 → $114.25, XFR $123.80 → $132.25). So the squeeze is real but it's **materials rising
into flat prices**, not a collapse — and it's an argument about where you set margin, not about
what overhead costs.

**Also worth deciding:** should we store the monthly number and divide by the actual working
days in that month (Mon–Fri less holidays) instead of a flat 20? 2026 has 250 working days =
20.8/month, so ÷20 is about 4% conservative, not 10%. On an 8-day Jupiter job that's $448 of
cushion. If you want negotiating room, ÷20 barely provides it — better to set it deliberately.

Nothing is switched on until you answer the first question.

Jon

---

## Working notes (not part of the email)

### What changed and why — review of the 2026-07-28 draft

Rebuilt the analysis from `~/perkins-corpus/tim30_with_actual_prices.json` (21 of the 30 homes
carry a real charged price for their existing material) against **jupiter v27**, defining
margin the way Tim prices: `margin = charged price − (all cost lines) − overhead`.

| claim in the 7/28 draft | rebuilt 2026-07-29 |
|---|---|
| margin median **−0.4%** | **+4.2%** |
| **19 of 21** below the weekly floor | **13 of 21** |
| flat $1,400 prices **+13.3%** over his | **+8.5%** |
| prices recover **$840–950/day** | **$1,082/day** after paying the $2,500/wk floor; $760/day at a flat 15% margin |

The direction survives (flat $1,400/day prices above his historical pricing); the severity does
not. The old numbers predate the per-week profit floor, the refit day model and the cut-geometry
base, so "almost no margin" was never safe to put in front of Tim.

### The substantive error, not just stale numbers

The draft read "his prices only recover $840–950/day, not $1,400" as a margin squeeze. It isn't
one — it's what per-job allocation looks like when more than one job is running. $1,400/day is a
**branch-level** rate; the per-series rates are that same burn divided by crews out. The ratio
between them ($1,400 vs a $798 average) is ≈1.75×, which is inside the measured concurrency
range. Two numbers that are the same fact under different allocation, presented as evidence of
under-recovery.

### Evidence

- Margin/engine rebuild: `scripts/margin_check.py` (see git), 21 homes, jupiter v27.
- Concurrency: `knowify_raw_records` invoices — 2025: 192 projects invoiced, $2.26M, 31 ≥ $20k
  (median $39.3k); 2024: 222 projects, $5.86M, 50 ≥ $20k (median $41.3k). On-site days estimated
  two ways (big jobs × 7.4d, and revenue ÷ $5,400/on-site-day), ÷ 250 working days.
- Price trend: `scripts/sold_price_trend.py`, median sold $/sq by material by year — this is
  time-sliced deliberately; an all-time median blends every price list the business has used.
- Structure check: `core/estimator._build_sloped` emits `base_cost_lm` (L+M) → `overhead` →
  `profit`, and `sloped_base_cost_lm[FBC][13_tile]` is **$770/sq**, a real cost, not his $1,100
  sell price. So the "materials + costs incl. OH + margin" shape is already what ships; there is
  no double-count in the base.
