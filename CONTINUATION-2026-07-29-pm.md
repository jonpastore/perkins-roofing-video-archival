# CONTINUATION 2026-07-29 pm — the portfolio pipeline got a privacy gate, and a lot of "success" was silent failure

**Read `CONTINUATION-2026-07-29.md` first** (the morning: video pipeline, WireGuard tunnel, and
the discovery that we publish to STAGING). Everything here is the afternoon.

**HEAD `5c9f0ca`**, pushed, CI green. **Deployed `platform:b44ef28`** (the `5c9f0ca` deploy was
still rolling at write time — it is docs-only, so the running code is current).

Verified live at write time:

| | |
|---|---|
| `portfolio_projects` | **13** (seeded from the old hardcoded list) |
| `portfolio_curation` | **0** — nobody has curated a project yet |
| `companycam_projects` / `_photos` / `_videos` | **3,684** / **155,997** / **11,635** |
| `idle_in_transaction_session_timeout` | **5min** (enforced) |
| migrations applied | through **0050** |

---

## 0. ⛔ STAY ON STAGING

Jon, 2026-07-29: *"stay on staging till we clear client approval."*

`PlatformConfig.WP_URL = https://1228404.us6.myftpupload.com` is the **correct, intended**
target. Do NOT change it, do NOT vault a prod WP application password, do NOT publish anything
to perkinsroofing.net. The prod cutover is a **parked business gate**, not missing work — every
"verified live" claim in these docs meaning *staging* is right for now. Mechanics live in
`docs/PRODUCTION_CUTOVER_PLAN.md` for whenever approval lands.

## 1. ▶ IMMEDIATE NEXT ACTION: fix the JSON-LD plugin on staging

**Symptom:** a project publishes correctly but carries **no JSON-LD at all**. Measured, not
guessed: `publish` returned `jsonld_stored: false` and the `_perkins_jsonld` meta was absent
when the post was read back.

**Cause:** the plugin live on staging registers `_perkins_jsonld` for post type **`post` only**,
and its `wp_head` hook fires only on `is_singular('post')`. Project pages are `avada_portfolio`
(and the nine public ones are `page`), so they can neither store nor render schema. WordPress
returns 200 for a write to an unregistered meta key, which is why nothing errored.

**Do NOT work around it by inlining `<script type="application/ld+json">` in the post body — that
was tried and WordPress strips it silently** on an application-password write. Verified by reading
the post back: the whole block was gone, no error raised. Schema belongs in post-meta, rendered
in `<head>` by the plugin.

**The fix is already in git** — `wp-mu-plugin/perkins-jsonld.php` now defines
`PERKINS_JSONLD_POST_TYPES = ['post','avada_portfolio','page']` and loops it for both
`register_post_meta` and the `wp_head` echo. It has to reach the WP host, which `deploy.sh`
cannot do.

**Use the ZIP route.** Measured 2026-07-29 against staging's `/wp-json/wp/v2/plugins` as admin
`jon`: what is live is the REGULAR plugin, `perkins-jsonld/perkins-jsonld` v1.2.0, **active**.
There is no mu-plugin — a published article renders exactly 2 `application/ld+json` blocks
(Rank Math's `@graph`, then our `FAQPage` + `VideoObject`), so only one emitter exists. An
earlier draft of this doc claimed the mu-plugin "matches what is installed now"; it does not,
and dropping the mu-plugin in alongside the active plugin is precisely what would duplicate
schema on all ~60 articles.

- **DO:** zip `wp-plugin/perkins-jsonld/` → wp-admin → Plugins → Add New → Upload → *Replace
  current with uploaded*. Same slug, so it upgrades in place: no deactivation, no SFTP, no
  second emitter. `perkins-jsonld/` is GENERATED from the mu-plugin (identical below the
  header) — `tests/test_wp_plugin_parity.py` fails if they drift.
- **DO NOT** install the mu-plugin on staging while `perkins-jsonld` is active. mu-plugins
  cannot be deactivated from wp-admin, so undoing that mistake needs the filesystem access the
  mu-plugin route was chosen to avoid.

⚠️ Never both. The version bump to **1.3.0** is the wp-admin-visible signal the upload landed.

**Verify after upload — do not assume:**

```bash
PYTHONPATH=. WP_USER=jon .venv/bin/python - <<'EOF'
import os, subprocess, json
pw = subprocess.run(['gcloud','secrets','versions','access','latest','--secret=db-password'],
                    capture_output=True, text=True).stdout
os.environ["DB_URL"] = f"postgresql+psycopg://app:{pw}@127.0.0.1:5432/perkins"
os.environ["WP_APP_PWD"] = subprocess.run(
    ['gcloud','secrets','versions','access','latest','--secret=wordpress-app-password'],
    capture_output=True, text=True).stdout.strip()
import adapters.wordpress as wp
r = wp._session.get(wp._wp_api_url("/wp-json/wp/v2/avada_portfolio/8296"),
                    auth=wp._auth(), params={"context": "edit"}, timeout=30)
meta = (r.json().get("meta") or {}).get("_perkins_jsonld") or ""
print("meta stored:", bool(meta),
      "| types:", [n.get("@type") for n in json.loads(meta)] if meta else [])
EOF
```

Post 8296 is "Miami Beach Olsen Condo" on staging — already published with a 4-image gallery and
contract scope, so it is the natural test subject. After the plugin lands, re-publish it through
the UI (SEO / AIO tab) and confirm `jsonld_stored: true`, then fetch the public staging URL and
grep `<head>` for `application/ld+json`.

## 2. What "success" claimed vs what was true

Five things reported success while doing nothing or the wrong thing. Every one was caught by
**reading back what actually landed** — never by a return value:

| it said | it was |
|---|---|
| `companycam-sync`: 50 projects, exit 0 | the account has **3,684** — pagination stopped on the first *short* page, and `/v2/projects` caps `per_page` at 50 |
| `publish_portfolio_post`: 200 OK | `"skipped-exists"` — all 13 drafts already existed, so curation changed **nothing** |
| JSON-LD inlined in the body, 200 OK | WordPress **stripped the whole `<script>`**, no error |
| CI coverage gate "97%" green | the real number was **96.83%** — it passed on *rounding* |
| PII detector unit tests green | **499 of 506** flags on real data were false positives |

The habit: after any write, fetch it back and count. `git`, a job's own log line, and an HTTP 200
are all equally happy to lie.

## 3. ⚠️ PII is a HARD GATE — the exposure was measured first

Jon: *"we need to not disclose PII and I wouldn't make the posts specific addresses.
neighborhood or city in address is fine but we can't be too specific."*

Measured against our own mirror **before** writing code:

- **3,684 / 3,684** CompanyCam projects carry `street_address_1` + `postal_code`
- **1,611 / 3,653** CompanyCam project NAMES are a customer's name ("Melissa Butterworth")
- **17** names embed a street address ("Melissa Naman - 1424 Willow Rd")
- **1** Knowify scope line reads *"pitch pans 10350 W. Bay Harbor Dr."* — and scope lines were
  publishing verbatim, so that address was one curation click from a public page

`core/pii.py` finds street addresses, PO boxes, ZIPs, unit/suite numbers, phones, emails and GPS
pairs, plus `person_name_risk` for titles. `core/portfolio_criteria.py` turns them into
**blockers that refuse a publish**, checked across **every surface at once** — body, meta, title,
**image alt text**, **JSON-LD captions**, scope lines. A body-only check passes an address hiding
in an alt attribute; that is now a test.

**Calibration mattered more than the regexes.** First pass: 506 of 26,063 scope lines flagged,
**499 false positives** — `ste` matching inside "**Ste**el" — while the unit tests were green. A
gate that blocks every metal-roof page is worse than none. After tightening (unit keywords need
a word boundary AND a digit; a ZIP needs a state; `#30` is 30-lb felt, not apartment 30):
**42 flags, 0 false positives**, every one verified by hand.

Same for titles: "Fort Lauderdale" and "Miami Isola" both match "First Last". Fixed by stripping
the record's own city, then rejecting place nouns ("Fisher **Island**") and work nouns ("Isola
**Roof**") in the surname slot. Of our 13 titles exactly one blocks — **"Jim Malooly Delray Beach
Roof"** — and it still refuses with all three permissions granted, because **privacy outranks
consent** for naming an individual.

⚠️ **Do not "simplify" these patterns without re-running the corpus check** against
`knowify_raw_records` deliverables. It must reproduce: 42 flags / 0 false positives over 26,063
lines, and exactly 1 of our 13 titles blocking.

## 4. There IS a critic now — two, deliberately different

- **`core/portfolio_criteria.py`** — deterministic gate, and the thing that **refuses**.
  `POST /{slug}/publish` returns **422 with every failing criterion and its evidence**; the UI
  disables the button rather than failing after a click. Blockers = privacy + client permission.
  Majors = quality (fewer than 4 images, duplicate alts, body under 120 words, no scope) because
  a thin project page competes with the nine real ones. Minors never block.
- **`core/portfolio_critique.py`** — three adversarial LLM lenses via `POST /{slug}/review`,
  same contract as `core.article_critique`: **privacy** (catches what a regex cannot — "the
  corner unit above the tennis courts"), **grounding** (every claim must trace to the record or
  the contract scope), **reader**. Advisory: an LLM verdict is not reproducible enough to gate
  on, but a blocker there should stop a human, and the UI shows it that way. Stateless — a review
  always reflects current curation.

## 5. Write-ups are grounded in the CONTRACT

Pages were one-line placeholders scoring 59%. The detail was already in the Knowify mirror:
contract **deliverables** are the scope lines Perkins actually sold. 6 of 13 candidates now carry
real scope; word counts roughly doubled; a fully curated project scores **86%**.

Four rules, each from a real failure in the data:

1. **Name-field matching only** — the pre-existing matcher `ILIKE`s the whole JSON payload, which
   is how "7900" matched a generic "Tile Re-Roof" whose *dollar amount* held those digits.
2. **Dominant-client attribution** — "warehouse" matches 9 projects across 7 customers; merging
   them publishes someone else's job. Olsen's 4 matches are one condo's phases, so they merge.
   No clear owner → no scope, deliberately.
3. **No "(OPTIONAL)" lines** — Knowify prices upgrades as deliverables; publishing a quoted clay
   tile upgrade as installed is a lie about the property.
4. **No quantities, ever** — Olsen's re-roof reads "7550 Squares" (755,000 sq ft); Miramar's "142
   Squares" sat against a RoofR report of 13,326. Descriptions are trustworthy, numbers are not.
   Prices never ship.

Deterministic, **not** LLM-written: the record holds ~6 facts, so a model asked for 500 words
invents 450 (the ~90%-invented articles are the precedent). A short honest page is the goal, and
the remaining word-count shortfall needs real project narrative from Perkins — not padding.

## 6. The UI is finished — 3 tabs + full CRUD

`web/src/pages/Portfolio.tsx`:

- **Project** — full CRUD on the record. This was a hardcoded Python list; a project could not be
  added or corrected without a code change and a deploy.
- **Media** — permissions, thumbnails, per-image alt text, drag-to-reorder (order is publish
  order and decides which image is `representativeOfPage`), plus arrow buttons so it is not
  mouse-only.
- **SEO / AIO** — score, the publish gate with its evidence, the adversarial review, publish, and
  a preview of the exact HTML that will ship.

API (`api/routes/portfolio.py`): `GET ""`, `POST ""`, `PUT /{slug}`, `DELETE /{slug}` (archive,
soft), `POST /{slug}/restore`, `GET /{slug}/media`, `PUT /{slug}/curation`,
`POST /{slug}/review`, `POST /{slug}/publish`. PII is refused at the door too — `POST /portfolio`
with an address in the notes is a 422.

## 7. CompanyCam is fully mirrored, incrementally

The mirror was seeing **1.4%** of the account. `_get_all` now stops only on an **empty** page and
**raises** rather than truncating if an endpoint ignores `page` or the cap is hit.

A full crawl is ~7,400 requests, so the sync is **incremental** (migration 0049): media is
re-fetched only when CompanyCam's `updated_at` moves. Verified — a second run **skipped 3,679 of
3,684** in 2m04s. A project whose photo *or* video fetch failed is deliberately **not** stamped
synced: `updated_at` will not move because our fetch failed, so remembering a partial pull as
complete would hide the missing half forever. A 404 on a project's media sub-resource is
**empty, not an error** (4 of 3,684 do this).

Data lands in prod Cloud SQL, **metadata only** — URLs, coordinates, `internal` flag. Media stays
on CompanyCam's CDN; we never copy bytes. Scheduler: `companycam-sync` 06:00 ET.

## 8. The idle-in-transaction leak that blocked a migration

`ingest_worker`, `knowify_sync` and `companycam_sync` each took their advisory lock and **never
committed**, so every holder sat idle-in-transaction for the whole job. Three such sessions
blocked a routine `ALTER TABLE videos`, and every later reader queued behind the blocked ALTER —
a self-inflicted stall from jobs that had already finished.

`pg_try_advisory_lock` is **session**-scoped, so one commit keeps the lock and closes the
transaction. Extracted to `core/single_flight.py`; Cloud SQL enforces
`idle_in_transaction_session_timeout = 5min`. ⚠️ Auditing that flag caught a trap: applied
naively it would have killed the *running* sync's lock session and silently defeated
single-flight. Code first, then the flag.

## 9. The coverage gate was a rounding cliff

`--cov-fail-under=97` compares the **rounded** total, so "97%" meant "≥96.5%": 96.56% passed,
96.47% failed and **silently skipped a deploy**. `.coveragerc` now sets `precision = 2`, which
exposed the repo at 96.83%. Earned rather than lowered: **`core/wireproxy.py` 41% → 100%** (the
tunnel every archive download depends on had its start, failure and teardown paths untested).
CI now reports **97.43%**.

---

## New this session

| file | what |
|---|---|
| `core/pii.py` | PII detection + `person_name_risk` (100% covered) |
| `core/portfolio_criteria.py` | THE publish gate (100%) |
| `core/portfolio_critique.py` | 3 adversarial LLM lenses (100%) |
| `core/portfolio_content.py` | write-up, grounded FAQ, JSON-LD builders |
| `core/portfolio_facts.py` | scope-line cleaning + dominant-client attribution |
| `core/portfolio_projects.py` | slug/validation rules + seeding |
| `core/portfolio_media.py` | curation rules + SEO/AIO scoring |
| `core/single_flight.py` | the advisory-lock primitive, extracted from 3 copies |
| `infra/migrations/0047-0050` | companycam_videos · portfolio_curation · companycam_projects · portfolio_projects |
| `scripts/margin_check.py` | reproducible overhead/margin analysis |

## Still open

1. ⛔ **Prod cutover — parked on client approval** (§0).
2. ▶ **The plugin fix** (§1) — the immediate next action.
3. **Replies to watch.** Both emails were **sent by Jon himself** 21:21 / 21:23 UTC with his own
   edits — do not re-send. He told Wendy *"I'm going to use the article standards for now until I
   hear from you"* (which is what the gate implements), and asked Tim *"Can you try some quotes
   and tell me if it's working like you expect and if the numbers make sense?"* — so expect
   Quoting UI feedback, not just an overhead answer. Tim's answer gates flipping `overhead_basis`.
4. **`featured_media` is still 0** — WP needs an attachment; our images are CompanyCam-CDN URLs.
5. **2 of 13 projects have no CompanyCam URL** — now fixable in the UI, needs the URL.
6. From the morning list: accent items priced but not selectable in the SPA · o365 refresh token
   expired (use gmail-enhanced) · `proposal-reminders-daily` paused with no recorded reason ·
   4 test files still `drop_all` at teardown.

## Gotchas earned today

- **After any write, read it back and count.** See §2.
- **Corpus-validate every heuristic.** Unit tests were green at a 98% false-positive rate.
- **A short page from a paginated API is not the last page.**
- **Terraform: apply BEFORE push.** The deploy workflow has a drift gate and will refuse if git
  carries an unapplied change. Committing the Cloud SQL flag first correctly blocked the deploy.
- **`gh run list` right after a push shows the PREVIOUS run** — match the SHA. And a `deploy`
  shown as **skipped** means nothing shipped (it skips when `ci` fails).
- **`pkill -f "<pattern>"` matches its own shell.** Two waiters killed themselves. Use a PID.
- **A repo guard caught a defect in my own schema:** `tests/api/test_negative_maxlength.py`
  compares Pydantic `max_length` against DB columns because SQLite accepts any length and
  Postgres 500s. Mirror the bounds on any new request model.
- **Changing a route's contract? grep for EVERY test that posts to it.** I enforced the gate and
  re-ran only the new test file; CI caught the older one asserting the pre-gate error shape.
- **The full suite takes 40-60 min on this box but ~6 min on CI.** `tests/api tests/core
  tests/adapters tests/jobs tests/tenancy` is 4,063 tests in 7m40s — use that pre-push. The
  root-level tests alone are 1,079 in 32s.
- **`app/models.py` is NOT ruff-gated** (CI lints `core adapters api jobs`); its E702s are
  pre-existing style, not yours to fix.
- **`tests/core/test_avatar_script.py` fails if `tests/core` runs ALONE** (it needs another module
  to have created `tenants`). Pre-existing — verified by stashing — and it passes in the full
  suite CI runs.
