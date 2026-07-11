# PLAN — Sales/Legacy console follow-ups (2026-07-11 eve)

Follow-up work after the Sales/Legacy/Dashboard overhaul + Knowify MCP-sync stopgap
shipped & deployed this session (commits `0ae2a12`, `2f546f9`, `2302cdf`; API rev
`api-00057`; web bundle `index-BVcuUusB.js`; first prod MCP sync succeeded —
7,404 clients / 8,492 projects / 16,748 contracts / 26,015 deliverables / 4,484
invoices / 4,897 payments in the raw mirror). Context memory: `sales-console-roadmap`,
`knowify-mirror-build`, `knowify-oauth-outage`.

**MCP token**: stashed for next session at repo-root `.env.knowify-mcp` (gitignored,
chmod 600) as `KNOWIFY_MCP_TOKEN_JSON=<blob>`. Also authoritative in Secret Manager
(`knowify-mcp-tokens`). Access tokens expire ~2h; if stale, reconnect Knowify MCP in
Claude and re-stash (re-bootstrap command is in the file header).

Discipline (unchanged): money/authz/migration/security → Claude review; implementation →
sonnet. Gate = `pytest --cov=core` (≥97) + `ruff` + `web: npm run build` on a clean tree.
R2 (architect+critic) per wave. Legacy data stays READ-ONLY; CRUD only on native v2.

---

## P0 — Bugs (broken in prod, fix first)

### 0.1 Estimator page hard-crashes: `TypeError: n.filter is not a function` (img #6)
- **Root cause (confirmed):** `web/src/pages/Quoting.tsx:505` does `customers.filter(...)`,
  but `customers` is being set to the paged `{items,total}` object, not an array. The
  "Estimator" nav tab renders `Quoting.tsx` (renamed label). Its customers fetch either
  calls `listQuotingCustomersPaged` (returns `{items,total}`) and stores the whole object,
  or hits `/quoting/customers` directly (now `{items,total}`).
- **Fix:** set `customers` from `.items` (or switch to the array-returning
  `listQuotingCustomers()`), and guard `Array.isArray` before `.filter`. Grep the whole
  frontend for other `.filter`/`.map` on list responses whose shape changed to `{items,total}`
  (Squares/Estimator/Proposals could have the same latent bug). This is the same seam class
  we hit with Quotes/Payments — audit ALL consumers of the changed endpoints.
- Files: `web/src/pages/Quoting.tsx` (+ audit `Estimator.tsx`, `Squares.tsx`, `Proposals.tsx`).

### 0.2 New Proposal: "Failed to load customers: [object Object]" (img #4)
- **Root cause:** `ProposalBuilder.tsx:416` renders `e instanceof Error ? e.message : String(e)`.
  The thrown value stringifies to `[object Object]` — either `errText` (`api.ts:370`) returns
  a non-string (the parsed JSON error body), or a non-Error object is thrown. Likely the
  `/quoting/customers` call is erroring (403? shape?) and the error body is an object.
- **Fix:** (a) make `errText` always return a string (extract `.detail`/`.message` from a JSON
  body); (b) in ProposalBuilder, coerce to a readable message. THEN determine WHY customers
  fails to load in prod for this page specifically — reproduce against the live API with an
  auth token (check the browser Network tab: status + body of `GET /quoting/customers`).
  It may be the same paged-shape issue as 0.1 (ProposalBuilder expects an array).
- Files: `web/src/api.ts` (`errText`), `web/src/pages/ProposalBuilder.tsx`.

### 0.3 Dashboard charts run off import date, not the real Knowify dates (img #7)
- **Root cause (confirmed):** `core/knowify/promote.py` maps `payment_date` (line ~493) but
  does **NOT** map `invoice_date` / `due_date` from Knowify `InvoiceDate` / `DueDate` onto the
  promoted `Invoice`. So legacy invoices carry a null/default (import-time) date → the
  "Payments & Invoices Issued" chart clusters everything on 2026-07-11 and AR Aging shows
  everything as "Current" (~$1.5M), because due dates are all null/recent.
- **Fix:** in `promote_invoices`, set `invoice_date` from `InvoiceDate` and `due_date` from
  `DueDate` (reuse the `_parse_date` helper already used for payments). MONEY/DATA-correctness
  → Claude review. After the fix, a re-sync re-promotes changed rows (hash changes) and
  backfills the dates — confirm the dashboard then shows the real historical distribution.
  Consider a one-off backfill if upsert-on-change doesn't re-touch unchanged-payload rows.
- Files: `core/knowify/promote.py`; verify with a fresh `knowify-sync` execution + dashboard.

### 0.4 Invoices list shows "#" for every legacy invoice number (img #2)
- **Root cause (confirmed):** the light list serializer added this session
  (`api/routes/invoices.py` `_invoice_list_dict`, ~line 178) returns only `invoice_number`
  (the v2 sequence, NULL for `source='knowify_import'`), not `knowify_invoice_number`. The UI
  renders `#{invoice_number}` → "#".
- **Fix:** include `knowify_invoice_number` in the light serializer and display
  `invoice_number ?? knowify_invoice_number` (label legacy rows with the Knowify number).
- Files: `api/routes/invoices.py`, `web/src/pages/Invoices.tsx`.

---

## P1 — UX polish (requested)

### 1.1 Payments "View" → modal (img #3)
Currently renders a detail **panel below** the table. Make it a popup modal. Build a small
reusable `Modal` in `web/src/ui/` (none exists) and reuse it across the console.
Files: `web/src/ui/Modal.tsx` (new), `web/src/pages/Payments.tsx`.

### 1.2 Customer "View" → modal
Same: customer detail should pop a modal (reuse `Modal` from 1.1).
Files: `web/src/pages/Customers.tsx`.

### 1.3 Quotes page is confusing (img #5)
- **`Default_Contract` rows with empty sums**: these are Knowify placeholder/draft shells
  (ContractName literally "Default_Contract", no `OriginalContractSum`). They're noise.
  **Fix:** filter them out by default (exclude `ContractName == "Default_Contract"` and/or
  `BusinessState in (Draft) with null sum`), or add a "hide drafts/placeholders" toggle.
  Decide with Jon whether drafts should show at all.
- **Add filters:** Type (`ContractType`), Business State (`BusinessState`), Signed
  (`IsSigned`). Backend already supports `business_state`; add `contract_type` + `is_signed`
  query params to `GET /quotes` + UI dropdowns.
- **Make every column sortable:** today only Id/DateCreated/OriginalContractSum/BusinessState
  are in the `_SORT_COLS` whitelist. Add Name (ContractName), Type, Signed to the whitelist +
  mark the columns `sortable` in the UI. (Keep it a whitelist — no arbitrary column sort.)
- Files: `api/routes/quotes.py`, `web/src/pages/Quotes.tsx`.

### 1.4 Legacy Data → Sync Health cleanups (img #1)
- **HIGH WATER always "—":** the sync runs a full-pull (v1, no `since=`) so
  `last_high_water` is never written. Either (a) populate `last_high_water` from
  `max(DateModified)` seen per entity, or (b) drop/relabel the column as "Full pull" so it's
  not misleading. Low priority; pick (b) unless incremental sync is planned.
- **Red "—" under ERROR for `payments` and `projects`:** investigate — `last_error` is null
  but styled red (or a stale non-fatal error). Confirm it's cosmetic; fix the conditional
  styling so a null error renders neutral, not red.
- Files: `web/src/pages/Knowify.tsx` (styling), `core/knowify/mirror.py` (high-water, optional).

---

## P2 — Consolidation & data enrichment (needs decisions)

### 2.1 Consolidate "New Proposal" + "Proposals"; why is Proposals empty?
- **Why Proposals is empty:** `Proposals.tsx` lists native **v2** `Proposal` records
  (`quote_snapshot`); there are none yet. Legacy Knowify quote/contract data lives in the raw
  mirror and is shown under **Quotes**, NOT Proposals. So Proposals is empty by design until
  v2 proposals are created.
- **Decision needed:** (a) fold "New Proposal" (the `ProposalBuilder` create wizard) into
  "Proposals" as a "＋ New" button (one tab, list + create); and (b) decide whether legacy
  contracts should also surface in Proposals or stay in Quotes only. Recommend: merge the two
  proposal tabs; keep legacy under Quotes; add an "adopt legacy contract → v2 proposal" action
  (the "adopt to v2" flow promised in the Legacy banner but not yet wired).
- Files: `web/src/App.tsx` (nav), `web/src/pages/Proposals.tsx`, `ProposalBuilder.tsx`.

### 2.2 Estimator vs Estimates — merge / clarify
- Two tabs today: **Estimator** (renders `Quoting.tsx`) and **Estimates** (`Estimator.tsx`).
  Confusing. Investigate what each does (Quoting.tsx = customer/quote builder that's currently
  crashing per 0.1; Estimator.tsx = pricing-config/estimate tool). **Decision needed:** merge
  into one "Estimator" surface or clearly differentiate labels. Neither is "for legacy" —
  legacy is Quotes. Resolve naming with Jon.
- Files: `web/src/App.tsx`, `web/src/pages/{Quoting,Estimator}.tsx`.

### 2.3 Customer contacts & properties — sync + columns
- **Confirmed:** `promote.py` does NOT create `Contact` or `Property` records from Knowify, so
  every synced customer has **0 contacts / 0 properties**. Knowify has the data:
  `Projects` carry addresses (Address1/City/StateProvince/Zip) and clients/contracts carry
  `ContactName`.
- **Plan:** (a) add `num_contacts` / `num_properties` columns to the Customers list
  (`GET /quoting/customers` — add counts via subquery/join); (b) new promote step (Claude
  review — it's a data-mapping + possible migration): map Knowify `Projects` → `Property`
  records linked to the customer (via `ClientId` → `knowify_customer_id`), and `ContactName`
  → a primary `Contact`. Dedup on re-sync. This is a wave of its own.
- Files: `api/routes/customers.py` (counts), `core/knowify/promote.py` (new `promote_*`),
  possibly a migration for crosswalk cols on Property/Contact.

### 2.4 Video topics — total count, no truncation, "show all" modal (img #8)
- **Investigate first (process vs UI):** the expanded video info shows 8 topics and a
  "8 topics" badge (`v.topic_count`, `Archive.tsx:908`). Determine whether the topic-mining
  step CAPS extraction (~8) — a **process limit that could miss topics** — or whether the UI
  truncates. Grep the STT/topic-mining job + the video-detail topics endpoint for a LIMIT/cap.
  (No UI `.slice(0,8)` was found, so suspicion is the extraction/endpoint.)
- **Then build:** (a) if extraction is capped, raise/remove the cap so no topic is missed;
  (b) surface a total topic count (already have `topic_count` — add it to the dashboard KPIs);
  (c) a "Show all topics" button → modal listing all topics with timestamp links, plus a
  per-topic "Find all videos for this topic" button that opens the Search/Ask interface
  pre-filled with that topic.
- Files: topic-mining job in `jobs/` + `core/`, video-detail topics endpoint in `api/routes/`,
  `web/src/pages/Archive.tsx`, `web/src/pages/Status.tsx` (KPI), `web/src/pages/SearchAsk.tsx`
  (deep-link a topic query).

---

## Suggested sequencing
1. **Wave A (P0, one focused pass):** 0.1 crash + audit all changed-endpoint consumers →
   0.2 error rendering → 0.4 invoice numbers. Ship + redeploy web. These are user-visible breaks.
2. **Wave B (P0 data):** 0.3 promote date mapping (Claude review) → re-sync → verify dashboard.
3. **Wave C (P1):** reusable `Modal` (1.1/1.2), Quotes filters+sort+Default_Contract (1.3),
   Sync Health cleanups (1.4).
4. **Wave D (P2 decisions):** confirm with Jon on 2.1/2.2 (proposal + estimator consolidation),
   then 2.3 contacts/properties enrichment (migration + promote), 2.4 topics (investigate → build).

## Deferred from prior session (still open)
- GCP-spend widget: needs BigQuery billing export enabled + `BILLING_BQ_TABLE` set +
  dataset-scoped `bigquery.dataViewer` (exact `bq` command in `infra/main.tf`).
- MCP token refresh (`resource=MCP_URL`) still UNPROVEN — first real hourly refresh is the
  test; if it 500s like REST, sync `auth_error`s + alerts (mirror stays intact).
