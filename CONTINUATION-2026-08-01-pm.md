# CONTINUATION — 2026-08-01 (overnight)

Follows `CONTINUATION-2026-08-01.md` (the bid-project work). Two threads landed: **portfolio
publishing is unblocked**, and **#430 slice 2 is built** — migration applied, ORM re-added,
`POST /estimator/project-quote` live in code.

⚠️ **NOTHING IS COMMITTED AND NOTHING IS DEPLOYED.** Jon asked for work, not for a push.

---

## §0 — THE HEADLINE: THE MIGRATION RUNNER WAS BROKEN, AND HAD BEEN FOR A WHILE

Applying 0052 should have been one command. It was not, and what it uncovered matters more than
the migration.

**`scripts/apply_migrations_adc.py` ignores `DB_URL` and has no applied-ledger.** It connects to
**prod** via the Cloud SQL Connector from `GOOGLE_CLOUD_PROJECT`, and re-executes **every**
migration from `MIN_MIGRATION` (0013) on every run. The `DB_URL=postgresql+psycopg://...` prefix
in this repo's own docs — including the previous continuation and `prompt.txt` — does nothing.

Three real defects fell out, each of which silently blocked every later migration:

| where | defect | fix |
|---|---|---|
| `0029` seed → `tc_versions` | 28 RLS policies use the **bare** `current_setting('app.tenant_id')` (no missing-ok flag), so any tenant-table write from a session that never set the GUC raises `42704` | `SET app.tenant_id = '1'` once in the runner. `0041` had been working around it with its own `SET LOCAL` |
| `0040_comment_platform.sql:18` | bare `ALTER TABLE ... ADD CONSTRAINT` — Postgres has no `IF NOT EXISTS` for constraints — while the file's own header claims "Idempotent: safe to re-run" | `DO $$ IF NOT EXISTS ... $$` guard, matching `0032` |
| `_statements()` splitter | not single-quote aware. `0046`'s column comment contains `'... unknown; 0 = no flat section.'` and split mid-literal → `42601` unterminated string. It also pre-stripped `--` line-by-line, so any literal with a double dash would truncate | one scanner tracking dollar-quote / string / comment state |

**Consequence: 0041–0052 could not be applied by this runner at all.** They were in prod by some
other path; 0052 was not.

⚠️ **Two unguarded `UPDATE`s re-assert on every run.** `0026` rewrites
`tenants.settings->integrations->workspace_admin_subject` to `jon@perkinsroofing.net`, and `0027`
sets four `cors_origins` rows back to `tenant_id = NULL`. **Both were verified harmless today only
because tenant 2 was never onboarded and Ez-Bids W2 never re-scoped those rows.** Onboard a second
tenant and the next migration run silently reverts it. The dangerous one — `0030`'s invoice
counter seed at 18732 — *is* correctly guarded with `WHERE NOT EXISTS`, so numbering was never at
risk.

New guard: `tests/test_migration_statement_splitter.py` (6 tests, incl. a balanced-quote sweep
over every real migration).

---

## §1 — #430 SLICE 2: BUILT, TESTED, NOT COMMITTED

**Schema first, ORM second** — held, and it mattered. `0052` applied and verified
(`bid_projects` exists, RLS **forced**, `profit_floor_basis` default `'project'`,
`estimates.bid_project_id` + `structure_name`, `proposals.bid_project_id`). Only then the ORM.
Proof the order was right: `SELECT` on **101 estimates and 7,365 proposals** works against the
live DB with the new columns declared.

**What was added**

- `app/models.py` — `class BidProject`, `Estimate.bid_project_id` + `structure_name`,
  `Proposal.bid_project_id`.
- `core/bid_project.py` — `dominant_roof_type()` (largest by **summed area**, tie-broken on name
  so it is stable) and `project_snapshot()`. The snapshot is **additive**: `roof_type` becomes the
  dominant building and `num_squares` the sum, so `core/proposal.py:_REQUIRED_SNAPSHOT_KEYS` needs
  **no change** and single-building proposals render unchanged. **100% coverage retained (R1).**
- `api/routes/estimator.py` — `POST /estimator/project-quote`. Refuses mixed branch or zone (422),
  persists one `bid_projects` row + N `estimates` carrying the join and the label, and
  `persist:false` returns the roll-up writing nothing (the SPA re-prices per keystroke).

**The refactor that made it safe.** The 110-line request→`QuoteInput` mapping was extracted from
`/quote` into `_quote_input_from_request()` and is now shared. A second copy would have been the
real hazard — 60 field assignments plus roof_type/specialty_tile validation and measurement-backed
cut-LF resolution, where a project quote diverging on any one field would look exactly like a
pricing bug. The cut-calc comparison quote now derives from `q` via
`replace(q, apply_cut_calc_to_base=True)` instead of rebuilding from `qkwargs`.

**Money path unchanged.** `scripts/validate_against_evergrene.py` still returns
**$390,230 vs Tim's $381,288 (+2.3%), profit $30,790 vs $30,363 (+1.4%)** — identical to slice 1.

---

## §2 — PORTFOLIO: PERMISSION WAS UPSTREAM OF EVERYTHING

Wendy answered the open question (7/31): **"We want to use the Avada Portfolio system. We will
disable the existing page once the projects are moved over."** So `adapters/wordpress.*_portfolio_*`
targets the RIGHT post type — the nine `/portfolio/` pages are the ones being retired. She did
**not** answer schema / JSON-LD / image count / alt text / service links.

Tim answered two more: **every project already has client permission** ("one of our contract
terms"), and location granularity is **town / city / HOA, never the street address**.

**The non-obvious part:** `_available_media` filters the mirror through `publishable_media`, so
with `permission_photos` false a project reports **zero photos available** — even though the mirror
holds **156,203**. All 13 read as "no media" purely because nobody had set a flag.

Recorded via `scripts/portfolio_grant_permissions.py` (idempotent — second run wrote 0 rows;
provenance in `updated_by`). **The deny-by-default in `_permissions` was deliberately left alone**
so a project created tomorrow still has no clearance.

**Five are one curation away** (only `gallery_size` fails): isola (1,452 photos), olsen (802),
fisher-island-7900 (311), fisher-77 (285), pinnacle (186). Jon curates in the admin UI.

⚠️ `gallery_html` reads `sel.get("alt")` — **alt text is typed per photo by an editor**, so
`alt_present`/`alt_unique` can only be satisfied by curating, never by code.

Still blocked: `jim-malooly-delray-beach-roof` trips `title_not_a_person` (rename it); `abacoa`
and `miami-warehouse` have **no CompanyCam url at all**; 6 match no Knowify scope; 4 are under 120
words.

---

## §3 — THE SIX QUESTIONS ALL SURVIVE

Swept all 15 non-OSM corpus files — 77 sheet comments, low-slope comments, both branch catalogs,
golden proposals, Tim's 7/30 and 7/31 emails. **Zero hits** for permit-per-structure,
bonus-per-mobilisation, **"commission" (the word appears nowhere)**, "general conditions", the
`+4250`/`+2550` labels, and per-building address.

Draft ready at `docs/2026-08-01-six-questions-for-tim.md`. **Not sent** —
`EMAIL_SEND_MODE=test`, and Jon sends client mail.

⚠️ **Tim's "town/city/HOA" answer is about public marketing pages and does NOT answer Q6.** A
proposal is a contract document. Do not collapse the two.

Q1 gained a second consumer: on the Workflow Notes thread (7/31) Chris asked whether the software
will bid jobs with Tim's calculator, and wants a **permitting agent**.

---

## §3.5 — R2 REVIEW (REAL, 2026-08-01): 2 CRITICAL + 3 HIGH FOUND AND FIXED

**The first attempt failed and the second worked. The difference was `run_in_background: false`.**
Backgrounded reviewer agents produced only idle notifications and never returned a report; run
synchronously, both delivered. If a review agent goes quiet, that is the knob.

### ⚠️ FIRST: MAIN WAS ALREADY RED, AND HAD BEEN SINCE SLICE 1

`gh run list` — CI **failure** on all three of `1e902a4`, `bc771b3`, `1d053be`. CI runs
`pytest tests/` (the whole tree); the documented pre-push set
(`tests/api tests/core tests/adapters tests/jobs tests/tenancy`) does **not** reach
`tests/test_f2_engine.py`, so "full suite PYTEST_EXIT=0" in the previous handoff was true of the
narrower set and false of CI. Verified by stashing every change and re-running: the two failures
reproduce on a clean HEAD.

Cause: slice 1 committed `tests/fixtures/golden/evergrene_project.json` — a **decoded-reference**
fixture (Tim's bid read out of his formulas), not a QuoteInput/expected pair. `GOLDEN_FILES`
globbed `*.json`, so the parametrized engine test swallowed it (`KeyError: 'input'`) and the
committed-count assertion went 3 → 4. Fixed by selecting on SHAPE, so a future reference fixture
cannot re-break the harness. **Run `pytest tests/` — the pre-push set is not what CI gates.**

### The two CRITICALs — both verified by execution before fixing

**C-1 · editor alt text defeated the `media_sanitized` blocker.** `gallery_html` interpolated
editor-typed alt into an attribute unescaped, and `unsanitized_media` matched only
DOUBLE-quoted attributes. An alt ending `" /><img src='<cdn url>` opened a second tag at a raw
CompanyCam file — burned-in GPS and all. Measured on the real gate:
`unsanitized_media → []`, `media_sanitized ok=True`, with the CDN image in the page. That is the
fail-closed contract in `core/photo_privacy.py`'s own docstring, broken.
Fixed BOTH halves: `html.escape` at the emitter **and** a quote-style-agnostic regex, because a
gate that is only correct because of what its caller does is not a gate.
⚠️ The widened regex then produced a FALSE POSITIVE on the now-escaped alt (`src=&#x27;…` inside
the alt value) — caught by my own new test, fixed by excluding a leading `&` from the bare branch.

**C-2 · `no_pii` advertises "or GPS" and missed the format CompanyCam actually burns in.**
Only the signed comma-decimal pair matched. `core/photo_privacy.py:4-5` quotes the real capture
stamp verbatim — `25.858694° N 80.120019° W` — and it returned clean. Now covers hemisphere,
labelled lat/lon and the original form, with a false-positive test over ordinary roofing prose
("25.5 squares at $1,100.00", "6/12 pitch", "185 mph").

### The three HIGHs

| finding | why it happened | fix |
|---|---|---|
| **Gutter accessories priced at $0 on the project path.** `/quote`'s 422 guard sits at line 397 — OUTSIDE the block I extracted — so `/project-quote` skipped it, and the engine prices the whole accessory block inside `if q.gutter_lf:` | I extracted the MAPPING and assumed that was the whole seam. The guards that need the loaded `config` live after it | guards extracted into `_validate_quote_guards`, called by both, and it names the structure |
| **Per-building `discounts` accepted, persisted, never applied.** `resolve_discounts` runs only in `/quote`; the discount went into `input_json` while never coming off the price — the audit row would disagree with the customer's number | `BuildingInput.quote` is the FULL `QuoteRequest`, so the endpoint advertises every field `/quote` supports and implements a subset | REFUSE the unsupported fields (422) instead of ignoring them — also `parent_estimate_id`, `source_proposal_id`, and a `config_id` agreement check |
| **Two contradictory `once_per_project` defaults**, each documented as deliberate, in opposite directions: `DEFAULT_ONCE_PER_PROJECT` has 4 keys incl. `tile_dumpster`; 0052's column default has 3 and argues against it | restating a list instead of importing it | the CODE is the measured authority (it produces Evergrene +2.3%; `tile_dumpster_count` is a `ceil()`, so per-building calls bill 14 loads for a 10-load site). ORM now imports it; **`0053` written to realign the DB — NOT APPLIED, Jon's call** |

### Also fixed

- **My grant script would have stamped Tim's July clearance onto projects created later**, with
  his name as provenance, because it was unfiltered and its docstring invited re-running. Now
  bounded by `GRANT_CUTOFF` (his email timestamp) + `archived_at IS NULL`, and it PRINTS the count
  of projects outside the grant rather than silently skipping them.
- **`property_id` was unvalidated.** Postgres evaluates FK constraints with row security
  BYPASSED, so RLS on `properties` never stopped a bid pointing at another tenant's property —
  only stopped reading it back. Now 404s. (gpt-oss's one genuine find.)

### Claims attacked that SURVIVED

The extraction is behaviour-identical for `/quote` (both reviewers verified ordering, the debug
gate, the measurement branch, and that `replace(q, apply_cut_calc_to_base=True)` equals the old
constructor since the field defaults True); no shared mutable state leaks between the N buildings
in one request; and no partial project is reachable — `get_db_session` commits on success and
rolls back on exception, and every raise happens before the first `db.add`.

### ⚠️ THE LOCAL MODELS WERE NET-NEGATIVE. THIS IS THE SECOND TIME.

- **qwen3.6-think FABRICATED a CRITICAL** and returned `VERDICT: BLOCKED`. It reported crashes on
  `r.quote_snapshot`, on `b.quote.num_squares` against `Estimate` objects, and on a three-element
  `zip`. None exist: `quote_snapshot` appears nowhere in the file, the zip has two targets, and
  `built` is `list[BP.Building]` whose `.quote` is correct. It asserted "crashes 100% of the time"
  against 11 passing tests and a live-config run. Last time it passed wrong code as "Correct";
  this time it invented defects. **Never gate on it.**
- **gpt-oss-120b-think** produced 12 findings, **1 real** (`property_id`). It hallucinated
  `core/migration_runner.py` (does not exist), called `claims` unused in a function that uses it
  for the debug gate, flagged a deliberate fix as a regression, and re-reported an already-fixed
  item. It also hit the documented empty-return trap TWICE: `finish_reason: length`, 0 content
  chars, 41,242 chars of reasoning. **Its real ceiling is 32,768, not 65,536**, and `llm` passes
  the body as curl argv so a >100KB prompt dies on `Argument list too long` — POST from a file.

Both Claude reviewers found real CRITICALs neither local model came near. Budget accordingly.

### ⚠️ `test_schema_maxlength` binds on IMPORTED CLASS NAMES, not on writes

It matched twice during this wave and the mechanism is not obvious. The heuristic is
`touched = {tbl for cls, tbl in model_tables.items() if cls in src}` — it scans the route
module's SOURCE TEXT for ORM class names, then requires every Pydantic `str` field sharing a name
with a column of those tables to carry `max_length`.

So **adding an import can newly bind an unrelated field**. Adding `bid_projects.branch
VARCHAR(100)` bound `QuoteRequest.branch`; later, importing `Property` for the `property_id`
check bound `QuoteRequest.county` against `properties.county` — even though `county` is written
to `estimates.county`, which is an unbounded `String`. Both bounds are worth having (an oversized
value 500s on Postgres and passes every SQLite test — the bug `16a662b` shipped), so the fix is
to bound the field, not to add an `ALLOW` entry. Just know that a new import can turn this red.

### Still flagged, deliberately NOT changed

`add_on_blocks` has no write path; `general_conditions_markup` is a scalar always written `1.0`
while real markup is per-item; `_estimate_row` omits the new columns so nothing reads a project
back; project `result_json` has a different shape from a single quote's, so `Quoting.tsx` will
render `—`; `persist` defaults True; `buildings` is unbounded; `permit_count`/`days` are not
persisted so a `week`-basis project cannot be reproduced. All are slice-3 scope — **stated here
because R2's definition of done is "no unwired code", and five deferrals stated is a pass while
five unstated is not.**

---

## §4 — NEXT

0. ⚠️ **RETRY R2 WITH THE AGENTS** (see §3.5). The formal requirement is unmet — both reviewer
   agents produced nothing. Everything below assumes that gets done or Jon waives it.
1. **Review and commit.** Nothing is committed. Then deploy — `deploy.sh` does NOT run migrations,
   and 0052 is already applied, so the ORM is safe to ship now.
2. **Slice 3 — the data-loss gate.** `web/src/pages/Proposals.tsx:414-419` re-quotes ONE estimate
   and overwrites `quote_snapshot`; on a project snapshot that **silently destroys eight
   buildings**. `Proposal.bid_project_id` now exists, so the gate has something to test. Also
   `_assemble_review_text` (`api/routes/proposals.py:143-167`) reads ONE roof, so the LLM send-gate
   would green-light a nine-building contract off one building.
3. **Send Tim the six questions.**
4. **Curate the five ready projects.**
5. `api-run-sa` still cannot create a secret (OAuth connect 502s) — a security-scope decision.

---

## §5 — VERIFICATION RUN

- `ruff check core adapters api jobs` — **clean** (CI's first gate).
- `tests/core/test_bid_project.py` — 22 pass, **100%** on `core/bid_project.py`.
- `tests/api/test_estimator_project_quote.py` — 10 pass (new).
- `tests/test_migration_statement_splitter.py` — 6 pass (new).
- 246 estimator tests pass after the extraction.
- `scripts/plan_as_ci.sh` — **plan exit 0, "No changes"** (R4).
- Evergrene validation — unchanged at +2.3% / +1.4%.

- Full pre-push suite after the fix — **`PYTEST_EXIT=0`**, no failures
  (`tests/api tests/core tests/adapters tests/jobs tests/tenancy`).

**But it went RED first, and the failure was real.**
`tests/api/test_schema_maxlength.py::test_route_schemas_bound_string_fields` — `PYTEST_EXIT=1`.

That test cross-checks every route schema's string fields against the strictest DB column of the
same name. Adding `bid_projects.branch VARCHAR(100)` put a bound on the name `branch` that had
never existed (`estimates.branch` is an unbounded `String`), and `project_quote` genuinely does
write that value into the new column — so an over-100-char branch would have **500'd on Postgres
while passing on SQLite**, which is exactly what the test says it exists to catch. Fixed by
bounding `QuoteRequest.branch` and `RepairQuoteRequest.branch` at `max_length=100`.

Worth keeping: the failure was invisible in the per-file runs I'd been doing all night and only
appeared in the whole-suite run, because it is a cross-cutting schema invariant rather than a
test of any one module. **Run the whole suite before believing anything.**

⚠️ Pre-existing: `app/models.py` carries 18 ruff `E702` errors on lines 63–233 (semicolon-joined
columns). `app/` is not in the CI ruff gate, so they have always been there and are not mine.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

**Performed:** `docs/continuations/CONTINUATION-2026-07-31.md` archived to `docs/continuations/`, keeping the latest
three at top level. Inbound links repointed and the docs index's "most recent" pointer refreshed.
