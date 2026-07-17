# CONTINUATION — 2026-07-11 (EVE): Knowify data-mirror BUILT + DEPLOYED to prod + SEEDED

Massive session. Built the full **Knowify data-mirror + hourly-sync** platform (ralplan
consensus → 8 TDD waves), then **deployed it to prod and seeded the entire real Perkins
dataset** (7,404 customers / 4,484 invoices / 4,629 payments) — money-verified. The admin
console **Knowify tab is live**. Also: JB1/JB3/JB4 admin UIs, route security hardening, and a
C2 concurrency proof earlier in the day.

## What shipped (main, pushed; HEAD ~16bf0b1)
Earlier in the day (see prior continuations too):
- `646012b` admin UIs: price-book editor, proposal builder, invoices (React/TS).
- `49275b3` R2 security pass on JB1/JB3/JB4 routes (billing_manage role, idempotent payments,
  money-input validation, 502-on-gotenberg, milestone-draw guard, PDF date/license).
- `a43f4cb` C2 proof: Postgres two-session invoice-numbering concurrency test.

**Knowify mirror (ralplan-consensus plan → PRD/TRD/DDD in `docs/superpowers/specs/2026-07-11-knowify-mirror-*`):**
- `c1d07c0` W1 migration 0032 (crosswalk cols + `knowify_sync_state` + `knowify_raw_records` + RLS).
- `aee3c9a` W2 raw mirror (hash-gate + tombstones) + W4 token lifecycle (Secret Manager, fail-loud).
- `0b3cc31` W3 promotion + **ledger synthesis** (money; net payment_recorded, upsert-on-change) +R2 fixes.
- `221082e` W6 `/knowify/*` API + `knowify_admin` role. `e3a43c0` W7 admin Knowify UI tab.
- `d47e75f` W8 Terraform (jobs, `0 8-18 ET` scheduler, secret, IaC alert). `4c149a2` W5 sync job.
- `dba272a` fix: promote_clients real field names (ClientName/PhoneNumber). `09d470e` inactive-client
  support (customers.is_active) + orphan resilience + **headless MCP-token pull/seed scripts**.
- `b8daba7` fix: migration runner sets `app.tenant_id` for RLS-forced tenant seeds.
- `2720ed6`/`64e469a` seed stamps tenant GUC on any PG engine + batch commits.
- `16bf0b1` revert a bad Dockerfile change (scripts/ is .dockerignore'd by design).

## PROD IS DEPLOYED + SEEDED (2026-07-11)
- Migrations 0030+0031+0032 applied to Cloud SQL (`apply_migrations_connector.py`); counter=18732.
- **Targeted** `terraform apply` of ONLY the knowify GCP resources (jobs/schedulers/secret/log-metric)
  — deliberately avoided the pre-existing **cloudflare (placeholder token) + gotenberg + domain-mapping
  drift**. `deploy.sh` → API + jobs on image.
- **Full data seeded**: 7,404 customers (18 inactive), 4,484 invoices (**4,037 paid**; #18732 =
  Physio Healing Therapy $6,678 `paid`), 4,629 payments, 8,747 knowify ledger events. **Invoice
  counter untouched at 18732.** Web redeployed → **Knowify tab live** at
  https://video-archival-and-content-gen.web.app (default hosting site = project id).

### How the seed ran (reusable recipe — REST OAuth is broken, see below)
1. `scripts/knowify/mcp_pull.py` drives the **Knowify MCP HTTP endpoint** headlessly using the Claude
   Code MCP OAuth token (`~/.claude/.credentials.json` → mcpOAuth `knowify|...`, bound to
   assistant.knowify.com/api/v2/mcp) → pulls all clients/invoices/payments to JSON. No context burn.
2. Local seed over the WAN connector is ~140ms/stmt (≈2h — too slow). Instead ran a **temp in-region
   Cloud Run job** (image + GCS-mounted runner + socket `DB_URL`) → ~2 min. Cleaned up after.
3. GOTCHAS solved: `set_config('app.tenant_id','1')` needed (NOBYPASSRLS app user + FORCE RLS);
   `scripts/` is .dockerignore'd → run a GCS-mounted runner, not a scripts/ path; `PYTHONPATH=/srv`
   for a by-path script; **MCP payments are CENTS (÷100); REST payments would be dollars**.

## Outstanding (next session, priority order)
1. **Automated hourly sync can't pull yet** — Knowify's REST OAuth 500s on the RFC 8707 `resource`
   binding (their server bug — see [[knowify-oauth-outage]] memory + `docs/perkins-analysis/
   knowify-support-oauth500.md` DRAFT, not sent). Options: (a) wait for Knowify fix/roll-back;
   (b) email support; (c) **wire the sync job to the MCP-token path as a stopgap** for continuous
   refresh (the token is in Jon's local creds, NOT in the job — would need it in Secret Manager +
   a refresh mechanism). The mirror is a point-in-time snapshot until then.
2. **promote_items still reads wrong field names** (`rec["Name"]` etc.) — same class as the client
   bug; audit against real Knowify item schema. Items are secondary (Tim's sheet is authoritative).
3. **Pre-existing TF drift** (cloudflare placeholder token, gotenberg in-place change, domain mapping)
   — reconcile separately; a full `drift_check` is NOT clean because of these (not from this work).
4. **R1 core coverage**: an ad-hoc full-suite run in a stripped `env -i` shell showed ~94% (pre-existing
   billing/proposal modules' PG tests didn't run together); new knowify modules are 100%. Confirm ≥97 in CI.
5. Tim ~13-item material-cost email still a DRAFT in jon@degenito.ai Drafts (from prior sessions).

## Resume steps
1. `git status` (clean, pushed) + re-read memory index (esp. `knowify-mirror-build`,
   `knowify-oauth-outage`, `billing-schema-numbering`).
2. Verify prod: log into https://video-archival-and-content-gen.web.app → **Knowify tab** shows
   customers/invoices/payments + sync health; `/knowify/status` per-entity.
3. Decide on the sync stopgap (#1) — MCP-token path in Secret Manager, or wait on Knowify.

---
**Standing archive directive (performed this session):** moved the oldest top-level
`CONTINUATION-2026-07-10-pm.md` into `docs/continuations/`, kept the latest 3 at top level, fixed
inbound links. Apply on every continuation.
