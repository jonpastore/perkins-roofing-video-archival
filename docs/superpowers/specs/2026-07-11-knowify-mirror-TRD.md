STATUS: pending approval

# TRD — Knowify Data Mirror + Hourly Sync

Technical contract for the PRD of the same date. Binding project rules: R1 (core ≥97% + I/O
behavioral validation), R2 (architect+critic per wave), R3 (100% IaC, git→apply), R4 (drift
clean), R5 (Ansible for non-TF). Money/OAuth/migration code stays on Claude opus.

---

## 1. Migration 0032 — exact schema

File: `infra/migrations/0032_knowify_mirror.sql`. Idempotent (`CREATE ... IF NOT EXISTS`,
`ADD COLUMN IF NOT EXISTS`). No migration-tracking table exists (per 0030/0031); apply via
`scripts/apply_migrations_connector.py` (MIN_MIGRATION honored). RLS follows the exact 0030/0031
convention: `ENABLE` + `FORCE` + drop/create `tenant_isolation` policy with the NULLIF 2-arg GUC.

### 1a. Crosswalk columns (added to existing money/job tables)

```sql
ALTER TABLE invoices  ADD COLUMN IF NOT EXISTS knowify_invoice_id     VARCHAR(100);
ALTER TABLE invoices  ADD COLUMN IF NOT EXISTS knowify_invoice_number TEXT;  -- Knowify InvoiceNumber is a STRING (user-facing, may be non-numeric)
ALTER TABLE invoices  ADD COLUMN IF NOT EXISTS source                 VARCHAR(30) NOT NULL DEFAULT 'v2';
ALTER TABLE invoices  ADD CONSTRAINT chk_invoices_source CHECK (source IN ('v2','knowify_import')) NOT VALID;
-- (NOT VALID then VALIDATE avoids a long lock on the existing table; or inline CHECK if empty.)
ALTER TABLE payments  ADD COLUMN IF NOT EXISTS knowify_payment_id VARCHAR(100);
ALTER TABLE jobs      ADD COLUMN IF NOT EXISTS knowify_job_id     VARCHAR(100);

CREATE INDEX IF NOT EXISTS ix_invoices_tenant_knowify ON invoices (tenant_id, knowify_invoice_id);
CREATE INDEX IF NOT EXISTS ix_payments_tenant_knowify ON payments (tenant_id, knowify_payment_id);
CREATE INDEX IF NOT EXISTS ix_jobs_tenant_knowify     ON jobs     (tenant_id, knowify_job_id);
```

Notes: `customers.knowify_customer_id` and `price_book_items.knowify_item_id` **already exist**
(models.py:436, 0031:38) — 0032 does NOT re-add them; it only adds a unique partial index if one
is missing:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_tenant_knowify
    ON customers (tenant_id, knowify_customer_id) WHERE knowify_customer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_tenant_knowify_id
    ON invoices (tenant_id, knowify_invoice_id) WHERE knowify_invoice_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_tenant_knowify_id
    ON payments (tenant_id, knowify_payment_id) WHERE knowify_payment_id IS NOT NULL;
```
These partial-unique indexes are what make the crosswalk upsert safe (ON CONFLICT target).

### 1b. `knowify_sync_state` — watermark table

```sql
CREATE TABLE IF NOT EXISTS knowify_sync_state (
    id              SERIAL PRIMARY KEY,
    entity          VARCHAR(50)  NOT NULL,          -- 'invoices','clients',...
    last_high_water TIMESTAMPTZ,                    -- max updated_at (or created_at) seen
    last_cursor     VARCHAR(500),                   -- opaque next-page cursor if API is cursor-paged
    last_run_at     TIMESTAMPTZ,
    last_status     VARCHAR(30)  NOT NULL DEFAULT 'never'
                        CHECK (last_status IN ('never','ok','partial','error','auth_error','skipped')),
    last_error      TEXT,
    rows_seen       INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_knowify_sync_state_tenant_entity UNIQUE (tenant_id, entity)
);
CREATE INDEX IF NOT EXISTS ix_knowify_sync_state_tenant ON knowify_sync_state (tenant_id);
```

### 1c. `knowify_raw_records` — generic lossless mirror

```sql
CREATE TABLE IF NOT EXISTS knowify_raw_records (
    id           SERIAL PRIMARY KEY,
    entity       VARCHAR(50)  NOT NULL,
    knowify_id   VARCHAR(100) NOT NULL,             -- the record's id in Knowify
    payload      JSONB        NOT NULL,
    content_hash VARCHAR(64)  NOT NULL,             -- sha256 of canonicalized payload
    high_water   TIMESTAMPTZ,                       -- record's updated_at (v2 incremental seed)
    is_present   BOOLEAN      NOT NULL DEFAULT TRUE, -- FALSE = absent from last full pull (deleted upstream)
    deleted_at   TIMESTAMPTZ,                        -- when tombstoned (§2a-bis)
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id    INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_knowify_raw_tenant_entity_id UNIQUE (tenant_id, entity, knowify_id)
);
CREATE INDEX IF NOT EXISTS ix_knowify_raw_tenant_entity ON knowify_raw_records (tenant_id, entity);
CREATE INDEX IF NOT EXISTS ix_knowify_raw_high_water    ON knowify_raw_records (tenant_id, entity, high_water);
```

### 1d. RLS block (verbatim pattern from 0030 lines 172-187)

```sql
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['knowify_sync_state','knowify_raw_records'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int) '
            'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int)', t);
    END LOOP;
END $$;
```

The existing `invoices`/`payments`/`jobs`/`customers` tables already carry this policy; adding
columns does not require re-declaring RLS.

**Dual-policy note (expected, NOT drift):** the ORM's `create_all` path also emits an
auto-generated `tenant_isolation_auto` policy alongside the migration's `tenant_isolation`. Two
policies coexisting on a table is the established repo state — `drift_check.sh` must treat this
as expected, not a diff. Match the existing tables' policy set exactly.

## 2. Sync job design — `jobs/knowify_sync.py`

Clones `jobs/ingest_worker.py` structure exactly:

- **Entry:** `python -m jobs.knowify_sync [entity ...]`. No arg → all entities.
- **Single-flight:** `_single_flight()` with a **distinct** advisory lock key (NOT 8274123 —
  use e.g. `8274124`) so it never contends with ingest. Session-scoped, PG-only, no-op on SQLite.
- **Exit code:** the job **exits non-zero** if any entity ends in `error`/`auth_error`, so Cloud
  Run marks the execution failed (this is what the alert policy §9 fires on). A clean run exits 0.
- **Log safety (PII):** error/log lines carry `entity + knowify_id + HTTP status` ONLY —
  **never the raw JSONB payload body** (it contains customer PII). Raw payloads live only in the
  DB (RLS-forced), never in logs.
- **Per-tenant:** `core.tenant_loop.for_each_tenant(SessionLocal, _fn)` — each tenant's session
  is stamped with its `app.tenant_id` GUC so RLS applies and raw records land in the right tenant.
- **Token access:** read tokens from Secret Manager `knowify-tokens` (JSON blob mirroring
  `tokens.json`: client_id, access_token, refresh_token, expires_in, scope). The container SA
  (`jobs-sa`) needs `roles/secretmanager.secretAccessor` **and** `secretVersionAdder` on
  `knowify-tokens` (to write the rotated refresh token back). Reuse the refresh logic from
  `scripts/knowify/knowify_pull.py` (`_refresh`, RFC-8707 `resource=API`, refresh+retry once).
- **Preflight token liveness:** each run first probes `GET /api/v2/valid` (200 = live token,
  401 = dead). On 401, attempt one refresh; if that fails, mark all entities `auth_error`, exit
  non-zero, and stop (no wasted per-entity 401s). Same probe backs `/knowify/status` and the
  keep-warm/reconnect check.
- **Fetch (v1 = full-pull + hash-gate):** reuse `knowify_pull.pull(entity, tok)` offset
  pagination, WITHOUT a `since=` filter, and add `ObjectState` to the query so voids/deletes
  surface for tombstoning (`GET /api/v2/<entity>?where[ObjectState][$in]=Active,Cancelled,Deleted`
  where the entity supports it). A full hash-gated pull per run is cheap at single-tenant volume
  and (unlike `since=`) catches deletes. Efficient variant: **`POST /api/v2/query`** batch fan-out
  runs all entity queries in ONE round-trip (the token holds the read meta-scope) — use it to
  collapse 24 requests into one per tick.
- **v2 optimization (CONFIRMED available, not aspirational):** `GET /api/v2/<entity>?since=<ISO>`
  natively returns records changed since a timestamp. The `knowify_sync_state.last_high_water`
  column is the real watermark for this. v1 does NOT use `since=` (it returns new/updated only,
  NOT deletes — full-pull is needed for tombstones), but the incremental path is de-risked: a v2
  optimization can pair a frequent `since=` delta pull with an occasional full ObjectState
  reconcile. Do not build v2 now.

### 2a. Watermark semantics (v1 records health only)

- v1 does NOT drive fetch from the watermark (full-pull). `knowify_sync_state` still records,
  per (tenant, entity): `last_run_at`, `last_status`, `last_error`, `rows_seen`, and
  `last_high_water = max(record.updated_at)` seen (recorded for observability + as the seed for
  v2). On any HTTP error → `'error'` (or `'auth_error'` for persistent 401); the next hourly run
  simply re-does the full pull (idempotent), so no windowed-retry logic is needed in v1.

### 2a-bis. Delete detection (tombstone-on-absence)

Required for the "system of record / eliminate the vendor" claim. Two signals, both from the
full pull:
1. **Explicit void/delete:** Knowify `ObjectState` (Active/Inactive/Cancelled/Deleted) and
   `Voided` ARE returned by REST when we query `where[ObjectState][$in]=Active,Cancelled,Deleted`.
   Cancelled/Deleted → mirror tombstone + first-class status `'voided'` (invoice) / excluded
   (payment). This is the primary, reliable delete signal.
2. **Absence fallback:** a row present in a prior pull but absent from the current full set (hard
   delete Knowify didn't surface) → tombstone by set-difference.

`knowify_raw_records` carries `is_present BOOLEAN NOT NULL DEFAULT TRUE` and `deleted_at
TIMESTAMPTZ`. On a **full** entity pass, after upserting the fetched set, mark
`ObjectState∈{Cancelled,Deleted}` rows AND any existing row whose `knowify_id` was absent as
`is_present=FALSE, deleted_at=NOW()` (once; re-runs no-op). Money rows (invoices/payments) are
NEVER hard-deleted — a voided/vanished invoice surfaces in `/knowify/status`, status flips to
`'voided'` via the ledger, but the row stays. `since=` incremental (v2) does NOT return deletes,
so the full ObjectState pull remains the delete path.

### 2b. Idempotency / hash-gating

- Raw layer: `content_hash = sha256(json.dumps(payload, sort_keys=True, separators=(',',':')))`.
  Upsert `ON CONFLICT (tenant_id, entity, knowify_id) DO UPDATE ... WHERE
  knowify_raw_records.content_hash IS DISTINCT FROM EXCLUDED.content_hash`. Unchanged records →
  zero writes (satisfies AC-2).
- First-class layer: upsert on the crosswalk unique index (§1a), hash-gated the same way so a
  no-op sync writes nothing to invoices/payments either.
- **Ledger event idempotency keys** (deterministic, so re-sync no-ops via `UNIQUE(tenant_id,
  idempotency_key)`, 0030:159):
  - issue → `knowify:issue:{tenant}:{knowify_invoice_id}`
  - payment → `knowify:payment:{tenant}:{knowify_payment_id}`
  - void → `knowify:void:{tenant}:{knowify_invoice_id}`

### 2c. Ledger synthesis on promotion (MONEY PATH — CRITICAL)

Invoice status is **derived**, never stored authoritatively: `core/invoicing.py
derive_invoice_status(events, total)` computes status from the `job_billing_events` ledger —
`paid` is summed ONLY from `payment_recorded` **events** (deduped by `idempotency_key`), NOT
from the `payments` table; an empty ledger derives `'draft'`. So writing an imported invoice's
columns is not enough — we must synthesize the ledger events the derive reads, or every imported
invoice shows `'draft'` regardless of real state.

**MONEY UNITS — DOLLARS (no ÷100 on the REST path).** The OpenAPI is explicit: REST
`GET /api/v2/invoices` returns `TotalAmount`/`OutstandingAmount`/`Credit`/… and
`GET /api/v2/payments` returns `Amount` **in dollars**. The sync uses REST, so it maps dollars
straight to `NUMERIC(12,2)` — **NO cents conversion, no ÷100** anywhere in the import mapping.
(The "cents/×1000" note applies only to the raw-DB/MCP layer we do NOT use; a stray ÷100 would
make every amount 100× too small.) Guardrail: AC-19 asserts an imported invoice's dollar amount
matches Knowify's display.

**Paid state comes from `OutstandingAmount` (dollars), not from summing Knowify payment rows.**
`paid = TotalAmount − OutstandingAmount`. We synthesize **ONE net `payment_recorded`** event of
that paid amount per invoice (not one-per-Knowify-payment) — simpler, and it makes invoice
status independent of whether the payments entity finished promoting. On promoting each invoice,
synthesize into `job_billing_events` (append-only, `source='knowify_import'`, deterministic keys
from §2b):

| Condition (from Knowify REST invoice) | Event | idempotency_key | payload |
|---|---|---|---|
| `BusinessState` != Draft (issued) | `invoice_issued` | `knowify:issue:{t}:{kiid}` | `{}` |
| `paid = Total − Outstanding > 0` | `payment_recorded` | `knowify:payment:{t}:{kiid}` | `{"amount": _money(paid_dollars)}` |
| `ObjectState` Cancelled/Deleted | `invoice_voided` | `knowify:void:{t}:{kiid}` | `{}` |

- Note the net-payment event is keyed by the **invoice** id (`knowify:payment:{t}:{kiid}`), since
  it is one aggregate net amount, not a per-Knowify-payment row. This keeps re-sync idempotent
  even as `OutstandingAmount` changes: a changed paid amount produces a *new* net value but the
  same key — so on re-sync it must **upsert** the net payment event's payload (not `DO NOTHING`)
  to reflect new payments. Implement as: delete-then-insert the single `knowify:payment:{t}:{kiid}`
  event inside the promotion txn when `paid` changed, else no-op. (This is the one place re-sync
  updates rather than no-ops; it is bounded to one row per invoice.)
- **Payload shape** matches the native path: `api/routes/invoices.py:299` writes
  `payload={"amount": amount}` with `amount = _money(body.amount)` (a `Decimal`); SQLAlchemy
  serializes it to JSONB and `derive_invoice_status._money()` re-parses (`core/invoicing.py:170`).
  Synthesize identically: `payload={"amount": _money(paid_dollars)}`.
- **Cache the derived status:** after synthesizing, set `invoices.status =
  derive_invoice_status(events_for(invoice), invoice.total)` — mirroring
  `api/routes/invoices.py:313`. Cross-check against `BusinessState` (Draft→draft, Outstanding→
  sent/partially_paid, Closed→paid) as a sanity assertion in tests. Ledger stays source of truth.
- **Idempotency:** `invoice_issued`/`invoice_voided` are `ON CONFLICT DO NOTHING` (immutable
  facts). The net `payment_recorded` is upsert-on-change (above). Paid totals never double
  because there is exactly one payment event per invoice, not one per Knowify payment (AC-15).
- **The `payments` entity is still first-classed** into our `payments` table (its own crosswalk,
  receivables only — §Payment mapping) for the payment *list* view, but it does NOT drive invoice
  status. Status is `OutstandingAmount`-derived. The two are reconciled by a test (sum of
  imported receivable payments ≈ paid_dollars) but the ledger uses the net figure as authoritative.
- **Rollback / recovery:** `job_billing_events` is append-only (no `updated_at`, no in-place
  edit). Recovery from a bad synthetic batch = delete-by-key-prefix
  `DELETE FROM job_billing_events WHERE tenant_id=:t AND idempotency_key LIKE 'knowify:%'` then
  re-run the sync. Document this as the only supported ledger-repair path for imported events.

### 2d. Intra-run ordering

Within one sync run, promote in FK-safe order: **clients → invoices → payments**.
`payments.invoice_id` is `NOT NULL REFERENCES invoices(id)` (0030:99), so a payment cannot be
inserted before its invoice exists. Items promote independently (no FK to the above). State this
ordering in `jobs/knowify_sync.py` (do not iterate the entity list in arbitrary order for the
first-class pass).

### 2e. Historical-invoice numbering (Knowify InvoiceNumber is a STRING)

- Knowify `InvoiceNumber` is a **user-facing STRING** (may be non-numeric / non-sequential), NOT
  our integer `invoice_number`. Imports store it in **`invoices.knowify_invoice_number` (TEXT)**
  and leave our integer `invoice_number = NULL`. Do NOT coerce the string into the integer
  counter; do NOT assume 18732 is a numeric max of these strings.
- The crosswalk key is Knowify `Id` (int) → `invoices.knowify_invoice_id`.
- The sync **never touches `tenant_invoice_counters`** — only the v2 `_issue_number` path writes
  it (confirmed). Imports carry `source='knowify_import'` with `invoice_number = NULL`, so they
  cannot collide with a future v2-issued integer (18733+).
- Guard test: assert `last_number` in `tenant_invoice_counters` is unchanged before/after a full
  import (AC-4). (18732 is re-confirmed at cutover per open-questions; the guard is that the sync
  never advances it, whatever its value.)

### 2f. Entity mapping (from Wave-0 OpenAPI/schema findings)

**Invoices** (`GET /api/v2/invoices` — regular only, **AIA skipped** per Jon; do NOT use
`/invoices/all`): `Id`→`knowify_invoice_id`; `InvoiceNumber`(str)→`knowify_invoice_number`;
`TotalAmount`(dollars)→`total`; `OutstandingAmount`(dollars)→net-paid math (§2c); `BusinessState`
(Draft/Outstanding/Closed) + `ObjectState` (Active/Cancelled/Deleted) → status/void; `ClientId`→
`customer_id` via `knowify_customer_id` crosswalk; `ProjectId`→`knowify_job_id` crosswalk.

**Payments** (`GET /api/v2/payments` — **receivables only**): filter `ReceivableId`/`InvoiceId`
NOT NULL; **EXCLUDE** vendor payables (`PayableId`/`VendorId` set), AIA (`isAIA=true` or
`InvoiceAIAId` set), `Voided=true`, and `ObjectState != Active`. Map: `Amount`(dollars)→`amount`
(NO ÷100); `isCreditCard=true`→`method='card'` else `CheckNumber`/`QBCheck` present→`'check'`
else `'other'`; `CheckNumber`→`reference`; `Memo`→`notes`; `PaymentDate`→`payment_date`;
`InvoiceId`→our invoice via crosswalk; `Id`→`knowify_payment_id`.

**AIA (`aia-invoices`):** optionally snapshot into `knowify_raw_records` for completeness, but
**no first-class import, no AC** (only 1 AIA invoice ever, 2023).

## 3. Token lifecycle + Secret Manager

- **Secret:** `google_secret_manager_secret "knowify_tokens" { secret_id = "knowify-tokens" }`
  (auto replication), mirroring the `internal-secret`/`db-password` pattern in `infra/main.tf`.
  The **value** is bootstrap-populated (not in TF/git) from the operator's local
  `~/.config/knowify/tokens.json` after a successful `knowify_oauth.py` login.
- **Rotate-on-refresh:** every access-token refresh that returns a new refresh token writes the
  full JSON blob back as a **new secret version** of `knowify-tokens`. Old versions are left for
  rollback; the job always reads `latest`.
- **Token-writer race — DECISION: SINGLE WRITER (v1).** Knowify refresh tokens are single-use:
  each refresh rotates (invalidates) the old refresh token. Two independent rotating writers
  (hourly sync + a nightly keep-warm) can interleave and write a *dead* (already-rotated)
  refresh token as `latest`, bricking auth until a human reconnects. **v1 has exactly ONE
  writer: the hourly 8am–6pm sync job, which refreshes-on-use.** No keep-warm job is deployed
  in v1.
  - Add a keep-warm writer ONLY IF Wave-0 measures the Knowify refresh-token **idle-expiry
    window < the overnight gap** (last run 18:00 → first run 08:00 = 14h). If it is, then AND
    ONLY then add `knowify-keepwarm`, and wrap **every** refresh+rotate+write (in BOTH jobs) in
    a shared Postgres advisory lock (distinct key `8274125`, held across read-refresh-write) so
    the sequence is atomic across processes and no writer can publish a stale token.
- **Keep-warm now EVIDENCE-BACKED, not hypothetical.** Wave-0's live probe found the stored
  refresh token **dead within <1 day** (401 auth-failed; refresh → 400 invalid_grant). So the
  refresh token lapses fast from disuse — the token lifecycle (keep-warm + Reconnect) is PROVEN
  load-bearing, not optional. But the single-writer safety still holds: **v1 keeps refresh-on-use
  in the hourly job**, and — because the hourly job only runs 08:00–18:00 — a keep-warm refresher
  covering the 14h overnight gap is expected to be required. Confirm the exact idle-TTL after
  re-login; if it is < 14h (likely), deploy `knowify-keepwarm` with BOTH writers sharing advisory
  lock `8274125` around refresh+rotate+write (atomic, no stale-token publish).
- **State machine (see DDD §token):** valid → (expiring/8-18 use) refresh(rotate-write) → valid;
  (overnight idle) keep-warm refresh → valid; (revoked/lapsed) dead → (human) Reconnect → valid.
- **Reconnect (PROVEN necessary):** `POST /knowify/reconnect` starts the interactive OAuth flow —
  required because a lapsed refresh token can only be recovered by a human re-login (exactly the
  Wave-0 situation Jon must resolve to unblock the live pull). Preferred: OAuth 2.0 **device-code**
  (browserless server). If Knowify's AS lacks device-code, host `GET /knowify/oauth/callback` on
  the API service and register that redirect URI with the DCR client. Resulting tokens →
  `knowify-tokens`.

## 4. Scheduler / Terraform resources (`infra/main.tf`)

Add `knowify-sync` to `local.job_names` (currently ingest/render/article/social) so it gets a
`google_cloud_run_v2_job` via the existing `for_each` (§470-512), plus `local.job_memory` and
`local.job_timeout` entries (`knowify-sync = "1Gi"`, `"1800s"`).

**v1 = ONE scheduler, ONE job** (single-writer decision, §3). Cloning `run_ingest` (§635-652,
OAuth-token → `<job>:run`):

```hcl
resource "google_cloud_scheduler_job" "knowify_sync" {
  name      = "knowify-sync"
  region    = var.region
  schedule  = "0 8-18 * * *"           # hourly 08:00–18:00 ET inclusive (11 runs/day)
  time_zone = "America/New_York"
  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/knowify-sync:run"
    http_method = "POST"
    oauth_token { service_account_email = google_service_account.scheduler_sa.email }
  }
  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}
```

**Keep-warm is NOT deployed in v1.** It is added only if Wave-0 measures the refresh-token
idle-expiry < the 14h overnight gap (§3). If required, it becomes a **second Cloud Run Job**
`knowify-keepwarm` in `local.job_names` whose deploy.sh `--args` is `python -m jobs.knowify_sync
--refresh-only`, with its own scheduler → `knowify-keepwarm:run` (no args) — and BOTH jobs then
share advisory lock `8274125` around refresh+write. (Documented for the contingency; not built now.)

Secret-injection: `deploy.sh --set-secrets` gains `KNOWIFY_TOKENS_SECRET=knowify-tokens:latest`.

**IAM (least-privilege — deliberate divergence).** The existing pattern grants roles
project-wide via `google_project_iam_member` (main.tf:235-238). For the token secret we scope
tighter: `secretAccessor` may reuse the broad pattern, but **`secretVersionAdder` is granted
resource-scoped** on `knowify-tokens` ONLY via `google_secret_manager_secret_iam_member` (member
= `jobs_sa`). Write access to a rotating credential must not be project-wide. Note this
divergence in the TF comment.

## 5. Read-only API routes (`/knowify/*`)

Follow existing FastAPI + `api.ts` conventions. All routes tenant-scoped (RLS via the request's
stamped session) and role-gated:

| Route | Method | Role | Purpose |
|---|---|---|---|
| `/knowify/status` | GET | `billing_manage` | per-entity sync health (from `knowify_sync_state`) |
| `/knowify/customers` `/invoices` `/payments` | GET | `billing_manage` | first-class mirror rows |
| `/knowify/raw/{entity}` | GET | `billing_manage` | paged raw records for any entity |
| `/knowify/sync-now` | POST | `knowify_admin` | trigger a bounded sync (single-flight) |
| `/knowify/reconnect` | POST | `knowify_admin` | start interactive OAuth |
| `/knowify/oauth/callback` | GET | (state-signed) | OAuth redirect landing (if not device-code) |

Authz roles reuse the existing role model (money entities behind `billing_manage`; a new
`knowify_admin` role for reconnect/trigger). RLS FORCED on every mirror table means even a role
bug cannot leak another tenant's rows.

## 6. Deploy / drift steps (R3/R4)

1. `git add` migration + job + TF + API + UI; commit (clean tree — `deploy.sh` refuses dirty).
2. **[HUMAN — Jon]** `gcloud auth login` / ADC, then apply migration 0032 in prod:
   `MIN_MIGRATION=0032 python scripts/apply_migrations_connector.py`.
3. `terraform apply` in `infra/` (adds secret container + 1 job + 1 scheduler + resource-scoped
   IAM + log-metric + alert-policy). [keep-warm job/scheduler only if Wave-0 requires it.]
4. **[HUMAN — Jon]** bootstrap-populate `knowify-tokens` secret from a fresh
   `knowify_oauth.py` login.
5. **[HUMAN — Jon]** `scripts/deploy.sh` (Cloud Build image → `gcloud run jobs update
   knowify-sync` with image/args/secrets + `gcloud run deploy api`).
6. `scripts/drift_check.sh` → terraform plan exit 0 + ansible check changed=0 (AC-6).

## 7. Prod-auth checkpoints (explicit HUMAN gates)

- **Migration apply (step 2):** needs Jon's gcloud/ADC — Cloud SQL Connector uses ADC.
- **Secret bootstrap (step 4):** needs Jon's local Knowify login to mint the first token pair.
- **Deploy (step 5):** needs Jon's gcloud auth.
- **Wave-0 status (RESOLVED by live recon 2026-07-11):** REST `/api/v2` is live and the stored
  DCR client is **scoped for every read** (invoices/clients/payments/… all 24) — entitlement is
  **verified-present, no longer a blocker, no Knowify-support ticket needed.** The actual gate is
  a **LIVE TOKEN**: the stored refresh token is DEAD (401 / invalid_grant). **[HUMAN — Jon]** must
  re-run `python scripts/knowify/knowify_oauth.py` (browser login) to mint fresh tokens.
- **This gates ONLY the live end-to-end pull + the AC-14..19 money assertions**, NOT the build.
  Migration 0032, the sync job, Secret-Manager tokens, keep-warm/Reconnect, API, UI, and the
  scheduler are all built and **fixture-tested now** against captured/sample payloads. Live
  cutover runs once Jon has re-authed.
- Still TODO on first live pull (record in open-questions): per-entity record counts + rate
  limits (full-pull cost sizing), and the refresh-token idle-TTL (sets keep-warm cadence).

## 8. Pre-mortem (DELIBERATE mode — 3 scenarios + mitigations)

1. **Refresh-token lapses and the sync silently stops** (PROVEN real — the stored token died
   within <1 day). Overnight idle (18:00→08:00 = 14h) lets the refresh token expire; next morning
   every entity 401s. → Mitigation: `/api/v2/valid` preflight + fail-loud `auth_error` + IaC
   alert (§9a); **keep-warm refresher** covering the overnight gap (evidence-backed, §3); UI
   **Reconnect** for the dead-token recovery a human must perform. Single-writer (or shared lock
   `8274125` if keep-warm is added) prevents a rotated-token race (AC-9).
2. **Money mapped in cents instead of dollars → every amount 100× too small** (silent money
   corruption). The raw-DB layer IS cents; the REST path we use is dollars. → Mitigation: **no
   ÷100 anywhere** in the mapping (§2c/§2f); AC-19 asserts an imported invoice's dollars match
   Knowify's display; opus + security review the money wave.
3. **Import advances the invoice counter** or a `knowify_invoice_number` string gets coerced into
   the integer `invoice_number`, colliding with a future v2-issued number. → Mitigation: string
   → `knowify_invoice_number TEXT`, integer `invoice_number = NULL` for imports, sync never
   touches `tenant_invoice_counters`; guard test asserts counter unchanged (AC-4).

## 9. Expanded test plan (DELIBERATE)

- **Unit (core ≥97%):** hash-gating (unchanged payload → no write); watermark advance/no-advance
  on error; counter-untouched invariant; token-refresh rotate-write; crosswalk upsert
  no-duplicate; RLS policy present on new tables (query `pg_policies`).
- **Integration (behavioral, new I/O — R1):** run `knowify_sync` against a **mocked** Knowify
  REST server (fixtures per entity) into a real Postgres (testcontainer/SQLite-PG shim) →
  assert raw rows, first-class rows, sync_state, idempotent re-run. Secret Manager read/write
  mocked.
- **E2e (staged, gated on a LIVE re-authed token, NOT entitlement):** after Jon re-runs
  `knowify_oauth.py`, one real read-only pull into a scratch schema; assert row counts match the
  pull summary; assert no writes to Knowify; `/api/v2/valid` returns 200.
- **Money-correctness (Wave-3 failing tests, AC-14..19):** imported PAID invoice derives
  `status='paid'` and paid == `invoice.total`; issued-but-unpaid derives `'sent'`; Cancelled/
  Deleted derives `'voided'`; full re-sync leaves `count(*) job_billing_events WHERE
  idempotency_key LIKE 'knowify:%'` unchanged and paid total not doubled; **AC-19: imported dollar
  amounts equal Knowify's displayed dollars (no ÷100)**; job exits non-zero on failure.
- **Observability:** each run logs per-entity `{rows_seen, status, high_water}` (NO payload
  bodies — PII); `/knowify/status` is the health surface.

### 9a. Alerting as IaC (R3 — NOT prose)

The silent-failure alert is Terraform in `infra/main.tf`, drift-clean:

- `google_logging_metric "knowify_sync_failures"` — counter on a log filter matching the job's
  `last_status='auth_error'` line OR the non-zero-exit execution-failed log.
- `google_monitoring_alert_policy "knowify_sync_stale"` — fires when the metric > 0 over the
  window, OR (stale-sync) when no successful `knowify-sync` execution logged in >24h.
- Notification channel: reuse the existing `alert_email` variable (`variables.tf:25`) →
  `google_monitoring_notification_channel` (email).
- **AC-18:** `scripts/drift_check.sh` reports no drift with the log-metric + alert-policy +
  channel present.
