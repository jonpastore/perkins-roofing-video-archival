STATUS: pending approval

# PRD — Knowify Data Mirror + Hourly Sync

**Feature:** Mirror all Knowify company data into the Perkins v2 DB, keep it fresh with an
hourly business-hours sync, expose it read-only in the API + admin UI, and use the mirror as
the on-ramp to **eliminating Knowify as a vendor**.

**Date:** 2026-07-11 · **Owner:** Perkins v2 platform · **Mode:** ralplan consensus (DELIBERATE)
**Tenant:** Perkins Roofing (tenant_id 1, Knowify tenant 9258 / company 11267).

---

## 1. Problem

Perkins' operational financial + job data (customers, invoices, payments, projects, and ~20
other entity types) lives **inside Knowify**, a third-party contractor SaaS. Today the Perkins
v2 platform can only *guess* at that data via one-off imports and an interactive MCP query
path that cannot run headless. Consequences:

- Staff must switch to Knowify to see their own invoices/payments — the v2 platform is not the
  system of record it needs to be.
- There is no continuously-fresh copy of the data, so any v2 feature that depends on Knowify
  data (billing, dashboards, the estimator) is working from stale snapshots.
- Perkins is **locked to the vendor**: there is no path to leave Knowify because the data has
  never been fully brought in-house.

## 2. Who / Why

| Persona | Need |
|---|---|
| Perkins billing staff | See customers, invoices, payments in the v2 admin console without opening Knowify. |
| Perkins ops/admin | Trust that the mirror is current (last sync time, row counts, errors) and re-connect when the Knowify login lapses. |
| Perkins leadership | A credible, incremental path off Knowify — the mirror is step one. |
| Platform engineering | A generic, lossless import so future features read from *our* DB, not Knowify. |

## 3. User-visible outcomes

1. A **"Knowify" tab** in the admin console lists mirrored customers, invoices, payments, and a
   generic viewer for every other Knowify entity (raw records).
2. Each entity view shows **sync health**: last successful sync time, high-water mark, rows
   seen, and last error (if any).
3. Two token-management controls:
   - **"Reconnect Knowify"** — starts an interactive OAuth login to mint fresh tokens when the
     stored refresh token is dead/revoked.
   - **"Sync now"** — a manual trigger that runs the sync immediately (bounded, single-flight).
4. Data refreshes automatically **every hour, 8:00 AM – 6:00 PM ET** (11 runs/day) with no
   human action.
5. Nothing is lost: **every** Knowify entity's raw payload is captured, even the ones not yet
   promoted to first-class tables.

## 4. Vendor-elimination roadmap (raw → first-class promotion)

The mirror is deliberately two-layered so we can leave Knowify incrementally without a 24-model
big-bang:

- **Layer A — raw mirror (day one):** ALL 24 Knowify entities land in one generic
  `knowify_raw_records` table (JSONB payload + content hash). v1 does a **full hash-gated pull**
  each run (server-side incremental is unverified — TRD §2); unchanged records write nothing.
  Upstream **deletes** are detected by tombstone-on-absence (a full pull's set-difference marks
  vanished records `is_present=FALSE`), so the mirror stays a faithful current copy, not just an
  append log. Together this makes the v2 DB a complete, queryable copy of Knowify.
- **Layer B — first-class (day one, the 4 that map cleanly):** `clients → Customer`,
  `items → PriceBookItem`, `invoices → Invoice`, `payments → Payment`, joined by a
  `knowify_*_id` crosswalk column.
- **Promotion:** As each additional entity earns a real v2 feature (projects, milestones,
  bills, time-entries, …), it is *promoted* — a first-class table is added and the sync
  back-fills it from the already-captured raw records. **No re-pull from Knowify is needed to
  promote** because the raw layer already holds the data.

Elimination milestone: when every entity Perkins actually uses is first-classed and writes flow
through v2, Knowify can be cancelled. This PRD delivers the foundation + the first 4; each later
promotion is a follow-on wave.

## 5. The two token flows (both required)

1. **Automatic refresh (refresh-on-use + keep-warm):** the hourly sync job refreshes/rotates the
   token as part of each run. Because Wave-0 proved the refresh token **dies within <1 day** and
   the hourly window leaves a 14h overnight gap, an off-hours **keep-warm** refresher is expected
   to be required (cadence from the measured idle-TTL). To avoid a rotated-token race, either one
   writer (refresh-on-use only) or both writers sharing a single advisory lock (TRD §3).
2. **UI Reconnect (manual, human) — PROVEN necessary:** an admin clicks "Reconnect Knowify" and
   completes an interactive OAuth login (device-code / redirect) to mint a fresh token pair when
   the refresh token has lapsed/revoked. This is exactly the Wave-0 situation (dead stored token)
   that a human must resolve — not a hypothetical.

Both flows write the resulting tokens to **Secret Manager (`knowify-tokens`)**, never to disk in
the container.

## 6. Sync window

- Hourly, **8:00 AM through 6:00 PM ET inclusive** → cron `0 8-18 * * *`, `America/New_York`,
  = **11 runs/day** (08,09,10,11,12,13,14,15,16,17,18).
- **Keep-warm is evidence-backed:** Wave-0 found the refresh token dead within <1 day, and the
  hourly window leaves a 14h overnight gap — so an off-hours keep-warm refresher is expected to be
  required (cadence set once the exact idle-TTL is measured post-re-login). Single writer or
  shared-lock keep-warm (§5) prevents a rotated-token race.
- Single-flight (advisory lock) so a slow run can never overlap the next tick.

## 7. Non-goals

- **No writes to Knowify.** Read-only mirror only; the sync never POSTs/PUTs to Knowify.
- **No 24 speculative first-class models.** Only the 4 clean entities are first-classed now;
  the rest live as raw records until a feature needs them.
- **No importing stale `OurCost` from Knowify items** — v2 pricing is authoritative (per
  0031/price-book rules).
- **No historical-invoice renumbering** and no advancing the live invoice counter (see AC-4).
  Knowify's `InvoiceNumber` is a string, kept in `knowify_invoice_number`; our integer
  `invoice_number` stays NULL for imports.
- **No AIA invoices** (Jon: only 1 ever, 2023). Import standard `/api/v2/invoices` only; exclude
  AIA payments. AIA may be raw-snapshotted for completeness but is not first-classed.
- **No cents conversion** — the REST path returns dollars; map straight to NUMERIC(12,2).
- **No new UI framework** — reuse existing api.ts / ui.tsx / App.tsx nav conventions.
- **No cross-tenant sync** — Perkins (tenant 1) only for now; the design is per-tenant so
  future tenants are additive.

## 8. Acceptance criteria (numbered, testable)

- **AC-1** Migration 0032 applies idempotently on both Postgres (prod) and SQLite (test),
  adds nullable `knowify_invoice_id` / `knowify_payment_id` / `knowify_job_id` crosswalk
  columns, and creates `knowify_sync_state`, `knowify_raw_records` — all RLS ENABLE+FORCE with
  the NULLIF 2-arg `tenant_isolation` policy. Re-running the migration is a no-op.
- **AC-2** After a full sync, `knowify_raw_records` contains one row per (entity, knowify_id)
  for every record the REST API returns; re-running with unchanged upstream data inserts/updates
  **zero** rows (hash-gated). A record that later disappears upstream is marked
  `is_present=FALSE, deleted_at=NOW()` on the next full pull (tombstone-on-absence) — so the
  mirror reflects deletes, not just adds/updates. ("Lossless" is qualified: raw rows are never
  hard-deleted; deletes are recorded as tombstones.)
- **AC-3** After a full sync, every Knowify `client` has a matching `Customer` row keyed by
  `knowify_customer_id`; likewise `items→PriceBookItem`, `invoices→Invoice`,
  `payments→Payment`, each keyed by its crosswalk id. Re-sync does not duplicate.
- **AC-4** Imported invoices are tagged `source='knowify_import'`; the Knowify `InvoiceNumber`
  (a string) is stored in `knowify_invoice_number` while integer `invoice_number` stays NULL; and
  the sync **does not modify `tenant_invoice_counters`** (verified: counter unchanged after import).
- **AC-5** `knowify_sync_state` records, per entity, `last_run_at`, `last_status`, `last_error`,
  `rows_seen`, and `last_high_water` (observability + v2 seed). v1 fetch is full-pull, not
  watermark-driven; server-side incremental (`last_high_water`/`last_cursor` driving fetch) is a
  v2 optimization gated on Wave-0 verifying `/query` accepts an `updated_at` filter.
- **AC-6** The hourly Cloud Scheduler job `knowify-sync` is defined in Terraform with schedule
  `0 8-18 * * *` / `America/New_York`, and `scripts/drift_check.sh` reports **no drift** after it
  is added.
- **AC-7** The sync job holds a Postgres advisory lock (single-flight): a second concurrent
  execution acquires no lock and exits without touching data.
- **AC-8** Each sync refreshes the access token and, when Knowify returns a rotated refresh
  token, **writes the new refresh token back to Secret Manager `knowify-tokens`**. The old
  local-disk token path is not used in the container.
- **AC-9** Token rotation is race-safe: with the single-writer design, concurrent/overlapping
  refreshes never publish a dead (already-rotated) refresh token as `latest` in Secret Manager.
  (If Wave-0 forces a keep-warm job, both writers share advisory lock `8274125` and this
  invariant is tested with both running.)
- **AC-10** `GET /knowify/status` returns sync health for each entity; `GET /knowify/<entity>`
  returns mirrored rows. Both enforce RLS (only tenant 1 data) and require an authorized role.
  An unauthenticated or unauthorized caller is rejected (401/403).
- **AC-11** `POST /knowify/reconnect` initiates the interactive OAuth flow and `POST
  /knowify/sync-now` triggers a bounded sync; both require the `knowify_admin` role.
- **AC-12** On a dead/lapsed token (401, refresh→invalid_grant), the sync fails **loudly** —
  `/api/v2/valid` preflight fails → `last_status='auth_error'` on every entity, surfaced in
  `/knowify/status`, job exits non-zero — rather than silently writing zero rows. (REST
  entitlement is verified-present; the live-token lapse is the real failure mode — TRD pre-mortem #1.)
- **AC-13** Admin UI "Knowify" tab renders customers/invoices/payments + a raw-entity viewer +
  sync-health panel + Reconnect / Sync-now buttons, following existing AdminConfig sub-tab
  conventions.
- **AC-14** (money) An imported **paid** Knowify invoice derives `status='paid'` via the ledger:
  paid = `TotalAmount − OutstandingAmount` (dollars) synthesized as one net `payment_recorded`
  event; the derived paid total == `invoice.total`. Status is derived from `job_billing_events`,
  not read from the `payments` table.
- **AC-15** (money) Re-running a full sync leaves `count(*) FROM job_billing_events WHERE
  idempotency_key LIKE 'knowify:%'` **unchanged** and does **not** double any paid total
  (deterministic keys + `UNIQUE(tenant_id, idempotency_key)`).
- **AC-16** (money) An imported **issued-but-unpaid** invoice derives `status='sent'` (not
  `'draft'`) via a synthesized `invoice_issued` event; a Knowify **Cancelled/Deleted**
  (`ObjectState`) invoice derives `'voided'`.
- **AC-17** The sync job **exits non-zero** when any entity ends `error`/`auth_error`, so Cloud
  Run marks the execution failed and the alert policy fires.
- **AC-18** (IaC) A `google_logging_metric` + `google_monitoring_alert_policy` +
  notification channel (reusing `alert_email`) exist in Terraform for auth-error / stale-sync,
  and `scripts/drift_check.sh` reports no drift with them present.
- **AC-19** (money guardrail) An imported invoice's monetary fields equal Knowify's **displayed
  dollars** (no ÷100). The mapping contains no cents conversion on the REST path.

## 9. Open questions (persisted to `.omc/plans/open-questions.md`)

1. Reconnect redirect landing: Cloud Run API route vs local browser. Device-code flow preferred
   for a browserless server — confirm Knowify AS supports device-code, else use a hosted
   redirect route on the API service.
2. Keep-warm cadence — set from the measured refresh-token idle-TTL after Jon re-logins
   (Wave-0 proved it dies within <1 day; likely needs an overnight refresher).
3. **[HUMAN — Jon] Re-run `python scripts/knowify/knowify_oauth.py`** to mint a fresh token —
   gates only the live pull + money ACs, not the build. (REST entitlement is already
   verified-present; no Knowify-support ticket needed.)
