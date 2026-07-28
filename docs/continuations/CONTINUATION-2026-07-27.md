# CONTINUATION 2026-07-27 — the email is SENT, prod is current, and two rules were wrong

**HEAD `542434f`, deployed, pushed.** Prod configs **jupiter v19 / miami v20 / naples v19**.
`drift_check` clean. The Tim email **went out at 16:08 on 2026-07-27** with two attachments.

This session was mostly not building. Jon asked twice whether the evidence had really been swept,
and both times the answer was no — the second sweep changed a live pricing rule.

---

## 0. What changed in the world

| | before | now |
|---|---|---|
| profit floor | flat $2,500 per job, 6-day week | **$2,500 × ceil(days/5)**, per on-site week |
| PM incentive, FBC residential 35 sq | $50 | **$100** |
| accuracy quoted to Tim | 93% within a day | **83%**, out-of-sample |
| 918 Mil Creek | $41,575 | **$43,075** |
| build-up section | hard-off, no UI | checkbox + customer/internal audience |
| deployed image | `27e076d` (21 behind) | `542434f` |

---

## 1. The two findings that mattered

### 1a. "93% within a day" was in-sample — and it was in the subject line

`four-way-review-2026-07-25.md` **F8** had already said so, named two falsification tests, and
recorded that neither had been run. They stayed un-run for two days while the number was quoted to a
client as measured accuracy. `scripts/honest_day_model_cv.py` now runs the first — feature
elimination **and** the steep-rule choice nested inside the CV loop:

| scoring | MAE | within 1d |
|---|--:|--:|
| in-sample | 0.52 | 93% |
| LOO, coefficients only | 0.64 | 86% |
| **LOO, rule selection nested** | **0.67** | **83%** |
| constant baseline | 2.29 | 34% |

**The rule survived; the headline didn't.** The ≥6/12 +0.5-day adder was re-selected in 27 of 29
folds and switched off in none. F8 was right about the number and wrong about the rule — worth
separating, because they need different fixes.

### 1b. Tim answered two "open" questions in an email on 2026-07-10 and nobody had looked

Round one read both Zoom transcripts end to end and took the cell comments on trust. It never
searched the mailbox. Round two swept 273 comments + all 89 emails from Tim (Josh 12, Marco 6):

- **`SHINGLE INSTALL: $700 per day`** — the draft asked for this and asserted "$700 is our number,
  not yours". He sent it 7/10 and again 7/24.
- **The profit floor is per on-site week**, with his own worked example: *"7 days of work, on a 40 SQ
  metal roof, I would charge closer to $5,000 at a min., because it's still taking up 2 weeks of work
  in window after inspections"* — and $2,500 on an 8-square 1.5-day roof. We had shipped
  `basis="job"`, and `seed_min_margin.py`'s docstring defended it with *"he never said $5,000 on a
  two-week job"*. He did, a week before the Zoom that docstring cites.

Both halves reproduce exactly at a **5-day** week (Jon's call; also what Miramar says twice).
Across his 29 homes: lifts 20, **+$28,655 (+2.6%)**.

---

## 2. Shipped

| commit | what |
|---|---|
| `6b1d706` | honest CV script; `seed_pm_incentive_axes.py`; **`e20aa18` had shipped two failing tests** and two seeders that would have reverted prod on replay |
| `4cb737f` | round-two validation — the comment + mailbox sweep |
| `50e7b64` | weekly floor, 5-day week; `docs/PRICING_RULES.md`; copy-config spec |
| `0b3a576` | spec rewritten on Jon's scope rule |
| `542434f` | **§1a checkbox + §1b customer audience** |

**`docs/PRICING_RULES.md`** — every rule the estimator follows, each with its source named (sheet
cell / comment / email / call timestamp), OPEN where we picked something. Renders to an 8-page PDF
via `scripts/render_pricing_rules_pdf.py`. It went to Tim as the second attachment.

**The customer build-up (§1b).** Folding, not hiding: removing the profit row leaves the rest summing
to the total, and folding only overhead+profit still leaks because Tim *publishes* a per-square
overhead. So base + overhead + profit collapse into one $/sq line.
`test_customer_mode_cannot_be_differenced_back_to_profit` brute-forces every subset of the visible
amounts and each subset's complement. Rows are frozen into the snapshot at create time — a proposal
must re-render as it was **sent**, and `_freeze_calc_breakdown` strips the raw trace the way
`_audit_payload` does, since a snapshot has the same readership as an estimate row.

---

## 3. Open, ranked

1. **R2 on this wave** — architect + critic, binding in CLAUDE.md, **still unrun**. Blocked on the
   session-directive conflict (surfaced, not resolved). It is the rule that caught the invented
   "Miami 15% / Jupiter 10%".
2. **Tim's 13 answers become config changes.** The one that can move numbers again: *what counts as a
   week* — crew-days ÷ 5 (built) vs calendar occupancy including inspection waits (his wording).
3. **Copy-config, step 1** — `docs/specs/2026-07-27-copy-config-between-branches.md`. Classify-only,
   no numbers move. Jon's rule: material `shared`, labour/overhead `branch`.
4. **Split L from M.** `sloped_base_cost_lm` fuses them, so Jon's rule can only be applied to about
   half the money. 29 of Tim's comments carry `L / M / OH / P` breakdowns.
5. Jarvis #430 project container, #427 commercial scope model, #418/419/424/428/429/431.

---

## 4. Gotchas that cost time

- **All 50 config keys are byte-identical across the three branches.** `daily_overhead_rates` are
  Jupiter's ($1,050/$745/$850/$700, from 30 Palm Beach homes) and Miami and Naples quote them today;
  Naples is supposed to carry zero overhead. `zones`/`counties` are a **global** county→zone map, not
  per-branch geography — I had that wrong in the first spec draft.
- **`pgrep -f "pytest tests/"` matches your own waiter shell.** An until-loop on it waited 1h55m on
  itself while the suite was fine. Wait on the PID.
- **A config change is four places** — fixture, prod, tests, and any seeder that could replay an old
  value. `e20aa18` did one of four.
- **A test docstring is not a source.** `profit_floor_days_per_week = 6` was justified in a docstring
  by "the crews work Mon-Sat" and then treated as settled fact for a week.
- Verify a guard can fail. My first fail-closed check tested the *output* being empty, which it never
  is; the real signal was the *input* carrying no `explain`.
- Cloud SQL proxy `127.0.0.1:5432`, db **`perkins`**, user **`app`**; every query needs
  `set app.tenant_id='1'`.
- Graph: `$filter` + `$orderby` together 400s — use `$search="from:…"`. Attachments are **additive**;
  delete before re-attaching.

**Standing archive directive:** `CONTINUATION-2026-07-25.md` archived to `docs/continuations/`,
keeping the latest three at top level.
