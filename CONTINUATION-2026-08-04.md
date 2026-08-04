# CONTINUATION — 2026-08-04

**`main` = `618a296`, DEPLOYED AND VERIFIED (prod image tag equals main).** Live configs are now
jupiter **v32**, miami **v33**, naples **v32** — all three on **overhead by days, per branch**.
Migrations through 0055. Closed 2026-08-03/04: **#342 #402 #429 #459 #504**, **#382 → 100%**.

⚠️ **PR #28 IS OPEN AND UNMERGED ON PURPOSE.** CI green. It is a pricing-path change and the
review found a money defect in my own work twice; merging deploys to prod, so it waits for a human.
See §3.

---

## §0 — THE PATTERN THIS SESSION. READ BEFORE TOUCHING THE ESTIMATOR.

**A displayed number and an input number are not the same thing, and this codebase keeps
conflating them.** Three separate defects, all the same shape:

| | what looked true | what was actually true |
|---|---|---|
| Tim's commercial workbook | "he prices low-slope overhead PER SQUARE" (a `$370/sq` cell) | that cell is `$1,175 × 25 days + $765 × 30 days ÷ 142 sq`. **A per-square OUTPUT read as an input.** |
| Knowify scope lines | "the engine underprices flat by 21–39%" | a line's `Price` carries allocated fixed costs; the engine's marginal does not. **Right table, right units, wrong level of aggregation.** |
| the day cells | "pre-filling shows the operator the suggestion" | the cells are an **override channel**. Filling 2 of 3 made the server stop deriving the 3rd — **−$2,940 / −$5,880 on 36% of the book.** |

**In all three I was confident and wrong, and in all three the correction came from opening the
actual artefact** — the untruncated cell, the whole-job total, the `if not q.daily_series` line.

**The review pass earned its keep and then some.** The architect and critic each independently
measured the day-cell defect. After I fixed it, the re-review found **two more defects created by
my fixes** — both from removing a guard that was load-bearing for something else. Do not skip R2
on this engine.

---

## §1 — OVERHEAD IS ON DAYS, PER BRANCH (shipped + applied)

Tim, 2026-08-03: *"Why is this still trying to use per SQ prices on the OH? It's all going to be
based on days."* His numbers, from 2026-07-30:

```
Jupiter / Naples   $1,470/day ÷ 1.5 crews  →   $980 per job-day
Miami              $4,257/day ÷ 4 crews    →  $1,064 per job-day
```

**The big one was ours: `concurrent_crews` was UNSET on all three branches**, so it defaulted to
1.0 and every job carried the whole office day. Miami repriced **−35.3%** (34 live estimates in
30 days); a 30-sq HVHZ tile roof went **$2,087/sq → $1,343/sq**. Jupiter +1.1%, naples +2.3%.

Also fixed: low-slope had **no day model at all** (fitted `days = 0.389 + 0.0851 × squares` from
the 9 homes in his workbook with both flat squares and flat days — it predicts 2.8 d for
Evergrene's 28-sq flat section, his own bid booked 3), and a mixed roof booked the sloped days and
**none** of the flat.

**⚠️ THE RESIDUAL IS THE DAY ESTIMATE, NOT THE BASIS.** On his 35 priced homes, changing only who
counts the days: **his days → 27/35 within 10% (77%); our model → 23/35 (66%)** — exactly his
*"only 2/3"*. Moving the overhead basis moves this by **one job**. Never answer his margin-of-error
complaint with an overhead change.

Reproduce: `scripts/overhead_basis_whatif.py` (what it moves) and `overhead_basis_backtest.py`
(what is right). Roll back by reactivating the prior config row; nothing was overwritten.

---

## §2 — ALSO SHIPPED

| task | what |
|---|---|
| **#342** | `evals/` — offline eval harness, 3 suites over frozen corpus snapshots, gates CI in 0.23s. Each gate verified to FIRE by mutating real code. |
| **#402/#382** | `[metal_roof_guide]` shortcode; plugin v1.4.0 live on staging, page rendering, all 13 provisions + 4 uplift figures + 3 videos present |
| **#429** | 890 mixed roofs analysed; flat section is median **6 sq**, 82% under 12 (= the Stockmeier minimum) |
| **#504** | CompanyCam webhook registered; verified live — correct signature 200, wrong 401, stale 401, old SHA256 scheme 401 |

**The supersede guard fired for real** on the #24/#25 double-merge:
`##[notice]Superseded — c70cf67 is behind origin/main (d066832)`. ⚠️ `gh run view --json headSha`
reports the *branch* head for `workflow_run` events, so both runs looked identical — **the log is
the truth, the JSON is not.**

---

## §3 — PR #28: OPEN, GREEN, DELIBERATELY NOT MERGED

Finishes Tim's *"suggested # of days that can be edited within the cell"*, plus the slope_type
audit fix. **It is a pricing path and it needs a human on the merge.**

What it contains, after two review rounds:
- day suggestion, with the rule **"if the model derived a series that has no cell, suggest
  NOTHING"** — mixed roofs keep the correct price and get no suggestion
- day cells clear when the day-determining inputs change (incl. `access_difficult`, a fitted term
  — a stale suggestion there measured **−$1,470**)
- editing a day cell marks the quote stale (without this, an operator's typed 6 days was
  **discarded** and the proposal priced at the suggested 3)
- a `slope_type == "sloped"` guard on the flat-days block (a pure low-slope quote was booking days
  for area `_build_low_slope` never prices: **+$1,575**)
- `estimates.input_json` persists the **coerced** slope_type; `proposals.py` coerces `daily_series`
  back from dicts (it raised an unhandled **500** on a customer-facing document)

**Still open on it, and worth a decision rather than a patch:** the flat section has no day cell
of its own, and server-side derivation is all-or-nothing (`core/estimator.py`: `if ... and not
q.daily_series`). Making derivation **additive per series** is the real fix and would let the UI
show all three. Both reviewers recommended it; I did not attempt it overnight.

---

## §4 — MEASURED AND REJECTED (do not retry)

**Term-matching the Content-Graph ILIKE** to "fix" its 0/60 coverage on question-shaped queries:
coverage goes to 60/60 and retrieval gets **much worse** — recall@1 **0.4000 → 0.1667**, mrr
**0.5104 → 0.3035**. An OR over distinctive terms matches so many videos the +0.1 boost lands on
wrong ones. **Low coverage there is what keeps the boost precise.** Recorded in `evals/scoring.py`
at the diagnostic itself.

---

## §5 — WHAT THE EVAL HARNESS SAYS IS ACTUALLY BROKEN

- **`pool_recall` 0.783 vs `recall@8` 0.717** — 22% of the time the right video never enters the
  candidate pool. Ranking is not the bottleneck; retrieval upstream is.
- **`groundedness` 0.376** — published articles name more than half their proper nouns outside
  Tim's transcripts. Worst: a 27,000-char article from a **514-word** source whose three cited
  videos hold 6 chunks between them.

Both are now numbers, not opinions, and any fix is provable against the baseline.

---

## §6 — BLOCKED / NEEDS A PERSON

- **#492 stucco metal** — Tim. The only open item with real money on it.
- **#444 BigQuery billing export** — a permission the SA lacks. ⚠️ Check terraform state, not
  `gcloud billing accounts list`; that is a different permission.
- **#456 WordPress cutover** — Jon + Wendy. Gates the content wave.
- **`infra/fixtures/pricing_config_exhibit_b.json` still has `overhead_basis: "series"`** and no
  `office_daily_overhead`/`concurrent_crews`, so **git cannot currently reproduce prod's overhead
  config** (R3). The low-slope day model was added to the fixture; the basis flip was not, because
  it moves golden numbers. Needs a reviewed change.
- **Email draft to Tim** is in his Outlook thread, unsent, and in
  `docs/email-drafts/2026-08-03-tim-overhead-by-days.md`.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation/handoff `.md`, ALWAYS end it with this directive AND perform
it: move the OLDEST top-level `CONTINUATION-*.md` into `docs/continuations/` (keep only the latest
three at top level), fix every inbound link to the moved file, refresh the docs index's "most
recent" pointer, and update related docs.

**Performed:** `CONTINUATION-2026-08-02-eve.md` archived to `docs/continuations/`. Inbound links
repointed and README's "Most recent" refreshed to this doc.
