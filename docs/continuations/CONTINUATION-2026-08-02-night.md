# CONTINUATION — 2026-08-02 (night)

**`main` = `4cb73a5`. DEPLOYED AND VERIFIED: API `platform:4cb73a5` (sha matches), SPA bundle
`/assets/index-C3NGvMvU.js`. Zero open PRs. Migrations through 0054, applied.** Live pricing
configs: jupiter **v29**, miami **v30**, naples **v29**.

Follows `docs/continuations/CONTINUATION-2026-08-02-eve.md`. That doc shipped Tim's four answers; this one is about
what a full backlog audit found underneath them — including a live pricing defect that was in no
task at all.

---

## §0 — THE ONE THING TO READ

**The backlog was lying, in one direction, repeatedly.** A verification sweep of all 64 open Perkins
tasks found **six describing work that had already shipped** — #430, #449, #418, #385/#386, and
#409/#410. The last two were fixed by a *single commit* (`4fd78f7`) whose subject names both task
numbers and closed neither.

R6.3 has required "update tasks on every commit" since 2026-07-18. It was skipped six times. **An
unenforced rule is a suggestion**, so it is now a hook (§4).

Everything below was verified against the code or the prod database before being believed. Two
greps lied and were caught: `#331`'s "solar" is solar panels as a roof *feature*, not the Google
Solar API; `#410`'s "placeholder" is prompt text, not the guard it claims. **A keyword hit is not a
done task.**

---

## §1 — A LIVE PRICING DEFECT THAT WAS IN NO TASK (shipped, #453)

`core/estimator.py` sums `num_squares + flat_squares`, and `measurements.total_sq` is **ambiguous by
provenance**: on Tim's sheet it is the SLOPED area only, on a RoofR transcription it is pitched +
flat. With no recorded split the SPA sent `total_sq` as `num_squares`, so a typed flat figure was
billed **twice**; left blank, the flat area was billed once at the *sloped* rate.

Prod when found: **13 of 42** measurements had no split, **10** estimates were quoted off one,
**0** were actually double-billed — a latent trap, not a fire.

**Fixed in `_quote_input_from_request`**, the shared mapper, so `/quote` *and*
`/estimator/project-quote` are both covered. A guard in `Quoting.tsx` would have fixed one screen
and left project-quote, `scripts/` and every direct API caller exposed.

| case | behaviour |
|---|---|
| recorded split | measurement wins, conflicting body ignored |
| no split + explicit `flat_squares > 0` | **422** naming both readings of `total_sq` |
| no split + flat omitted | prices, stamps `split_unknown` on the audit row |

⚠️ **The first cut of this shipped a worse bug and R2 caught it.** The override was unconditional —
but `_build_low_slope` prices `base * num_squares` and never reads `flat_squares`, so applying a
sloped split to a low-slope quote took 45 squares of `tpo_adhered` from **$35,050 to $8,250, 76%
under**, silently. Now gated on `effective_slope_type == "sloped"`, with a regression test. **This
is why R2 is binding.**

**Then #429a backfilled it** — and the task was wrong about the population too. It described
inferring the split for 890 Knowify contracts by address matching; that is a different table and a
different task (**#429b**, analysis, now in the tail). The `measurements` population was 13 rows and
**7 already carried the answer** in `raw_payload.pitched_sqft`/`.flat_sqft`, reconciling to the
cent. 7 backfilled, 6 left alone with reasons. Pre-image is in
`measurements_split_backfill_preimage`; `scripts/backfill_measurement_split.py --rollback` restores.

⚠️ It **moved prices, correctly**: measurement #13 is 8.28 sloped + 15.51 flat and was quoted as
23.79 all-sloped — **$28,236 → $22,808, −19.2%**.

---

## §2 — #436: THE DAY MODEL, AND WHY 95% IS NOT REACHABLE

Tim wants 95% of homes within a day of his own booked days. Shipped model was 83%.

The analysis already existed and reported **86%** — but that is the score of a *procedure* that
re-picks the feature set inside every fold, and **the folds disagree** (access 14, stories 8, both
7). Shipping one fixed set and quoting 86% would repeat the in-sample selection that turned the old
"93%" headline into 83%, one level up. So a `--frozen` mode now scores each candidate with the set
**fixed**:

    geometry only (shipped)   MAE 0.672 d   83% within a day
    + stories                 MAE 0.586 d   86%
    + access                  MAE 0.586 d   90%   <- SHIPPED
    + stories + access        MAE 0.603 d   90%   same score, worse MAE, one more feature

`access` ships on three independent signals: joint-best score, lowest MAE, fewest features — and it
won 14 of 29 folds. Fitted per series, and the ordering is its own sanity check: **tile +0.747 d,
demo +0.514, metal +0.339, shingle +0.225** — by how much material must be carried.

⚠️ **Quote the RANGE, not the best cell.** Picking the winning arm of four on 29 homes is itself
worth something. The honest number is **between 86% and 90%**.

⚠️ **95% is not reachable from this data and more features will not fix it.** At n=29 one home is
worth **3.4 points**, so the binding constraint is DATA. **Tim offered another 20 homes on the 7/27
call — that is the cheapest next move and it belongs in his letter.**

Shipped end to end so it is not built-and-never-called: `QuoteInput` + `QuoteRequest` + an SPA
checkbox + `scripts/seed_day_model_access.py`, applied to all three branches. It moves **time**,
never a rate; Evergrene is unmoved at +4.2% / +1.4% because the term is inert unless a quote sets it.

---

## §3 — THE PLAN, AND WHAT RALPLAN DID TO IT

`docs/2026-08-02-perkins-execution-plan.md` (v2) survived a three-pass consensus review
(planner → architect → critic, deliberate mode). **Verdict on v1: REJECT. On v2: ITERATE**, with six
text blockers now applied. Each pass found what the previous missed and they contradicted each other
twice — both cases are recorded in the doc.

What the review found that the plan could not:

- **Wave 4 was gated by 11 unchecked WordPress cutover gates that exist in no Jarvis task** (#456).
  Prod's newest post is still **2026-07-02**; everything publishes to staging. **All content work is
  shelfware until this clears.** Jon owns 2 gates, Wendy 3.
- **`#429` was mis-ranked #1** on dollar magnitude (890 / 36%) when its Knowify half cannot move a
  price.
- **The "one letter to Tim" theory was falsified by its own evidence.** He answered a short
  six-question ask **4 of 6 in ~24h**; both failures were *phrasing* — "General Conditions" did not
  land, and he wanted a link. **Ordering was never the variable.** The letter is rebuilt on
  corpus-exhaustion for inclusion and HIS artefact for phrasing (`D19 = SUM(B19:B20)×1.15`, never
  our vocabulary).
- **v1's provenance line was the root defect**: "built from every open Jarvis task" — true, and
  that is what made it blind.

---

## §4 — R6.3 IS NOW A HOOK

`.githooks/` + `core.hooksPath` (tracked, so it survives a clone — `.git/hooks` held only samples).

    Closes #453          finished it — REQUIRES a `Verified:` line
    Refs #429 60%        progress, never closes
    No-Task: <reason>    deliberately not task work

`commit-msg` blocks a commit that references no task, or a `Closes` with no evidence. `post-commit`
syncs Jarvis in real time and runs `ruff` on the changed Python first, leaving the task **open at
90%** instead of closing on a red gate.

**Proven live:** a no-reference commit was refused, a `Closes`-without-`Verified` was refused (HEAD
unchanged both times), and #473 / #436 were closed by the hook itself.

⚠️ **What it cannot do, stated so a green check is not read as more than it is:** it cannot evaluate
acceptance criteria — they are prose ("95% out-of-sample with rule selection nested inside the CV")
and no parser settles that. It cannot run the coverage gate either; R7 forbids it and an hour-long
commit hook gets bypassed within a day. **CI remains the verdict.**

⚠️ **Its first version had a real bug, found by using it:** it linted `scripts/`, which CI does not
(`ruff check core adapters api jobs`), so it held #436 at 90% on a commit CI passes. A gate that
fires on work the repo does not gate is noise, and noise gets ignored. It now mirrors CI's roots.

---

## §5 — BACKLOG STATE

**One project**, named for the repo: **`perkins-roofing-video-archival`**. Six fragmented records
were merged into it (21 tasks re-filed keeping their numbers via `external_id` upsert) and the other
five archived. The naming rule is enforced in code — `jarvis@b1add89` makes `add_task` derive the
project from the git remote and warn on mismatch — **so it cannot re-fragment.**

**~58 open.** 19 wait on a person (13 on Tim), 9 are Jon's decisions, the rest are buildable.

### NEXT UP — verified not-done as of this session's last check

1. **#359 tenant-2 hardening** — `strict=True` present, `require_role_db` used in 2 routes,
   **branch FK absent** (`grep -c 'ForeignKey("branches'` = 0). The `branches` table exists at
   `app/models.py:686`. That FK is what is left.
2. **#360 CompanyCam reader** — `api/routes/companycam.py` has **only** `@router.post("/webhook")`.
   The mirror is still write-only; `CompanyCamPhoto` exists. The PAT half stays blocked on Tim.
3. **#417** thirteen low-slope gaps · **#342** eval harness (`evals/` absent) · **#402** aluminum
   link (5 min).
4. **#452** project-bid commission — plumbing buildable, the *base* waits on #451.

---

## §6 — WHAT IS BLOCKED, AND ON WHOM

**Tim (13):** #451 GC visibility · #422 floor vs commission · #454 Josh's 7.5% · #455 week/inspection
allowance · #414 #426 #428 #431 #441 #446 #448 #415 · #318 (closeable on existing evidence).
**Send, don't ask:** #457 the permit divergence we owe him (+2.3% → +4.2%, *further* from his own
bid) — a telling, not an asking, and it must not ride in the letter.
**Others:** #315/#324 Josh · #407/#442/#443 Wendy+Marco · #408 the invite promised 7/20.
**Jon:** #319's identity decision (blocks starting a 2–4 week clock) · #456 cutover · #444 · #363 ·
#460 (a client-facing milestone — 58 tasks contain zero).

---

## §7 — GOTCHAS (cumulative; new first)

- ⚠️ **A keyword hit is not a done task.** Two greps lied this session and were caught by reading
  the match.
- ⚠️ **`_build_low_slope` never reads `flat_squares`.** Moving area into it on a low-slope quote
  deletes that area from the price (76% under, measured).
- ⚠️ **`measurements.total_sq` is ambiguous by provenance** — Tim's sheet = sloped-only, RoofR =
  pitched+flat.
- ⚠️ **A default is only a default where nothing supplies a value.** The SPA sends
  `commission_rate` on every quote.
- ⚠️ **Bump `_PDF_TEMPLATE_VERSION`** whenever `DEFAULT_TEMPLATE_HTML` changes.
- ⚠️ **A reproduction path needs a different default from a creation path** (`permit_count`).
- ⚠️ **Knowify: deliverables carry `ContractId`, NOT `ProjectId`.** Money is in **CENTS**.
- ⚠️ **CI runs `pytest tests/`** — the whole tree. CI ruff scope is `core adapters api jobs` only.
- ⚠️ **CI deploys the SPA now** (since 2026-08-02) — still verify the SERVED bundle.
- ⚠️ **Migrations are applied BY HAND**; the runner ignores `DB_URL` and has no ledger.
- ⚠️ **Reviewer agents need `run_in_background: false`**, and R2 needs BOTH — the critic found the
  architect's fix was aimed at the wrong layer this session.
- ⚠️ Do NOT `source .env` before GCS work. `DB_URL` in `.env` is sqlite; prod is user **app** over
  the proxy.
- ⚠️ **Search the mailbox, not just transcripts.**

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

**Performed:** `docs/continuations/CONTINUATION-2026-08-02.md` archived to `docs/continuations/`, keeping the latest
three at top level. Inbound links repointed and README's "Most recent" refreshed.
