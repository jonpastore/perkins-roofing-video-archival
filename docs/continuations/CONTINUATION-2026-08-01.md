# CONTINUATION — 2026-08-01

**HEAD `bc771b3`, pushed, tree clean. Full suite green (`PYTEST_EXIT=0`). Terraform drift clean
(plan exit 0).** Warranty plugin **1.3.4** live on staging. Prod migrations through **0051** —
⚠️ **0052 is committed and NOT APPLIED, deliberately** (§3).

Read `CONTINUATION-2026-07-31-pm.md` for the warranty-tool and OAuth work this follows.

---

## §0 — THE HEADLINE: A MULTI-BUILDING BID IS NOW ONE PROJECT

Jarvis #430/#449, the largest open correctness gap in the money path. Tim's Evergrene bid prices
**9 structures at one address as ONE deal**. `estimate()` is a pure function of ONE roof, so every
site-scoped quantity was silently reinterpreted as roof-scoped and multiplied by nine.

**Scored against his actual bid** (`scripts/validate_against_evergrene.py`):

| | ours | Tim | delta |
|---|---|---|---|
| project total | $390,230 | $381,288 | **+2.3%** |
| profit | $30,790 | $30,363 | **+1.4%** |

Per building, before → after: **Bus Stop +84.9% → −24.3%**, Gazebo +43.4% → −29.8%,
Pool Pump +36.6% → −1.6%, Clubhouse +10.2% → +7.8%.

### ⚠️ The task's diagnosis was wrong in a way that changed the plan

#430 records "−7.8% ONLY because the errors offset", which reads as two pricing errors cancelling.
Measured, it is **one systematic over-charge masked by scope we never quoted**:

```
every building OVER by +10.2% to +84.9%  (+15.0% on the buildings together)
$116,420 of project scope with nowhere to live ($79,850 add-ons + $36,570 General Conditions)
```

The Clubhouse only *looked* 20% under because Tim's number for it carries $77,300 of project
add-ons. **Consequence: fixing only the floor and fees would have swung the bid from −9% to about
−23% — worse, and under.** Both halves had to land together. `scripts/evergrene_gap_analysis.py`
re-runs the whole comparison so this stays a measurement.

### And #449's spec does not reconcile with his bid

#449 says the floor becomes **"$2,500 per site per WEEK"**. On Evergrene that is 17 × $2,500 =
**$42,500 against his actual margin of $30,363 — the spec as written still over-prices by 40%.**

So: `week` is implemented and available, the **default is `project`** (one floor for the bid, which
never binds here — what Tim actually did), and **both numbers are returned on every call** so the
divergence is visible rather than buried. `building` restores the old behaviour per project without
a deploy.

---

## §1 — WHAT IS SITE-SCOPED, AND THE ONE THAT IS SUBTLE

| fee | scope | why |
|---|---|---|
| `delivery_plywood_vents` | **project** | One truck. **Tim's own sheet agrees** — his Delivery day column is EMPTY for 8 of 9 rows, with the site figure on the totals row. |
| `new_bonus_values` | **project** | Back-end crew money. Per mobilisation vs per roof is genuinely 50/50 — **PENDING TIM**. |
| `permit_processing` | **a COUNT, not a scope** | Palm Beach may issue one per structure. `permit_count` exists so neither answer is hard-coded, default 1 — **PENDING TIM**. |
| `tile_dumpster` | **project, recomputed** | ⚠️ **The subtle one.** Not a flat fee, so "charge it once" is *also* wrong. `tile_dumpster_count` is a `ceil()`, so nine calls round up nine times — **14 loads billed for a 10-load site**. Now one ceil over the summed squares. |
| `stories_3_5_delivery_chute` | **per building** | A chute is rented for the tall structure. Unchanged. |

**Measured, the fixed fees are ~$24,000 of the error and the floor ~$5,000.** #449 leads with the
floor, which is the smaller half. That sizing came from the architect agent.

---

## §2 — TIM'S ACTUAL MODEL, DECODED FROM HIS FORMULAS

`tests/fixtures/golden/evergrene_project.json` — decoded from the **formulas**, not retyped, so it
is recoverable. Source: `~/perkins-corpus/roofr-attachments/2026-07-24__Evergrene_Project_Bid_Spreadsheet.xlsx`.

```
per building   price/sq = (base_cost/sq + overhead/sq) x markup
               markup 1.10-1.14 PER BUILDING, base 750-1085 PER BUILDING
overhead       (demo + metals_demo + delivery) x $885 + tile_install x $745
Bus Stop       (900 + 1630/3) x 1.10 x 3 sq = $4,763   — reproduced exactly
```

**Four things his sheet does that nobody had written down:**

1. **General Conditions is referenced by NO total formula.** `D19 = SUM(B19:B20)*1.15` =
   (22,800 + 9,000) × 1.15 = $36,570 and it stands alone as its own quoted block. The $15,000
   cedar nailer is **not** in GC — it is in a separate $42,050 sloped add-ons block.
2. **His stated total excludes a building.** `K42 = SUM(K35:K41)+K33` skips K34, the Clubhouse
   Flats ($38,480). Any comparison against K42 must exclude GC and the Flats or it reads +11.9%
   from the comparison alone.
3. **He attaches project blocks to ONE building** (the Clubhouse), not spread.
4. **He hand-edits the OH formula per row** — `I3` uses 735 where `I5`–`I11` use 745, `J5` uses 885
   where `J6`–`J11` use 1050. **That is drift, not a model. Do not reproduce it.**

⚠️ **Unexplained and do not guess:** a bare `+4250` in `K33` and `+2550` in `K35`, unlabelled
anywhere on the sheet.

### His day rates diverge from our config

| | ours | Evergrene actual |
|---|---|---|
| tile install | 745 | **745 ✓ exact** |
| demo | 1,050 | **885** |
| metal install | 850 | **735 — ours is 15% high** |

His $1,050 appears only as *metal-scope mobilisation*, so the rate may depend on which scope the
day belongs to, not on the activity alone. Recorded in the fixture. **A question for Tim, not a
config change.**

---

## §3 — ⚠️ MIGRATION 0052 IS COMMITTED AND NOT APPLIED. READ BEFORE DEPLOYING.

`infra/migrations/0052_bid_projects.sql` exists in git. **The ORM change deliberately does not
accompany it.**

**Migrations here are applied BY HAND** (`scripts/apply_migrations_adc.py`), not by deploy — I
checked `scripts/deploy.sh` and the CI workflows, and neither runs them. So committing the models
alongside would ship an app whose ORM selects `bid_project_id` against a database without it, and
**every SELECT on estimates and proposals would fail**. Schema first, ORM second.

The migration is additive and idempotent (new table, three nullable columns, `IF NOT EXISTS`
throughout). Applying it changes no behaviour on its own.

```
DB_URL=postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins \
  .venv/bin/python scripts/apply_migrations_adc.py
```

The ORM half was written and then **reverted on purpose** — it is not in git. It adds
`class BidProject`, `Estimate.bid_project_id` + `structure_name`, `Proposal.bid_project_id`.
Re-write it only after 0052 is applied.

---

## §4 — SLICES 2-4, AND THE DATA-LOSS TRAP IN SLICE 3

Slice 1 (shipped) is headless: **nothing in prod changes because no caller passes the new flags.**

- **Slice 2 — persistence.** Apply 0052, add the ORM, `POST /estimator/project-quote` returning the
  roll-up and persisting N estimates + one `bid_project`. Snapshot gains `buildings` /
  `project_items` / `project_totals`; keep `roof_type` as the dominant building and `num_squares`
  summed so `core/proposal.py:_REQUIRED_SNAPSHOT_KEYS` needs no change at all.
- **Slice 3 — proposal surface.** ⚠️ **`web/src/pages/Proposals.tsx:414-419` re-quotes exactly one
  estimate and overwrites `quote_snapshot`. On a project snapshot that SILENTLY DESTROYS EIGHT
  BUILDINGS.** Hard-gate the edit path (`bid_project_id != null` → disable) in the same slice that
  first creates a project proposal, or it is a data-loss bug. Also: `_assemble_review_text`
  (`api/routes/proposals.py:143-167`) reads ONE roof, so the LLM send-gate would review one
  building and green-light a nine-building contract — a *silently weakened safety gate*, not a
  visible failure. And `api/routes/estimator.py:441-450` fires `min_margin_breached` per building
  under project scope; skip it there and re-run once against the project floor.
- **Slice 4 — SPA.** `Quoting.tsx` has ~55 scalar `quote*` inputs at page level; a per-building
  repeat means lifting that whole block into a per-building record.

**Later:** Knowify export has no multi-building shape; project-level tile/metal alternates
(`K42` vs `L42` are whole-project alternates, not per-building) as sibling `bid_projects` with a
`root_id` self-FK.

---

## §5 — EARLIER TODAY (all pushed, all green)

| commit | what |
|---|---|
| `5ccb9f5` | **OAuth store accepted `account_id` and discarded it** — four QuickBooks branch COMPANIES shared one token. Now `tenants-{t}-{platform}-{account}-{key}`, legacy path still read. Three callers disagreed on the id and only interoperated BECAUSE it was discarded. |
| `42c1ead` | **A 2011 reading was voiding warranties in 2026.** 65 of 171 gauges hadn't reported in 30+ days; 33 were classed salt/brackish and moving verdicts, worst 42,300 µS/cm from **5,415 days** ago. |
| `9320c90` → `b73e7ee` | Clip fix, then **the review caught a false VOID in my own fix** — see below. |
| `e30ca68` | Two skips reporting green; `calc_audience` default pinned. |
| `6b3cb68` | HVHZ extrapolation + commercial profit warnings. |
| `3821701` | **The article gallery could not contain a drone shot** — YouTube's auto-frames are all at 25/50/75%, so Tim's opening/closing aerials were never candidates. |
| `f04d27b` | The profit floor now states it also raised commission (#422). |

### The review earned its keep

Exempting `tagged` from the tidal clip shipped a **false VOID**: freshwater Dunns Creek, 25 mi
inland, because **OSM `tidal=yes` describes water LEVEL, not salinity** — the St Johns' tidal signal
runs ~160 mi inland. I made the exact category error I had diagnosed one paragraph earlier. Only
gauge-anchored `measured` is exempt now; 78 lake polygons excluded; pin clearance 56,369 → 76,200 ft.

⚠️ **qwen3.6 passed all three review areas as "Correct" and was wrong twice.** Local review is a
second opinion, never a gate.

---

## §6 — OPEN, IN PRIORITY ORDER

1. **Slices 2-4 above.** Slice 2 starts with applying 0052.
2. **Six questions for Tim** (none defaultable — he has never stated them):
   permit per structure or per site? · is `new_bonus_values` per mobilisation or per roof? ·
   **is commission paid on General Conditions?** (~$8-16k on this bid alone) · is the GC markup
   always 1.15? · what are the bare `+4250` and `+2550`? · must a proposal list each building's
   address (two Evergrene gates are on different roads)?
   Plus the day-rate divergence in §2.
3. **`api-run-sa` cannot create a secret** — it holds `secretAccessor`, `secretVersionAdder`,
   `viewer`, nothing granting `secrets.create`. The OAuth connect flow 502s and the migration
   cannot self-complete. Needs an IAM grant in Terraform; **a security-scope decision, left for
   Jon deliberately.**
4. **`#444` GCP budget** — Billing API disabled, SA cannot enable it or list accounts. TF resource
   written, waits on `var.billing_account`.
5. **`REACH_MI` residual** — 8 of 18 far live gauges still absent because they never snap to mapped
   water within `GAUGE_SNAP_M`; OSM maps those wide rivers as `natural=water` polygons, not
   `waterway` lines.
6. **Banking is correct and inert** — every latest-only gauge is also stale (the two sets are
   byte-identical), so there is nothing to bank until a dormant station resumes.
7. `#447(3)` commission_pct still keyed by slope type, not per salesperson. `#445` code done, the
   Wendy/Crypt Keepers review meeting is separate. `naples` carries Jupiter's $1,400.

---

## §7 — GOTCHAS EARNED (cumulative, the ones that cost real time)

- ⚠️ **Migrations are applied BY HAND.** Neither `deploy.sh` nor CI runs them. Schema first, ORM
  second, always.
- ⚠️ **`tile_dumpster_count` is a `ceil()`** — anything calling it per building over-counts.
- ⚠️ **`profit_guidance` is absent from the estimate result** unless it is a daily-overhead quote.
- ⚠️ **`.dockerignore` allowlists `scripts/`** — a job importing a NEW script needs
  `!scripts/<name>.py` or the image ships an EMPTY namespace package ("unknown location", not
  ModuleNotFoundError). Guarded by a test now.
- ⚠️ **The job container has NO writable `$HOME`** — `Path.home()` raises `PermissionError:
  '/home/appuser'`. Use `tempfile.gettempdir()`; durable state to GCS.
- ⚠️ **Green CI + clean terraform + a firing scheduler proved nothing, twice.** Both salinity-sweep
  bugs existed only inside the built image. Verify a job by RUNNING it and reading its stdout.
- ⚠️ **Do NOT `source .env` before GCS work** — it sets `GOOGLE_APPLICATION_CREDENTIALS` to
  `./infra/vertex-dev-sa.json`, **a file that does not exist**. Use
  `$HOME/.config/gcloud/perkins-deploy-sa.json`.
- ⚠️ **`DB_URL` in `.env` is sqlite.** The platform DB needs
  `postgresql+psycopg://app:...@127.0.0.1:5432/perkins` over the proxy. **`+psycopg`** — psycopg2
  is not installed and plain `postgresql://` selects it and fails.
- ⚠️ **`pricing_configs` columns are `config` and `is_active`**, not `config_json`/`active`.
  Roof types are `13_tile` / `barrel_tile` / `3tab_shingle` / `dimensional_shingle` /
  `standing_seam_metal`.
- ⚠️ **`resolved_wp_url()` swallows every exception** and returns `""`. Empty means a config or
  driver error, not an unset value.
- ⚠️ **Quoted gauge readings are 30-day medians over a sliding window** — they MOVE. The C-8 pair
  read 473/29,900 on 07-30 and 465/20,450 on 07-31. The ORDERING is the durable fact.
- ⚠️ **OSM `tidal=yes` means water LEVEL, not salinity.**
- ⚠️ **A bare `until` spin with no sleep burns the whole timeout**; `sleep N` chained after a
  command is blocked by the harness.
- ⚠️ Printing `.env` leaks `WP_PWD` — it reached a transcript on 7/31, worth rotating.
- Pre-push: `.venv/bin/python -m pytest tests/api tests/core tests/adapters tests/jobs tests/tenancy`
  (~8m). **The EXIT CODE is the evidence** — the summary line may not flush to a redirected log.
- CI gates `ruff check core adapters api jobs` FIRST, then pytest `--cov-fail-under=97`.
  `tests/` is NOT ruff-gated; `tests/jobs/test_search_indexing_job.py` carries 9 pre-existing errors.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation, move the OLDEST top-level `CONTINUATION-*.md` into
`docs/continuations/` (keep only the latest 3 at top level), fix every inbound link to the moved
file, refresh the docs index's "most recent" pointer, and update related docs.
**Performed:** `CONTINUATION-2026-07-30-pm.md` archived to `docs/continuations/`, inbound links
repointed, and README.md's "Most recent" moved to this document.
