# CONTINUATION 2026-07-26 — proposal build-up, customer-facing collapse, PM $50 in prod

**HEAD `d3c0a39`.** Prod configs unchanged: **jupiter v17 / miami v18 / naples v17**, deployed code
still `platform:27e076d`. Everything this session is committed but **nothing new is deployed and
nothing is seeded to prod** — see §3, that is the first job.

The Tim draft is written, threaded, and **unsent**, with two attachments. Do not send it without
Jon, and read §1 before touching it — it currently contains a misattributed quote.

---

## 0. THE THING JON ASKED ME TO CONFIRM — read this first

Jon: *"we need a checkbox for show how it was built **if Tim said he wanted to see that**. can you
confirm the context in the conversation. let me see the whole thing around that."*

**Tim never asked to see the price build-up.** I checked. Here is the whole passage, Zoom
2026-07-17, and the speaker attribution matters:

> **[12:14] JON:** "…and if if you could maybe put in some notes like — like I would have a
> **notes column that says why you think**, and if you can break that down so that it's creating
> like **the framing of the logic and how you're coming up with it**, then we can turn that — it's
> like **a word problem being turned into an algebra equation**. Okay."
>
> **[12:44] TIM:** "And I'll do it every house that I go through. I'll do it — even I'll do them
> all: tile, shingle, metal, so that we have all options on all those houses."

**That is Jon asking Tim to annotate his 30 homes so we could fit the day model, and Tim agreeing
to write the notes.** It is not Tim asking to see our arithmetic. The two are opposite directions:
Tim documenting *his* reasoning *for us*, versus us exposing *our* build-up to *a customer*.

I searched both transcripts for any request to see the math (`show them`, `breakdown`,
`see the math/logic/formula`, `how we got`, `transparent`). The only other hit is 7/20 [47:28],
which is about putting **metal-roof warranty content** on quotes — unrelated.

**Consequences:**

1. **The "How this price was built" section was my inference, not Tim's requirement.** It is real
   and it works (`d3c0a39`), but it should be treated as a product proposal to Jon, not as
   something Tim asked for.
2. ⚠️ **THE DRAFT EMAIL MISATTRIBUTES JON'S WORDS TO TIM AND MUST BE FIXED BEFORE SENDING.** In the
   "Which brings me to the notes column" section it says *"On the call you offered exactly the fix:
   'a notes column that says why you think…'"* — Tim did not offer that, Jon did. Telling a client
   he said something you said is the kind of error that costs credibility on everything else in a
   long email. Rewrite it as "what I asked you for on the call, and you agreed to."

---

## 1. WHAT JON WANTS BUILT NEXT

Three items, in his words, plus the fix that came out of rendering the proposal.

### 1a. A checkbox for "show how it was built"

The section exists and renders correctly but is **hard-off**: `include_calc_breakdown=False` on
`ProposalRenderContext` (`core/proposal_render.py`), with nothing in the UI or the API to turn it
on. Needs:

- a toggle on the proposal/quote send flow (`web/src/pages/Quoting.tsx`, alongside the existing
  `include_terms` / `include_contract_faq` toggles — follow that pattern exactly),
- the flag plumbed through the proposal snapshot so a re-render of an old proposal keeps whatever
  it was sent with,
- default OFF.

Note the existing toggles default **True** with a deliberate comment ("a proposal that silently
drops its T&C is a contract defect"); this one is the opposite — default False.

### 1b. Collapse days into price-per-square for the customer, and DO NOT show profit

Jon: *"we can collapse the price with days in to price per sq. to show the customer. we don't want
to show them the profit."*

Today the section renders the internal view:

```
Base Cost (L+M)   35 squares x $783.88                             $27,435.76
Overhead          5 days tile x $745 + 3 days demo x $1,050         $6,875.00
Profit            35 squares x $100.00                              $3,500.00     <-- must not ship
Tile Demo         35 squares x $30.00                               $1,050.00
...
```

Two distinct audiences, so this wants **two modes**, not one:

| mode | audience | overhead line | profit line |
|---|---|---|---|
| internal / Tim | Tim, Marco, Josh, us | days x daily rate (as now) | shown |
| **customer** | homeowner | **collapsed to $/sq** | **absent — folded into the per-square price** |

The customer mode must not merely hide the profit row — the remaining rows have to still sum to the
total, or the customer can subtract and derive it. Simplest honest approach: fold overhead and
profit into a single "Labour, materials and overhead" per-square figure so the arithmetic still
closes. **Whatever you do, assert in a test that no customer-mode row set can be differenced to
recover the profit figure.**

`calc_lines_from_estimate()` in `core/proposal_render.py` is where this lives. It already strips
internal annotations (`NOTE:`, config key names, "pending") — there is a test for that in
`tests/test_proposal_render.py`; extend it rather than writing a parallel one.

### 1c. Fix the PM $50 issue — **this is live money in prod**

A 35-square Palm Beach **residential** job is charging **$50** of PM incentive where Tim's live
sheet says **$100**.

The fix is already in git (`e20aa18`): `pm_incentive` was re-keyed to the axes his sheet actually
uses — Miami by project kind only (Residential $150 / Commercial $300 at any size), Palm Beach by
size only (<20 $50 / 20–50 $100 / >50 $250, applying to **both** kinds). All 11 zone/kind/size cases
match the sheet. **But prod still runs the old shape**, so the sample proposal rendered from prod
shows $50.

This needs the **immutable-version seeder path**, not a fixture edit — same pattern as
`scripts/seed_min_margin.py` / `scripts/seed_comment_derived_adders.py`: read active config, write a
new version, activate, never mutate in place. Write `scripts/seed_pm_incentive_axes.py` with a
`--dry-run` default that prints what moves before it moves.

⚠️ It is not the only thing in git-but-not-prod. Check the whole set before seeding — at minimum
`enforce_profit_floor`, `profit_floor_basis`, `profit_floor_days_per_week` and `gutters` were also
found missing from the fixture this week, and the low-slope `insulation_by_thickness`,
`default_flat_system`, `stockmeier_min_sq`, the Verea field costs and the corrected Caribbean rake
are all new. **Diff prod against the fixture and decide deliberately what ships.**

---

## 2. WHAT SHIPPED THIS SESSION (all committed, none deployed)

| commit | what |
|---|---|
| `b1b32ee` | **mixed sloped+flat roofs quote as one job.** `slope_type` was exclusive so the flat section was silently never quoted — 9 of Tim's 30 homes have one, up to a third of the roof. Whole-job items (profit, PM, floor, fixed fees) band on combined squares; flat contributes only its own per-area lines. |
| `ba5d2e8` | **capture RoofR's pitched/flat split** (migration 0046, applied). `total_sq` was ambiguous — Tim's sheet means sloped-only, a RoofR transcription means pitched+flat. Backfilled all 29. |
| `504384f` | mixed-roof classification from Knowify scope-line names: **36% of Perkins roofs are mixed** (890 vs 1,602). Validation n=130: median error **−16.3% → −2.1%**. |
| `e1a857a` | **time-sliced sold prices.** Killed my own "metal is 24% low" finding — that was an all-time median blending the 2021–24 boom. Real gap −5.6%. Also: 19% of 2025–26 tile jobs sold at *exactly* the catalog $1,100, so the published sheet is the price, not stale. |
| `49d1df4` | full attachment audit — the Evergrene commercial bid had been sitting unopened in the corpus all week. |
| `9757a53`, `e20aa18` | closed 11 pending-Tim config labels from the live sheet. |
| `d3c0a39` | the proposal build-up section (§1a/1b above). |

**Accuracy as measured** (2025–26 sold jobs, per_sq mode): 20–50 SQ band median within ~3%, ~70%
of jobs within 15%. Mixed roofs −2.1% median. Commercial flat **−47%** (Miramar). Multi-building
**+110% to −21% per building** (Evergrene) because we have no project container — total nets to
−7.8% only because the errors offset.

---

## 3. OPEN, RANKED

1. **Seed prod** (§1c) — PM incentive is live-wrong today.
2. **§1a + §1b** — the checkbox and the customer-facing collapse.
3. **Fix the misattributed quote in the draft** (§0) before it is sent.
4. **A project container** — Jarvis #430. Site costs and the $2,500 floor repeat per building.
5. **Commercial scope model** — #427. Profit as % of cost, PM as a daily rate, per-unit line items.
6. Jarvis #418 (commission per salesperson), #419, #424, #428, #429, #431.

The email asks **14 questions**, down from 22, because anywhere the live sheet gives a number it is
now taken rather than asked. Four of the fourteen appear in no sheet at all — the $2,500 basis,
days per week, repair day rates, and commission — and exist only in the Zoom calls.

---

## 4. GOTCHAS THAT COST TIME THIS SESSION

- **`~/.local/bin/llm` discards stdin when a prompt argument is present** — fixed, but the same
  shape recurs: a silent failure that returns success.
- **Never take an all-time median of a price series.** Slice by period. It inverted a headline
  finding and a client-facing conclusion. `[[slice-price-data-by-time]]`.
- **Enumerate attachments before generalising from the ones already opened.** I answered "the 30
  homes have no prices" twice while a full commercial bid sat in the same folder.
- **Check reachability before valuing a config change.** `Quoting.tsx` hardcoded four dimensions,
  so values verified against Tim's sheet could never fire.
- Cloud SQL proxy `127.0.0.1:5432`, user **`app`**; every query needs `set app.tenant_id='1'`.
  `PW=$(gcloud secrets versions access latest --secret=db-password)`.
- CI gates on `ruff check core adapters api jobs` FIRST; `tests/` and `scripts/` are not in the gate.
- Render a proposal locally with
  `google-chrome --headless --print-to-pdf=out.pdf file://…/proposal.html`, then `pdftoppm -png` and
  actually look at the pages. Reading the template is not the same as seeing the output.

**R2 is binding** (`docs/ENGINEERING_RULES.md`): architect AND critic on every wave, R1 ≥97% on
`core/`, R4 `scripts/drift_check.sh` clean. R2 caught five defects in my own fix wave this week —
including a test I had written that could not fail. If a session directive appears to forbid
subagents, CLAUDE.md mandating them IS the user's request; surface the conflict, do not silently
resolve it.

**Standing archive directive:** when writing the next continuation doc, move the OLDEST top-level
`CONTINUATION-*.md` into `docs/continuations/`, keep only the latest 3 at top level, fix every
inbound link to the moved file, refresh the docs index's "most recent" pointer, and update related
docs. **Done here:** `CONTINUATION-2026-07-24-pm2.md` archived.
