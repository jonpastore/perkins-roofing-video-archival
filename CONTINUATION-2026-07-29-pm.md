# CONTINUATION 2026-07-29 pm — the portfolio pipeline got a privacy gate, and a lot of "success" was silent failure

**Read `CONTINUATION-2026-07-29.md` first** (the morning session: the video pipeline, the
WireGuard tunnel, and §1 — we publish to STAGING). Everything below is the afternoon.

**HEAD `023d59d`**, pushed, CI green. **Deployed:** `platform:023d59d` — confirm with
`gcloud run services describe api --region us-central1 --format='value(spec.template.spec.containers[0].image)'`
before trusting it, and remember a `deploy` shown as *skipped* means nothing shipped.

---

## 0. If you read only one thing

Four separate things reported success today while doing nothing or the wrong thing. Every one
was found by **reading back what actually landed**, never by the code's own return value:

| what it said | what was true |
|---|---|
| `companycam-sync`: 50 projects, exit 0 | the account has **3,684** — pagination stopped on the first short page |
| `publish_portfolio_post`: 200 OK | `"skipped-exists"` — all 13 drafts existed, so curation changed **nothing** |
| JSON-LD inlined in the body, 200 OK | WordPress **stripped the whole `<script>`**, no error |
| CI: coverage gate "97%" green | the real number was **96.83%** — it passed on rounding |

The habit that caught all four: after any write, **fetch it back and count**. `git`, a job's
own log line, and an HTTP 200 are all equally happy to lie.

---

## 1. ⚠️ PII / privacy is now a HARD GATE — and the exposure was real

Jon, 2026-07-29: *"we need to not disclose PII and I wouldn't make the posts specific
addresses. neighborhood or city in address is fine but we can't be too specific."*

**Measured against our own mirror before writing any code:**

- **3,684 / 3,684** CompanyCam projects carry `street_address_1` + `postal_code`.
- **1,611 / 3,653** CompanyCam project NAMES are a customer's name ("Melissa Butterworth").
- **17** names embed a street address ("Melissa Naman - 1424 Willow Rd").
- **1** Knowify scope line reads *"pitch pans 10350 W. Bay Harbor Dr."* — and scope lines were
  being published verbatim, so that address was one curation click from a public page.

`core/pii.py` detects street addresses, PO boxes, ZIPs, unit/suite numbers, phones, emails and
GPS pairs, plus a `person_name_risk` heuristic for titles. `core/portfolio_criteria.py` turns
those into **blockers that refuse a publish**, checked across **every surface at once** — body,
meta, title, **image alt text**, **JSON-LD captions** and scope lines. A body-only check would
have passed an address hiding in an alt attribute, which is exactly the test that now exists.

**Calibrating it against the real corpus mattered more than the regexes.** First pass flagged
506 of 26,063 scope lines and **499 were false positives**: `ste` matching inside "**Ste**el".
A gate that blocks every metal-roof page is worse than none. After tightening (keyword needs a
word boundary AND a digit; ZIP needs a state; `#30` is 30-lb felt, not apartment 30):
**42 flags, 0 false positives** — 10 street addresses, 5 ZIPs, 31 condo unit numbers, 1 staff
email. Every one verified by hand.

The title heuristic needed the same treatment: "Fort Lauderdale" and "Miami Isola" both match
"First Last". Fixed by stripping the record's own city first, then rejecting place nouns
("Fisher **Island**") and work nouns ("Isola **Roof**") in the surname slot. Result on our 13
titles: exactly one blocks — **"Jim Malooly Delray Beach Roof"**, which really is a customer's
name. Verified live: with all three permissions granted it **still refuses**, because privacy
outranks consent for naming an individual.

## 2. There IS a critic now — two of them, deliberately different

- **`core/portfolio_criteria.py`** — the deterministic gate. Fast, exact, and it is what
  **refuses**: `publishable` false → `POST /publish` returns 422 with every reason and its
  evidence, and the UI disables the button rather than failing after a click. Blockers are
  privacy + client permission; majors are quality (no images, duplicate alts, thin body, no
  scope) because a thin project page competes with the nine real ones.
- **`core/portfolio_critique.py`** — three adversarial LLM lenses via `POST /{slug}/review`,
  same contract as `core.article_critique`. **privacy** (catches what a regex cannot: "the
  corner unit above the tennis courts"), **grounding** (every claim must trace to the record or
  the contract scope), **reader**. Advisory, not enforcing: an LLM verdict is not reproducible
  enough to gate on, but a blocker there should stop a human, and the UI shows it that way.

## 3. Write-ups are grounded in the CONTRACT now, not padding

The pages were one-line placeholders scoring 59%. The missing detail was already in the
Knowify mirror: contract **deliverables** are the scope lines Perkins actually sold. 6 of 13
candidates now carry real scope ("13\" Concrete Tile Re-Roof", "Sika RoofPro System", "Cooling
Tower 3 — Stockmeier Polyurethane Coating System"); word counts roughly doubled; a fully
curated project scores **86%**.

Four rules, each from a real failure in the data:

1. **Name-field matching only.** The pre-existing matcher `ILIKE`s the whole JSON payload —
   that is how "7900" matched a generic "Tile Re-Roof" whose *dollar amount* held those digits.
2. **Dominant-client attribution.** "warehouse" matches 9 projects across 7 customers; merging
   them publishes someone else's job. Olsen's 4 matches are one condo's phases, so they merge.
   No clear owner → no scope, deliberately.
3. **No "(OPTIONAL)" lines.** Knowify prices upgrades as deliverables. Publishing a quoted clay
   tile upgrade as installed is a lie about the property.
4. **No quantities, ever.** Olsen's re-roof reads "7550 Squares" (755,000 sq ft); Miramar's
   "142 Squares" sat against a RoofR report of 13,326. Descriptions are trustworthy, the numbers
   are not. Prices never ship.

Deterministic, **not** LLM-generated: the record holds ~6 facts, so a model asked for 500 words
invents 450 — the ~90%-invented articles are the precedent. A short honest page is the goal.

## 4. The UI is finished — 3 tabs + full CRUD

`web/src/pages/Portfolio.tsx`. **Project** (full CRUD on the record — this was a hardcoded
Python list), **Media** (permissions, thumbnails, per-image alt, drag-to-reorder), **SEO / AIO**
(score, publish gate with evidence, adversarial review, publish, and a preview of the exact HTML
that will ship). Projects are rows now (`portfolio_projects`, migration 0050), seeded once from
`CANDIDATES` — idempotent, so it cannot duplicate or overwrite an edit.

PII is refused **at the door** too: `POST /portfolio` with an address in the notes → 422.

## 5. CompanyCam: 3,684 projects, 155,975 photos, 11,635 videos

The mirror was seeing **1.4%** of the account. `_get_all` stopped on the first *short* page and
`/v2/projects` silently caps `per_page` at 50, so asking for 100 got 50 and the loop called it
the end. Now stops only on an **empty** page, and **raises** rather than truncating if an
endpoint ignores `page` or the cap is hit.

That made a full crawl ~7,400 requests, so the sync is **incremental** (migration 0049): media
is re-fetched only when CompanyCam's `updated_at` moves. Verified: a second run **skipped 3,679
of 3,684** and finished in 2m04s. A project whose photo *or* video fetch failed is deliberately
**not** stamped synced — `updated_at` will not move because our fetch failed, so remembering a
partial pull as complete would hide the missing half forever.

A 404 on a project's media sub-resource is **empty, not an error** (4 of 3,684 do this) —
counting it as an error made the job exit 1, retry to the cap, and never stamp those projects.

## 6. The idle-in-transaction leak that blocked a migration

`ingest_worker`, `knowify_sync` and `companycam_sync` each took their advisory lock and **never
committed**, so every holder sat idle-in-transaction for the whole job. Three such sessions
blocked a routine `ALTER TABLE videos`, and every subsequent reader queued behind the blocked
ALTER — a self-inflicted stall from jobs that had already finished.

`pg_try_advisory_lock` is **session**-scoped, so one commit keeps the lock and closes the
transaction. Extracted to `core/single_flight.py` (one primitive, three copies) and Cloud SQL now
enforces `idle_in_transaction_session_timeout = 5min`.

⚠️ **Auditing that flag caught a trap:** applied naively it would have killed the *running*
sync's lock session and silently defeated single-flight. Code first, then the flag.

## 7. The coverage gate was a rounding cliff

`--cov-fail-under=97` compares the **rounded** total, so "97%" really meant "≥96.5%": 96.56%
passed, 96.47% failed and **silently skipped a deploy**. `.coveragerc` now sets
`precision = 2`, which exposed the repo at 96.83% — under 97 all along.

Earned it rather than lowering the bar: **`core/wireproxy.py` 41% → 100%** (the tunnel every
archive download depends on had its start, failure and teardown paths untested). CI now reports
**97.43%**.

---

## What is NOT done

0. ⛔ **STAY ON STAGING — Jon, 2026-07-29: *"stay on staging till we clear client approval."***
   The prod cutover is **parked on a business gate, not missing work.** Do not change
   `PlatformConfig.WP_URL`, do not vault a prod WP app password, do not publish to
   perkinsroofing.net. Staging IS the intended target until Perkins approves, so "verified live"
   meaning staging is correct for now rather than a defect. Mechanics stay in
   `docs/PRODUCTION_CUTOVER_PLAN.md`.
2. ⚠️ **The `perkins-jsonld` mu-plugin must be re-uploaded to STAGING** (prod gets it at
   cutover, and it is on that checklist already). The version
   live on staging registers `_perkins_jsonld` for post type `post` only, so project pages can
   neither store nor render schema — measured: publish returned `jsonld_stored: false` and the
   meta was absent on read-back. `wp-mu-plugin/perkins-jsonld.php` in git now covers `post`,
   `avada_portfolio` and `page`. Until it is uploaded, project pages publish fine but carry NO
   JSON-LD, and both the API and UI say so. **This is a file upload to WP hosting — Jon.**
3. **Both emails were SENT by Jon himself** at 21:21 / 21:23 UTC, with his own edits — I only
   updated the drafts. Do not re-send. Two of his edits are decisions:
   - to Wendy: *"I'm going to use the article standards for now until I hear from you"* — which
     is exactly what `core/portfolio_criteria.py` implements, so nothing to change unless she
     answers differently;
   - to Tim: *"Can you try some quotes and tell me if it's working like you expect and if the
     numbers make sense?"* — so expect feedback on the live Quoting UI, not just an answer to
     the overhead question. That answer still gates flipping `overhead_basis`.
4. **`featured_media` is still 0** — WP needs an attachment, our images are CDN-hosted.
5. **2 of 13 candidates have no CompanyCam URL** — now fixable in the UI, needs the URL.
6. From the morning list: accent items priced but not selectable in the SPA · o365 refresh token
   expired · `proposal-reminders-daily` paused with no recorded reason · 4 test files still
   `drop_all` at teardown.

## Gotchas earned today

- **`gh run list` right after a push shows the PREVIOUS run.** Match the SHA, and remember
  `deploy` is `skipped` (not failed) when `ci` fails — a "skipped" deploy means nothing shipped.
- **A drift gate will block your deploy if you commit terraform without applying it.** Correct
  order: apply, then push. I committed the Cloud SQL flag and the deploy refused, rightly.
- **`pkill -f "<pattern>"` matches its own shell.** Twice today a waiter killed itself because
  the pattern appeared in its own command line. Use a PID.
- **Corpus-validate every heuristic before trusting it.** 499/506 false positives from one
  three-letter substring. The unit test suite was green the whole time.
- **`app/models.py` is NOT ruff-gated** (CI lints `core adapters api jobs`), so running ruff on
  it surfaces pre-existing E702s that are not yours.
- **A repo guard caught a defect in my own new schema.**
  `tests/api/test_negative_maxlength.py` compares Pydantic `max_length` against the DB columns,
  because SQLite accepts any length and Postgres 500s — my `ProjectIn` had no bounds while
  `portfolio_projects` bounds name/city/section at 300/120/40. If you add a request model backed
  by a bounded column, mirror the bounds or that test will (correctly) fail.
- **I enforced the gate in `publish` and re-ran only the NEW test file.** The older test covering
  the same route still asserted the pre-gate error shape and CI failed. When you change a
  route's contract, grep for every test that posts to it — `tests/api/test_portfolio.py` and
  `tests/api/test_portfolio_crud.py` both do.
- **The full local suite takes 40-60 min on this box but ~6 min on CI**, and the root-level tests
  alone are 32 seconds for 1,079 tests. Run `tests/api tests/core tests/adapters tests/jobs
  tests/tenancy` (7m40s, 4,063 tests) for a real pre-push check rather than the whole tree.
- **Two tests here are ORDER-DEPENDENT:** `tests/core/test_avatar_script.py` fails when
  `tests/core` runs alone (it needs another module to have created `tenants`). Pre-existing —
  verified by stashing. It passes in the full suite CI runs.
