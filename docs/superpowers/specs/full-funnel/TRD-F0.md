# TRD-F0 — Thin Tenancy

**Wave:** F0  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Date:** 2026-07-08  
**Estimate:** 0.5 sessions  
**Depends on:** nothing (first wave)  
**Blocks:** F1 (IA reorg), F2 (Estimating), all subsequent waves  

---

## 1. Scope & non-goals

### In scope
- `tenants` table — create, seed Perkins = tenant 1
- `tenant_id INT NOT NULL DEFAULT 1 REFERENCES tenants(id)` added to every tenant-scoped table
- ORM `TenantMixin` base class with the seam F4's `SET LOCAL` pattern will plug into
- Backfill all existing rows to `tenant_id = 1`
- Composite indexes on the hottest query patterns
- Migration `0013_thin_tenancy.sql` (idempotent)
- Rule: every future table is born with `tenant_id` — documented in `docs/ENGINEERING_RULES.md`
- Full test suite green; Perkins behavior 100% unchanged

### Non-goals (explicitly deferred)
- Row-Level Security policies → F4
- `SET LOCAL app.tenant_id` session pattern (written as a stub here so F4 doesn't rework it) → F4 activates it
- GCIP / Firebase Identity Platform upgrade → F4
- `platform_admin` role → F4
- `for_each_tenant()` job wrapper → F5
- Per-tenant GCS prefixes / Secret Manager paths → F5
- Multi-tenant UI of any kind → F6

---

## 2. Table classification

### 2a. Tenant-scoped tables (receive `tenant_id`)

Derived from full enumeration of `app/models.py` at commit `b19b34b`:

| Table | Model | Justification |
|---|---|---|
| `videos` | `Video` | channel content is per-tenant |
| `ingestion_runs` | `IngestionRun` | tracks per-video ingest; video is tenant-scoped |
| `segments` | `Segment` | transcript data per video |
| `words` | `Word` | word-timing data per video |
| `content_graph` | `GraphNode` | extracted topics/claims per video |
| `chunks` | `Chunk` | pgvector embeddings per video; tenant-isolated for search |
| `email_templates` | `EmailTemplate` | per-tenant branded templates |
| `clusters` | `Cluster` | pillar/cluster planning is per-tenant content strategy |
| `articles` | `Article` | per-tenant content |
| `scheduled_content` | `ScheduledContent` | per-tenant publish queue |
| `mini_series` | `MiniSeries` | per-tenant clip generation |
| `social_posts` | `SocialPost` | per-tenant social publishing |
| `aggregated_topics` | `AggregatedTopic` | per-tenant content graph aggregation |
| `comment_drafts` | `CommentDraft` | per-tenant YouTube comments |
| `user_settings` | `UserSetting` | per-tenant user email signatures |
| `faq_entries` | `FaqEntry` | per-tenant FAQ corpus |

**Total: 16 tenant-scoped tables.**

### 2b. Platform-exempt tables (NO `tenant_id`)

| Table | Model | Justification |
|---|---|---|
| `platform_config` | `PlatformConfig` | global platform key-value store (API keys, feature flags affecting all tenants); will gain per-tenant config table in F5 |
| `secret_audit` | `SecretAudit` | audit log for secret-manager writes; global audit integrity must not be filtered by tenant |
| `tenants` | `Tenant` (new) | platform-level registry; obviously not self-referential |

**Total: 3 platform-exempt tables.**

---

## 3. Data model

### 3a. `tenants` table

```sql
CREATE TABLE IF NOT EXISTS tenants (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR NOT NULL,
    slug       VARCHAR NOT NULL UNIQUE,   -- url-safe identifier; e.g. "perkins"
    status     VARCHAR NOT NULL DEFAULT 'active',  -- active | suspended | offboarded
    settings   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

`settings` JSONB carries per-tenant loose config not worth a dedicated column (e.g., `brand_kit_url`, feature flags). Strongly-typed per-tenant tables (pricing configs, proposal templates, etc.) are added in F2/F3 waves and are themselves tenant-scoped. Per-tenant default admin users are managed in the `tenant_default_admins` table (TRD-F4), not in this JSONB envelope.

### 3a-1. Settings envelope registry

The `tenants.settings` JSONB is the canonical store for lightweight per-tenant config keys that do not warrant their own table. Every wave that writes a key here MUST register it in this table before use. Unknown keys written by any migration or service layer must round-trip without being dropped (writers preserve unknown keys; no writer may do a wholesale replace that discards keys it does not own).

| Key | Type | Owner wave | Description |
|---|---|---|---|
| `deposit` | object `{type: "percent"\|"fixed", value: number}` | F3 | Default deposit requirement for proposals |
| `reminder_cadence_days` | int[] | F3 | Days-after-send schedule for proposal reminder notifications |
| `license_number` | string | F3 | Contractor license number displayed on proposals |
| `brand_kit` | object (see TRD-F5 §2.1) | F5 | Brand colors, logo URL, font preferences |
| `kb_config` | object (see TRD-F5 §2.1) | F5 | Knowledge-base feature flags and category config |
| `marketing_config` | object (see TRD-F5 §2.1) | F5 | Social publishing and content scheduling config |

**Rule:** future waves register their keys here (in TRD-F0) before use. Any settings key not in this registry is permitted to exist (forward-compat) but is not guaranteed to be understood by any wave prior to its registration.

Seed in the same migration (idempotent):

```sql
INSERT INTO tenants (id, name, slug, status, settings)
VALUES (1, 'Perkins Roofing', 'perkins', 'active', '{}')
ON CONFLICT (id) DO NOTHING;

-- Advance the sequence past the seed row so new tenants start at 2
SELECT setval('tenants_id_seq', 1, true);
```

### 3b. `tenant_id` column pattern (all 16 tables)

```sql
ALTER TABLE <table> ADD COLUMN IF NOT EXISTS
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
```

`DEFAULT 1` serves two purposes simultaneously: it backfills all existing rows to Perkins and it ensures new rows in F0 land on Perkins without any application change. F4 replaces the need for the default at the ORM layer (the session context provides `tenant_id`); the column default remains as a hard safety net for raw-SQL migrations.

### 3c. ORM `TenantMixin`

File: `core/tenant.py` (new file)

```python
"""Tenant isolation primitives.

TenantMixin — attach to every new ORM model to get tenant_id + the F4 seam.
TenantSession — thin wrapper that will issue SET LOCAL in F4; in F0 it is a
                no-op so the existing SessionLocal continues to work unchanged.
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import Session


class TenantMixin:
    """Mixin that adds tenant_id to a SQLAlchemy model.

    Usage (new tables, F2+):
        class MyModel(Base, TenantMixin):
            __tablename__ = "my_table"
            ...

    Existing tables are backfilled via migration 0013; their model classes
    gain the column declaration below without needing this mixin (the mixin
    is for NEW tables going forward).  Existing models will be updated to
    inherit TenantMixin in a follow-up cleanup so the column is declared in
    one place.
    """
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id"),
        nullable=False,
        default=1,
        index=False,  # composite indexes declared at the table level (see migration)
    )


def set_tenant_context(session: Session, tenant_id: int) -> None:
    """Seam for F4's RLS session pattern.

    In F0 this is a documented no-op — it exists so F4 can activate the
    SET LOCAL without touching any call sites.  Call sites must exist and
    be plumbed BEFORE F4 can be wired.

    F4 implementation (do NOT implement here):
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
    """
    # F0: intentional no-op. F4 uncomments the body above.
    pass


class TenantQueryMixin:
    """ORM query helper — belt (complements F4's RLS suspenders).

    Usage in service layer:
        rows = session.query(Article).filter(
            *TenantQueryMixin.tenant_filter(Article, tenant_id)
        ).all()

    F4 will additionally rely on RLS; this filter stays as defense-in-depth.
    """
    @staticmethod
    def tenant_filter(model_cls, tenant_id: int):
        return (model_cls.tenant_id == tenant_id,)
```

**Rule for future tables** (to be added to `docs/ENGINEERING_RULES.md` as R6):

> **R6 — Every new table is born tenant-scoped.** Any `CREATE TABLE` not in the platform-exempt list above MUST include `tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id)` and inherit `TenantMixin`. PRs that omit this are rejected at review.

---

## 4. Migration — `0013_thin_tenancy.sql`

File: `infra/migrations/0013_thin_tenancy.sql`

Style matches existing migrations: idempotent (`IF NOT EXISTS`, `ON CONFLICT`), raw SQL, applied via `scripts/apply_migrations_connector.py`.

```sql
-- Migration 0013: Thin tenancy foundation (F0).
-- Creates the tenants table, seeds Perkins as tenant 1, and adds tenant_id
-- (NOT NULL DEFAULT 1, FK tenants.id) to all 16 tenant-scoped tables.
-- Idempotent: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- PROD APPLY: requires Jon's explicit permission + fresh ADC (gcloud auth
-- application-default login). Run: .venv/bin/python scripts/apply_migrations_connector.py

-- ── 1. tenants table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR NOT NULL,
    slug       VARCHAR NOT NULL,
    status     VARCHAR NOT NULL DEFAULT 'active',
    settings   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenants_slug UNIQUE (slug)
);

INSERT INTO tenants (id, name, slug, status, settings)
VALUES (1, 'Perkins Roofing', 'perkins', 'active', '{}')
ON CONFLICT (id) DO NOTHING;

SELECT setval('tenants_id_seq', 1, true);

-- ── 2. tenant_id column on all 16 tenant-scoped tables ──────────────────────
ALTER TABLE videos           ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE ingestion_runs   ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE segments         ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE words             ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE content_graph    ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE chunks            ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE email_templates  ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE clusters          ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE articles          ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE scheduled_content ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE mini_series       ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE social_posts      ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE aggregated_topics ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE comment_drafts    ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE user_settings     ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE faq_entries        ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);

-- ── 3. Composite indexes (hot query patterns filter on tenant_id first) ──────
-- Pattern: tenant_id + the existing lookup key on the table's hottest queries.

-- videos: most queries are "all videos for this tenant" or "video by id for this tenant"
CREATE INDEX IF NOT EXISTS ix_videos_tenant_id
    ON videos (tenant_id);

-- ingestion_runs: hot query is (video_id, stage) — tenant added for isolation
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_tenant_video_stage
    ON ingestion_runs (tenant_id, video_id, stage);

-- segments / words: fetched by video_id, so tenant_id + video_id composite
CREATE INDEX IF NOT EXISTS ix_segments_tenant_video
    ON segments (tenant_id, video_id);
CREATE INDEX IF NOT EXISTS ix_words_tenant_video
    ON words (tenant_id, video_id);

-- content_graph: fetched by video_id; kind is a secondary filter
CREATE INDEX IF NOT EXISTS ix_content_graph_tenant_video
    ON content_graph (tenant_id, video_id);

-- chunks: vector search is HNSW (separate); tenant_id + video_id for join queries
CREATE INDEX IF NOT EXISTS ix_chunks_tenant_video
    ON chunks (tenant_id, video_id);

-- articles: most queries filter on status + tenant
CREATE INDEX IF NOT EXISTS ix_articles_tenant_status
    ON articles (tenant_id, status);

-- scheduled_content: queries filter on status (scheduled/published) + tenant
CREATE INDEX IF NOT EXISTS ix_scheduled_content_tenant_status
    ON scheduled_content (tenant_id, status);

-- faq_entries: fetched by video_id + status
CREATE INDEX IF NOT EXISTS ix_faq_entries_tenant_video
    ON faq_entries (tenant_id, video_id);

-- comment_drafts: fetched by status (pending/drafted) per tenant
CREATE INDEX IF NOT EXISTS ix_comment_drafts_tenant_status
    ON comment_drafts (tenant_id, status);

-- clusters: small table; tenant_id alone is sufficient
CREATE INDEX IF NOT EXISTS ix_clusters_tenant_id
    ON clusters (tenant_id);

-- social_posts: looked up by series_id + tenant
CREATE INDEX IF NOT EXISTS ix_social_posts_tenant_series
    ON social_posts (tenant_id, series_id);

-- mini_series: looked up by video_id + approved
CREATE INDEX IF NOT EXISTS ix_mini_series_tenant_video
    ON mini_series (tenant_id, video_id);

-- aggregated_topics / email_templates / user_settings: tenant_id index only (low query rate)
CREATE INDEX IF NOT EXISTS ix_aggregated_topics_tenant_id ON aggregated_topics (tenant_id);
CREATE INDEX IF NOT EXISTS ix_email_templates_tenant_id   ON email_templates (tenant_id);
CREATE INDEX IF NOT EXISTS ix_user_settings_tenant_id     ON user_settings (tenant_id);
```

---

## 5. TEST PLAN — fail-first TDD sequence

Tests live in `tests/test_f0_tenancy.py`. Write each test, run it, confirm it fails for the expected reason, then implement the minimum to make it pass. Do not skip the red step.

No test runner exists in `web/` (package.json has no `test` script; only `build`, `lint`, `preview`). F0 has no frontend changes, so the web gate for F0 is: `npm run build` green (unchanged).

### Red tests to write BEFORE implementation

**Group 1 — Schema existence (introspection via SQLAlchemy inspect)**

**Dual-path note:** unit tests run on SQLite (via `tests/conftest.py` — schema comes from `Base.metadata.create_all`, not from the `.sql` migration file). The `.sql` migration is validated separately against dev Postgres (idempotency-tested there). This means:

- `settings` column is declared on the `Tenant` ORM model as `JSON().with_variant(JSONB, "postgresql")`. On SQLite the type resolves to JSON; on Postgres it resolves to JSONB. Unit tests assert `"settings"` is present in the column list — they do not assert the dialect-specific type name.
- `ADD COLUMN IF NOT EXISTS` is Postgres DDL syntax only — it is never executed during SQLite unit tests (schema comes from `create_all`). Migration idempotency is verified against dev Postgres only, not in the SQLite unit suite.
- FK and DEFAULT assertions use SQLAlchemy inspector in a backend-agnostic way: `col["default"]` for the default value, `inspector.get_foreign_keys(table)` for FK targets. Do not hard-code Postgres type names or DDL tokens in unit tests.

```
test_tenants_table_exists
    Use Base.metadata.create_all on the SQLite test engine (conftest fixture).
    Assert "tenants" in inspector.get_table_names().
    Red reason: Tenant model / table does not exist yet.

test_tenants_table_has_required_columns
    Assert columns: id (INTEGER PK), name, slug, status, settings, created_at.
    Assert settings column is present (type-agnostic — JSON on SQLite, JSONB on Postgres).
    Red reason: Tenant model does not exist.

test_all_16_tenant_tables_have_tenant_id
    For each of the 16 table names listed in §2a, inspect columns and assert
    "tenant_id" is present and NOT NULL.
    Default value assertion: ORM Column(default=1) — verified via model inspection, not
    DDL introspection (SQLite inspector does not reliably expose server defaults).
    Red reason: columns not added yet.

test_tenant_id_fk_references_tenants
    Use inspector.get_foreign_keys(table_name) on a representative set (videos, chunks, articles).
    Assert referred_table == "tenants".
    Red reason: FK not declared on ORM models yet.
```

**Postgres-only migration tests** (run against dev Postgres, not in the SQLite unit suite):
- Apply `0013_thin_tenancy.sql` twice; assert second run produces no errors (`ADD COLUMN IF NOT EXISTS` is idempotent).
- Assert `settings` column type is `jsonb` via `information_schema.columns`.
- Assert `tenant_id NOT NULL DEFAULT 1` via `information_schema.columns` on representative tables.

**Group 2 — Seed data**

```
test_perkins_is_tenant_1
    Query tenants table. Assert exactly one row with id=1, slug='perkins',
    status='active'.
    Red reason: table or seed row absent.
```

**Group 3 — Default backfill**

```
test_existing_rows_have_tenant_id_1
    For each of the 16 tables that have rows (at minimum: videos, segments,
    chunks, articles based on dev data), assert all rows have tenant_id = 1.
    Test is parameterized over table names; uses raw SQL via the test engine.
    Red reason: column absent, so query fails.
```

**Group 4 — New-row defaults**

```
test_new_video_defaults_to_tenant_1
    Insert a Video row with no tenant_id specified. Assert tenant_id == 1.
    Red reason: column absent / no default.

test_new_article_defaults_to_tenant_1
    Same pattern for Article.
    Red reason: column absent / no default.

test_new_chunk_defaults_to_tenant_1
    Same pattern for Chunk (important: pgvector HNSW searches must be
    tenant-filtered in F4; confirm the column is there now).
    Red reason: column absent / no default.
```

**Group 5 — ORM mixin unit tests**

```
test_tenant_mixin_declares_tenant_id_column
    Instantiate a throwaway model class inheriting TenantMixin (or check
    the column descriptor exists on the mixin). Assert column name == "tenant_id".
    Red reason: core/tenant.py does not exist.

test_set_tenant_context_is_noop_in_f0
    Call set_tenant_context(mock_session, 1). Assert mock_session.execute
    was NOT called (verifies F0 no-op contract).
    Red reason: function does not exist.

test_tenant_query_mixin_filter_returns_correct_clause
    TenantQueryMixin.tenant_filter(Article, 42) should return a filter
    expression equivalent to Article.tenant_id == 42.
    Red reason: class does not exist.
```

**Group 6 — Indexes (introspection)**

```
test_composite_indexes_exist
    For a representative set (videos, ingestion_runs, chunks, articles,
    faq_entries), assert the named composite index is present in
    inspector.get_indexes(table_name).
    Red reason: indexes not created yet.
```

**Coverage gate:** `pytest --cov=core --cov-fail-under=97` must pass after F0. The new `core/tenant.py` must reach 100% (it will: all three exported symbols are tested above). The migration runner is in `scripts/` (coverage-omitted) — it gets a behavioral validation instead: run the migration against a fresh SQLite test DB and assert all DDL applied cleanly.

---

## 6. Implementation steps

Perform in this exact order (TDD: write test → red → implement → green → next):

1. Create `tests/test_f0_tenancy.py` with all Group 1–6 tests (all red).
2. Run `pytest tests/test_f0_tenancy.py -x` — confirm failures are "table not found" / "module not found", not assertion errors from wrong data.
3. Create `core/tenant.py` with `TenantMixin`, `set_tenant_context`, `TenantQueryMixin`. Groups 5 tests go green.
4. Write `infra/migrations/0013_thin_tenancy.sql` (§4 above).
5. Apply migration to dev DB: `psql $DEV_DB_URL -f infra/migrations/0013_thin_tenancy.sql` (or via the connector script pointed at dev). Groups 1–4, 6 tests go green.
6. Add `tenant_id` column declarations to all 16 ORM model classes in `app/models.py` (aligning with the column added by the migration — no `create_all` needed, column already exists). For existing models, add the column directly; for new models going forward, use `TenantMixin`.
7. Run full suite: `pytest tests/ --cov=core --cov-fail-under=97 -q`. Must be green.
8. Run `ruff check core adapters api jobs`. Fix any issues.
9. Add R6 rule to `docs/ENGINEERING_RULES.md`.
10. Commit on `feat/f0-thin-tenancy`.

---

## 7. Exit gate

All of the following must be true before F0 is "done":

- [ ] `infra/migrations/0013_thin_tenancy.sql` applied to dev DB without errors
- [ ] `pytest tests/test_f0_tenancy.py` — all tests green (Groups 1–6)
- [ ] `pytest tests/ --cov=core --cov-fail-under=97 -q` — green (existing suite unbroken)
- [ ] `ruff check core adapters api jobs` — clean
- [ ] `npm run build` in `web/` — green (no frontend changes, sanity check)
- [ ] Behavioral validation: run migration against a fresh empty schema; assert idempotent (apply twice, second run is a no-op)
- [ ] Manual smoke: existing Perkins features work (search/ask, articles, estimator) — no regression
- [ ] R2: architect + critic review — no unaddressed HIGH findings
- [ ] R4: `scripts/drift_check.sh` — `terraform plan` clean (migration is DB DDL, not Terraform-owned infra; no drift expected)

---

## 8. Rollout / rollback

### Dev apply
```bash
psql $DEV_DB_URL -f infra/migrations/0013_thin_tenancy.sql
# or via connector:
.venv/bin/python scripts/apply_migrations_connector.py
```

### Prod apply — REQUIRES JON'S EXPLICIT PERMISSION
The migration runner requires fresh Application Default Credentials that only Jon can mint:
```bash
gcloud auth application-default login   # Jon runs this interactively
.venv/bin/python scripts/apply_migrations_connector.py
```
Do NOT apply to prod without Jon's explicit "go" in the session. Document the apply in the continuation doc.

### Rollback
This migration is purely additive: a new table + new nullable-with-default columns. Rollback path:

```sql
-- Down (safe — no data lost, all original columns untouched):
ALTER TABLE videos            DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE ingestion_runs    DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE segments          DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE words              DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE content_graph     DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE chunks             DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE email_templates   DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE clusters           DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE articles           DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE scheduled_content  DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE mini_series        DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE social_posts       DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE aggregated_topics  DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE comment_drafts     DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE user_settings      DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE faq_entries         DROP COLUMN IF EXISTS tenant_id;
DROP TABLE IF EXISTS tenants;
```

No application code reads `tenant_id` in F0 (the column is added to the DB and ORM models but no business logic filters on it yet), so dropping the column restores the exact pre-F0 state. Application behavior is identical with or without the column in F0.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| `NOT NULL DEFAULT 1` on large tables causes a full table rewrite on Postgres < 11 | Postgres 11+ rewrites are metadata-only for NOT NULL + DEFAULT; Cloud SQL for Postgres is at Postgres 14+. Non-issue. |
| Migration applied twice corrupts seed row | `ON CONFLICT (id) DO NOTHING` on the INSERT. Idempotent. |
| ORM model `tenant_id` declaration conflicts with migration-added column | SQLAlchemy `Column()` declarations are checked against the DB schema at `create_all` time only; no conflict at runtime. Column must be added to model classes AFTER the migration runs on dev. |
| Existing tests that assert exact column lists break | Tests that introspect schema must be updated to include `tenant_id`. The test plan above includes these assertions, so they drive the correct update. |
| F4 RLS pattern requires session-scoped `SET LOCAL` — the seam must be at every query entry point | `set_tenant_context()` is the single seam. It must be called from every FastAPI route dependency that creates a DB session. The function exists in F0 as a no-op, so F4 only needs to fill in the body — no call-site surgery. Call-site plumbing is part of F0's implementation step 6. |
| pgvector HNSW index performance with tenant-filtered searches | Tenant filter applied post-HNSW recall in F0/F4 (safe for single-digit tenants). Partition-by-tenant lever documented in plan §3.9 for scale. |

---

## 10. F4 seam — explicit contract

F4 activates tenancy enforcement. The F0 seam is:

1. `core/tenant.py::set_tenant_context(session, tenant_id)` — body is a no-op in F0. F4 replaces the body with `session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})`.
2. Every FastAPI route that opens a DB session must call `set_tenant_context(db, resolved_tenant_id)` after obtaining the session. F0 plants these call sites (they call a no-op). F4 fills in the function body. This means F4 requires zero call-site changes.
3. `TenantQueryMixin.tenant_filter()` — ORM-layer belt. F4 adds RLS as the suspenders layer. Both stay active in F4+.
4. The `tenant_id` column default of `1` on every table acts as a final safety net: raw SQL executed outside the session context still lands on Perkins, not a cross-tenant null. F4 RLS will reject a cross-tenant read even if the column is wrong.
