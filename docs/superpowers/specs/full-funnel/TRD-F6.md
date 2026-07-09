# TRD-F6 — Edge + Onboarding

**Wave:** F6 · **Status:** DRAFT (R2 fixes applied — pending Jon approval)
**Depends on:** F4 (RLS + GCIP), F5 (per-tenant configs + offboarding function)
**Grounding:** full-funnel-plan §8 (infra/edge), §4 (GCIP), §9 F6 row, §10.1 (custom domain), §11 risks

---

## 1. Scope & non-goals

**In scope:**
- Cloudflare zone onboarding for `perkinsroofing.net` (import ALL records before NS change)
- `app.perkinsroofing.net` → Firebase Hosting custom domain (SPA) + Cloud Run API domain mapping
- Cloudflare WAF + rate limiting rules (accept pages, auth endpoints)
- Cloud Armor origin allowlist of Cloudflare IP ranges (hardening step)
- Tenant provisioning UI (platform_admin): create tenant → seed configs → GCIP tenant → invite admin
- Per-tenant SSO via GCIP (SAML/OIDC, $0.015/MAU)
- Security re-review (opus-model architect + critic; R2)
- Load pass: demonstrate system under simulated multi-tenant load
- Scaling lever documentation: list-partition `chunks` by `tenant_id` when/if needed

**Non-goals for this wave:**
- Per-tenant subdomains (revisit at ~10 tenants; requires SPA hosting move to GCS+LB or Cloud Run with wildcard cert)
- Payment processing
- Native iOS app
- Accounting / QBO integration
- CDN-level media streaming optimization (separate future wave)

---

## 2. Cloudflare ingress

### 2.1 Zone onboarding sequence (email-safe; ordered)

**CRITICAL: Google Workspace MX, SPF, and DKIM records must be imported before the nameserver
change. Email for `@perkinsroofing.net` must not break at any point.**

Step-by-step (Jon executes DNS steps; agent executes Terraform):

1. **Jon creates Cloudflare API token** (Zone:Edit, DNS:Edit, Firewall:Edit scopes for `perkinsroofing.net`) and adds it as Secret Manager secret `cloudflare-api-token`. Jarvis #330 tracks this.
2. **Terraform init** with Cloudflare provider (see §7.1): `terraform init` picks up the new provider.
3. **Import existing DNS records** via Terraform import OR Cloudflare API zone-scan. All records including:
   - `MX` records for Google Workspace (typically `aspmx.l.google.com` + alternates)
   - `TXT` records: SPF (`v=spf1 include:_spf.google.com …`), DKIM (`google._domainkey`)
   - `CNAME` or `A` records for existing website (do NOT proxy these until after validation)
   - Any existing `TXT` for domain ownership / Search Console
4. **Verify record completeness** with `dig MX perkinsroofing.net @ns1.cloudflare.com` before NS change.
5. **Jon changes nameservers** at Tucows/registrar to Cloudflare's assigned NS pair. Propagation: up to 48 hrs; test email send/receive before proceeding.
6. **After propagation confirmed:** set `app.perkinsroofing.net` CNAME (see §2.2); enable Cloudflare proxy (orange cloud) only on `app.perkinsroofing.net`.
7. **Existing website records** (`www`, apex `@`): keep DNS-only (grey cloud) unless the existing host is being moved. Do not proxy records for infrastructure not under our control.

### 2.2 `app.perkinsroofing.net` routing

Two targets, both behind the same subdomain:

| Path pattern | Target | Protocol |
|---|---|---|
| `/api/*` | Cloud Run API service (custom domain mapping) | Full-strict TLS → Cloud Run managed cert |
| `/*` (all other) | Firebase Hosting custom domain | Full-strict TLS → Firebase managed cert |

**Firebase Hosting custom domain:** add `app.perkinsroofing.net` in Firebase console → Hosting →
Add custom domain. Firebase issues a TXT ownership verification and provisions a managed cert.
Terraform codifies this via `google_firebase_hosting_custom_domain` resource if available;
otherwise documented as a one-time console action (tracked in SECRETS.md / R3 gap note).

**Cloud Run domain mapping:**
```hcl
resource "google_cloud_run_domain_mapping" "api" {
  location = var.region
  name     = "app.perkinsroofing.net"  # Cloud Run maps on path /api via CF routing rule

  metadata { namespace = var.project_id }
  spec { route_name = google_cloud_run_service.api.name }
}
```

**Cloudflare routing rule** (Page Rule or Transform Rule) to split traffic:
```
If URI path begins with /api → forward to Cloud Run origin
Else → forward to Firebase Hosting origin
```

Origins are configured as Cloudflare custom hostnames / origin rules pointing to the
Firebase Hosting and Cloud Run URLs (both on `*.run.app` / `*.web.app` — kept in Terraform).

### 2.3 TLS configuration

Cloudflare SSL/TLS mode: **Full (strict)** — requires a valid cert at origin.
- Firebase Hosting: issues its own managed cert for custom domains automatically.
- Cloud Run: managed cert via domain mapping resource above.
- Cloudflare edge: uses Cloudflare's shared cert for `app.perkinsroofing.net`.

**Interim option (if Cloudflare onboarding waits on Jon/Tucows):**
Add a direct CNAME at Tucows:
```
app.perkinsroofing.net  CNAME  <firebase-hosting-target>.web.app
```
and expose the API at `api.perkinsroofing.net` or `app.perkinsroofing.net/api` via Firebase
Hosting rewrite. This skips WAF until Cloudflare is live. Document as a temporary state in
SECRETS.md. Remove interim CNAME when CF onboarding completes.

### 2.4 WAF + rate limiting rules

**Hard dependency from TRD-F3:** the proposal accept-page brute-force protection that TRD-F3 explicitly defers to F6 is the `"Proposal accept page rate limit (e-sign)"` rule below. This rule is a **hard requirement before public go-live of the F3 accept pages** (`/p/{token}/accept`). F3 preprod may operate without it; production accept pages must not go live until this ruleset is applied and verified. Record this as an exit-gate item (see §11).

All rules defined in Terraform via the Cloudflare provider (`cloudflare_ruleset` resource).

```hcl
resource "cloudflare_ruleset" "waf_rate_limits" {
  zone_id = var.cloudflare_zone_id
  name    = "perkins-rate-limits"
  kind    = "zone"
  phase   = "http_ratelimit"

  rules {
    description = "Auth endpoint rate limit"
    expression  = "(http.request.uri.path contains \"/api/auth\" or http.request.uri.path contains \"/__/auth\")"
    action      = "block"
    ratelimit {
      characteristics      = ["ip.src"]
      period               = 60   # seconds
      requests_per_period  = 20   # 20 auth requests/min/IP
      mitigation_timeout   = 600  # block for 10 min
    }
    enabled = true
  }

  rules {
    description = "Proposal accept page rate limit (e-sign)"
    expression  = "http.request.uri.path contains \"/accept\""
    action      = "block"
    ratelimit {
      characteristics     = ["ip.src"]
      period              = 60
      requests_per_period = 10
      mitigation_timeout  = 300
    }
    enabled = true
  }

  rules {
    description = "API general rate limit"
    expression  = "http.request.uri.path contains \"/api/\""
    action      = "block"
    ratelimit {
      characteristics     = ["ip.src"]
      period              = 60
      requests_per_period = 300
      mitigation_timeout  = 120
    }
    enabled = true
  }
}
```

### 2.5 Cloud Armor origin allowlist (hardening)

Restrict Cloud Run origin to accept traffic only from Cloudflare IP ranges:

```hcl
resource "google_compute_security_policy" "cf_allowlist" {
  name = "cloudflare-origin-allowlist"

  # Cloudflare IPv4 ranges (current as of 2026; update when CF publishes changes)
  # Source: https://www.cloudflare.com/ips-v4
  dynamic "rule" {
    for_each = var.cloudflare_ipv4_ranges
    content {
      action   = "allow"
      priority = rule.key + 1000
      match {
        versioned_expr = "SRC_IPS_V1"
        config { src_ip_ranges = [rule.value] }
      }
    }
  }

  rule {
    action   = "deny(403)"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "Default deny"
  }
}
```

`var.cloudflare_ipv4_ranges` = list in `variables.tf`. **Update cadence:** CF IP ranges change
rarely; pin to a known-good list and document update process. Add IPv6 equivalent separately
(`cloudflare_ipv6_ranges` variable, separate security policy rule set).

Attach to Cloud Run via `google_compute_backend_service` if behind a Load Balancer, or via
NEG annotation. If Cloud Run is directly addressed (current state: no LB), Cloud Armor is not
applicable until a GFE LB fronts it — document as a hardening gap and add the LB in a future
wave, or accept CF WAF as the sole rate-limiting layer at this scale.

---

## 3. Tenant provisioning UI (platform_admin)

### 3.1 Target: <1 hour from zero to first admin login

Provisioning flow:
```
platform_admin clicks "New Tenant"
  → Form: name, slug, admin_email, plan (for future billing; free tier default)
  → POST /internal/tenants  [creates DB row, seeds configs, creates GCIP tenant, sends invite]
  → UI shows provisioning status (polling GET /internal/tenants/{id}/status)
  → When complete: "Invite sent to {admin_email}" + copy invite link
```

### 3.2 `POST /internal/tenants` — provisioning endpoint

Platform_admin role required. Steps performed atomically where possible:

```python
def provision_tenant(name: str, slug: str, admin_email: str, db: Session) -> dict:
    """Create a new tenant end-to-end.

    1. Validate slug uniqueness.
    2. INSERT into tenants (status='provisioning').
    3. Seed tenants.settings with platform defaults (from PlatformConfig).
    4. Create GCIP tenant via Firebase Admin SDK:
         tenant = auth.tenant_manager().create_tenant(
             display_name=name,
             enable_email_link_sign_in=True,
             email_privacy_config={"enable_improved_email_privacy": True}
         )
    5. INSERT into tenant_gcip_map (tenant_id, gcip_tenant=tenant.tenant_id).
    6. Add admin_email to tenant_default_admins for new tenant_id.
    7. Send invite email via Firebase Admin SDK:
         link = auth.tenant_manager().get_tenant(gcip_tenant_id)  # scoped auth
         action_code = auth.generate_sign_in_with_email_link(admin_email, settings)
         # embed ?tenant=<gcip_tenant_id>&oobCode=... in the link
    8. UPDATE tenants SET status='active'.
    9. Return {tenant_id, gcip_tenant_id, invite_link}.
    """
```

Rollback on failure: if any step fails after step 2, set `tenants.status = 'provisioning_failed'`
and log the error. The GCIP tenant (if created) must be deleted via Admin SDK on rollback.
Platform_admin can retry or manually clean up via the GCIP console.

**Offboard/seed ownership:** `tenant_offboard_log`, `platform_admins`, and `tenant_default_admins` are owned by F4's migration 0018. F6's `provision_tenant()` and `offboard_tenant()` calls reference these tables; they do not re-create them. Any seed operations in F6's migration 0020 use `INSERT ... ON CONFLICT DO NOTHING` to remain idempotent with respect to 0018.

### 3.3 Admin UI: Tenants tab (platform_admin only)

```
Admin → Tenants (visible only to platform_admin)
  ├─ Tenant list: name | slug | status | MAU | created_at | actions
  ├─ [+ New Tenant] button → provisioning form
  └─ Per-tenant: [View usage] [Edit settings] [Offboard]
```

Offboard button calls `DELETE /internal/tenants/{id}` (F5 `offboard_tenant()` function,
now wired to the endpoint). Requires a confirmation dialog with the tenant name typed.

### 3.4 New API endpoints (platform_admin only)

```
POST   /internal/tenants                     # provision new tenant
GET    /internal/tenants                     # list all tenants + status
GET    /internal/tenants/{id}/status         # provisioning status (polling)
DELETE /internal/tenants/{id}               # offboard (calls F5 offboard_tenant())
POST   /internal/tenants/{id}/resend-invite  # resend admin invite
GET    /internal/tenants/{id}/usage          # usage metering summary (from Cloud Logging)
```

All `/internal/*` routes are blocked at the Cloudflare WAF edge (WAF custom rule:
`URI path begins with /internal → block` for all source IPs except `platform_admin`
authenticated sessions). Defense-in-depth: the FastAPI router also enforces `platform_admin`
role on every `/internal` route via a router-level dependency.

---

## 4. Per-tenant SSO (GCIP SAML/OIDC)

### 4.1 How it works

GCIP supports per-tenant IdP configuration. When a tenant wants SSO (Microsoft Entra, Okta,
Google Workspace, etc.), a platform_admin or tenant admin configures the IdP in the GCIP
tenant via the Admin SDK or GCIP console.

**Cost:** $0.015/MAU for SAML/OIDC IdPs. Email/password and Google sign-in remain free ≤50k MAU.

### 4.2 UI surface (Admin → Users → SSO)

Visible to tenant `admin` role (not `platform_admin`-only; each tenant manages their own SSO).

```
Admin → Users → SSO
  ├─ [+ Add Identity Provider]
  │    ├─ Type: SAML | OIDC
  │    ├─ SAML: Entity ID, SSO URL, Certificate (PEM)
  │    └─ OIDC: Issuer URL, Client ID, Client Secret
  └─ Active providers list + [Remove]
```

API endpoints (admin role, tenant-scoped):
```
GET    /admin/sso/providers           # list configured IdPs for this tenant
POST   /admin/sso/providers           # add IdP (calls GCIP Admin SDK per-tenant)
DELETE /admin/sso/providers/{idp_id}  # remove IdP
```

The SPA sign-in flow already handles `auth.tenantId` (set from invite link; §4.3 of TRD-F4).
SAML/OIDC providers are surfaced as additional sign-in buttons when configured. No SPA changes
needed beyond the provider list rendering.

### 4.3 Terraform

GCIP per-tenant IdP config is runtime data (not infra); it is managed via Admin SDK, not
Terraform. The `google_identity_platform_tenant_inbound_saml_config` Terraform resource
exists but is awkward for runtime-managed tenants. Document this as an explicit R3 exception:
tenant SSO IdP configs are owned by the Admin SDK at runtime, not Terraform. Record this
exception in `infra/README.md`.

---

## 5. Security re-review (R2)

Before F6 exit, run the full R2 review with **both** `architect` and `critic` agents, scoped
to the entire F4–F6 surface:

Mandatory review checklist items:
- RLS policy correctness on all tenant-scoped tables (F4)
- Session pattern: `SET LOCAL` isolation proof (F4)
- GCIP token claim mapping: no privilege escalation path (F4)
- `platform_admin` impersonation path: can it be abused to exfiltrate cross-tenant data? (F4)
- Cloudflare WAF rules: bypass possibilities (HTTP method confusion, header injection) (F6)
- `/internal/*` route protection: WAF + FastAPI role dependency both required (F6)
- E-sign accept page: token entropy, replay protection, timing attacks (F3 seam) (F6)
- Proposal accept token: 404-indistinguishable for unknown/expired tokens (F3)
- Secret Manager per-tenant paths: IAM blast radius if one SA is compromised (F5)
- Offboarding: is the cascade complete? Can a deleted tenant's data be accessed after deletion? (F5)
- CI grep gate: is it exhaustive? (F4/F5)

All HIGH/CRITICAL findings must be fixed before F6 exits. Record the review verdict in
`.omc/plans/` or the F6 wave notes.

---

## 6. Load pass

Not a load test framework — a structured manual + scripted validation that the system handles
concurrent multi-tenant traffic without cross-tenant data leakage or degraded p99 latency.

### 6.1 Scenarios

| Scenario | Method | Pass criterion |
|---|---|---|
| 2 tenants, 50 concurrent API requests each | `locust` (pinned in `dev-requirements.txt`) | p99 < 2s; zero cross-tenant responses |
| pgvector search under RLS (10k chunks each tenant) | `pytest` benchmark | p99 recall < 500ms |
| Render job for 2 tenants simultaneously | Cloud Run Job trigger | Both complete; GCS output in correct tenant prefix |
| 20 concurrent proposal accept page loads | `locust` | p99 < 1s; rate limit not triggered for normal load |

### 6.2 Scaling lever documentation

Add `docs/scaling-levers.md` (not a TRD task — one paragraph in F6 release notes suffices):

> **pgvector + RLS at scale:** As tenant count grows, `HNSW` index recall degrades when
> `ef_search` must scan many filtered-out rows. The pre-planned mitigation is list-partitioning
> the `chunks` table by `tenant_id` (`PARTITION BY LIST (tenant_id)`). Each partition gets its
> own HNSW index, eliminating cross-tenant index scan waste. This is a pure DDL change with no
> app-layer impact; trigger it when p99 recall exceeds 500ms under load with ≥10 active tenants.
> Migration: `CREATE TABLE chunks_p1 PARTITION OF chunks FOR VALUES IN (1)` + HNSW index per
> partition. The `tenant_isolation` RLS policy applies identically to partitioned tables.

---

## 7. Terraform changes (`infra/main.tf`)

### 7.1 Cloudflare provider

```hcl
# infra/versions.tf (add to required_providers)
cloudflare = {
  source  = "cloudflare/cloudflare"
  version = "~> 4.0"
}

# infra/variables.tf (add)
variable "cloudflare_zone_id"    { type = string; sensitive = false }
variable "cloudflare_api_token"  { type = string; sensitive = true  }
variable "cloudflare_ipv4_ranges" { type = list(string) }

# infra/main.tf (add provider config)
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
```

`cloudflare_api_token` is sourced from Secret Manager at plan time via a `data` block or
passed via `TF_VAR_cloudflare_api_token` from `scripts/deploy.sh`. Never committed to git.

### 7.2 DNS records (import existing + add app subdomain)

```hcl
# All existing DNS records imported first (see §2.1 step 3)

resource "cloudflare_record" "app_cname" {
  zone_id = var.cloudflare_zone_id
  name    = "app"
  type    = "CNAME"
  value   = "<firebase-hosting-target>.web.app"
  proxied = true   # orange cloud; CF handles TLS + WAF
  ttl     = 1      # auto (proxied)
}
```

MX, SPF, DKIM, and all other imported records are managed in Terraform after import.

### 7.3 WAF + rate limiting

As shown in §2.4 (`cloudflare_ruleset` resource).

### 7.4 Cloud Run domain mapping

As shown in §2.2 (`google_cloud_run_domain_mapping` resource).

### 7.5 Cloud Armor (hardening; apply after CF IPs stable)

As shown in §2.5. Gated on having a GFE LB in front of Cloud Run. If Cloud Run is still
directly addressed at F6 completion, document the LB requirement as a post-F6 hardening task.

### 7.6 Secret for Cloudflare token

```hcl
resource "google_secret_manager_secret" "cloudflare_token" {
  secret_id = "cloudflare-api-token"
  replication { auto {} }
}
# Version created manually by Jon; not in Terraform (secret values are not in state)
```

---

## 8. Migrations

File: `infra/migrations/0020_f6_provisioning.sql`

**Important:** must be `.sql` — `scripts/apply_migrations_connector.py` globs `*.sql` only. A `.py` file would be silently skipped.

**Ownership:** `tenant_offboard_log` and `platform_admins` are owned by F4's migration 0018. F6 references to these objects (steps 2–3 below) are idempotent no-ops — use `INSERT ... ON CONFLICT DO NOTHING` for seeding and `CREATE TABLE IF NOT EXISTS` guards if any table reference is needed.

1. No schema changes needed for tenant provisioning (tables exist from F4's 0018).
2. Add `tenant_gcip_map` entry for existing tenants if any real GCIP tenants were created
   manually during F4/F5 development (check before running; idempotent: `INSERT ... ON CONFLICT DO NOTHING`).
3. Seed `platform_admins` with Jon's email if not already done in F4 migration (idempotent: `INSERT ... ON CONFLICT DO NOTHING`).

---

## 9. TEST PLAN

Tests written first; each must be red before implementation.

### Unit tests (`tests/test_provisioning.py`)

```
test_provision_tenant_creates_db_row()
    — POST /internal/tenants → tenant row exists with status='active'

test_provision_tenant_idempotency_on_slug_conflict()
    — duplicate slug → 409, no partial state

test_provision_tenant_rollback_on_gcip_failure()
    — mock GCIP SDK raises → tenant status='provisioning_failed', no orphan in DB

test_provision_tenant_requires_platform_admin()
    — admin-role token → 403

test_offboard_endpoint_wired_to_f5_function()
    — DELETE /internal/tenants/{id} calls offboard_tenant(); verifies cleanup

test_resend_invite_sends_email()
    — POST /internal/tenants/{id}/resend-invite calls Firebase Admin SDK sign-in link
```

### Unit tests (`tests/test_sso.py`)

```
test_add_saml_provider_stores_in_gcip()
test_add_oidc_provider_stores_in_gcip()
test_list_providers_returns_configured()
test_remove_provider_calls_gcip_delete()
test_sso_endpoints_require_admin_role()
```

### Integration / behavioral tests

```
test_onboard_tenant_under_60_minutes()
    — timed wall-clock test: provision → seed → GCIP tenant → invite link generated
      within 60 seconds of API call (the "< 1 hour" criterion is dominated by human
      steps; this tests the automated portion)

test_cloudflare_waf_blocks_internal_routes()
    — requires CF test mode or mock; verify /internal/* returns 403 without
      platform_admin auth (FastAPI layer enforced in CI; CF layer in staging)

test_drift_clean_after_f6()
    — terraform plan exits 0; ansible --check changed=0
```

### Security re-review (non-automated, R2)

As described in §5. Verdict recorded before exit gate.

### Load pass

As described in §6.1. Results recorded (p99 timings, zero cross-tenant responses observed).

---

## 10. Implementation steps

1. Write all tests in §9 → confirm red for correct reasons
2. Add Cloudflare Terraform provider to `infra/versions.tf` + `variables.tf`
3. Jon creates Cloudflare token → stored in Secret Manager → Terraform variable wired
4. Import existing `perkinsroofing.net` DNS records into Terraform state
5. Add `app` CNAME record + WAF ruleset to `infra/main.tf`; `terraform apply`
6. Verify MX/SPF/DKIM intact: `dig MX perkinsroofing.net`; send test email
7. Jon changes Tucows nameservers → wait for propagation → verify
8. Add Cloud Run domain mapping to Terraform; `terraform apply`
9. Implement `POST /internal/tenants` provisioning endpoint + Admin SDK GCIP tenant creation
10. Implement `GET/DELETE /internal/tenants` endpoints; wire `offboard_tenant()` from F5
11. Implement `/admin/sso/providers` endpoints (SAML/OIDC via GCIP Admin SDK)
12. Add Tenants tab to Admin UI (platform_admin conditional render)
13. Add SSO tab to Admin → Users (tenant admin conditional render)
14. Migration `0020_f6_provisioning.sql` — must be `.sql`, not `.py`
15. Run security re-review (R2): architect + critic agents; fix all HIGH/CRITICAL
16. Run load pass scenarios (§6.1); record results
17. `scripts/drift_check.sh` → no drift (R4)
18. Onboard a test tenant end-to-end; timer < 1 hour
19. Confirm Perkins login unchanged post-NS change

---

## 11. Exit gate

All of the following must be true before F6 is marked done:

- [ ] `app.perkinsroofing.net` serves the SPA and API (verified in browser + curl)
- [ ] Firebase Hosting and Cloud Run certs valid (Full-strict TLS; no mixed-content)
- [ ] WAF rate limit: 21st auth request/min from same IP → blocked
- [ ] WAF accept-page rate limit active and verified (hard requirement from TRD-F3 §3.5 deferral — F3 public accept pages must not go live before this gate passes)
- [ ] `/internal/*` routes return 403 to non-platform_admin tokens (FastAPI layer)
- [ ] Onboard test tenant end-to-end: create → GCIP tenant → invite sent → admin logs in → data isolated → offboard complete in < 1 hr elapsed
- [ ] Perkins login unchanged (existing users authenticate, data intact, no GCIP disruption)
- [ ] DNS: MX/SPF/DKIM records intact post-NS change; email tested
- [ ] Load pass: p99 < 2s under 2-tenant concurrent load; zero cross-tenant responses observed
- [ ] R2 security re-review: no unaddressed HIGH/CRITICAL findings
- [ ] `terraform plan` exits 0 (R4)
- [ ] `pytest --cov=core --cov-fail-under=97` green (R1)

---

## 12. Rollout / rollback

**Rollout order (each step verified before proceeding):**
1. Terraform apply (Cloudflare provider + DNS import + WAF rules) — no user impact yet
2. Add `app` CNAME — no user impact (subdomain is new)
3. NS change at Tucows — highest risk step; verify email immediately after propagation
4. Firebase + Cloud Run domain mapping go live
5. Provisioning endpoint deployed
6. Tenant admin SSO UI deployed
7. Security re-review + load pass
8. First real licensee tenant provisioned

**Rollback:**
- CF WAF: disable rules via Terraform (`enabled = false`); instant
- `app` CNAME: delete record; instant (propagation ≤5 min on CF)
- NS change: revert Tucows to original nameservers; propagation up to 48 hrs — this is the
  hardest rollback; mitigated by importing all records before the NS change (original zone
  data is intact at Tucows during propagation window)
- Provisioning endpoint: feature-flag the route (`if settings.PROVISIONING_ENABLED`); toggle
  env var in Cloud Run revision without code deploy
- GCIP tenant SSO: delete IdP config via GCIP console; users fall back to email/password

---

## 13. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| MX records missed before NS change → email outage | Medium | Mandatory pre-check: `dig MX @cf-ns` before NS cutover; checklist step in §10 |
| Cloudflare NS propagation delays CI timeline | Low | Interim CNAME option (§2.3) unblocks development |
| GCIP tenant creation fails midway → orphaned DB row | Low | Rollback in provisioning function (§3.2); `platform_admin` can clean up |
| WAF rate limits block legitimate burst traffic | Low | Tune limits post-go-live; start permissive, tighten based on Cloud Logging data |
| Cloud Armor LB requirement blocks origin hardening | Medium | Accept CF WAF as sole edge layer at this scale; LB is post-F6 hardening |
| Security review finds HIGH finding post-merge | Low (R2 pre-gate) | R2 is an exit gate; wave does not close until all HIGH findings fixed |
| pgvector recall degrades before partition migration | Low (single-digit tenants) | Documented lever; trigger when p99 > 500ms |

---

## 14. Unresolved questions

1. **Cloudflare zone ID**: Jon provides this when creating the API token (jarvis #330). Needed before Terraform variables can be populated.
2. **`perkinsroofing.net` registrar**: Tucows via Amber (tracked ask). NS change requires Amber's action. Confirm Amber has been contacted and has agreed to make the change on request.
3. **Firebase Hosting custom domain Terraform support**: `google_firebase_hosting_custom_domain` resource exists in the Google provider but may require beta provider. Verify provider version compatibility; if not supported, document as manual step and track as R3 gap.
4. **Cloud Run domain mapping with path routing**: Cloud Run domain mappings are per-service and route all traffic, not path-prefixed. The `/api/*` vs `/*` split must be done at the Cloudflare edge (Transform Rule or Worker), not at the Cloud Run mapping. Confirm Cloudflare plan tier supports Transform Rules (available on Free plan as of 2026).
5. **GCIP Admin SDK for tenant creation**: `firebase-admin >= 7.5` (already pinned in `app/requirements.txt`) supports `auth.tenant_manager()` for multi-tenant operations — this open question is resolved. No version update needed; confirm the pin is present before implementing the provisioning endpoint.
6. **Load pass tooling**: neither `hey` nor `locust` is pre-installed in the dev environment. **Chosen tool: `locust`** — pip-installable, scriptable, supports parametrized multi-tenant scenarios. Add `locust` as a pinned entry in `dev-requirements.txt` (e.g. `locust>=2.20`). A `scripts/load_test.sh` wrapper must be provisioned and tested before the load pass runs — do not attempt the load pass without first confirming `locust` is installed and the `locustfile.py` is written.
