STATUS: pending approval

# DDD — Knowify Data Mirror + Hourly Sync

Design / domain document. Pairs with the PRD and TRD of the same date.

---

## 1. Domain model

The mirror has **two layers** over one external source (Knowify, tenant 9258):

```
Knowify (external, read-only)
        │ pull (REST /api/v2, full-pull + hash-gate (v1); since= incremental is v2)
        ▼
┌───────────────────────────────────────────────────────────┐
│ RAW LAYER  — knowify_raw_records                           │
│   one row per (tenant, entity, knowify_id), payload JSONB  │
│   lossless snapshot of ALL 24 entities                     │
└───────────────────────────────────────────────────────────┘
        │ promote (map fields → columns)  ── first-class ──▶
        ▼
┌───────────────────────────────────────────────────────────┐
│ FIRST-CLASS LAYER — existing v2 tables                     │
│   clients  → Customer         (knowify_customer_id)        │
│   items    → PriceBookItem     (knowify_item_id)           │
│   invoices → Invoice           (knowify_invoice_id)        │
│   payments → Payment           (knowify_payment_id)        │
└───────────────────────────────────────────────────────────┘

CONTROL PLANE — knowify_sync_state (watermark, cursor, status per entity)
TOKEN PLANE   — Secret Manager knowify-tokens (state machine, §4)
```

## 2. Aggregate boundaries

- **RawRecord aggregate** (`knowify_raw_records`): the boundary is `(tenant_id, entity,
  knowify_id)`. It owns nothing else; it is an immutable-until-changed snapshot keyed by content
  hash. It never references first-class rows (no FK) — the crosswalk goes the other way.
- **First-class aggregates** are the *existing* v2 aggregates (Customer, Invoice+lines, Payment,
  PriceBookItem). The mirror only *feeds* them via the crosswalk column; it does not create new
  invariants inside them. Critically, **Invoice's money invariants (0030) stay owned by the v2
  billing code** — the mirror writes `source='knowify_import'` rows and does not touch invoice
  numbering or totals recomputation. It DOES synthesize a **namespaced** set of billing-events
  (keys `knowify:%`, `source='knowify_import'`) so imported invoices derive correct paid/voided
  status (§3a) — but the append-only-never-mutate invariant applies to NATIVE (`source='api'`)
  events only; the single imported net `payment_recorded` per invoice is upsert-on-change by
  design (§3a). Native billing events remain immutable.
- **SyncState aggregate** (`knowify_sync_state`): boundary `(tenant_id, entity)`. Owns the
  watermark/cursor/status. It is the only writer of "where are we" and the read model behind
  `/knowify/status`.

Boundary rule: **raw ↔ first-class is a one-way promotion**, never a two-way sync. Raw is the
source of truth for "what Knowify said"; first-class is the source of truth for "what v2 uses".
When they disagree, promotion re-derives first-class from raw; raw is never rewritten from
first-class.

## 3. Crosswalk + raw-record boundary

- **Crosswalk = a nullable `knowify_*_id` column on the first-class row.** Present ⇒ this v2 row
  originated from (or is linked to) a Knowify record. Absent ⇒ v2-native (e.g. an invoice issued
  in v2 after cutover). This is exactly the pattern already used by
  `Customer.knowify_customer_id` and `PriceBookItem.knowify_item_id`.
- **Raw record = the full JSONB.** Even for the 4 first-classed entities we still keep the raw
  row, because (a) first-class columns are lossy (we only map the fields we use) and (b) the raw
  row is the substrate for future promotions and for diffing when Knowify changes shape.
- The two are joined logically by `knowify_id`, never by a DB FK (raw has no lifecycle tie to
  first-class; deleting a promotion must not cascade to raw).

### 3a. Promotion is column-map **plus** ledger synthesis (money entities)

For invoices, promotion is NOT just column-copy. Invoice status is **derived** from the
append-only `job_billing_events` ledger (`core/invoicing.py derive_invoice_status`), and `paid`
is summed ONLY from `payment_recorded` **events** — never the `payments` table. So promoting a
paid Knowify invoice by writing columns alone would still derive `'draft'`.

**Money is dollars on the REST path** (OpenAPI-confirmed) — map straight to `NUMERIC(12,2)`, no
÷100. Paid comes from the invoice's own `OutstandingAmount`: `paid = TotalAmount − Outstanding`.
Promotion synthesizes the ledger events the derive reads (deterministic keys → idempotent):
`invoice_issued` (BusinessState != Draft), **one net** `payment_recorded {"amount":
_money(paid_dollars)}` keyed by the invoice id (not one-per-Knowify-payment), `invoice_voided`
(ObjectState Cancelled/Deleted), then caches `invoices.status`. The one net event keeps invoice
status independent of the payments-entity promotion and bounds re-sync to one upsert-on-change
row per invoice. The `payments` table is still populated (receivables only) for the list view but
does NOT drive status. Ledger — not the row — is the money source of truth (TRD §2c/§2f).

Ordering inside a run is FK-safe: **clients → invoices → payments** (`payments.invoice_id` is
NOT NULL, 0030:99).

## 4. Token state machine

```
        ┌─────────┐  access token near expiry / 401   ┌──────────┐
        │  VALID  │ ────────────────────────────────▶ │ REFRESH  │  (SINGLE writer = hourly job)
        └─────────┘                                    └──────────┘
             ▲                                              │ 200 (rotates refresh token)
             │                                              ▼   → write new version to Secret Mgr
             │                                         ┌─────────┐
             └─────────────────────────────────────── │  VALID  │
                                                       └─────────┘
             │ refresh fails: invalid_grant / revoked / scope change
             ▼
        ┌─────────┐   human clicks "Reconnect Knowify"  ┌──────────────┐
        │  DEAD   │ ──────────────────────────────────▶ │  RECONNECT   │
        └─────────┘   interactive OAuth (device-code /  │ (interactive)│
                       redirect) mints NEW token pair    └──────────────┘
                                                              │ writes new blob
                                                              ▼  to Secret Mgr → VALID
```

- **VALID → REFRESH → VALID:** on 401 or pre-expiry; refresh once, rotate-write, retry the call
  (mirrors `knowify_pull._get` refresh-once logic). **Refresh-on-use keeps the token warm** —
  the hourly job using the token IS the keep-warm.
- **KEEP-WARM (evidence-backed):** Wave-0 found the stored refresh token dead within <1 day, and
  the hourly job runs only 08:00–18:00 (14h overnight gap) — so an off-hours keep-warm refresher
  is expected to be required (cadence from the measured idle-TTL). To avoid a two-writer race that
  could publish a dead rotated token, EITHER keep one writer (refresh-on-use only) OR run both
  writers under shared advisory lock `8274125` so refresh+rotate+write is atomic across processes.
- **REFRESH → DEAD:** persistent `invalid_grant` / revoked token. The sync marks every entity
  `auth_error`, exits non-zero, and stops (fails loud, AC-12) — it does NOT keep burning the
  refresh token (the pull script already learned this: unbounded retry burned the token).
- **DEAD → RECONNECT → VALID:** only a human can recover a dead token (interactive login). This
  is why the UI Reconnect flow is a hard requirement, not a nice-to-have.

## 5. Failure / retry / backfill / partial-sync semantics

- **Per-entity isolation:** one entity's HTTP error does not abort the others (mirrors
  `ingest_worker`'s per-video try/except). Each entity's `knowify_sync_state` records its own
  status; `/knowify/status` shows a mixed picture (some `ok`, some `error`).
- **Retry:** v1 does a full pull every run, so a failed entity is simply re-pulled next tick; no
  windowed-retry logic and no retry queue (YAGNI) — the hourly cron *is* the retry loop.
- **Backfill:** every v1 run is a full pull (all pages), so there is no separate "first-run"
  special case; the first run and every run fetch the whole entity and hash-gate.
- **Delete detection (two signals):** (1) explicit — Knowify `ObjectState` Cancelled/Deleted
  (returned when the pull filters `where[ObjectState][$in]=Active,Cancelled,Deleted`) → tombstone
  + invoice status `'voided'`; (2) absence fallback — a `knowify_id` present before but absent now
  → tombstone by set-difference. Raw rows are never hard-deleted; money first-class rows are never
  auto-deleted (a voided/vanished invoice surfaces in `/knowify/status`). `since=` incremental (v2)
  does not return deletes, so the full ObjectState pull stays the delete path.
- **Partial sync:** if a run hits the job timeout mid-entity, the advisory lock releases on
  process exit and the next run re-pulls that entity from scratch. Idempotency (hash-gating +
  deterministic ledger keys) makes the redo cheap and safe. The tombstone set-difference is
  skipped for an entity that did not complete its full pull (avoids false tombstones).
- **Promotion backfill:** when a new entity is first-classed later, its promotion wave reads
  existing `knowify_raw_records` (already captured) and upserts into the new table — **no
  Knowify re-pull required**. This is the core payoff of the two-layer design.

## 6. Why this shape (design rationale)

- **Full-pull + hash-gate now, incremental later** beats "model 24 tables now": the raw layer
  captures every record (with ObjectState tombstones for deletes) while we only pay modeling cost
  for entities that earn a feature. v1 uses full-pull because it catches deletes; `since=`
  incremental IS confirmed available (Wave-0) but returns no deletes, so it is a v2 optimization
  (frequent `since=` delta + occasional full reconcile), not day-one work. `POST /api/v2/query`
  batch fan-out collapses 24 requests to one per tick (ponytail: cheap full pull now, de-risked
  incremental later — don't build it speculatively).
- **One-way promotion** keeps the money path safe: Invoice/Payment invariants stay owned by the
  audited 0030 billing code; the mirror is a feeder, not a co-owner.
- **Reuse over invention:** the sync job is a clone of `ingest_worker` (single-flight,
  per-tenant loop); token refresh is the `knowify_pull` logic; RLS/idempotency are the 0030/0031
  conventions. Almost no novel machinery — the novelty budget is spent only on the watermark and
  the Secret-Manager token rotation.
