# Adversarial review: Perkins overhead allocation

I am not reviewing “whether the system matches Tim’s sheets.” That is already verified at 0.0% on cost/materials. I am reviewing whether the *model choices and the validation story around overhead* hold up. They mostly do not.

---

## 1. Are “per day by roof type” and “per-man-day × crew size” the same model?

**They are the same *functional form* with different free parameters. They are not observationally the same model.**

Both are:

\[
\text{OH} = \sum_{\text{phases}} r_{\text{phase}} \times d_{\text{phase}}
\]

- “Per day by roof type”: \(r\) is four emailed scalars ($745 / $700 / $850 / $1,050).
- “Per-man-day × crew”: \(r = c \times m\), with \(c \in \{210, 238\}\) and \(m \in \{5, 3\}\).

Load-bearing distinction:
- Under pure man-day, **ratio of any two phase rates must equal the ratio of crew sizes**. Demo/install = 5/3 ≈ 1.667.
- His emailed rates: demo/tile = 1050/745 ≈ 1.41; demo/shingle = 1.50; demo/metal = 1.24. **None equal 1.667.**

So they are *not* the same model unless you allow non-integer or phase-specific crew sizes (or phase-specific burdened man-day rates). The other AI’s line “$210 × 5 = $1,050 exactly, therefore the emailed rates are just baked-in crews” is half-right for demo and **false for installs**. That is decoration presented as load-bearing.

**Observable that distinguishes them:**
1. Hold days fixed, vary only roof type on otherwise identical jobs. If OH tracks the four scalars rather than \(c \times m\), emailed rates win.
2. Ask whether a 4-man tile crew day is billed at $745 or at \(4c\). If Tim says “tile day is $745 regardless of headcount,” the models diverge in production the first time crew size leaves his template.
3. Regression: \(\text{OH}_\text{implied} \sim \beta_t d_t + \beta_s d_s + \beta_m d_m + \beta_d d_d\). Test \(H_0: \beta_i / \beta_j = m_i / m_j\).

His own words favor per-day-by-type as the *intent* (“we were using OH Metrics… not as accurate”). That does not make the four numbers coherent — see Q2.

---

## 2. Fractional crews (3.55, 3.33, 4.05, 5.00)

Dividing emailed rates by $210/man-day:

| phase | rate | ÷210 | ÷238 |
|------|------|------|------|
| demo | 1050 | 5.00 | 4.41 |
| tile | 745 | 3.55 | 3.13 |
| shingle | 700 | 3.33 | 2.94 |
| metal | 850 | 4.05 | 3.57 |

**Plausible explanations, ranked:**

1. **The four rates are not derived from $1,470/7 at all.** They are older rules of thumb (15 years + estimator’s manual) that predate the $1,470 figure. $210 is *our* reconstruction, not his generative model. Most likely. Supported by: he said OH Metrics is older/less accurate; he still quotes the four rates separately; install ratios do not match whole crews.
2. **Burden is not uniform across trades.** Tile/metal may carry higher effective burden (supervision, equipment, insurance, waste) than headcount suggests. Metal at 4.05 is the tell — metal is slow and equipment-heavy in his sheet mythology, even though actual sq/day says otherwise.
3. **Rates smuggle profit, contingency, or under-recovery padding**, not pure OH. Especially plausible for metal ($850) and demo ($1,050).
4. **Crew sizes really are fractional in his head** (3.5 tile “because sometimes a helper”). Weak — he writes integer crews everywhere else.
5. **Arithmetic residue from blending Jupiter and Miami.** 4140/ something. e.g. 4140/5.5 ≈ 753 near tile; 4140/6 ≈ 690 near shingle. Possible contamination from Miami OH Metrics (~$4,140) into “Jupiter” rates. Not proven; worth asking.

**How to test:**
- Ask Tim in one question: “If a tile day runs 4 men instead of 3, is OH still $745 or does it move?”
- Ask: “Derive $745 for me from daily office burn.” If he cannot, they are folklore constants.
- Compare rates × his stated 1.5 crews against $1,470: \(0.5 \times 1050 + 1.0 \times 745 = 1,270\) (tile day mix) ≠ 1,470. **$200/day structural hole.** Shingle mix: \(525 + 700 = 1,225\). Metal: \(525 + 850 = 1,375\). Demo-heavy day closer. **His emailed rates under-recover Jupiter burn under his own 1.5-crew assumption.** The other AI did not flag this. It is the single most important arithmetic fact in the file.

---

## 3. Validating against “2026 median sold $/sq”

**This validation is weak and partly circular. It is not “sound.”**

Problems, specifically:

1. **Wrong population.** Benchmark = ~45 sold re-roofs/type in 2026 job-costing. Comparison set = 21 of 30 homes Tim hand-sent (selection bias: homes he still has day counts for, i.e. ones clean enough to document). Hand-sent medians: tile $1,222 vs 2026 sold $1,100 (+11%); metal $1,688 vs $1,252 (+35%). **The 21 homes are not drawn from the same price distribution as the benchmark.** Metal in the 21 is at 2024 spike levels. Comparing model quotes on 2024-priced jobs to 2026 medians is garbage.
2. **Median $/sq collapses job structure.** OH is driven by *days*, hence by mix of demo vs install, squares, access, pitch, tear-off layers. A single $/sq median assumes OH/sq is stable. His own formula says it is not (small jobs have higher OH/sq).
3. **Composition mismatch.** 2026 sold medians include whatever mix Jupiter actually sold. The 21-home set has its own mix. No stratification by size bucket, zone (FBC/HVHZ), or branch.
4. **n is tiny for metal in the validation set** (3 homes). Reporting “+0.8% metal” to one decimal is false precision. With n=3 at 2024 prices, the metal column in the comparison table should be marked unusable, not cited as evidence.
5. **Confounds price with cost recovery.** Sold price = materials + labor + OH + profit − discounts + sales effects. Matching sold median means the *stack* matched, not that OH is right (see Q8).

**Better validation, in order:**
1. **Component-level:** on jobs with known day counts, compute OH three ways (emailed rates, man-day $210, man-day $238) and compare to what Tim *actually put in the quote as OH* if the sheet preserves it — not to final price.
2. **Recovery test:** over a month of Jupiter production, \(\sum \text{OH charged}\) vs \(1,470 \times \text{working days}\). Target ≈ 1.0. This is the only test that answers “does the allocator fund the office?”
3. **Stratified price backtest:** by roof type × size quintile × zone, compare quote to sold, with profit levers frozen at Tim’s defaults. Report P50/P90 error, not a single median delta.
4. Hold out jobs **after** model freeze; stop tuning on the 21.

The table “his emailed rates +11.7% tile / +1.0% shingle / +3.7% metal” is being used as if it ranks models. It ranks how close a full quote lands to a non-matching median. **Decoration.**

---

## 4. Metal 5.5 sq/day (sheet) vs 8.0 (actual jobs)

**Pricing system should use observed productivity for day counts; OH rate per day is a separate question.**

- OH/sq = (rate per day) / (sq per day). If you feed the estimator 5.5 sq/day metal when crews actually do 8.0, you overstate days by 8.0/5.5 − 1 ≈ **45%**, and overstate metal OH by ~45% before any rate debate.
- His 30-home actuals: tile 7.1 vs sheet 8 (−11%), shingle 18.8 vs 25 (−25%), metal 8.0 vs 5.5 (+45%). **Errors are large and signed differently by type.** Using sheet productivity does not even keep relative OH/sq rankings honest between types.
- Counter-argument for using sheet (manual) numbers: license-manual days are what he tells the building department / what a franchisee can defend / what a slow crew needs. That is a **padding policy**, not a cost estimate. If you want pad, put it in profit or a contingency line where it is visible and negotiable. Hiding pad inside metal days makes metal look structurally more expensive than it is and will lose bids on metal against anyone using real crews.

**What the other AI likely missed:** the productivity error dominates the rate-model error. On metal, switching 5.5 → 8.0 moves OH ~45%. Switching emailed rates → uniform $210 moves metal OH by a few percent (see their own table, +3.7% vs +0.8%). **They are sweating the 3% while the 45% elephant sits in the room.**

For day-count generation in the estimator: use empirical sq/day by phase from job-costing, with a floor at some percentile (e.g. P25) if Tim wants conservative scheduling. Do not use the OH Metrics sheet’s 5.5/25/8.

---

## 5. “1.5 crews” vs 6.17 men/day vs demo 5 + install 3 = 8

**Nothing reconciles cleanly. At least one of these is a slogan, not an operating fact.**

Arithmetic:
- Stated template: 1.5 crews = demo 5 + install 3 = **8 men**, or “one demo and one other.”
- Logged Jupiter: mean **6.17** men/day (n=157), median 6, monthly avgs mean 5.68. Range 1–12.
- 6.17 / 8 = 0.77 of the template. He is running ~**¾ of a 1.5-crew day** on average — or crews smaller than 5+3, or many single-crew days, or repair days with 2–3 men dragging the mean down.
- Office burn allocation: $1,470 / 6.17 ≈ $238/man-day; $1,470 / 8 = $184/man-day; $1,470 / 7 = $210 (config assumption). **The config’s 7 is closest to a round-number compromise, not to either his slogan or his log.**

Which is wrong:
- “1.5 crews” is an **aspiration / capacity planning slogan** (“I assume 1.5 crews on any given day”), not a description of the log. The log wins as description of reality.
- Crew composition 5+3 is a **phase template for a full re-roof day**, not every calendar day. Many logged days are repair-only, punch, or single-phase → mean men pulled down.
- Miami “4 crews/day min” is a **break-even capacity target** against $4,257 burn, not current headcount fact. Treat it as such.

**Implication the other AI soft-pedaled:** if you set man-day rates from 7 or 8 men but only 6.17 show up, you **under-recover** real OH per man-day worked unless volume of days goes up. Recovery test (Q3.2) will show this immediately. Using $238 is more honest to Jupiter’s log; using $210 is more honest to his config fiction.

Also: 1.5 crews × his emailed rates never hits $1,470 (Q2). So **both** the crew slogan **and** the four rates are inconsistent with the stated daily burn. The burn and the log are the only two numbers I would trust without sitting next to him.

---

## 6. Miami

**What breaks:**

1. **Identical per-day rates as Jupiter with 2.9× burn** ($4,257 / $1,470 ≈ 2.90). Every Miami job priced on Jupiter rates recovers ~1/2.9 of office OH it should, all else equal.
2. **Capacity math he already stated:** 4 crews/day minimum to not lose money. If 4 crews × ~8 men = 32 men-days of production capacity needed against 14 `office_men` config — config headcount (14) and “4 crews” do not match either (4 × 3–5 ≈ 12–20). The 14 is another fiction-compromise.
3. **Cannot see Miami OH sheet** (salaries). So we cannot validate whether $4,257 is real, seasonal, or includes non-operating noise (owner draw, one-time, shared corp).
4. **Current system:** `overhead_basis = "branch"` flat $1,400/day for **all three branches**. Miami is being priced as if it were Jupiter. **That alone can explain Miami losing money every quarter since Q2 2024** if volume was planned assuming rates cover Miami burn. This is the smoking gun and should have been the lead finding, not a bullet.
5. Storing Jupiter’s four roof-type rates on Miami is actively harmful: it gives a false sense that “series” basis is ready for Miami when the rates are wrong by ~3×.

**Correct treatment:**
- **Do not** invent Miami per-type rates by scaling Jupiter’s four by 2.9. That preserves folklore ratios and multiplies them.
- Branch flat basis for Miami: $4,257 × days, with days from empirical productivity. Until a Miami OH breakdown exists, flat branch is more honest than fake series.
- Break-even check: required OH recovery / day = 4,257. At 4 crews and his phase mix, back into either required days-sold/day or required OH/sq. If sales capacity cannot hit that, **no allocator fixes Miami** — pricing or cost structure must change.
- Franchisee path: he said Jupiter numbers are “what any franchisee should use.” That is a **product decision** (standard franchise cost book) distinct from **operating Miami truth**. Estimator needs both: a franchise-default book and a branch-override burn. Collapsing them is why Miami is broken.
- Refuse to ship Miami “series” rates until someone shares the sheet or a sanitized total with headcount and crew-day logs parallel to Jupiter’s 157-day log.

---

## 7. What the other AI missed entirely

Questions that should have been asked and were not:

1. **Does the allocator recover the office over a real month?** \(\sum\) OH_charged vs days × burn. Never mentioned. This is the only non-circular OH test.
2. **Why do emailed rates × 1.5 crews under-recover $1,470 by $100–250/day?** (~7–17% hole every day).
3. **Selection bias of the 21 homes** and metal n=3 at 2024 prices. The comparison table should have been withdrawn for metal, not published as “+0.8%.”
4. **Productivity dominates rate choice** (metal +45% days error). Entire debate is on the wrong decimal place.
5. **Miami flat $1,400 is a direct business failure mode**, not a config nit.
6. **Where did the four rates come from?** No derivation requested from Tim. Without derivation, “achieve per day by roof type” is cargo-culting four numbers that fail internal arithmetic.
7. **Is OH allocated on calendar days or crew-days?** If two crews run in parallel on one job, is it 1 day or 2 of OH? His “1.5 crews on any given day” and “days per task” collide here. Estimator must define this. If two phases same calendar day, double-charging OH against a burn that is per calendar day is a silent overcharge; single-charging under-recovers when multiple jobs run.
8. **Multi-job parallelism:** Jupiter burn is per branch-day, not per job-day. Allocating full daily OH to each job when 1.5 jobs share a day **double-counts**. The sheets Tim built are single-job calculators; they silently assume the job owns the day. At 1.5 crews that is false ~every day. **This is likely the largest conceptual miss in the whole effort.**
9. **Repair/maintenance excluded from sold medians** but Miami “needs 2 re-roof + 2 repair.” Repair OH allocation never modeled. If repairs absorb crew-days but estimator only prices re-roofs with full templates, re-roofs subsidize or starve repairs.
10. **HVHZ vs FBC** affects code/labor/materials (matched 0.0%) but OH days may differ (more inspections, more dry-in time). No one checked whether day counts differ by zone.
11. **Profit levers exist** (Q9) — so why is the team ranking OH models by total-price error against sold medians that include negotiated profit?
12. **Franchise vs captive Miami.** He explicitly split “what franchisee should use” (Jupiter) from Miami. System architecture ignores that.

---

## 8. Circular validation

**Yes, it partially invalidates the “+0.8% metal” type results.**

Sold prices embed Tim’s then-current OH method (old OH Metrics, or per-day rates, or vibes — he has changed methods). Matching sold medians means:

\[
\text{our materials + labor + our OH + our default profit} \approx \text{his materials + labor + his OH + his negotiated profit}
\]

If materials/labor already match his sheets at 0.0%, the residual match is:

\[
\text{our OH + our profit} \approx \text{his OH + his profit}
\]

You can pass this test with **wrong OH and compensating profit**. The metal “+0.8%” result is especially meaningless: n=3, 2024 prices, profit negotiable.

**How to break circularity:**
1. Recover **OH dollars as a line** from historical quotes/sheets if stored; compare OH to OH, not price to price.
2. **Branch recovery identity** (Q3.2, Q7.1): independent of sold prices entirely. Uses burn (from accounting) and days charged (from estimator). Gold standard.
3. **Cost-plus audit on a sample:** rebuild OH from timesheets (men × days × burden) and compare to model OH. Jupiter has men-on-site logs — join them to jobs.
4. Freeze profit at a stated default; report OH and price errors **separately**.
5. Stop using “closeness to 2026 sold median” as a model-selection criterion. It is a market-fit check on the full stack after OH is grounded.

Motivated reasoning flag: the comparison table is structured to make “uniform crews @ $210” look like the winner (lowest deltas). $210 is also the config’s existing assumption. That is convenience, not evidence.

---

## 9. Does overhead precision matter commercially?

**Somewhat, but the team is over-fitting the wrong layer — with one critical exception (Miami).**

Profit levers available: size-sliding curve, $2,500/on-site-week floor, %/amount discounts, $/sq overrides. Those can absorb tens of percent on a deal. OH model differences in their table are 1–3% on shingle/metal total price, ~10–12% on tile.

When precision **does** matter:
- **Miami vs Jupiter:** 2.9× is not absorbable by a discount lever without destroying margin visibility. Branch burn is load-bearing.
- **Small jobs:** OH/sq blows up; wrong days or wrong daily rate flips jobs from profit to loss under the $2,500/week floor interaction.
- **Franchise packaging:** if franchisees get Jupiter book, numbers must be defensible and recover a standard office, not Tim’s gut.
- **Tile at +11%:** that is enough to lose bids or dump margin, and tile is high n (45). Worth real attention — but fix days and recovery first, not crew-fraction theology.

When it **does not**:
- Arguing $210 vs $238 man-day (13% on OH, ~2–4% on price) while profit is freely negotiated and metal productivity is 45% wrong.
- Ranking models by total-price error to sold medians that already include his OH and his sales discounts.

**Commercial order of operations the other AI should have prescribed:**
1. Fix Miami branch burn (or stop selling Miami on Jupiter rates). Hard gate.
2. Define OH as recovery of branch calendar-day burn, with explicit rule for parallel crews/jobs.
3. Replace sheet productivity with empirical sq/day (especially metal 8.0, shingle 18.8).
4. Pick one simple rate model (flat branch $/day × job_days allocated, or man-day × logged men), calibrate to recovery ≈ 1.0 on Jupiter log.
5. Leave profit levers to do market work; stop pretending OH tuning is price tuning.
6. Only then, if franchise needs per-type rates, **derive** them from recovery math — do not enshrine the emailed four.

---

## Load-bearing vs decoration (summary verdict)

| Claim | Verdict |
|------|---------|
| Cost/materials match sheets at 0.0% | Load-bearing, done |
| Emailed four rates are what Tim currently “uses” | Load-bearing as intent; arithmetically inconsistent with $1,470 and 1.5 crews |
| Four rates ≡ man-day × integer crews | **False** for installs; demo only |
| Uniform $210 wins because table deltas are small | **Decoration / circular** |
| 2026 sold medians validate OH model | **Unsound** (selection, composition, circularity, metal n=3) |
| Jupiter log 6.17 men/day | Load-bearing; kills “1.5 crews = 8” as description |
| Miami on Jupiter rates | **Load-bearing failure**; likely contributor to Miami losses |
| Productivity sheet vs actual | Load-bearing; dwarfs rate-model debate |
| Parallel jobs vs per-job day OH | **Missed entirely**; conceptual hole |
| Profit levers make OH cosmetics | Half-true for Jupiter fine-tuning; false for Miami and small jobs |

**Bottom line:** The other AI optimized a cosmetic match to Tim’s folklore rates and a circular price table, while missing (a) the recovery identity, (b) parallel-job double-count risk, (c) productivity errors 10× larger than model differences, and (d) Miami being priced at one-third burn. The direction “achieve per day by roof type” is Tim’s voice, not a coherent model — and following it uncritically is the mistake.
