# CONTINUATION — 2026-08-02 (pm)

**`main` = `be59ad5` + this doc's PR. CI green. Deployed and VERIFIED in prod: API
`platform:8b3f5cd` (sha matches), SPA bundle `/assets/index-DSRtfOBu.js`. Migrations through
0053, all applied.** #430/#449 shipped (all four slices).

Follows `docs/continuations/CONTINUATION-2026-08-02.md`, which recorded Tim's first pass at the six questions. This
doc records **Jon's follow-up directives** and the evidence gathered for them.

---

## §0 — THE THREE DIRECTIVES, AND WHAT EACH ONE NOW NEEDS

### 1. PERMITS — "check against other multi building/property quotes" ✅ CHECKED. HIS RULE HOLDS.

Queried the Knowify mirror through the real join (deliverables → `ContractId` → contracts →
`ProjectId` → projects; **deliverables carry no `ProjectId`**, which broke a first attempt and
made it report a meaningless zero):

    505  permit deliverable lines
    333  projects carrying at least one permit line
     73  projects carrying MORE THAN ONE          <- 22%

Top of the list is exactly the case in question — **`ISOLA CONDOMINIUM ASSOCIATION RE ROOF`, six
permit lines** (values are cents, per [[knowify-mcp-incremental-sync]]):

    $1,858.40 · $7,227.79 · $566.00 · $1,662.88 · $2,223.35 · $20,000.00 (Permitting and
    Engineering Allowance)

Also `Gulliver Prep Dugouts` (4 — multiple dugouts), `TerracotaGres BRASTILE` (4), and a tile
re-roof "w/ transition into neighbouring unit" (4).

**Verdict: multi-permit billing is normal on multi-structure jobs, and Evergrene's single permit
is the outlier.** Tim's "1 per building/structure" is confirmed by his own books. Ship it.

⚠️ **BUT NOTE WHICH FEE.** Those Knowify lines are the **county's permit fees passed through** —
variable amounts. Our `permit_processing` is a **flat $500 (+$500 commercial) processing fee**.
Their own catalog scope says *"Obtain the roofing permit. We do all processing, you pay permit
fee(s) only"* — **fee(s), plural**, which independently supports per-structure. Both scale the
same way, so the rule applies either way, but do not conflate the two lines: we charge for
processing, the customer pays the county.

**Still true and still worth saying when it ships:** on Evergrene this takes the bid from
**+2.3% to about +4.4%** (9 × ($500 + $500) = $9,000 against the $1,000 charged now), i.e.
further from the number he actually bid. Report the divergence in the same message.

### 2. COMMISSION — ANSWERED, AND OUR NUMBERS ARE MATERIALLY WRONG

> **"commission either on gross or net. commission is to the sales person. they can take 15% of
> gross or 50% of net and that's how we default the sliders."**

That maps cleanly onto machinery that already exists — `QuoteInput.commission_basis` is
`"job"` (gross) | `"profit"` (net), and `core/estimator.py:1628` already does
`comm_base = project_total if basis == "job" else margin.profit_dollars`.

**What is wrong is the RATE.** `config.commission_rate(slope_type, zone)` is keyed by slope type
and zone — a dimension Tim's rule does not mention at all — and returns:

    live jupiter/miami/naples:  {"sloped": 0.10, "low_slope": 0.15, "sloped_hvhz": null}

So today, with the default basis `"profit"` (net):

    we report   10% of NET      Tim says   50% of NET     -> 5x UNDER
    on gross    10% of GROSS    Tim says   15% of GROSS   -> a third under

⚠️ **THIS IS A REPORTING ERROR, NOT A PRICING ERROR — say so precisely.** Commission is computed
*after* `project_total` and `margin` and surfaces only as `estimated_commission`; it is not a
priced line and no customer quote moves. What is wrong is **the number a salesperson is shown for
their own payout**, which is its own kind of serious.

**What to build:**
- rate should default **from the basis**, not from slope/zone: `job` → **0.15**, `profit` → **0.50**
- these are **slider defaults**, so both must stay operator-adjustable per quote
  (`commission_rate_override` already exists)
- commission is **to the salesperson** — which finally closes `#447(3)`: `PRICING_RULES §11` says
  per-salesperson and the config keys it by slope type. See [[commission-is-per-salesperson]]
  (Marco 15% / Josh 7.5% on an identical grid, no Jupiter tab has a commission cell).

⚠️ **Reconcile before shipping:** the 15%-of-gross figure matches Marco's 15% in the NEW sheet,
but Josh's 7.5% has no home in Tim's two-option rule. Ask whether 7.5% is a different
salesperson's *negotiated* split or a stale number, rather than silently deleting it.

⚠️ And the original question is now answered *by implication*: if commission is a share of **net**
profit, General Conditions is a **cost** that reduces the pool — it is not a commissionable
revenue line. Worth confirming in one line rather than assuming.

### 3. PER-BUILDING ADDRESSES (#6) — "build it"

Tim: *"yes but they can share."* Not built. The spec:

- an **optional** address per building, defaulting to the bid project's property
- `bid_projects.property_id` stays the site; buildings gain their own optional address
- the proposal render lists each structure with its address, collapsing to one line where
  buildings share it (the Evergrene default) and separating where they differ (the two gates on
  different roads)
- schema: either `estimates.structure_address VARCHAR` (simplest — the estimate already carries
  `structure_name`) or an address blob on the building entry in the snapshot. **Prefer the
  column** — it survives a snapshot rewrite, and the snapshot is exactly what
  `validate_project_snapshot` exists to stop being rewritten carelessly.
- migration **0054**, applied BY HAND (`scripts/apply_migrations_adc.py`, which ignores `DB_URL`
  and has no ledger — see gotchas)

### 4. #5 ATTACHMENT — SAVED

`~/Downloads/Evergrene_Project_Bid_Spreadsheet_K33-K35.xlsx` (copy of Tim's own 2026-07-24
attachment). Sheet **`Bid Sheet`**; the four cells to look at:

    K33  =(G33*J33)+D22+D25+4250     row 33 = the 206-sq building (Clubhouse)
    L33  =(H33*J33)+D22+E25+4250     the metal alternate carries it too
    K35  =G35*J35+2550               row 35 = the 21-sq building
    L35  =H35*J35                    the metal alternate does NOT

---

## §1 — "DEPLOY WITH IaC SHOULD HAPPEN WITH GITOPS RIGHT?"

**Yes — and for the API it already does.** Merge to `main` → CI → `deploy` workflow (keyless WIF,
repo-pinned, main-only, drift-gated) → Cloud Run. Nothing is deployed by hand; `scripts/deploy.sh`
even refuses a dirty tree because the image is tagged with the git SHA. That is why running it
manually during this work would have been *wrong*: a second concurrent deploy hits the Cloud Run
job optimistic-lock (see [[deploy-not-concurrency-safe]]).

**The exception is the SPA, and it is a real gap.** `.github/workflows/deploy.yml` builds the API
image and **never touches `web/`**. The SPA ships only by a hand-run

    cd web && npm run build && npx --no-install firebase deploy --only hosting:app \
      --project video-archival-and-content-gen

so slice 4's entire UI was merged, CI-green and **invisible to users** until someone remembered.
**"Deployed" in a commit message or a green badge is a claim about the API only.**

**Recommendation:** add a hosting-deploy step to `deploy.yml` behind the same WIF identity, so the
two halves cannot drift. Flagged rather than done because it changes the deploy path, and R3 says
that is a deliberate decision, not a drive-by.

---

## §2 — WHAT SHIPPED (verified running, not merely green)

| | evidence |
|---|---|
| API | `platform:8b3f5cd` — image SHA matches `main` |
| `/estimator/project-quote`, `/quoting/proposals/from-project` | live, **401**-gated (a fake route 404s) |
| SPA | served bundle contains `Multi-building bid`, `Add this roof`, `SAME property`, `own block` |
| Money path | Evergrene **$390,230 vs $381,288 (+2.3%)**, profit **$30,790 vs $30,363 (+1.4%)** |
| Backend | `PYTEST_EXIT=0`, coverage **97.89%** |
| Frontend | build clean, **26 vitest**, now CI-gated |

---

## §3 — OPEN, IN PRIORITY ORDER

1. **Commission rate from basis** (15% gross / 50% net, salesperson-scoped). Biggest money-adjacent
   item; currently 5× under-reported on the default basis. Reconcile Josh's 7.5% first.
2. **`permit_count` = building count.** Evidence supports it (73 of 333 projects bill multiple
   permits). Ship + report the +2.3% → ~+4.4% Evergrene divergence.
3. **#6 per-building addresses** — migration 0054 + proposal render.
4. **GC markup slider** — keep `bid_projects.general_conditions_markup` (Tim: "we have a slider
   for this"), wire a project-level control; today only per-block markup is settable.
5. ⚠️ **The `week` profit-floor basis measures the wrong thing.** Tim 2026-07-28: *"how long it
   ties up the schedule... including inspections"*; `_apply_project_floor` does
   `ceil(crew_days / 5)`. No price moves today (default `project`, UI cannot select `week`), but
   #449 is written in those terms. **His inspection/cleanup allowance is not a number we have.**
6. **Wire the SPA deploy into `deploy.yml`** (§1).
7. **Jon's calls:** `estimating_view` on a writing endpoint; whether to expose `floor_basis` at all.
8. **Curate 5 ready portfolio projects** (human: pick photos AND type alt text) — isola 1,452 ·
   olsen 802 · fisher-7900 311 · fisher-77 285 · pinnacle 186. Separately blocked:
   `jim-malooly-delray-beach-roof` trips `title_not_a_person`; `abacoa` and `miami-warehouse` have
   no CompanyCam url; 6 match no Knowify scope; 4 are under 120 words.
9. Older: `api-run-sa` cannot create a secret (OAuth 502s); `#444` budget blocked on the Billing
   API; `REACH_MI` 8 of 18 gauges unsnapped; Miami charges a whole office day per job
   (~$2,087/sq vs $1,113 accepted).

---

## §4 — GOTCHAS (cumulative)

- ⚠️ **Knowify: deliverables have `ContractId`, NOT `ProjectId`.** Join deliverables → contracts →
  projects. Joining on the wrong field returns a clean, confident, wrong answer (it reported
  "0 projects with multiple permits" before I noticed).
- ⚠️ **Knowify money is in CENTS** in the mirror deliverables.
- ⚠️ **CI runs `pytest tests/`** — the whole tree. The pre-push set does not reach
  `tests/test_f2_engine.py`, which is how main stayed red for three commits.
- ⚠️ **CI does not deploy the SPA** (§1). Verify the SERVED bundle, not the CLI's "Deploy complete!".
- ⚠️ **`npx tsc --noEmit` is NOT the build gate**; `npm run build` (`tsc -b`) is.
- ⚠️ **`test_schema_maxlength` binds on IMPORTED CLASS NAMES**, not on writes.
- ⚠️ **Migrations are applied BY HAND**; `apply_migrations_adc.py` **ignores `DB_URL`** (always
  prod) and has **no ledger**. `0027`'s UPDATE is unguarded and re-asserts every run.
- ⚠️ **`tile_dumpster_count` is a `ceil()`** — per-building calls over-count.
- ⚠️ **Reviewer agents must run with `run_in_background: false`** or they return nothing. R2 needs
  BOTH architect and critic — the critic found two MAJORs inside the architect's own fixes.
- ⚠️ **Local models were net-negative on review** — see
  `docs/2026-08-01-local-model-review-postmortem.md`. Never gate on them.
- ⚠️ Do NOT `source .env` before GCS work. Use `$HOME/.config/gcloud/perkins-deploy-sa.json`.
- ⚠️ `DB_URL` in `.env` is sqlite; app code needs `postgresql+psycopg://…` over the proxy, and
  sessions must set `db.info["tenant_id"]` or `["platform_scope"]`.
- ⚠️ **Search the mailbox, not just transcripts.**

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

**Performed:** `CONTINUATION-2026-08-01.md` archived to `docs/continuations/`, keeping the latest
three at top level. Inbound links repointed and README's "Most recent" refreshed.
