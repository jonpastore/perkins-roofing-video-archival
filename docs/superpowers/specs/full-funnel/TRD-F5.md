# TRD-F5 — Marketing / KB Tenant-ization

**Wave:** F5 · **Status:** DRAFT (R2 fixes applied — pending Jon approval) · **Parallel-safe with:** F4
**Depends on:** F4 (RLS + GCIP; `get_db_session` dependency must exist before F5 jobs run)
**Grounding:** full-funnel-plan §3 (mechanics 5, 7, 10), §7 (Admin config tabs), §9 F5 row

---

## 1. Scope & non-goals

**In scope:**
- `for_each_tenant()` job wrapper — all cron jobs iterate active tenants, set tenant context, reset per-run cost counters
- Job catalog audit: classify each job as tenant-looped vs platform-level
- Per-tenant configs: `settings` JSONB on `tenants` table + Admin UI config tabs (KB, Marketing)
- Per-tenant social/API credentials in Secret Manager under `tenants/{id}/…` paths
- `OAuthStore` replacement: Secret Manager-backed real implementation (per-tenant key paths)
- Per-tenant usage metering: LLM tokens, STT minutes, render minutes on the structured-log path
- Brand kit: logo, colors, fonts, intro/outro GCS URIs, voice sample GCS URIs — stored in `tenants.settings` JSONB, consumed by render pipeline
- Wire Track A engines into Clip Studio UI + render job (jarvis #320)
- GCS per-tenant prefixes `tenants/{id}/…` (enforce on all new writes; migration plan for existing Perkins data)
- Offboarding: tenant delete = RLS-scoped cascade + GCS prefix delete + audit record

**Non-goals for this wave:**
- Tenant provisioning UI (F6)
- Per-tenant SSO (F6)
- Usage billing / invoicing (future)
- IG/TikTok OAuth (blocked on app review; scaffold stays)
- Track B/C/D/F engines wiring (Track A only per plan)

**Platform priority tiers for social distribution:**
- **Must (baseline):** YouTube, Facebook — credentials available, no app-review blocker.
- **Should (conditional):** Instagram, TikTok — blocked on Meta/TikTok app review (jarvis #315/#319). Any F5 claims that IG/TikTok publishing is "live" or "complete" must be downgraded to "scaffolded, pending app-review credential unblock." These platforms remain Should-tier until the blockers are resolved.
- **Should (cost-gated):** X (Twitter) — API access cost is a blocker; treat as Should-tier until Jon approves the spend. Do not implement X publishing in F5 without explicit authorization.

---

## 2. Data model changes

### 2.1 `tenants.settings` JSONB schema (enforced at app layer, not DB)

The `tenants` table already has a `settings JSONB DEFAULT '{}'` column (added in F0). F5 populates
and reads the following top-level keys. All keys are optional; missing keys use platform defaults.

```jsonc
{
  // Brand kit
  "brand": {
    "logo_gcs_uri":    "gs://…/tenants/1/brand/logo.png",
    "primary_color":   "#1a3c5e",          // hex
    "accent_color":    "#f4a226",
    "font_heading":    "Montserrat",
    "font_body":       "Open Sans",
    "intro_gcs_uri":   "gs://…/tenants/1/brand/intro.mp4",
    "outro_gcs_uri":   "gs://…/tenants/1/brand/outro.mp4",
    "voice_sample_gcs_uri": "gs://…/tenants/1/brand/voice.wav"
  },
  // Knowledge Base admin
  "kb": {
    "ingest_enabled":       true,
    "abstain_threshold":    0.35,           // cosine distance floor for /ask
    "faq_policy":           "auto",         // "auto" | "manual"
    "channel_sources":      ["UCxxxxxxxx"]  // YouTube channel IDs
  },
  // Marketing admin
  "marketing": {
    "caption_prompt_version": "v5",
    "publish_cadence_days":   7,
    "seed_pct":               0.20,
    "social_accounts": {
      "instagram": {"account_id": "…"},
      "tiktok":    {"account_id": "…"}
    },
    "safety_denylist": ["competitor_name"],
    "royalty_free_music_catalog": "pixabay"  // "pixabay" | "ytaudio" | "fma"
  }
}
```

Validation: a Pydantic model `TenantSettings` in `core/tenant_settings.py` validates the JSONB on read. **TRD-F0 owns the canonical `tenants.settings` schema; F5's `TenantSettings` model is the authoritative Pydantic representation of that schema and must include all registered keys across waves.**

Key requirements for `TenantSettings`:

1. **Must include F3 quoting keys** at the top level (not nested under `brand`/`kb`/`marketing`):
   ```python
   deposit: DepositPolicy | None = None          # F3 — see TRD-F3 §3.8
   reminder_cadence_days: list[int] = [3, 7, 14] # F3
   license_number: str | None = None             # F3
   ```
2. **`model_config = ConfigDict(extra="allow")`** — unknown keys are preserved on read and round-tripped on write without being dropped. This ensures future waves can add settings keys without requiring a `TenantSettings` update first.
3. **No silent fallback for structural errors:** wrong-type values (e.g. `deposit.mode = 123` instead of a string) raise a `ValidationError` that is surfaced to the Admin UI as an explicit error response (HTTP 422 with a human-readable message). Silent fallback to defaults is prohibited — it masks data corruption.
4. **Settings-preservation red test:**
   ```python
   def test_f3_settings_keys_preserved_through_f5_admin_model():
       """Write tenants.settings with F3 keys via TenantSettings; read back via Admin settings
       endpoint; confirm deposit/reminder_cadence_days/license_number are unchanged."""
   ```

### 2.2 New table: `tenant_offboard_log`

```sql
CREATE TABLE tenant_offboard_log (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL,   -- not FK; tenant row may be deleted
    offboarded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    offboarded_by TEXT NOT NULL,      -- platform_admin email
    gcs_prefix    TEXT NOT NULL,      -- "tenants/{id}/" — for audit
    row_counts    JSONB NOT NULL,     -- {"videos": 832, "chunks": 12400, ...}
    status        TEXT NOT NULL DEFAULT 'pending'  -- pending | complete | failed
);
```

This is a **platform-level table** (no `tenant_id` FK, no RLS). It is exempt from the
tenant isolation policy.

### 2.3 Existing Perkins data migration (GCS prefix)

Current Perkins videos and assets are at the bucket root (e.g. `videos/abc123/…`).
F5 adds the logical prefix `tenants/1/` at the **application layer** for new writes only.
Existing objects are NOT moved in F5 (move is expensive and risky). Instead:

- `core/gcs_path.py` (new): `tenant_prefix(tenant_id) → "tenants/{tenant_id}/"`. For
  tenant 1, the function checks the object's existing path and falls back to the legacy
  root if the tenanted path is not found. This backward-compat shim is removed in a
  future cleanup wave after a bulk copy job is run (tracked as a separate task).
- New licensee tenants write directly to `tenants/{id}/…` with no legacy shim.

---

## 3. Job tenant-loop mechanics

### 3.1 `for_each_tenant()` wrapper

Location: `core/tenant_loop.py` (new, 100%-coverable pure logic)

```python
from __future__ import annotations
from typing import Callable, Iterator
from sqlalchemy.orm import Session
from app.models import Tenant  # F0 model


def active_tenants(db: Session) -> list[int]:
    """Return tenant IDs for all tenants with status='active'.
    Platform-level query; runs without tenant context (no RLS on tenants table)."""
    rows = db.execute(
        text("SELECT id FROM tenants WHERE status = 'active' ORDER BY id")
    ).fetchall()
    return [r[0] for r in rows]


def for_each_tenant(db_factory: Callable[[], Session], fn: Callable[[Session, int], None]) -> None:
    """Iterate active tenants; call fn(db, tenant_id) for each.

    Guarantees:
    - fn receives a fresh DB session scoped to tenant_id (SET LOCAL fires via after_begin).
    - Exceptions in fn are caught, logged, and do not abort the loop for remaining tenants.
    - Per-tenant cost counters are reset before fn is called (see §3.2).
    """
    # Use a platform-level session (no tenant_id) for the tenants query only
    with db_factory() as platform_db:
        tenant_ids = active_tenants(platform_db)

    for tid in tenant_ids:
        db = db_factory()
        db.info["tenant_id"] = tid
        try:
            _reset_cost_counters(db, tid)
            fn(db, tid)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("for_each_tenant: tenant %d failed: %s", tid, exc, extra={"tenant_id": tid})
        finally:
            db.close()
```

### 3.2 Per-tenant cost counter reset

Each job run resets an in-process cost accumulator for the tenant before work begins.
The accumulator is a `contextvars.ContextVar` dict (see §5 for the `core/cost_tracker.py` design — `threading.local()` is explicitly rejected as wrong for Cloud Run Jobs).
At the end of each tenant's work, the accumulated totals are emitted as structured log
events (see §5). This is the "record now, bill later" pattern.

### 3.3 Job catalog classification

| Job | Classification | Rationale |
|---|---|---|
| `crawl_comments.py` | **tenant-looped** | comment drafts are tenant-scoped |
| `distribute_job.py` | **tenant-looped** | posts per platform account per tenant |
| `render_job.py` | **tenant-looped** | brand kit + GCS prefix are per-tenant |
| `social_job.py` | **tenant-looped** | social accounts are per-tenant |
| `article_job.py` | **tenant-looped** | articles are tenant-scoped |
| `publish_job.py` | **tenant-looped** | publish planner is per-tenant corpus |
| `propose_series_job.py` | **tenant-looped** | mini_series per tenant |
| `propose_topic_series.py` | **tenant-looped** | topic selection per corpus |
| `promote_job.py` | **tenant-looped** | promotion targets per tenant |
| `aggregate_topics.py` | **tenant-looped** | per-corpus aggregation |
| `embed_job.py` | **tenant-looped** | chunks are per-tenant |
| `ingest_worker.py` | **tenant-looped** | ingestion runs are per-tenant |
| `consolidate_faqs.py` | **tenant-looped** | FAQ entries are per-tenant |
| `archive_job.py` | **tenant-looped** | GCS archive per-tenant prefix |
| `backfill_archive.py` | **tenant-looped** | per-tenant channel sources |
| `backfill_metadata.py` | **tenant-looped** | per-tenant videos |
| `poll_archive_kpis.py` | **tenant-looped** | per-tenant videos |
| `enumerate_channel.py` | **tenant-looped** | per-tenant channel sources from settings |
| `prime_backlog.py` | **tenant-looped** | per-tenant content backlog |
| `regen_articles_seo.py` | **tenant-looped** | tenant-scoped articles |
| `regen_stub_articles.py` | **tenant-looped** | tenant-scoped |
| `reprocess_articles.py` | **tenant-looped** | tenant-scoped |
| `upgrade_articles.py` | **tenant-looped** | tenant-scoped |
| `avatar_job.py` | **tenant-looped** | per-tenant avatar config |
| `whisper_asr.py` | **platform-level** | audio transcription service; files fetched per-job by tenant context |

**Refactor pattern for existing jobs** (illustrative, using `crawl_comments.py`):

```python
# Before (single-tenant, implicit):
def main():
    db = SessionLocal()
    # ... operates on all videos without tenant filter

# After (tenant-looped):
def _run_for_tenant(db: Session, tenant_id: int) -> None:
    # ... same logic; db session already has tenant_id set via after_begin event
    # ... all queries automatically filtered by RLS + ORM filter

def main():
    from core.tenant_loop import for_each_tenant
    for_each_tenant(SessionLocal, _run_for_tenant)
```

The existing job logic moves verbatim into `_run_for_tenant()`. No query changes needed —
RLS + ORM filter handle the scoping automatically.

---

## 4. Per-tenant credentials (Secret Manager)

### 4.1 Secret naming convention

All per-tenant secrets follow the path pattern:
```
tenants/{tenant_id}/{platform}/{key}
```

Examples:
```
tenants/1/youtube/api_key
tenants/1/instagram/access_token
tenants/1/instagram/refresh_token
tenants/1/tiktok/access_token
tenants/2/youtube/api_key
```

Platform-level secrets (not tenant-scoped) keep existing names (e.g. `google-idp-client-secret`).

### 4.2 `OAuthStore` → Secret Manager implementation

Replace `adapters/distribution/oauth_store.py` in-memory singleton with a real
Secret Manager-backed implementation. The interface (`put`, `get`, `access_token`, `refresh`)
stays identical; the implementation changes.

```python
class SecretManagerOAuthStore:
    """Production OAuth token store backed by GCP Secret Manager.

    Secret paths: tenants/{tenant_id}/{platform}/{key}
    Thread-safe: Secret Manager is the source of truth; no shared in-process state.
    """

    def __init__(self, tenant_id: int, sm_client=None):
        self._tenant_id = tenant_id
        self._client = sm_client or secretmanager.SecretManagerServiceClient()
        self._project = settings.GCP_PROJECT

    def _secret_name(self, platform: str, key: str) -> str:
        return (f"projects/{self._project}/secrets/"
                f"tenants-{self._tenant_id}-{platform}-{key}/versions/latest")

    def access_token(self, platform: str, account_id: str) -> str:
        return self._access_secret(platform, "access_token")

    # ... put() creates/updates secret versions; get() reads + checks expires_at
```

The existing in-memory `OAuthStore` is retained as the `MockOAuthStore` for tests
(no live Secret Manager calls in unit tests).

### 4.3 Terraform: Secret Manager IAM for per-tenant secrets

The existing `roles/secretmanager.secretAccessor` IAM binding on the API run SA and jobs SA
covers all secrets in the project. No new IAM bindings needed.

New secrets are created at tenant provisioning time (F6 UI calls `secretmanager.create_secret`
via the Admin SDK). Terraform does not own individual tenant secrets (they are runtime data).

---

## 5. Usage metering

Per-tenant counters emitted on the existing GCP Cloud Logging structured path
(`adapters/gcp_logging.py`). Three metric types:

| Metric | Unit | Emitted by |
|---|---|---|
| `llm_tokens` | integer (prompt + completion) | `app/llm.py` `chat()` wrapper |
| `stt_minutes` | float | `adapters/stt.py` after transcription |
| `render_minutes` | float | `jobs/render_job.py` after render complete |

Log payload (added to every existing structured log record when `tenant_id` is set):

```json
{
  "severity": "INFO",
  "tenant_id": 1,
  "metric": "llm_tokens",
  "value": 1247,
  "model": "gemini-1.5-flash",
  "job": "article_job",
  "timestamp": "2026-07-08T14:23:01Z"
}
```

The `tenant_id` logging filter (added in F4) ensures every record already carries the tenant.
F5 adds the `metric`/`value` fields in the relevant adapters. No new GCP log sink needed in F5;
a BigQuery export for billing analytics is a future wave.

### 5.1 Per-tenant soft caps

Each tenant may have a per-month soft cap configured for each metered resource. Cap thresholds are stored as settings keys registered in TRD-F0's `tenants.settings` envelope:

```jsonc
{
  "metering_caps": {
    "llm_tokens_per_month":    5000000,   // integer; null = unlimited
    "stt_minutes_per_month":   500.0,     // float; null = unlimited
    "render_minutes_per_month": 120.0     // float; null = unlimited
  }
}
```

**Enforcement in `for_each_tenant()`:** before calling `fn(db, tenant_id)`, check the month-to-date counter totals (queried from the structured log aggregate or a per-tenant DB counter row) against the configured caps. If a cap is exceeded for a tenant:

- Skip that tenant's job run for this cycle.
- Emit a structured log alert: `{"severity": "WARNING", "tenant_id": tid, "event": "metering_cap_exceeded", "metric": "...", "cap": ..., "current": ...}`.
- Do NOT raise an exception that would abort the loop for other tenants.

**Deferral option (owner sign-off required):** if implementing the cap-check in F5 is judged out of scope after reviewing the full F5 workload, the counters (§5 above) MUST still be implemented in F5 as specified — they are the prerequisite for any future cap enforcement. The cap check itself may be deferred to a named post-F5 wave, but this deferral requires explicit sign-off from Jon and must be tracked as a jarvis task before F5 exits. Silent omission of both counters and caps is not acceptable.

Cost counter accumulator in `core/cost_tracker.py` (new, pure logic):

**Design note:** `threading.local()` is wrong for Cloud Run Jobs, which execute as separate processes (one process per job invocation). `threading.local()` is also not context-safe for async code. Use `contextvars.ContextVar` instead — it is correct for both threaded and async execution contexts, and each Cloud Run Job process gets a clean context automatically.

```python
from contextvars import ContextVar
from typing import Any

_counters: ContextVar[dict[str, Any]] = ContextVar("cost_counters", default={})

def reset(tenant_id: int) -> None:
    _counters.set({"tenant_id": tenant_id, "llm_tokens": 0,
                   "stt_minutes": 0.0, "render_minutes": 0.0})

def add(metric: str, value: float | int) -> None:
    c = _counters.get()
    if not c:
        return  # outside a tenant loop context; no-op
    _counters.set({**c, metric: c.get(metric, 0) + value})

def flush() -> dict:
    """Return current counters and reset. Called at end of each tenant's job run."""
    c = _counters.get()
    _counters.set({})
    return c
```

The `for_each_tenant()` loop calls `reset()` before each tenant's `fn()` and `flush()` after. Because each tenant's work runs synchronously in sequence within a single process invocation (not concurrently), `ContextVar` isolation is correct — there is no cross-tenant counter leakage.

---

## 6. Brand kit

### 6.1 Storage

Brand assets stored in GCS under `tenants/{id}/brand/`:
```
tenants/1/brand/logo.png
tenants/1/brand/intro.mp4
tenants/1/brand/outro.mp4
tenants/1/brand/voice.wav
```

GCS URIs stored in `tenants.settings["brand"]` JSONB (§2.1). Upload via the Admin →
Marketing config tab (pre-signed upload URLs issued by the API; never streamed through
Cloud Run).

### 6.2 Render pipeline integration

`jobs/render_job.py` currently reads intro/outro from platform config. F5 changes the
lookup to:

```python
tenant_settings = TenantSettings.from_db(db, tenant_id)
brand = tenant_settings.brand
intro_uri = brand.intro_gcs_uri or settings.DEFAULT_INTRO_GCS_URI
outro_uri  = brand.outro_gcs_uri or settings.DEFAULT_OUTRO_GCS_URI
```

Platform defaults (existing Perkins assets) remain as fallbacks so existing render jobs
continue working before tenant brand kits are uploaded.

Font and color settings are passed into the caption overlay and title-card render steps.

---

## 7. Track A engines → Clip Studio UI

### 7.1 Engine inventory (all exist in `core/`)

| Module | Function | UI control needed |
|---|---|---|
| `core/clip_select.py` | Select best clip windows from a video | clip selector slider / approval |
| `core/reframe.py` | Reframe 16:9 → 9:16 (vertical crop) | reframe preview |
| `core/captions.py` | Burn-in captions from transcript | caption style selector |
| `core/speech_cleanup.py` | Remove filler words, silences | toggle on/off |
| `core/broll.py` | Insert B-roll segments | B-roll source selector |
| `core/music_mix.py` | Background music mix | music catalog picker + volume |
| `core/clip_fx.py` | Transitions, color grade, text overlays | FX preset selector |

### 7.2 Data model: `render_spec` on `mini_series`

**SUPERSEDED (2026-07-09):** the #320 carry-over (commit `c0a12c9`) already stores
`render_spec` inside the existing `parts_json` JSON column as an envelope
(`core/render_spec.py`; read live in `jobs/render_job.py`). Migration 0019 does
**not** add a `render_spec` column — a second store would be dead code. The
envelope is the single source of truth. (Original plan, no longer applied:
`ALTER TABLE mini_series ADD COLUMN render_spec JSONB DEFAULT '{}';`)

`render_spec` captures UI selections:
```jsonc
{
  "reframe":         true,
  "captions":        {"style": "bold_bottom", "font": "Montserrat"},
  "speech_cleanup":  true,
  "broll":           {"source": "pexels", "query_auto": true},
  "music":           {"catalog": "pixabay", "track_id": "upbeat-001", "volume_db": -18},
  "fx":              {"transition": "cut", "color_grade": "vivid", "title_card": true}
}
```

### 7.3 Clip Studio UI → render_spec → render_job

Flow:
1. User opens Clip Studio for a `mini_series` row
2. UI shows per-engine controls (§7.1) backed by the `render_spec` JSONB
3. User adjusts controls → `PUT /series/{id}/render_spec` (new endpoint, `approve_video` action)
4. User clicks "Render" → `POST /series/{id}/render` → enqueues `render_job` with `render_spec`
5. `render_job` reads `render_spec` and calls each Track A engine in sequence:
   `clip_select → reframe → speech_cleanup → broll → music_mix → captions → clip_fx`
6. Output MP4 written to `tenants/{tenant_id}/renders/{series_id}/output.mp4`
7. `SocialPost` rows seeded for distribution (existing behavior)

### 7.4 New API endpoints

```
PUT  /series/{id}/render_spec          # save UI selections (approve_video role)
POST /series/{id}/render               # trigger render job (approve_video role)
GET  /series/{id}/render_status        # poll render status (any authenticated)
```

---

## 8. GCS per-tenant prefixes

All new GCS writes in F5+ use `core/gcs_path.py`:

```python
def tenant_object_path(tenant_id: int, relative_path: str) -> str:
    """Return the full GCS object path for a tenant-scoped asset.
    For tenant 1, falls back to the legacy root path if the tenanted path
    does not exist (backward-compat shim; removed in cleanup wave).
    """
    return f"tenants/{tenant_id}/{relative_path}"
```

Enforce: all `gcs_client.upload()` / `gcs_client.download()` calls in adapters must
go through `tenant_object_path()`. CI grep gate (same pattern as raw SQL gate):
```
grep -rn "bucket.blob\|storage_client.bucket" adapters/ jobs/ | grep -v "tenant_object_path"
```
Any hit fails CI.

---

## 9. Offboarding

Triggered by `DELETE /internal/tenants/{tenant_id}` (platform_admin only; F6 UI calls this).
Implemented in F5 as a callable function; the UI endpoint is wired in F6.

```python
def offboard_tenant(tenant_id: int, platform_admin_email: str, db: Session, gcs_client) -> None:
    """Offboard a tenant. Steps:
    1. Verify tenant exists and is not tenant 1 (Perkins; protected).
    2. Collect row counts per table for audit.
    3. INSERT tenant_offboard_log (status='pending').
    4. SET LOCAL app.tenant_id = tenant_id; DELETE cascade on all tenant-scoped tables.
       (RLS is active; the DELETE is automatically scoped to the tenant.)
    5. Delete GCS prefix tenants/{tenant_id}/ (list + delete all objects).
    6. Delete GCIP tenant via Admin SDK (F6 wires this; stub in F5).
    7. UPDATE tenant_offboard_log status='complete'.
    8. UPDATE tenants SET status='offboarded'.
    Note: tenant row is retained for audit; the DB cascade removes data rows only.
    """
```

---

## 10. Admin UI config tabs

Two new Admin config tabs (Marketing and KB) backed by:

```
GET  /admin/tenant/settings            # read full TenantSettings (admin role)
PUT  /admin/tenant/settings/kb         # update KB section (admin role)
PUT  /admin/tenant/settings/marketing  # update Marketing section (admin role)
POST /admin/tenant/brand/upload-url    # get pre-signed GCS upload URL for brand asset
```

The Estimating and Quoting tabs (already specced in F2/F3) follow the same pattern.

---

## 11. Migrations

File: `infra/migrations/0019_f5_tenant_settings.sql`

**Important:** must be `.sql` — `scripts/apply_migrations_connector.py` globs `*.sql` only. A `.py` file would be silently skipped.

**Ownership note:** `tenant_offboard_log` is owned by F4's migration 0018 (see TRD-F4 §8). Step 2 below is an idempotent reference check, not a creation — if 0018 ran first (correct order), the table already exists and this step is a no-op.

1. Add `render_spec JSONB DEFAULT '{}'` column to `mini_series` (idempotent: `ADD COLUMN IF NOT EXISTS`)
2. `CREATE TABLE IF NOT EXISTS tenant_offboard_log` — idempotent no-op if 0018 already ran; F4 is the authoritative owner
3. Seed `tenants.settings` for tenant 1 with brand defaults from current `PlatformConfig` keys
   (intro_uri, outro_uri from existing config, if present)

---

## 12. TEST PLAN

Tests written first; each must be red before implementation.

### Unit tests (`tests/test_tenant_loop.py`)

```
test_for_each_tenant_iterates_active_only()
    — tenants with status='inactive' are skipped

test_for_each_tenant_exception_does_not_abort_loop()
    — fn raises for tenant 2; tenant 3 still runs

test_for_each_tenant_sets_tenant_context()
    — captured session.info["tenant_id"] matches the tenant being processed

test_cost_tracker_reset_clears_counters()
test_cost_tracker_add_accumulates()
test_cost_tracker_flush_returns_and_resets()
```

### Unit tests (`tests/test_tenant_settings.py`)

```
test_tenant_settings_defaults_for_missing_keys()
test_tenant_settings_validates_color_format()
test_tenant_settings_invalid_structure_uses_defaults()
test_gcs_path_tenant_prefix()
test_gcs_path_tenant1_legacy_fallback()
```

### Unit tests (`tests/test_render_spec.py`)

```
test_render_spec_roundtrip()
test_render_job_reads_render_spec_engines()
test_clip_studio_api_saves_render_spec()
test_render_job_defaults_when_render_spec_empty()
```

### Integration / behavioral tests

```
test_job_tenant_loop_publishes_only_to_own_corpus()
    — two tenants with separate videos; crawl_comments loop produces drafts only for each
      tenant's own videos

test_brand_kit_applied_in_render()
    — tenant with custom intro/outro URI produces render output with those segments

test_track_a_engine_sequence_in_render_job()
    — render_job with full render_spec calls all 7 engines in correct order

test_offboard_deletes_all_tenant_data()
    — post-offboard: all tenant-scoped tables return 0 rows for that tenant_id;
      tenant_offboard_log has status='complete'

test_offboard_blocks_tenant_1()
    — offboard_tenant(1, ...) raises ProtectedTenantError

test_usage_metering_emits_log_event()
    — after article_job run, structured log contains metric=llm_tokens, tenant_id correct
```

### CI grep gates (add to existing gate test)

```python
# No GCS blob access outside gcs_path utility
def test_no_direct_gcs_blob_outside_utility():
    ...  # same pattern as raw SQL gate; grep adapters/ jobs/
```

---

## 13. Implementation steps

1. Write all tests in §12 → confirm red for correct reasons
2. `core/tenant_loop.py` — `active_tenants()` + `for_each_tenant()`
3. `core/cost_tracker.py` — cost counter with `reset()`/`add()`/`flush()`
4. `core/tenant_settings.py` — Pydantic `TenantSettings` + `from_db()` loader
5. `core/gcs_path.py` — `tenant_object_path()` + legacy shim for tenant 1
6. Refactor all tenant-looped jobs (§3.3) to use `for_each_tenant()` wrapper
7. Replace `OAuthStore` in-memory singleton with `SecretManagerOAuthStore`; retain mock for tests
8. Extend `adapters/gcp_logging.py` and `app/llm.py` / `adapters/stt.py` with cost metric emission
9. Add `render_spec` column to `mini_series` (migration `0019`)
10. Update `jobs/render_job.py` to read `render_spec` + brand kit; call Track A engines in sequence
11. Add Clip Studio API endpoints (`PUT /series/{id}/render_spec`, `POST /series/{id}/render`, `GET /series/{id}/render_status`)
12. Add Admin settings endpoints + pre-signed upload URL endpoint
13. `offboard_tenant()` function in `core/offboard.py`
14. Migration `0019_f5_tenant_settings.sql` — run with Jon's permission (must be `.sql`)
15. `scripts/drift_check.sh` → no drift (R4)
16. R2 review: architect + critic agents

---

## 14. Exit gate

- [ ] `for_each_tenant()` tests green (all jobs iterate active tenants, tenant context set correctly)
- [ ] Test tenant (tenant 2) publishes to its own corpus without touching tenant 1 data
- [ ] Clips render with brand kit (intro/outro/font/color) + Track A engines (transitions/music/text)
- [ ] Cost metering: structured log events contain `tenant_id` + `metric` + `value`
- [ ] Offboard test: all tenant data deleted, GCS prefix removed, log complete
- [ ] CI GCS blob grep gate clean
- [ ] `pytest --cov=core --cov-fail-under=97` green (R1)
- [ ] `scripts/drift_check.sh` no drift (R4)
- [ ] R2 architect + critic sign-off

---

## 15. Rollout / rollback

**Rollout:**
- Migration `0019` is additive (new column, new table, settings seed); safe to apply with app running
- Job refactor is backward-safe: existing single-tenant behavior is preserved for tenant 1
- Track A engine wiring: `render_spec` defaults to `{}` → existing render behavior unchanged
- `OAuthStore` swap: the in-process mock is replaced; behavior for existing (uncredentialed) platforms is identical (KeyError on access_token remains)

**Rollback:**
- Jobs: revert the `for_each_tenant()` wrapper; single-tenant function bodies are unchanged
- `render_spec`: column stays (no data loss); render_job falls back to empty spec
- `OAuthStore`: swap back to in-memory singleton; no prod state lost (Secret Manager secrets remain)

---

## 16. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Job fails for one tenant and silently stops others | Low | `for_each_tenant` catches per-tenant exceptions; loop continues |
| Legacy GCS paths (tenant 1) break after prefix change | Medium | Backward-compat shim in `gcs_path.py`; shim tested explicitly |
| Track A engine sequence produces bad output | Low | Each engine independently unit-tested; behavioral test in render pipeline |
| Secret Manager API rate limits under many concurrent tenants | Low | Single-tenant Secret Manager reads per job run; not concurrent |
| Cost counter isolation between tenants | Low | `contextvars.ContextVar` used (not `threading.local`); `reset()` called before each tenant in `for_each_tenant`; flush tested |

---

## 17. Unresolved questions

1. **Track A engine call signatures**: confirm `reframe`, `broll`, `music_mix`, `clip_fx` all accept a `render_spec` dict or individual kwargs — check actual function signatures in `core/` before writing render_job integration.
2. **Pre-signed upload URL IAM**: which service account issues the signed URLs for brand asset uploads? The API run SA needs `roles/storage.objectCreator` scoped to the `tenants/{id}/brand/` prefix — verify current bucket IAM grants.
3. **Test tenant provisioning in CI**: how is the second tenant (tenant 2) created in CI for the isolation tests? F5 tests need a fixture that creates a tenant row + test data. This fixture should be shared with F4's denial test fixtures to avoid duplication.
4. **`whisper_asr.py` is platform-level**: it receives per-tenant audio file references from the job that calls it. Confirm the audio fetch path correctly uses `tenant_object_path()` when called from a tenant-looped job.
