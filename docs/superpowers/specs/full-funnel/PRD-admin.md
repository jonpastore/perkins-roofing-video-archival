# PRD — Admin Section
**Platform:** Perkins v2 full-funnel (multi-tenant) · **Section:** Admin
**Version:** 1.0 · **Date:** 2026-07-08 · **Author:** DeGenito AI
**Status:** DRAFT (R2 fixes applied — pending Jon approval)

---

## 1. Purpose

The Admin section is the operator control plane for the Perkins v2 platform. It surfaces
per-section configuration tabs that govern how each functional area (Knowledge Base, Marketing,
Estimating, Quoting) behaves for a given tenant, plus the cross-cutting concerns of user
management and (for DeGenito staff only) tenant provisioning.

Admin is deliberately narrow: it configures the platform; it does not duplicate any of the
functional UIs it governs. The separation keeps role boundaries clean — a `web_admin` can
publish content without touching pricing; a `sales` user can build proposals without seeing
brand kit or model thresholds.

---

## 2. Personas & User Stories

### 2.1 Tenant Admin (`admin` role, per-tenant)
The owner or office manager of a roofing company using the platform. Has full access within
their own tenant. Cannot see or touch any other tenant's data.

| ID | User Story |
|----|-----------|
| UA-01 | As a tenant admin, I can navigate to Admin → Knowledge Base to configure which YouTube channels feed the corpus, so I control what the AI draws from. |
| UA-02 | As a tenant admin, I can set the abstain threshold and FAQ policy without touching code, so I can tune conservative vs. confident AI behavior per our brand voice. |
| UA-03 | As a tenant admin, I can upload our logo, brand colors, fonts, and intro/outro clips in Admin → Marketing, so every generated asset reflects our identity. |
| UA-04 | As a tenant admin, I can edit and version our pricing configuration in Admin → Estimating, see its RFC 8785 SHA-256 hash, and know exactly which config produced any quote. |
| UA-05 | As a tenant admin, I can create and manage proposal templates and T&C library entries in Admin → Quoting, so our proposals always have the right legal language. |
| UA-06 | As a tenant admin, I can invite team members by email (internal Workspace lookup or external free-text), assign their role, and revoke access, all from Admin → Users & Roles. |
| UA-07 | As a tenant admin, I cannot delete accounts flagged as `is_default_admin`, so I cannot accidentally lock myself out. |

### 2.2 Platform Admin (`platform_admin` role, DeGenito-only)
The DeGenito engineer or account manager who provisions new licensees. Cross-tenant. This role
corresponds to the "SaaS Web Admin" in the Ez-Bids proposal, generalized to the multi-tenant
platform.

| ID | User Story |
|----|-----------|
| UP-01 | As a platform admin, I can create a new tenant (name, slug, status), seed it with default pricing and template configs, and provision its GCIP tenant in one workflow. |
| UP-02 | As a platform admin, I can send the first admin invite to a newly created tenant. |
| UP-03 | As a platform admin, I can view per-tenant usage metering (LLM tokens, STT minutes, render minutes) so I can track consumption for future billing. |
| UP-04 | As a platform admin, I cannot access or modify any tenant's operational data (quotes, corpus, customer records) — only configuration and provisioning. |

### 2.3 Regular User (`sales`, `web_admin` roles)
Has no access to Admin. Attempting to navigate to any Admin route returns a role-gated
"access denied" panel, not a 404, so users know the section exists and who to ask.

---

## 3. Functional Requirements

Each requirement is numbered, testable, and tagged with the wave that delivers it.

### 3.1 Admin Shell & Navigation (F1)

| # | Requirement |
|---|------------|
| A-01 | Admin appears as the fifth top-level sidebar item, below Quoting. It is visible only to users with `admin` or `platform_admin` role. |
| A-02 | Admin contains six sub-tabs: Knowledge Base · Marketing · Estimating · Quoting · Users & Roles · Tenants. All six are present in the navigation from F1 forward. |
| A-03 | Each sub-tab that has not yet been filled in by its wave shows a placeholder panel: tab label + "Configuration coming in [wave name]" message. No broken routes. |
| A-04 | The Tenants sub-tab is hidden for `admin` role and visible only to `platform_admin`. An `admin` navigating to `/admin/tenants` receives the role-gated access-denied panel. |
| A-05 | All Admin route changes are captured in the router without breaking existing bookmark-able URLs for other sections. |
| A-06 | The Admin section passes the existing 100% `core/authz.py` test coverage gate; new action strings added to the matrix are covered by unit tests. |

### 3.2 Authz Extensions (F1, hardened in F4)

The existing `core/authz.py` `_MATRIX` extends in F1. **TRD-F1 §11 is the single normative
registry of section-scoped action strings.** This section cites those strings; it does not
redefine them. The `can()` function signature does not change.

**Action strings per tab, from TRD-F1 §11:**

| Admin tab | Config-gating action (TRD-F1 §11) | Roles permitted |
|-----------|-----------------------------------|----------------|
| Knowledge Base config | `admin_config` | `admin` |
| Marketing config | `admin_config` | `admin` |
| Estimating config | `admin_config` | `admin` |
| Quoting config | `admin_config` | `admin` |
| Users & Roles | `admin_users` | `admin` |
| Tenants | `admin_tenants` | `platform_admin` only |

Full section-scoped action list (KB, Marketing, Estimating, Quoting, and cross-cutting) is in
TRD-F1 §11. New F2/F3/F5 endpoints use those exact strings in their `require_role()` calls.

New `platform_admin` role entry in `_MATRIX` (TRD-F1 §11):
```python
"platform_admin": {"admin_tenants", "admin_users"},
```
`platform_admin` does **not** inherit `"*"` — it has a narrow, explicitly enumerated set of
cross-tenant actions and cannot perform tenant-operational actions (quoting, corpus writes, etc.).
See TRD-F4 for session/impersonation mechanics and enforcement.

| # | Requirement |
|---|------------|
| A-07 | `core/authz.py` adds all section-scoped action strings listed in TRD-F1 §11 to the `_MATRIX` for `web_admin`, `sales`, and `admin` roles, plus the `platform_admin` role entry. All new strings are unit-tested. |
| A-08 | FastAPI route decorators for all Admin config endpoints use `require_role("admin_config")` (or the specific section action from TRD-F1 §11), so a `sales` user calling them directly receives 403. |
| A-09 | `DEFAULT_ADMINS` per-tenant lookup is delivered by TRD-F4's `tenant_default_admins` table (F4 wave). The env-var path remains functional for tenant 1 as a seed/fallback and logs a deprecation warning when used. |
| A-10 | `is_default_admin` flag logic (currently in `api/routes/users.py`) moves to a per-tenant lookup against the `tenant_default_admins` table (TRD-F4). Perkins behavior unchanged post-F4 migration. |

### 3.3 Knowledge Base Tab (F5)

Manages the corpus that powers Search/Ask and FAQ.

| # | Requirement |
|---|------------|
| KB-01 | Displays list of configured YouTube channel sources (channel ID, name, last-synced timestamp, video count). |
| KB-02 | Allows adding/removing channel sources; triggers a manual ingest or schedules next auto-ingest. |
| KB-03 | Exposes a numeric `abstain_threshold` slider (0.0–1.0, default configurable); saved to `platform_config` under key `kb_abstain_threshold`. |
| KB-04 | Exposes FAQ policy toggle (Enabled / Disabled / Review-only) and FAQ review queue link. |
| KB-05 | All KB config values are tenant-scoped; changing them affects only the current tenant's corpus behavior. |

### 3.4 Marketing Tab (F5)

Manages brand assets and content generation parameters.

| # | Requirement |
|---|------------|
| MK-01 | Brand kit upload: logo (PNG/SVG ≤2 MB), primary/secondary/accent hex colors (validated), heading font + body font (Google Fonts name or upload). |
| MK-02 | Intro/outro clip upload (MP4 ≤500 MB); stored in GCS under `tenants/{id}/brand/`. |
| MK-03 | Voice sample upload for ElevenLabs voice cloning (WAV/MP3, ≤30 min); stored in GCS under `tenants/{id}/voice/`. |
| MK-04 | Caption prompt version selector: shows the active caption prompt version (default: v5); allows pinning to a prior version with a warning. |
| MK-05 | Publish cadence: posts-per-week target (int 1–21), seed percentage (0–100%), configured per platform channel (YouTube / Instagram / TikTok). |
| MK-06 | Social account connection: OAuth flow entry points for each platform; shows connection status (connected / expired / not connected) per account. |
| MK-07 | Safety-gate denylist: free-text list of blocked terms/phrases added to the content safety gate; stored in `platform_config` under `safety_denylist`. |
| MK-08 | All marketing config values are tenant-scoped; a second tenant's brand kit is fully independent. |

### 3.5 Estimating Tab (F2)

Manages pricing configuration, branches, and measurement provider.

| # | Requirement |
|---|------------|
| ES-01 | Lists all pricing config versions for this tenant (version number, created_at, created_by, status: active/archived). |
| ES-02 | Provides a structured JSON editor (or form-based editor) for the active `pricing_configs` JSONB row; saving creates a new version (immutable append). |
| ES-03 | Displays the RFC 8785 canonical SHA-256 hash of the active config after every save, next to the version number. Clicking the hash copies it to clipboard. |
| ES-04 | Lists configured branches (e.g., Miami, Jupiter, Naples) with their default `code_zone`; allows adding/editing branches. |
| ES-05 | Per-branch: county coverage list (Broward, Miami-Dade → HVHZ; Palm Beach, Lee, St. Lucie → FBC) with per-county override fields (permit fees, materials-tax flag, county-specific line items). |
| ES-06 | Measurement provider selector: Google Solar API or Manual Entry; toggling saves to `platform_config`. The Solar API key is configured via `SOLAR_API_KEY` in Secret Manager (TRD-F2b §5). SquareQuote adapter was dropped per locked architecture decision. |
| ES-07 | If Google Solar API is selected and `SOLAR_API_KEY` is not yet configured in Secret Manager, shows an inline prompt to add the key via Settings → Secrets. No silent fallback to manual entry. |
| ES-08 | All estimating config is tenant-scoped. The Exhibit B seed fixture for Perkins (tenant 1) is the canonical default for newly provisioned tenants until overridden. |

### 3.6 Quoting Tab (F3)

Manages proposal templates, T&C library, deposit policy, and reminder cadence.

| # | Requirement |
|---|------------|
| QT-01 | Lists all proposal templates for this tenant (name, last-modified, status: active/draft). |
| QT-02 | Template editor: branded HTML with logo, colors, cover page layout, T&C section selector, attachment slots. Preview renders via Gotenberg to a PDF in a side panel. |
| QT-03 | T&C library: add/edit/archive named T&C blocks (e.g., "Standard Residential", "Commercial"); referenced by templates by ID so template PDFs stay up-to-date automatically. |
| QT-04 | Deposit policy config: default deposit percentage (0–100) OR fixed dollar amount; shown on the acceptance confirmation page and in the job-handoff notification. |
| QT-05 | Reminder cadence: enable/disable automated follow-up nudges; configurable intervals (e.g., 3 days, 7 days after sent); max reminder count. |
| QT-06 | All quoting config is tenant-scoped. The default template for new tenants is a plain branded shell; Perkins' templates are their own. |

### 3.7 Users & Roles Tab (F1 — already partially shipped)

Consolidates the existing Users page (`web/src/pages/Users.tsx`) into the Admin sub-tab. No
functional regressions.

| # | Requirement |
|---|------------|
| UR-01 | The Users & Roles tab renders the existing Users page content at `/admin/users-roles`; the old `/users` route redirects here. |
| UR-02 | User list shows: display name, email, role badge, `is_default_admin` shield icon, last-sign-in. |
| UR-03 | Role assignment dropdown: `admin`, `web_admin`, `sales`, (empty = no access). Changing own role shows a confirmation dialog. |
| UR-04 | Invite flow: Internal (Workspace directory lookup) / External (free-text email) toggle. Fields: email, display name (auto-filled for Internal), role. Sends Firebase invite via `POST /admin/users/invite`. |
| UR-05 | Delete is disabled (button hidden + API returns 403) for any user whose email appears in the tenant's `default_admins` config. |
| UR-06 | The `platform_admin` role does not appear in the tenant admin's role dropdown. It can only be granted by another `platform_admin` via the Tenants tab provisioning flow. |

### 3.8 Tenants Tab (F6, platform_admin only)

Allows DeGenito staff to provision and manage licensee tenants without direct DB access.

| # | Requirement |
|---|------------|
| TN-01 | Tenant list: name, slug, status (active/suspended/offboarding), created_at, usage summary (tokens/STT-min/render-min current month). |
| TN-02 | Provision tenant wizard (3 steps): (1) Tenant name + slug + initial contact email; (2) Seed config selection (clone Perkins defaults, or blank); (3) GCIP tenant creation + first admin invite. All three steps are transactional — partial failure rolls back and surfaces the error. |
| TN-03 | Per-tenant detail view: config summary, usage metering chart (current + last 3 months), user count, status toggle (active ↔ suspended). |
| TN-04 | Usage metering reads from structured-log–emitted counters (LLM tokens, STT minutes, render minutes) per tenant per month. No new metering infrastructure required in F6; counters are already emitted on the existing log path (plan §3.10). |
| TN-05 | Tenant offboarding: status → offboarding + scheduled deletion confirmation (2-step); actual cascade delete of RLS-scoped rows, GCS prefix, GCIP tenant, and audit record is a separate admin-CLI command (not in the UI in v1). |
| TN-06 | The Tenants tab and all `/admin/tenants/*` API routes require `platform_admin` role. A request from any other role returns 403, same response shape as other role-denied routes. |

---

## 4. Acceptance Criteria

| ID | Criterion | Wave |
|----|-----------|------|
| AC-01 | All six Admin sub-tabs are reachable via the sidebar; placeholder panels display for unfilled tabs; no 404s on any Admin route. | F1 |
| AC-02 | A user with `sales` or `web_admin` role cannot reach any Admin route (403 from API; access-denied panel in UI). | F1 |
| AC-03 | `core/authz.py` 100% coverage maintained after adding `kb_config`, `marketing_config`, `estimating_config`, `quoting_config`, and `platform_admin`. | F1 |
| AC-04 | `is_default_admin` protection: deleting a default admin user via API returns 403; delete button is hidden in the UI for that user. | F1 |
| AC-05 | A versioned pricing config save produces a new `pricing_configs` row, the previous row status = archived, and the SHA-256 hash displayed matches the RFC 8785 canonical encoding of the new row's JSONB. | F2 |
| AC-06 | Setting the measurement provider to Google Solar API with `SOLAR_API_KEY` absent from Secret Manager shows the inline prompt to configure it; no silent fallback to manual entry occurs. | F2 |
| AC-07 | A proposal template saved in Admin → Quoting is available in the Proposal Builder template selector for the same tenant and not visible to any other tenant. | F3 |
| AC-08 | Deposit policy and reminder cadence saved in Admin → Quoting are reflected on the next proposal created. | F3 |
| AC-09 | `platform_admin` role can create a tenant, seed it, and issue the first invite in a single wizard flow; all three steps succeed or the entire wizard rolls back. | F6 |
| AC-10 | A `platform_admin` cannot read or write any tenant's quotes, corpus, or customer records via the API. | F6 |
| AC-11 | Usage metering totals in the Tenants tab match the sum of structured-log counters for the tenant + month via an independent log query. | F6 |
| AC-12 | All Admin config values are tenant-scoped: updating a value for tenant A produces no observable change in tenant B. (Covered by the ≥30 tenancy-denial tests required in F4.) | F4 |

---

## 5. Non-Goals (v1)

These are explicitly out of scope; do not implement them in this section.

- **Billing / invoice generation.** Usage metering is recorded now; billing UI and payment processing are not v1 deliverables.
- **Per-tenant custom domains.** Deferred until ~10 tenants; covered in plan §4.
- **Per-tenant SAML/OIDC/SSO configuration UI.** The GCIP backend supports it; the Admin UI for provisioning it is post-v1.
- **Tenant-level audit log viewer.** Audit records are written; search/export UI is not v1.
- **Role-based field-level permissions.** Authz is action-grained, not field-grained.
- **Self-service tenant signup.** Provisioning is operator-initiated via the Tenants tab.
- **Accounting / QuickBooks integration.** Tim's backend stays separate.
- **Engagement simulation or bot management.** Explicitly excluded from the product.

---

## 6. Multi-Tenant Considerations

### 6.1 Config isolation

Every config value surfaced in Admin is stored in a tenant-scoped table (either a
`platform_config` row with `tenant_id`, or a dedicated table like `pricing_configs` or
`proposal_templates`). The RLS policy `USING (tenant_id = current_setting('app.tenant_id')::int)`
ensures that even a raw SQL mistake cannot read another tenant's config rows. The ORM-level
`tenant_id` filter is a belt-and-suspenders second layer.

### 6.2 Secrets

Per-tenant API credentials (social OAuth tokens, ElevenLabs key, Solar API key) are stored in
Secret Manager under `tenants/{id}/social/{platform}`, `tenants/{id}/elevenlabs_key`, etc. The
Admin UI initiates OAuth flows and writes secrets via `PUT /config/secrets` (existing endpoint);
the secret key path prefix enforces tenant isolation at the GCP IAM level. Platform-level secrets
(the Firebase service account, Gotenberg URL, etc.) are never exposed in the per-tenant Admin UI.

### 6.3 GCS prefixes

Brand assets (logo, intro/outro, voice samples) are stored under `tenants/{id}/brand/` and
`tenants/{id}/voice/`. Upload endpoints validate that the `tenant_id` in the path matches the
caller's token claim before writing. Signed-URL generation for playback similarly enforces this.

### 6.4 Usage metering counters

LLM token counts, STT minutes, and render minutes are emitted on the existing structured-log
path (Cloud Logging → BigQuery) with `tenant_id` on every log line (plan §3.10). The Tenants
tab aggregates them via a BigQuery read or a daily-rolled counter table — implementation choice
deferred to F6, but no new instrumentation is needed because the fields are already present.

### 6.5 Default admins migration

The current `DEFAULT_ADMINS` env var is a global allowlist. In the multi-tenant model it becomes
a per-tenant `tenant_default_admins` table delivered by TRD-F4. That table holds one row per
(tenant_id, email) and is the canonical source for `is_default_admin` checks post-F4.
`platform_config` remains platform-exempt and is not used for per-tenant default admin storage.
The F4 migration backfills `DEFAULT_ADMINS` (if set) into tenant 1's `tenant_default_admins`
rows. After F4, the env var path is deprecated but still honored for tenant 1 with a log
warning, providing a safe rollback seam during F4 testing.

---

## 7. Dependencies & Open Items

### 7.1 Dependencies

| Dependency | Needed by | Status |
|-----------|-----------|--------|
| `tenants` table + `tenant_id` on tenant-scoped tables | all tab isolation | F0 migration (unbuilt) |
| `tenant_default_admins` table | A-09, A-10, AC-04 | F4 (TRD-F4) |
| Sidebar IA reorg (two-level nav) | A-01, A-02, A-03 | F1 |
| `platform_admin` role in GCIP custom claims | TN-06, UP-01 | F4 (GCIP upgrade) |
| RLS + SET LOCAL session pattern | AC-12 | F4 |
| Gotenberg Cloud Run service | QT-02 (template preview PDF) | F3 |
| BigQuery / log-roll counters for usage metering | TN-04, AC-11 | F6 |
| GCIP tenant provisioning API | TN-02 step 3 | F6 |

### 7.2 Open Items

| # | Item | Owner | Blocks |
|---|------|-------|--------|
| OI-01 | Entity/IP decision: does "Ez-Bids LLC" own the quoting config templates, or the unified platform entity? Affects branding in the Quoting tab and the Tenants provisioning wizard. | Jon + counsel | QT-02, TN-02 |
| OI-02 | Which emails become `platform_admin` at launch? (DeGenito staff list.) Needed to seed the first GCIP custom claim. | Jon/DeGenito | TN-06 |
| OI-03 | Usage metering aggregation method for Tenants tab: BigQuery view vs. daily-rolled Postgres counter table. Cost and latency tradeoff. | Architect review at F6 | TN-04 |
| OI-04 | Sliding-scale boundary rule (lower-inclusive / upper-exclusive) confirmation with Tim — affects pricing config schema for boundary-band display in Estimating tab. | Tim (plan §10.3) | ES-02 |
| OI-05 | ~~SquareQuote API base URL and key structure~~ — CLOSED. SquareQuote adapter dropped per locked decision; measurement provider is Google Solar API or Manual Entry only. | — | ES-06, ES-07 (resolved) |
