# Four-way review of the estimator pricing model — validated findings (2026-07-25)

Reviewers: Claude `critic`, Claude `architect`, local `gpt-oss-120b-think`, local `qwen3.6-coder`.
Sources given: both Zoom recordings (transcripts + frames + video), `~/perkins-corpus/` (37 RoofR
PDFs, golden proposals, material prices, lumber schedule, low-slope comments by cell), the three
live Google sheets, prod configs, and the repo.

**Every finding below was re-verified directly before being recorded here.** Reviewer claims that
did not survive that check are in §5, including two false positives and one overstatement.

---

## 0. A process bug found first — the local reviews initially ran blind

`~/.local/bin/llm` read stdin **only when there was no prompt argument**, so
`cat bundle.md | llm -m gpt-oss-120b-think "question"` silently discarded 20k tokens of context and
the model answered from nothing. No error; plausible-looking output. Both local reviews had to be
re-run. Fixed — stdin now prepends, verified for stdin-only, arg-only, and both.

The global CLAUDE.md documents the prepending behaviour that did not exist. This is the same class
as the pricing bugs below: **a silent failure that returns success.**

---

## 1. CRITICAL — live, silent, costs money today

### F1. Low-slope insulation always prices at $255/sq. The $275 and $310 tiers are unreachable.

`core/pricing_config.py:309-319` returns on the first tier whose `max_sq is None`; the fixture holds
`[[null,255],[null,275],[null,310]]`, so the loop exits on iteration one. Verified:

```
5 sq -> $255   50 sq -> $255   134 sq -> $255   500 sq -> $255
```

Root cause is the §4 pattern: the schema is `[max_sq, price]` — a **job-size** breakpoint — but
Tim's cells K15/K16/K17 price **board thickness** (1" $255 / 1.5" $275 / 2" $310). Thickness is not
size, so all three rows got `max_sq=null` and the mismatch degenerated to a constant. There is no
thickness input at all: `include_insulation: bool` is the only control
(`core/estimator.py:398`, `api/routes/estimator.py:163`).

**Impact:** every 1.5" or 2" spec under-quotes $20–$55/sq, silently, no warning. On the 134-square
Miramar-class job Tim actually sent, $2,680–$7,370.

### F2. The app cannot send four priced dimensions — including the 7/12 adder this whole session was about.

`web/src/pages/Quoting.tsx:1051-1056` hardcodes:
```js
project_kind: "residential",   tile_pointing: "no",   pitch_7_12: false,
```
and `specialty_tile` is never sent (grep returns only these three lines).

So, from the live app:
- **The 7/12+ adder can never fire.** $305 vs $200 — the question the email leads with, the thing
  the comment-derived pricing changed — is commercially inert until this line changes.
- **No commercial job can be quoted.** `permit_commercial_add` ($500) and both commercial PM bands
  are unreachable.
- **Tile pointing** ($200/sq) unreachable.
- **Specialty tile upgrades unreachable** — Santa Fe $160, Verea "S" $195, Verea Caribbean $120.
  Note the irony: earlier today I verified these match Tim's sheet exactly. They cannot be selected.

---

## 2. HIGH

### F3. The $2,500 floor raises the salesperson's commission by 79% on exactly the jobs it protects.

Order of operations, `core/estimator.py`: `_apply_min_margin` (1180) **mutates the profit line**,
then `_compute_margin` (1202) reads the floored value, then `commission = profit_dollars × rate`
(1206-7). Measured, 10 SQ HVHZ 13" tile:

| | profit | commission | project total |
|---|---:|---:|---:|
| floor off | $1,400 | $140 | $15,250 |
| floor on | **$2,500** | **$250** | $16,350 |

The floor exists because a small job cannot carry itself. It currently pays out 79% more commission
for that fact. Nobody has stated whether Tim's $2,500 is before or after commission — if after, the
floor should be `2500 / (1 - rate)`. **Needs Tim, not just a code change.**

### F4. "Job" basis does not survive Tim's own words, and flipping to "weekly" would currently be a no-op.

Verbatim, 7/17 [08:52]:
> "i like to make 2500 bucks a week that we're on the job it's kind of like my minimum **and if it's
> one day it still counts as one week** and i'm still gonna charge 2500 bucks minimum on re-roofs"

"If it's one day it still counts as one week" is a **round-up clause inside a multiplier** — it is
only worth saying if longer jobs count as more weeks. Under a flat per-job floor the sentence is
vacuous. We shipped `basis="job"` on the reasoning that he never said "$5,000 on a two-week job";
that reasoning cannot distinguish the two readings.

And the flip would not take effect: `overhead_mode` defaults to `per_sq`
(`api/routes/estimator.py:172`, `Quoting.tsx:642`), so `q.daily_series` is empty, `on_site_weeks`
is `None`, and `effective_floor` falls back to `job_profit_floor`. **Fix the plumbing before asking
Tim, or his answer cannot be applied.**

### F5. A second floor tier was dropped.

7/17 [08:15]: *"i'm not gonna do this job unless i make at least 2500 bucks right unless unless i
make at least four grand."* Jon then offers rules "if it falls into one of those **tiers**" and Tim
says *"that's perfect"*. Most defensible reading: **$4,000 absolute walk-away per job, $2,500 per
on-site week** — two different quantities. Config sets `job_profit_floor = weekly_profit_floor =
2500`, and since `effective_floor = max(absolute, weeks × weekly)`, the two collapse. **No test in
the repo can distinguish them.**

### F6. The discount guardrail is dead under the basis we are about to switch to.

`api/routes/estimator.py:403-405` reads `result.get("profit_floor_guidance")` when
`basis == "weekly"`. Verified: that key exists **neither at top level nor nested**. So the read is
`float(None or 0)` = 0, falsy, and `min_margin_breached` can never fire. Harmless today only because
prod runs `"job"` — a landmine directly under open question #1. The comment above it states the
threat model correctly ("Sales holds `quoting_create`, so that lever is exactly the one they have").

### F7. The day model is calibrated only on Jupiter and deployed to all three branches.

I enumerated all 37 RoofR PDFs: Palm Beach Gardens (14), Jupiter (10), Palm/Juno/Delray/Boynton
Beach (8), Port St. Lucie (2), Wellington, Boca Raton, Greenacres. **Zero Miami-Dade. Zero Broward.
Zero Collier. Therefore zero HVHZ homes.**

This is precisely the argument `scripts/revert_miami_office_overhead.py` used to kill the Miami
overhead multiplier — *"the test was mathematically incapable of detecting an error in the only
branch the change moves"* — not applied to the day model, which is fit on the same homes.

**The sample is also clustered:** 9 of the files are one complex (Evergrene Parkway, Palm Beach
Gardens). Leave-one-out on clustered data leaks — holding out one unit leaves eight near-twins in
training. The reported LOO R² (tile 0.80, metal 0.90) is inflated by an unknown amount.

### F8. "93% within a day" is an in-sample number after four rounds of selection on the same 29 rows.

The ladder 69% → 83% → 86% → 93% was obtained by adding rules and re-scoring on the identical set.
LOO fitted the *coefficients*; the *rule choices* were scored in-sample. The steep-roof rule is the
clearest case and the code says so (`core/estimator.py:171-176`): as a fitted regressor,
cross-validation **rejected** it (tile 0.825 → 0.778); re-admitted as a hand-set threshold it was
accepted on an in-sample move of 86% → 93% — **two homes out of 29**.

Two cheap falsification tests, neither yet run:
1. **Leave-one-cluster-out** (group all Evergrene units) instead of leave-one-out.
2. **Report the constant baseline** — predict each series' training mean and compute "% within one
   day". Shingle LOO R² is already 0.364 because his shingle days barely vary (1–3 days), so a
   constant predictor may score near-identically on the headline metric.

### F9. Tim sent an HVHZ **commercial** calculator on 2026-07-24 that nobody had opened.

`~/perkins-corpus/roofr-attachments/2026-07-24__…Commercial__Miramar_Project_Calculator.xlsx`.
Miramar is **Broward — the only HVHZ time data in the corpus.** Read now; it contradicts or answers
four shipped values:

| what it says | vs what we ship |
|---|---|
| *"Re-Roof 8-10 weeks — **5 days per week**"* and *"12 weeks — **5 days per week**"* | `profit_floor_days_per_week = 6`, marked "ASSUMED" |
| Overhead *"$1,175 × 25 days & $765 × 30 days"* | `demo_dry_in_flat 1050`, `tile 745` (residential) |
| **`Profit (14%)`** and **`Profit (15%)`** — commercial profit as a **% of cost** | engine applies the residential per-square `profit_scale` to commercial unconditionally |
| Overhead $560/sq with *"Multiple Increase 2.36"* over a $180 base | no commercial overhead model at all |

At 5 days/week a 6-day job becomes two weeks (`ceil(6/5)=2`) — **+$2,500 under a weekly basis.**
Caveat: this is commercial PM scheduling and may not transfer to residential crews. It is evidence,
not proof — but it is Tim's own document and it is the only thing he has ever put in writing about
days per week.

### F10. The profit floor switch is not in git.

Prod has four keys the fixture lacks: `enforce_profit_floor`, `profit_floor_basis`,
`profit_floor_days_per_week`, `gutters`. `core/pricing_config.py:394` returns
`bool(self.raw.get("enforce_profit_floor"))` → **False** against the fixture. Any tenant or branch
built from git — the GC tenant, tenant-2, a DR rebuild — ships with **no profit floor** and quotes a
1-square tile roof at $400 profit. Against ENGINEERING_RULES **R3**; `scripts/drift_check.sh` (R4)
covers Terraform and Ansible, not `pricing_configs`.

### F11. Two checked-in seeders now disagree, and the older one silently reverts today's work.

`scripts/seed_office_overhead_config.py:36-41` still carries `pitch_7_12_add {HVHZ:200, FBC:305}`
and `winterguard_add {HVHZ:140, FBC:150}`. `scripts/seed_comment_derived_adders.py:51-55` set both
to 305/305 and 135/135. Neither is idempotent against the other. Re-running the older one — a
plausible act when finally seeding Naples' office burn — reverts the comment-derived pricing with no
diff to review.

---

## 3. MEDIUM

- **F12. Repair day rates are unresolvable from the record and Tim promised to email them.**
  7/20 [44:55-45:29], three different two-man figures in 34 seconds: *"$11.85 for one man for a
  day… if it's a two man job, then I charge **$14.35**… I charge **$1400** for two men, one day…
  So $11.85 is one guy, **$14.85** is two guys."* And at [44:39]: *"the main thing in regards to
  the price is just going to be a fixed price, **which I'll provide to you on an email**."* No such
  email is in `tim_emails_manifest.json`. We ship $1,435 with a note reading "CONFIRMED (Tim's
  words)". These exact numbers already suffered a 100× decimal slip once. **Chase the email.**
- **F13. Shingle daily overhead $700 is ours, not Tim's.** He states demo/flat $1,050, tile $745,
  metal $850 and never a shingle rate. Jon says on 7/20 [35:10] *"seven hundred dollars a day is
  configured in admin"* — we told him and he did not object. That is not confirmation.
- **F14. Low-slope `tear_off_extras` is unread.** `{hauling 20, labor 20, oh 35}` plus a `+$75/sq`
  extra-layer rule; `core/estimator.py:1303-1305` prices only the $20. Tear-off bills at ~27% of
  its own config.
- **F15. `roof_cuts` is a 3-way enum but Tim uses it as a free-form dollar catch-all.** Config is
  `{low:0, medium:25, high:50}` per square; Tim's own worked example was **$45/sq** for hand-loading
  a rear roof with no truck access, and he describes the field as *"for roof cuts or for random
  stuff like extra delivery fee"* [7/17 03:29]. $45 is not expressible. Same shape error as
  commission and PM incentive.
- **F16. Dead config with no reader:** `zones`, `counties` (both *required* keys), `pressure_cleaning`,
  `roof_height_notes`, `crane_threshold_stories`, `coatings_inhouse_oh` (unreachable — `all_in_systems`
  gates it out before the key is read), `profit_mode_default`. `counties` is the only structure that
  could stop a Naples rep selecting HVHZ, and Collier is not in it.
- **F17. `crane_threshold_stories` says 5+, code raises manual review at `6_plus`.** Off by one
  story; code wins.
- **F18. Unmapped roof types silently take the demo rate.** `Quoting.tsx:1039`
  `INSTALL_SERIES_BY_ROOF[rt] ?? "demo_dry_in_flat"` — a new config-driven roof type prices its
  install at $1,050/day.
- **F19. Coatings have no size floor.** Tim's sheet: *"Coating Prices Based on 25+ squares (Demo not
  included - add $100)"*. `all_in_systems` is a flat list with no size guard, so a 10-square silicone
  job quotes at the 25-square rate.

---

## 4. The pattern behind all of it

**Config keys were shaped from where a number was found — which sheet tab, which column — rather
than from what it actually varies by.** Tim's tabs are named for zones and for people
interchangeably, so tab-derived keying produced a zone axis wherever the real axis was branch,
person, thickness, or material.

| key | keyed by | actually varies by |
|---|---|---|
| `commission_pct` | (slope_type, zone) | **salesperson** — "it just varies by the salesperson" [7/20 03:41] |
| `pm_incentive` FBC | residential/commercial | **size only** |
| `insulation_tiers` | job squares | **board thickness** |
| `tile_demo_add`/`metal_demo_add` | two named keys | **existing roof material** (4 values; shingle and flat price $0) |
| `roof_cuts` | low/med/high enum | **free-form dollars** |
| `tile_dumpster_boundary_inclusive` | one global bool | **per zone** (15 / 30 / 17.5 across three tabs) |
| low-slope zone axis | HVHZ vs FBC | **nothing** — one table, no zone split |

The sloped-HVHZ commission refutation was the first instance caught. It is the general case.

---

## 5. Reviewer claims that did NOT survive verification

- **"Tile demo contradicts Tim's $25/$35/$65"** (gpt-oss) — **false positive.** Those are different
  line items: $65/sq is tile *hauling*, $25/$35 are labour adders inside base-cost build-ups. Our
  `tile_demo_add` is the sheet's separate demo adder.
- **"Gutters and deck types are missing"** (qwen) — **false positive.** Both fully modelled; gutters
  carry 6"/7", alum/copper/half-round, two-story uplift, elbows, removal.
- **"Tim says roof cuts must be manual, contradicting the automated cut calculator"** (qwen) —
  **misread.** [04:31] refers to *roof height* (crane/harness). The cut calculator is a separate
  thing he demoed approvingly. The real finding is F15, which is narrower.
- **"Eight fixture keys missing"** (architect) — **overstated.** Verified: four
  (`enforce_profit_floor`, `profit_floor_basis`, `profit_floor_days_per_week`, `gutters`), plus one
  the fixture has and prod doesn't (`profit_mode_default`). The severity is unchanged: the floor
  switch is among them.
- **"`profit_floor_guidance` is nested under `profit_guidance`"** (architect) — **partly wrong.**
  It is in neither location for a default quote. The conclusion (dead guard) holds; the explanation
  did not.

## 6. What the reviewers agreed is sound

Config versioning and provenance (immutable versioned rows, never mutate in place, RFC 8785 hashing,
`pricing_config_hash` stamped on every response and persisted per estimate); `_strip_pending_keys`
so annotations cannot move the hash; the `zoned_add` scalar/dict tolerance with ConfigError-not-
KeyError plus per-zone admin rendering; `_audit_payload` stripping debug traces before persistence;
`explicit_profit` refusing to floor an operator-typed number; `derive_daily_series`'s guard against
evaluating the geometry model when every complexity term is zero; `roof_type` validated at the
request boundary against the active config rather than a Python `Literal`; and the profit-band
boundary fix, which is correct for fractional squares as well as integers.

`fit_nonneg`'s monotonicity constraint, rejecting pitch-as-a-linear-term because it degraded
out-of-sample, and testing and rejecting Jon's own padding hypothesis are the most disciplined
decisions in this body of work.

---

## 7. FIXES APPLIED (same day) and the recalculation

### Config/engine changes

| finding | fix |
|---|---|
| F1 insulation always $255 | re-keyed to `insulation_by_thickness {1in:255, 1_5in:275, 2in:310}` + `insulation_thickness` input on `QuoteInput` and the API. Legacy `insulation_tiers` rows now map **positionally** as a fallback, so **already-seeded prod configs resolve all three thicknesses without a reseed**. Unknown thickness raises `ConfigError` (→422) rather than defaulting. |
| F2 four dimensions unreachable | `Quoting.tsx` now sends `project_kind`, `tile_pointing`, `specialty_tile` from real controls, and derives `pitch_7_12` from `selectedMeasurement.pitch_primary >= 7`. Commercial jobs, tile pointing, the specialty-tile upgrades and the 7/12 adder are all reachable for the first time. |
| F6 dead discount guard | reads `result["profit_guidance"]["effective_floor"]`, the path the value actually lives at. `min_margin_breached` can now fire under the weekly basis. |
| F10 floor switch not in git | fixture gained `enforce_profit_floor`, `profit_floor_basis`, `profit_floor_days_per_week`. **This immediately broke two tests that had been passing against a floor-less config** — proof the fixture had not been reproducing prod. |
| F11 seeders disagree | `seed_office_overhead_config.py`'s stale `ZONED_ADDS` removed; `seed_comment_derived_adders.py` is now the single writer of the zoned adders. |
| F14 tear-off billed 27% | new `low_slope_tear_off_total()` sums `tear_off_extras` (hauling $20 + labor $20 + OH $35 = $75/layer/sq), falling back to the old scalar for configs without the block. |
| F15 `roof_cuts` not free-form | added `roof_cuts_per_sq` (engine + API + a UI field). The low/medium/high picker stays as the guide; an explicit dollar amount wins — so Tim's own $45/sq hand-load example is now expressible. |
| F18 silent demo-rate fallback | `INSTALL_SERIES_BY_ROOF[...] ?? "demo_dry_in_flat"` removed. An unmapped roof type now omits the install series instead of billing it at the $1,050/day demo rate. |
| F19 coating basis | two warnings — `coating_below_price_basis` (published on a 25-sq basis) and `coating_demo_not_in_price` (+$100/sq). **Deliberately not priced**: we know the basis is wrong, not what the right number is, and inventing it is how the earlier defects happened. |

### Overhead mode now defaults to BY-TIME (Jon's call)

Tim, 2026-07-17 [09:46]: *"that's how we get the overhead is based on time … this is just a guide
… more of a guide than it is a rule."* `overhead_mode` now defaults to `"daily"` in both the API and
the SPA. With no days typed the engine derives them from the roof's geometry.

This also makes the weekly profit-floor basis **operable** — under `per_sq` the day series was empty,
so `on_site_weeks` was `None` and a `basis="weekly"` config silently behaved as `"job"` (F4).

### Recalculation over Tim's 29 homes — `scripts/compare_overhead_modes_29_homes.py`

| | mean | min | max | total |
|---|--:|--:|--:|--:|
| **B−A** repricing caused by the default flip | **+$227** | −$1,758 | +$2,212 | **+$6,588** |
| **B−C** derived days vs Tim's OWN days | **+$2** | −$1,375 | +$1,050 | — |

Days: **mean absolute error 0.53 d, 93% within one day, 66% within half a day** — the previously
claimed figures, reproduced against prod config.

**Baseline test, run:** predicting every job at the mean 7.0 days lands within one day on **7/29
(24%)**; the geometry model lands **27/29 (93%)**. So the headline is not riding on low variance.

⚠️ **WITHDRAWN — this does NOT refute F8.** The R2 pass was right to call it out: this compares a
6-parameter model fitted on these 29 homes against a 1-parameter mean of the same 29, both scored
in-sample. A 6-parameter model wins that by construction. F8's actual objection was that the *rule
choices* (eaves-on-demo, the ≥6/12 threshold, the elimination stopping point) were selected
in-sample across four rounds — and the steep-roof rule is still inside the 93%. **F8 stands
unrefuted.** The honest test is to refit with the steep-roof rule held out, or to cross-validate
over rule selection, neither of which has been done.

**And F7's clustering objection is wrong on the facts.** The 9 Evergrene Parkway files are in
`~/perkins-corpus/roofr-attachments/` but are **not** in the fitted set: all 29 stored measurements
are distinct addresses, none of them Evergrene. The reviewer conflated the corpus directory (37 PDFs)
with the training set (29 homes). Leave-one-out does not leak.

**What does survive from F7:** all 29 fitted homes are Palm Beach County, so there is still **zero
HVHZ calibration**, and the model is applied to all three branches. That remains open.

### Still open after this wave

F3 (the floor inflates the commission base) needs Tim, not a code change — though the sheet formula
`B27 = (B4*B18)*rate` confirms commission is computed **from** profit and never added to the total,
so his "$2,500 minimum" is a pre-commission floor and our implementation matches his structure.
F5 (the $4,000 second tier), F9 (commercial pricing as a % of cost), F12 (repair day rates), F13
(shingle daily rate) are all in the draft email. F16/F17 dead config keys are untouched.
