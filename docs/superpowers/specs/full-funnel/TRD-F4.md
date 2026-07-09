# TRD-F4 — Tenancy Hardening: RLS + GCIP

**Wave:** F4 · **Status:** DRAFT (R2 fixes applied — pending Jon approval) · **Parallel-safe with:** F5
**Trigger:** must complete before tenant #2 is provisioned; not on the critical path to F3 (Tim's demo)
**Grounding:** full-funnel-plan §3 (mechanics 1–10), §4 (GCIP), §8 (infra), §9 F4 row, §11 risks

---

## 1. Scope & non-goals

**In scope:**
- PostgreSQL Row-Level Security (RLS) on every tenant-scoped table
- SQLAlchemy `SET LOCAL app.tenant_id` session pattern (pool-safe)
- Firebase Auth → Google Cloud Identity Platform (GCIP) upgrade
- `platform_admin` role (cross-tenant provisioning, DeGenito staff only)
- `DEFAULT_ADMINS` → per-tenant config (remove global constant)
- Cloud SQL PITR enabled via Terraform
- ≥30 denial tests in CI covering the full cross-tenant matrix
- Cross-tenant timing probe (404-indistinguishable, ≤100 ms differential)
- CI grep gate blocking raw `text()`/`execute()` outside approved modules
- `tenant_id` on every structured log line

**Non-goals for this wave:**
- Per-tenant subdomains (deferred; revisit at ~10 tenants)
- SAML/OIDC per-tenant SSO (F6)
- Tenant provisioning UI (F6)
- Usage metering UI (F5)
- Payment gating on tenant status

---

## 2. Data model changes

### 2.1 New tables / columns (migration `0018_rls_gcip.sql`)

```sql
-- Already exists after F0; documented here for completeness
-- tenants table (seeded by F0):
--   id SERIAL PK, name TEXT, slug TEXT UNIQUE, status TEXT DEFAULT 'active',
--   settings JSONB DEFAULT '{}'

-- New: platform tenant → GCIP tenant mapping
CREATE TABLE tenant_gcip_map (
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    gcip_tenant TEXT    NOT NULL,  -- GCIP tenant ID string (e.g. "perkins-abc123")
    PRIMARY KEY (tenant_id),
    UNIQUE (gcip_tenant)
);

-- New: per-tenant admin email list (replaces global DEFAULT_ADMINS)
CREATE TABLE tenant_default_admins (
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email       TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, email)
);

-- New: platform_admin grants (DeGenito staff; cross-tenant)
CREATE TABLE platform_admins (
    email       TEXT PRIMARY KEY,
    granted_by  TEXT NOT NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Platform-level tables (no `tenant_id`, RLS-exempt):**
`tenants`, `tenant_gcip_map`, `tenant_default_admins`, `platform_admins`, `platform_config`,
`secret_audit`, `alembic_version`

**Tenant-scoped tables (receive RLS; exhaustive list as of F4):**
`videos`, `ingestion_runs`, `segments`, `words`, `content_graph`, `chunks`,
`email_templates`, `clusters`, `articles`, `scheduled_content`, `mini_series`,
`social_posts`, `aggregated_topics`, `comment_drafts`, `user_settings`, `faq_entries`

Additionally, tables added in F1–F3 (`customers`, `properties`, `leads`, `proposals`,
`proposal_events`, `pricing_configs`, `measurements`) must have `tenant_id` and receive
RLS policies before F4 exits.

### 2.2 App DB role change (critical)

The application's Cloud SQL user must be a **non-superuser** with **no BYPASSRLS**.

Current state: verify with `SELECT rolsuper, bypassrls FROM pg_roles WHERE rolname = '<app-user>';`

Required migration step (run as the Cloud SQL postgres superuser via the connector, with Jon's
explicit permission):

```sql
ALTER ROLE <app-role> NOSUPERUSER NOBYPASSRLS;
```

Document this role change in the migration file header; it is a one-way DDL change. If the role
was previously a superuser for convenience, service behavior must be validated in staging first.

---

## 3. RLS mechanics (exhaustive)

### 3.1 Policy template

Applied to every tenant-scoped table. Two policies per table: one for DML, one to force
the security barrier even when other row-level filters exist.

```sql
-- Enable RLS + force it (force means even the table owner sees filtered rows)
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;

-- Read + write policy (single USING clause covers SELECT/UPDATE/DELETE;
-- WITH CHECK covers INSERT/UPDATE)
CREATE POLICY tenant_isolation ON <table>
    USING      (tenant_id = current_setting('app.tenant_id')::int)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
```

`current_setting('app.tenant_id')` raises an error if the GUC is unset. This is intentional:
any code path that omits SET LOCAL before a query will fail loudly in testing, not silently
pass without a filter. In production the after-begin event guarantees the GUC is always set
before the first SQL of a transaction.

### 3.2 SQLAlchemy session pattern

Location: `app/db.py` (new module, or `app/models.py` alongside `SessionLocal`).

```python
from sqlalchemy import event, text
from app.models import SessionLocal

@event.listens_for(SessionLocal, "after_begin")
def _set_tenant_id(session, transaction, connection):
    """Set transaction-scoped tenant context immediately after BEGIN.

    Sources ONLY from session.info["tenant_id"] which must be populated
    from verified token claims before the session is used. Never from
    a request header, URL parameter, or any client-supplied value.
    Pool-safe: SET LOCAL dies with the transaction; the GUC is never
    visible to the next connection checkout.
    """
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None:
        raise RuntimeError(
            "tenant_id not set on session; populate session.info['tenant_id'] "
            "from verified token claims before the first query."
        )
    connection.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
```

**FastAPI dependency integration** (update `api/auth.py`):

```python
def get_db_session(claims: dict = Depends(require_role("any"))):
    """Yield a DB session pre-configured with the caller's tenant context."""
    db = SessionLocal()
    db.info["tenant_id"] = claims["tenant_id"]  # sourced from verified token claims only
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

`claims["tenant_id"]` is resolved in `api/auth.py::_verify()` from the Firebase/GCIP token
claims (see §4.2). It is never accepted from a request body or header.

**`platform_admin` session handling (critical fix):** §4.4 sets `claims["tenant_id"] = None` for non-impersonating `platform_admin` users. The `after_begin` event above would raise `RuntimeError` for these sessions because `tenant_id is None`. Fix: define a separate **platform-scoped session dependency** that does NOT set the `app.tenant_id` GUC. This dependency is used exclusively by endpoints that touch only RLS-exempt platform-level tables (`tenants`, `tenant_gcip_map`, `tenant_default_admins`, `platform_admins`, `tenant_offboard_log`).

```python
def get_platform_db_session(claims: dict = Depends(require_role("platform_admin"))):
    """Yield a DB session with NO tenant GUC set.
    May only be used by endpoints that touch RLS-exempt platform-level tables.
    Do NOT use for any endpoint that reads tenant-scoped data.
    """
    db = PlatformSessionLocal()  # separate session factory without the after_begin hook
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

`view_all_tenants`-class endpoints (e.g. `GET /internal/tenants`) use `get_platform_db_session`. Endpoints that operate on tenant-scoped data on behalf of a platform_admin (impersonation path) use `get_db_session` with `claims["tenant_id"]` populated from the `X-Tenant-ID` header after validation (see §4.4 and §6 red tests).

**Red test — platform_admin session isolation:**
```python
def test_platform_admin_can_list_tenants_without_impersonation():
    """platform_admin without X-Tenant-ID header → GET /internal/tenants returns 200."""

def test_platform_admin_cannot_read_tenant_scoped_table_without_impersonation():
    """platform_admin without X-Tenant-ID header → GET /videos returns 403 (no tenant context)."""
```

### 3.3 ORM base-query filter (belt)

The F0 mixin (`TenantScopedMixin`) already adds a `tenant_id` column. In F4 we additionally
enforce a SQLAlchemy query event that appends `.filter(Model.tenant_id == session.info["tenant_id"])`
on every `Query` involving a tenant-scoped model. This is the belt; RLS is the suspenders.
Neither alone is sufficient; both together mean a missed filter is caught at two layers.

Implementation: override `Query` via a custom session factory or use
`@event.listens_for(Session, "do_orm_execute")` to inject the filter on tenant-scoped models.

### 3.4 Rollout sequence (per-table, staged)

Enable RLS one table at a time in a single migration, verifying each in the test suite before
the next. Order: highest-data-volume tables last (chunks, segments) so any performance impact
is measured in isolation.

Rollback: `ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;` — the `tenant_id` columns and FK
constraints remain, preserving data integrity. Re-enabling restores full protection without
data changes.

---

## 4. GCIP upgrade mechanics

### 4.1 Firebase Auth → Identity Platform

Upgrade path: Firebase console → "Upgrade to Identity Platform" (one-click, reversible,
no user migration, same project). Perkins' existing project-level user pool becomes
"tenant 1" (no GCIP tenant ID on their tokens; `firebase.tenant` claim absent).

**Terraform:** add `google_identity_platform_config` resource to `infra/main.tf` to codify
the upgrade state and multi-tenancy enable. The existing `google_identity_platform_default_supported_idp_config`
resource already present in main.tf is compatible.

```hcl
resource "google_identity_platform_config" "default" {
  project                 = var.project_id
  autodelete_anonymous_users = true

  sign_in {
    allow_duplicate_emails = false
    email { enabled = true; password_required = true }
  }

  # multi_tenant block managed by GCP; ignore_changes is already present
  lifecycle { ignore_changes = [multi_tenant] }
}
```

Real GCIP tenants are created for new licensees via the Admin SDK (called from the tenant
provisioning endpoint in F6), not via Terraform (tenants are runtime data, not infra).

### 4.2 Token claim mapping

In `api/auth.py::_verify()`, after `verify_token()` returns claims:

```python
def _resolve_tenant(claims: dict, db_session) -> int:
    """Resolve GCIP token claims → platform tenant_id.

    Rules (in order):
      1. No firebase.tenant claim → tenant 1 (Perkins; project-level pool).
      2. firebase.tenant claim present → look up tenant_gcip_map.
         Row missing → 401 (unknown tenant; token is valid but not provisioned).
    """
    gcip_tenant = claims.get("firebase", {}).get("tenant")
    if gcip_tenant is None:
        return 1  # Perkins stays on project-level pool; zero disruption

    # Platform-level lookup (no RLS; this runs before tenant_id is set)
    row = db_session.execute(
        text("SELECT tenant_id FROM tenant_gcip_map WHERE gcip_tenant = :g"),
        {"g": gcip_tenant}
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="tenant not provisioned")
    return row[0]
```

`claims["tenant_id"]` is populated from this lookup and used to seed `session.info["tenant_id"]`
in the DB dependency (§3.2). Perkins' users see zero change: their tokens have no
`firebase.tenant` claim, they resolve to tenant 1, and the existing auth flow is unchanged.

### 4.3 Invite-link tenant resolution (v1)

No per-tenant subdomains. Invite links encode the GCIP tenant ID as a query param:
`/accept-invite?tenant=<gcip_tenant_id>&oobCode=<firebase-oob-code>`.

The SPA reads `tenant` from the URL and calls `signInWithEmailLink(auth, email, window.location.href)`
on a Firebase Auth instance initialized with the GCIP tenant set:
`auth.tenantId = params.get("tenant")` before the sign-in call.

For users with no invite (Perkins staff): normal sign-in, no `tenantId` set on the Auth instance,
resolves to tenant 1.

### 4.4 `platform_admin` role

DeGenito staff only. Stored in `platform_admins` table. Resolved in `_verify()` before
`effective_role()`:

```python
if email in _platform_admin_emails(db):  # cached set, refreshed per request or TTL
    claims["role"] = "platform_admin"
    claims["tenant_id"] = None  # platform_admin operates across tenants; see §3.2 for session handling
    return claims
```

`platform_admin` is added to `_MATRIX` in `core/authz.py` with actions:
`{"provision_tenant", "view_all_tenants", "manage_platform_config", "impersonate_tenant"}`.

**`impersonate_tenant` invariants (security-critical):**

`impersonate_tenant` allows a platform_admin to scope a single request to a specific tenant via the `X-Tenant-ID` header. The following invariants are non-negotiable:

1. **Auth gate:** `X-Tenant-ID` is read ONLY after a verified `platform_admin` token claim. A non-platform_admin token with this header must not receive elevated access.
2. **Route gate:** `X-Tenant-ID` is ONLY honored on `/internal/*` routes. The header is stripped and ignored at the app layer on all other routes (and at the Cloudflare edge in F6).
3. **Audit:** every impersonated request writes an audit row: `(platform_admin_email, target_tenant_id, route, method, timestamp)` to a `platform_audit_log` table (add this platform-level table to migration 0018).
4. **No header leakage:** regular tenant sessions are never affected by the presence of this header; §3.4's invariant holds — regular tenant context is always sourced from verified token claims, never from headers.

**Denial + audit tests (add to `tests/test_tenant_denial.py`):**

```python
def test_x_tenant_id_ignored_for_non_platform_admin():
    """Regular tenant token + X-Tenant-ID header → header ignored; tenant context from token."""

def test_x_tenant_id_only_on_internal_routes():
    """platform_admin + X-Tenant-ID on /videos → header stripped; 403 (no tenant context on non-internal route)."""

def test_impersonation_writes_audit_row():
    """platform_admin + X-Tenant-ID on /internal/tenants/{id} → audit row written with correct fields."""
```

### 4.4a `tenant_default_admins` ownership

**F4 is the single owner** of the `tenant_default_admins` table. It is created in migration 0018 (this file). PRD-admin will reference it; F0 does NOT put default_admins in the `tenants.settings` JSONB envelope — default admins are a DB-backed per-tenant list, not a settings key.

### 4.5 `DEFAULT_ADMINS` → per-tenant

Remove `settings.DEFAULT_ADMINS` (currently a list in `app/config.py`).
Replace with a DB lookup in `effective_role()`:

```python
def effective_role(email, role, tenant_id, db_session, email_verified=False):
    if email_verified and email:
        # Check tenant-scoped default admins (platform-level query, no RLS)
        row = db_session.execute(
            text("SELECT 1 FROM tenant_default_admins WHERE tenant_id=:t AND email=:e"),
            {"t": tenant_id, "e": email.lower()}
        ).fetchone()
        if row:
            return "admin"
    return role
```

Seed migration: INSERT existing `DEFAULT_ADMINS` values into `tenant_default_admins` for
`tenant_id = 1`.

---

## 5. Defense-in-depth layers (all must be green at exit gate)

| Layer | Implementation | Test coverage |
|---|---|---|
| ORM filter | `do_orm_execute` event appends tenant filter on every tenant-scoped model | denial matrix (see §6) |
| RLS | `USING (tenant_id = current_setting('app.tenant_id')::int)` + FORCE | denial matrix — tests bypass ORM and use raw SQL with a mismatched tenant_id GUC |
| Denial tests | ≥30 tests in CI (see §6) | CI gate |
| Cross-tenant probe | HTTP probe: resource of tenant B requested with tenant A's token → 404 in ≤100 ms | timing assertion in test |
| CI grep gate | `ruff` plugin or `pytest` fixture greps for raw `text()`/`execute()` outside `app/db.py` and `scripts/apply_migrations_connector.py` | pre-commit + CI |
| Structured logging | `tenant_id` injected into every log record via Python `logging.Filter` on the root logger | existing `adapters/gcp_logging.py` extended |

### 5.1 Denial test matrix (≥30 tests)

Each cell = 1 test. Resource types × operations × cross-tenant scenario:

| Resource | Read (GET) | Write (POST/PUT) | Delete (DELETE) |
|---|---|---|---|
| videos | T | T | T |
| segments | T | T | — |
| chunks | T | T | — |
| articles | T | T | T |
| mini_series | T | T | T |
| social_posts | T | T | T |
| comment_drafts | T | T | T |
| faq_entries | T | T | T |
| proposals (F3) | T | T | T |
| customers (F3) | T | T | T |

**T** = cross-tenant denial test (token from tenant A, resource owned by tenant B → 404).

That matrix gives ≥30 cells. Additional tests:
- Unauthenticated request → 401 (not 403 or 404)
- `platform_admin` with `impersonate_tenant` header → 200 for the target tenant
- `platform_admin` without header → 403 on tenant-scoped resources
- RLS bypass attempt: raw SQL with wrong `app.tenant_id` → 0 rows (not error)
- `current_setting('app.tenant_id')` unset → query raises, transaction rolls back

---

## 6. API changes

No new public endpoints in F4. Internal changes:

- `api/auth.py`: `_verify()` adds `tenant_id` resolution; `get_db_session()` seeds `session.info`
- `core/authz.py`: add `platform_admin` to `_MATRIX`; `effective_role()` signature adds `tenant_id` + `db_session`
- All existing route handlers: replace bare `SessionLocal()` with `Depends(get_db_session)` if not already doing so

New internal endpoint (platform_admin only):
```
POST /internal/tenants/{tenant_id}/impersonate
```
Sets `X-Tenant-ID` context for a single request. Used by the provisioning UI (F6) and
support tooling. Not exposed at the Cloudflare edge (blocked by WAF rule on `/internal/*`).

---

## 7. Terraform changes (`infra/main.tf`)

### 7.1 Cloud SQL PITR

```hcl
resource "google_sql_database_instance" "main" {
  # ... existing config ...
  settings {
    # ... existing settings ...
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true  # ADD THIS — currently missing
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }
  }
}
```

**Note:** enabling PITR on a running instance causes a brief I/O spike as WAL archiving
begins. Schedule the `terraform apply` during off-peak hours (Perkins is FL-based; apply
after 11 PM ET).

### 7.2 GCIP config

Add `google_identity_platform_config` as shown in §4.1. No new IAM bindings needed; the
existing `firebase-adminsdk` service account already has Identity Platform Admin rights.

### 7.3 Secret Manager paths for platform_admins

No Terraform change needed — `platform_admins` is a DB table, not a secret. The existing
`secretmanager.secretAccessor` binding on the API service account covers it.

---

## 8. Migrations

File: `infra/migrations/0018_rls_gcip.sql`

**Important:** this file must be `.sql` — `scripts/apply_migrations_connector.py` globs `*.sql` only. A `.py` file at this path would be silently skipped by the migration runner.

**Ownership:** migration 0018 owns the `platform_admins` seed. **CORRECTION (2026-07-09):** 0018 as implemented created `tenant_gcip_map`, `tenant_default_admins`, `platform_admins`, and `platform_audit_log` but did NOT ship `tenant_offboard_log` (the doc intended it here but the code omitted it). Migration **0019** (F5) is therefore the actual creator of `tenant_offboard_log` (`CREATE TABLE IF NOT EXISTS`, idempotent). F6 references to it must remain idempotent no-ops.

Steps (in order, idempotent):
1. `CREATE TABLE IF NOT EXISTS tenant_gcip_map`
2. `CREATE TABLE IF NOT EXISTS tenant_default_admins`
3. `CREATE TABLE IF NOT EXISTS platform_admins`
4. `CREATE TABLE IF NOT EXISTS tenant_offboard_log` — F4 owns this table; F5 references it, not re-creates it
5. Seed `tenant_default_admins` from current `DEFAULT_ADMINS` setting for tenant 1
6. For each tenant-scoped table (exhaustive list in §2.1):
   a. `ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;`
   b. `ALTER TABLE <t> FORCE ROW LEVEL SECURITY;`
   c. `CREATE POLICY IF NOT EXISTS tenant_isolation ON <t> USING (...) WITH CHECK (...);`
7. `ALTER ROLE <app-role> NOSUPERUSER NOBYPASSRLS;` — **requires superuser; Jon must confirm and run**
8. Insert `google_identity_platform_config` TF resource → `terraform apply`

Migration is applied via `scripts/apply_migrations_connector.py` with Jon's explicit permission
(per CONTINUATION-2026-07-08 §6 prod DDL rule).

---

## 9. TEST PLAN

Tests written **first** (TDD); each must be red before implementation begins.

### Unit tests (`tests/test_rls.py`, `tests/test_gcip_claims.py`)

```
test_set_local_fires_on_begin()
    — confirms the after-begin event executes SET LOCAL before any query

test_set_local_missing_tenant_raises()
    — session without tenant_id in info raises RuntimeError on first query

test_resolve_tenant_no_claim_returns_1()
    — token with no firebase.tenant → tenant_id = 1

test_resolve_tenant_gcip_claim_maps_correctly()
    — token with firebase.tenant = "x" → looks up tenant_gcip_map, returns correct id

test_resolve_tenant_unknown_gcip_raises_401()
    — token with firebase.tenant not in map → 401

test_effective_role_tenant_default_admin()
    — email in tenant_default_admins for tenant 1 → "admin"

test_platform_admin_role_resolution()
    — email in platform_admins → "platform_admin", tenant_id = None

test_platform_admin_can_provision_tenant()
    — can("platform_admin", "provision_tenant") is True

test_platform_admin_cannot_bypass_rls_on_data()
    — platform_admin without impersonate header → 403 on tenant-scoped GET
```

### Postgres fixture requirement (critical — do not skip)

The test suite runs on SQLite by default (`tests/conftest.py`). SQLite cannot exercise RLS policies, `SET LOCAL`, `FORCE ROW LEVEL SECURITY`, `INET` columns, or partial indexes. Running the ≥30 denial tests and the timing probe against SQLite would produce false-green results — the RLS policies do not exist on SQLite and the ORM filter alone is not sufficient evidence.

**Mandate:** the tenancy suite (denial matrix, RLS bypass test, timing probe) runs against a real PostgreSQL instance. Two supported options:

1. **testcontainers-python** (`testcontainers[postgresql]`): spins up a real Postgres Docker container per test session. Add to `dev-requirements.txt`. Fixture:
   ```python
   @pytest.fixture(scope="session")
   def pg_engine():
       from testcontainers.postgres import PostgresContainer
       with PostgresContainer("postgres:16") as pg:
           yield create_engine(pg.get_connection_url())
   ```
2. **CI service container**: add a `postgres:16` service to the CI workflow YAML; pass `TENANCY_PG_URL` env var.

**`TENANCY_PG_URL` env switch:** if set, the tenancy suite uses the provided Postgres URL; otherwise it is skipped with an explicit `pytest.skip("TENANCY_PG_URL not set — tenancy tests require real Postgres")` marker. Tests in this suite are marked `@pytest.mark.postgres`. They must NEVER silently pass on SQLite.

```python
# tests/conftest.py addition
import pytest, os

def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: requires a real PostgreSQL instance (TENANCY_PG_URL)")

@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("TENANCY_PG_URL")
    if not url:
        pytest.skip("TENANCY_PG_URL not set — tenancy suite requires real Postgres")
    return url
```

### Denial matrix tests (`tests/test_tenant_denial.py`)

30+ tests per §5.1. All marked `@pytest.mark.postgres`. Pattern (pytest-parametrize):

```python
@pytest.mark.parametrize("resource,method,path_template", [
    ("videos",         "GET",    "/videos/{id}"),
    ("articles",       "GET",    "/articles/{slug}"),
    ("mini_series",    "GET",    "/series/{id}"),
    # ... all cells from §5.1 matrix ...
])
def test_cross_tenant_denial(resource, method, path_template, two_tenant_fixture):
    tenant_a_token, tenant_b_resource_id = two_tenant_fixture[resource]
    resp = client.request(method, path_template.format(id=tenant_b_resource_id),
                          headers={"Authorization": f"Bearer {tenant_a_token}"})
    assert resp.status_code == 404  # 404-indistinguishable, not 403
```

### Timing probe test (`tests/test_timing_probe.py`)

All tests in this file are marked `@pytest.mark.postgres` — timing behavior on SQLite is not representative.

```python
@pytest.mark.postgres
def test_cross_tenant_timing_differential():
    # Own resource (200) vs cross-tenant (404) timing differential ≤ 100 ms
    t_own   = timeit(lambda: client.get(f"/videos/{own_id}",   headers=own_token), number=10)
    t_cross = timeit(lambda: client.get(f"/videos/{cross_id}", headers=own_token), number=10)
    assert abs(t_own - t_cross) / 10 <= 0.100  # seconds
```

### RLS bypass test (raw SQL)

Marked `@pytest.mark.postgres` — RLS does not exist on SQLite.

```python
@pytest.mark.postgres
def test_rls_blocks_raw_sql_wrong_tenant(db_session_tenant_1):
    # Directly set a wrong tenant GUC and attempt to read tenant 2 data
    db_session_tenant_1.execute(text("SET LOCAL app.tenant_id = 99"))
    rows = db_session_tenant_1.execute(text("SELECT * FROM videos")).fetchall()
    assert rows == []  # RLS policy returns 0 rows, not an error
```

### CI grep gate (`tests/test_raw_sql_gate.py`)

```python
def test_no_raw_text_execute_outside_approved():
    approved = {"app/db.py", "scripts/apply_migrations_connector.py",
                "infra/migrations/"}
    import subprocess, re
    result = subprocess.run(
        ["grep", "-rn", r"text(\|\.execute(", "--include=*.py",
         "api/", "core/", "jobs/", "adapters/"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        file_path = line.split(":")[0]
        assert any(file_path.startswith(a) for a in approved), \
            f"Raw SQL outside approved modules: {line}"
```

---

## 10. Implementation steps

1. Write all tests in §9 → confirm red for the right reasons
2. Add `tenant_gcip_map`, `tenant_default_admins`, `platform_admins` tables to `app/models.py`
3. Implement `app/db.py` with `after_begin` event and `get_db_session` dependency
4. Update `api/auth.py`: `_verify()` → `_resolve_tenant()`, seed `claims["tenant_id"]`
5. Update `core/authz.py`: add `platform_admin` to matrix; update `effective_role()` signature
6. Wire `get_db_session` into all route handlers (replace bare `SessionLocal()`)
7. Add ORM `do_orm_execute` tenant filter event
8. Add `tenant_id` logging filter to `adapters/gcp_logging.py`
9. Write migration `0018_rls_gcip.sql` (tables + policies; app role change is a separate manual step) — must be `.sql`, not `.py`, so the migration runner picks it up
10. Add GCIP TF resource + PITR to `infra/main.tf`; `terraform apply` (PITR during off-peak)
11. Run denial matrix tests → iterate until all green
12. Run timing probe → confirm ≤100 ms differential
13. Smoke test: sign in as Perkins user → confirm normal flow, no disruption
14. `scripts/drift_check.sh` → no drift (R4)
15. R2 review: architect + critic agents

---

## 11. Exit gate

All of the following must be true before F4 is marked done:

- [ ] ≥30 denial tests green in CI
- [ ] Cross-tenant timing probe green (≤100 ms differential)
- [ ] CI grep gate: zero raw `text()`/`execute()` outside approved modules
- [ ] Perkins login smoke: existing users authenticate, role resolves correctly, data unchanged
- [ ] `terraform plan` exits 0 (no drift; R4)
- [ ] PITR enabled on Cloud SQL instance (verified via `gcloud sql instances describe`)
- [ ] R2 architect + critic sign-off, no unaddressed HIGH findings
- [ ] `pytest --cov=core --cov-fail-under=97` green (R1)

---

## 12. Rollout / rollback

**Rollout:**
- RLS enabled per-table in migration (see §3.4); each table enable is independently safe
- GCIP upgrade is one-click, reversible via console; Perkins users see zero change
- `terraform apply` for PITR during off-peak window
- App role change (`NOSUPERUSER NOBYPASSRLS`) is the highest-risk step: validate in staging first

**Rollback (if denial suite fails post-deploy):**
- Per-table: `ALTER TABLE <t> DISABLE ROW LEVEL SECURITY;` — instant, no data change
- GCIP: downgrade via console (user pool preserved)
- PITR: `backup_configuration.point_in_time_recovery_enabled = false` → `terraform apply`
- App role: `ALTER ROLE <app-role> SUPERUSER BYPASSRLS;` — requires superuser access

---

## 13. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| One raw query bypasses RLS silently | Medium | Four-layer defense + CI grep gate |
| App role NOSUPERUSER breaks a hidden privilege | Low | Test in staging; rollback is instant |
| GCIP upgrade disrupts Perkins login | Very Low | Project-level pool unchanged; fire drill tested before deploy |
| pgvector recall degrades under RLS with many tenants | Low (v1) | Partition-by-tenant pre-planned lever (plan §3.9); not a v1 concern |
| PITR I/O spike during apply | Low | Off-peak window |

---

## 14. Unresolved questions

1. **App DB role name**: what is the exact Cloud SQL user/role name used by the API? Needed for the `ALTER ROLE` DDL. Check `infra/main.tf` or `scripts/apply_migrations_connector.py`.
2. **Staging environment**: does a staging Cloud SQL instance exist for testing the app role change before prod? If not, plan §11 recommends creating one before this step.
3. **`platform_admin` email list**: initial seed = `{jon@degenito.ai}`. Confirm with Jon before migration.
4. **`impersonate_tenant` header name**: proposed `X-Tenant-ID`; confirm it doesn't conflict with any existing proxy headers at the Cloudflare edge.
