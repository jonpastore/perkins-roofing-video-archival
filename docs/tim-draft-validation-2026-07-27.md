# Validating the Tim draft against the evidence — 2026-07-27

Jon: *"validate the contents of the email, make sure it's all accurate, and note what's addressed in
the Zoom transcription. I'm afraid you have not 100% analysed everything because there are too many
questions."*

He was right on both counts. **Both Zoom transcripts were read end to end this session** (7/17,
11,682 words; 7/20, 12,027 words) — not grepped, read. Three of the email's fourteen questions are
already answered on the calls, one asks Tim for something he supplied on camera, and the email's
headline number does not survive its own repo's review.

Method: every claim traced to a primary source — transcript line, RoofR PDF, live-sheet cell, prod
DB row, or a re-run of the script that produced it. Where a number could not be reproduced, that is
recorded as a finding rather than assumed correct.

---

## 1. The headline is in-sample, and it is in the subject line

`docs/four-way-review-2026-07-25.md` **F8** — marked "stands unrefuted" — says the "93% within a
day" figure came from four rounds of rule selection re-scored on the same 29 homes, and that the
steep-roof rule was *rejected* by cross-validation as a regressor before being re-admitted as a
hand-set threshold on an in-sample gain of two homes. The review named two falsification tests and
recorded that neither had been run. The email states 93% / 66% / 0.5 days as measured accuracy, with
no caveat, in both the subject line and the opening.

**The test has now been run** — `scripts/honest_day_model_cv.py`, which nests the feature
elimination *and* the steep-rule choice inside the cross-validation loop:

| scoring | MAE (days) | within 1.0d | within 0.5d |
|---|--:|--:|--:|
| in-sample (what the email quotes) | 0.52 | **93%** | 69% |
| LOO, coefficients only, rule frozen | 0.64 | 86% | 59% |
| **LOO, rule selection nested — honest** | **0.67** | **83%** | **59%** |
| constant baseline (training mean) | 2.29 | 34% | 21% |

Two conclusions, and the second is good news:

1. **The honest figure is 83% within a day and an average miss of 0.67 days**, not 93% / 0.5. The
   email must quote 83%.
2. **The steep-roof rule is real, not an artifact.** Re-chosen from a
   (threshold × days) grid on the training fold alone, it was selected in **27 of 29 folds** and
   switched off in **none**; the only competing pick was the adjacent `≥5/12, +0.5d`. F8's specific
   suspicion is answered — it just answered against the headline, not against the rule.
   The model also beats a flat 7-day guess 83% to 34%, so the number is not riding on low variance.

Bias is small either way: +0.07 d in-sample, +0.16 d honest. We run marginally long, not skewed.

---

## 2. Already answered on the calls — questions that should not be asked

### 2a. Commission — Tim answered the shape on 7/20

The email asks *"Commission — is it per salesperson?"* and reasons from the sheets. He said it
outright at **7/20 [03:28]–[03:49]**, replying to Jon on commission defaults:

> "yeah mostly net mostly net … unless it's like outside so like **it just varies by the salesperson**."

That settles two things the email treats as open: it is **per salesperson**, and it is **mostly net**
— a percentage of profit, not of contract. Only the per-person rates remain open.

The email also repeats a reading this repo already withdrew: *"Miami says 15% and Palm Beach 10%, so
I read it as a branch rule."* Per `open-questions-resolved-from-live-sheets-2026-07-25.md` §S3, the
"Miami 15% / Jupiter 10%" label **"was invented, not read"** — no Jupiter tab on any of the three
sheets carries a commission cell at all. Repeating it to Tim re-asserts a claim we know is unsourced.

### 2b. Naples overhead — the email says we have nothing; Tim told us

Email: *"Naples I have nothing for at all."* At **7/17 [40:20]**:

> "that's good because **Miami's overhead is more than Jupiter's and Naples has zero overhead right now**."

That is an answer. The question narrows to whether it still holds and when Naples starts carrying
overhead — not "what is it".

### 2c. Repair day rates — the third number is probably Josh's, not Tim's

Email: *"you said $1,185 and $1,435, then $1,400, then $1,485."* The passage, **7/20 [44:55]–[45:29]**:

> **TIM:** "$11.85 for one man for a day is what I'm charging … if it's a two man job, then I charge
> $14.35. **I don't know what you're using Josh** for your overhead and labor and gas, but that's my
> numbers." — "I charge $1400 for two men, one day, same thing." — "Yeah, $14.35 and $11.85." —
> "So $11.85 is one guy, $14.85 is two guys."

Tim hands off to Josh by name immediately before the $1,400, so that is most likely **Josh's Miami
number, not a third Tim number** — the same per-person pattern as commission. And "$14.85" is an ASR
slip for $14.35 in the same breath. Presenting four numbers as Tim contradicting himself is unfair to
him and misreads the evidence. ✓ Accurate: he did promise the fixed prices by email ([42:37]).

---

## 3. 1141 Vintner Blvd — we are asking for something he already gave us, on camera

Email: *"1141 Vintner Blvd is the one home with no RoofR report in what came through. Send it and
the model covers all 30."*

Tim entered that house into the app **live on the 7/17 call**, and the screen share captured it.
Frame 291 of the recording (`~/Documents/Zoom/2026-07-17…/video1033724674_frames/`) shows
`1141 Vintner Boulevard, Palm Beach Gardens FL 33418, Palm Beach County · FBC` with the measurement
form filled: **43 SQ, 255 hips, 64 ridges, 99 valleys, 5 rakes, 370 eaves, 83 wall flashing, 4/12**.

Those exact values are in prod today — `measurements`, `provider='manual'`, `provenance_note='RoofR'`,
`created_by='tim@perkinsroofing.net'`.

His **day figure is corroborated three ways**: he says it at **7/17 [09:32]** — "four days for us to
do the demo and then six days to do the tile" — frame 12 shows the same job in his own Custom Tile
Calc (43 SQ, base $768 → he uses $770), and his sheet's overhead for Vintner ($202/sq × 43 = $8,686)
reconciles to 4 × $1,050 + 6 × $745 = **$8,670**.

The one thing genuinely missing is the **RoofR PDF**, and therefore the **facet count** — which is
why the fitted set is 29, not 30. Ask for the PDF and say why. Do not ask for measurements he
already typed in front of us.

---

## 4. Live in git, not in prod — the email claims fixes a customer can log in and disprove

Prod runs `platform:27e076d` (**21 commits behind HEAD**) with configs jupiter v17 / miami v18 /
naples v17. Exact diff of the active prod config against `infra/fixtures/pricing_config_exhibit_b.json`,
identical on all three branches:

| path | prod | fixture | email says |
|---|---|---|---|
| `pm_incentive` | old commercial-keyed matrix | size/kind bands | "That is corrected" |
| `cuts_calc.tile_brands.verea_caribbean.rake` | 19.14 | 13.98 | "All fixed from your sheet" |
| `cuts_calc.tile_brands.verea_caribbean.field` | null | 230.00 | — |
| `cuts_calc.tile_brands.verea_s.field` | null | 297.04 | — |
| `cuts_calc.tile_brands.other.field` | null | 310.00 | — |
| `low_slope.overhead.FBC.tpo_oh` | 135 | 125 | "All fixed" |
| `low_slope.default_flat_system` | absent | polyglass_sav_sap | asks Tim to confirm a default that isn't live |

Priced through the real resolver, the PM defect is exactly as documented:

```
FBC  residential 35 sq -> $50          ->  $100     <-- live money, understated
FBC  residential 60 sq -> $50          ->  $250     <-- live money, understated
HVHZ commercial  10 sq -> ConfigError  ->  $300     <-- small commercial cannot be quoted at all
```

Mixed sloped+flat as one job (`b1b32ee`) is also code-only. **Resolved this session:** seeded and
deployed (§7), so the claims are true when he reads them.

**Deployed and safe to claim** (all in `27e076d`): decision-page proposal redesign, lumber-chart
attachment, T&C + contract-FAQ sections, licence on the PDF, named scope templates, gutters and the
separate downspout rate, repair day rates.

---

## 5. Numbers no committed artifact reproduces

Re-running the scripts that should produce the email's analysis gives different figures. None of
$1,448 / $1,705 / $1,276 / $2,392 / $20,669 / $3,025 / −$204 / −$77 / −$73 / −$81 / 4.6% appears
anywhere in the repo.

| email | `scripts/sold_price_trend.py` (calendar-year medians) |
|---|---|
| tile 2024 peak $1,448 | $1,426 |
| metal 2024 peak $1,705 / 2026 $1,276 | $1,697 / $1,255 |
| shingle 2024 peak $770 / 2026 $678 | $757 / $689 |

| email | `scripts/validate_against_tim_30_homes.py` |
|---|---|
| tile −$77/sq (15 homes) | −$72/sq (16) |
| shingle −$73/sq | −$61/sq |
| metal −$81/sq | −$58/sq |
| worst 314 5th St. −$204/sq | −$181/sq |

The likeliest explanation is a trailing-twelve-month slice that was never committed, versus the
script's calendar years — and the home counts differ because the email scores 29 homes and the
script 30. Either way **these cannot be defended if Tim asks how they were derived**, and
`[[slice-price-data-by-time]]` is the memory of what happens when a price series is sliced wrong.
Recommendation: quote only what a committed script prints, or commit the slice that produced them.

---

## 6. Verified correct — no change needed

Transcript quotes, checked verbatim against the recordings:

- **$2,500/week** — 7/17 [08:52], quoted exactly, including "on re-roofs" ✓
- **"unless I make at least four grand"** — 7/17 [08:15], and it genuinely is just before ✓. Context
  the email misses: both numbers are about the same thing — a **6-square** roof he won't do at 10%
  because "it's not worth the liability". He revises himself upward mid-sentence.
- **Daily rates** $1,050 demo/flat, $745 tile, $850 metal, shingle never given — 7/17 [09:16] ✓
- **Two 30-square houses, one with towers, 2 vs 5–6 days** — 7/17 [10:12] ✓
- **Tile demo hauling $65 vs shingle $30** — 7/17 [13:28], [13:56] ✓
- **§0 attribution** — confirmed by reading the passage in context. [12:01]–[12:40] is Jon (he is
  answering Tim's "how many is enough for the AI to learn"); [12:44] is Tim agreeing. The transcripts
  carry **no speaker labels**, so this was inferred from turn structure — but the inference is solid.

Arithmetic and data:

- **918 Mil Creek** — every line checks and sums to $41,575 ✓; matches the regenerated attachment
  line for line. 35 × $770 = $26,950; 5 tile × $745 + 3 demo × $1,050 = $6,875 = $196.43/sq;
  35 × $100 = $3,500; demo $1,050; $650 + $1,350 + $500 + $600 + $100 = $3,200 ✓
- **892 Camellia** — 21.5 × $110 = $2,365, floored to $2,500; the PDF prints `floored = True` ✓
- **Flower Drive 8.0 vs 9.5, Fairview 9.0 vs 10.5** ✓, and both Mil Creek and Flower Drive total
  $41,575 ✓
- **210 Lone Pine 9 facets @ 6/12; 233 Hampton 17 facets @ 5/12** — read from the RoofR PDFs ✓
- **The lot descriptions are grounded, not invented** — rendered page 1 of both reports: Lone Pine is
  a tract street with houses tight on both sides, a dense tree line along the rear and pool cages
  behind; Hampton is on open water. ✓
- **451 South Juno 32.5 sloped + 17.0 flat** ✓, "a third of that roof" ✓, banded as 49.5 ✓
- **Nine of thirty homes are mixed** ✓ (DB: 9 with `flat_sq > 0`)
- **375 articles** ✓ (262 scheduled + 112 published + 1 draft) — note only 112 are actually published
- **25 approved contract-FAQ answers** ✓
- **Tile dumpsters read 15 / 30 / 17.5 across three tabs** ✓
- **Flat $2,500 per job, 6-day week** ✓ — prod `profit_floor_basis="job"`,
  `profit_floor_days_per_week=6`, matching what the email tells him
- **Shingle at $700/day is ours, not Tim's** ✓ — the PDF prints $700 and the email says so

---

## 7. Evidence the email under-uses

- **Access — Tim already gave the mechanism and a price.** 7/17 [02:28]–[03:34]: he adds a manual
  "roof cuts" amount, **$45/sq on Vintner**, because the delivery truck cannot reach the rear
  section and the tile has to be hand-loaded — *"you got to hand load all that shit."* And
  [03:39]–[04:31]: three storeys or high visibility means harnesses all day, which moves his subs
  from **$160/sq to $250/sq**, plus cranes. The email says only "I suspect access, because you raised
  it on the call." He raised it with numbers.
- **His own margin floors** — 7/17 [07:03]: *"I want to make at least 13"* profit and a minimum
  **profit-plus-overhead of 33%**. Prod carries `profit_floor_pct` / `profit_plus_oh_floor_pct`.
  Worth stating as confirmed rather than leaving silent.
- **Lumber schedule** — 7/20 [30:48]: *"we have a lumber chart that is attached onto **all** of our
  contracts."* The email calls it "a one-click optional attachment"; it should default on.

---

## 8. What shipped this session

1. `scripts/honest_day_model_cv.py` — the F8 test, with a `--selftest` that fails if a fold ever
   sees the home it is scoring (a leak would silently restore the in-sample number).
2. `scripts/seed_pm_incentive_axes.py` — immutable-version seeder, dry-run default, merges the six
   git-only paths onto the active config rather than overwriting it, and asserts prod-only keys
   (`office_daily_overhead`, `enforce_profit_floor`, `gutters`) survive the merge.
3. `tests/test_cut_calculator.py` — **`e20aa18` shipped with two failing tests.** It moved the
   fixture and left the assertions on the old values. Both rewritten; the missing-field-cost guard
   now asserts against a config with the cost removed, so filling the real values cannot silently
   delete the guard.
4. `scripts/seed_cuts_calc_config.py`, `scripts/reconcile_tile_brands.py` — both still carried
   `rake 19.14, field None` and would have reverted prod on a replay.

**Standing lesson.** `e20aa18`'s own message says the rule is "the LIVE sheet is the source, and
within it a COMMENT beats the headline cell" — and it applied that rule to the fixture while leaving
the tests, two seeders and prod on the old value. A config change is four places, not one.
