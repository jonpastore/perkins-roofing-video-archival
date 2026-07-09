# TRD-F3 — Quoting / Proposals (Wave F3)

**Date:** 2026-07-08  
**Wave:** F3 — commercial deliverable  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Grounding:** full-funnel-plan §6/§8/§9/§11 · CONTINUATION-2026-07-08 §3 · perkins-knowify-teardown · perkins-ezbids-proposal · ENGINEERING_RULES R1–R5

---

## 0. Scope & Non-goals

### In scope

- `customers` + `contacts` + `properties` + `leads` data model
- `proposal_templates` — tenant-branded HTML, self-serve multi-template editor in Admin
- `proposals` — builder, version/revision chain, status machine, accept_token
- `proposal_events` — tracking (sent/viewed/accepted/declined/reminder)
- E-sign lite — tokenized no-login accept page: view → select tier/options → consent checkbox → typed name → accept → audit trail + signed-PDF copy emailed via Resend
- Gotenberg Cloud Run service (HTML→PDF), IAM-locked, Terraformed
- Reminder nudge jobs (Cloud Scheduler via Terraform, SKIP LOCKED)
- Deposit + handoff on acceptance (status field + email notification)
- Knowify migration tooling: XLS customer/catalog import + one-time PDF archive to GCS
- `quoting_*` authz actions wired into `core/authz.py`
- SPA Quoting section: quote list, proposal builder, template editor (Admin), public accept page

### Non-goals (scope gravity fence — do not drift)

- Payment processing of any kind (Stripe, ACH, check capture) in v1
- Full CRM (leads is a status field, not a pipeline, not activities, not SLA timers)
- Accounting / QuickBooks / Knowify job backend integration
- Zapier bridge (optional for Tim post-migration; not in F3)
- Dropbox Sign / SignWell / BoldSign integration (seam only — `ESignProvider` interface stub)
- Native iOS app
- Client portal (Knowify Advanced feature — not v1)
- SMS notifications
- Multi-currency / international tax

---

## 1. Data Model

All tables carry `tenant_id INTEGER NOT NULL REFERENCES tenants(id)` (F0 thin-tenancy convention). RLS is added in F4; F3 uses ORM-layer tenant filter (belt) only. All `created_at` / `updated_at` are naive UTC (`datetime.now(timezone.utc).replace(tzinfo=None)` — matches existing `_utcnow()` convention in `app/models.py`).

### 1.1 `customers`

```sql
CREATE TABLE IF NOT EXISTS customers (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    display_name  VARCHAR(255) NOT NULL,
    company_name  VARCHAR(255),
    email         VARCHAR(255),
    phone         VARCHAR(50),
    knowify_customer_id  VARCHAR(100),          -- nullable; populated by XLS import
    notes         TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_customers_tenant ON customers(tenant_id);
CREATE INDEX IF NOT EXISTS ix_customers_knowify ON customers(tenant_id, knowify_customer_id)
    WHERE knowify_customer_id IS NOT NULL;
```

### 1.2 `contacts`

One customer may have multiple contacts (project manager, billing contact, etc.).

```sql
CREATE TABLE IF NOT EXISTS contacts (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    customer_id   INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name          VARCHAR(255) NOT NULL,
    role          VARCHAR(100),                 -- e.g. "Project Manager", "Owner"
    email         VARCHAR(255),
    phone         VARCHAR(50),
    is_primary    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_contacts_customer ON contacts(customer_id);
```

### 1.3 `properties`

One customer may have multiple job-site properties.

```sql
CREATE TABLE IF NOT EXISTS properties (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id),
    customer_id          INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    street               VARCHAR(255) NOT NULL,
    city                 VARCHAR(100) NOT NULL,
    state                VARCHAR(2)   NOT NULL DEFAULT 'FL',
    zip                  VARCHAR(10),
    county               VARCHAR(100),          -- Broward | Miami-Dade | Palm Beach | Lee | St. Lucie
    code_zone            VARCHAR(10) NOT NULL DEFAULT 'FBC',  -- HVHZ | FBC; per-property, overridable per quote
    knowify_customer_id  VARCHAR(100),          -- mirrors customers.knowify_customer_id for legacy cross-ref
    gcs_pdf_prefix       VARCHAR(500),          -- gs://bucket/tenants/{id}/properties/{prop_id}/archive/ — set on import
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_properties_tenant    ON properties(tenant_id);
CREATE INDEX IF NOT EXISTS ix_properties_customer  ON properties(customer_id);
```

### 1.4 `proposal_templates`

Tenant-branded HTML templates. Multiple per tenant — the key Knowify differentiator.

```sql
CREATE TABLE IF NOT EXISTS proposal_templates (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    name          VARCHAR(255) NOT NULL,        -- display name in Admin dropdown
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    html_body     TEXT NOT NULL,                -- Jinja2-compatible HTML; see §3.2 variable contract
    logo_url      VARCHAR(1000),               -- GCS signed URL or data-URI embedded at render time
    primary_color VARCHAR(7),                  -- hex e.g. "#C0392B"
    accent_color  VARCHAR(7),
    footer_text   TEXT,                        -- T&C short block or link
    tc_attachment_gcs VARCHAR(1000),           -- gs:// path to a PDF attachment appended by Gotenberg
    cover_page_html TEXT,                      -- optional separate cover page HTML; null = no cover
    created_by    VARCHAR(255) NOT NULL,       -- email of admin who created it
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_default_per_tenant
    ON proposal_templates(tenant_id) WHERE is_default = TRUE;
CREATE INDEX IF NOT EXISTS ix_templates_tenant ON proposal_templates(tenant_id);
```

**Only one default per tenant** enforced by partial unique index. When a new default is set, the prior default is cleared in the same transaction.

### 1.5 `proposals`

Core proposal record. A proposal version chain shares the same `root_id`; each edit-after-send produces a new row with `parent_id` pointing to the prior version.

**E-sign terminal-state behaviour:** `GET /p/{token}` returns HTTP 200 with a terminal page for tokens that are valid but in a terminal state — specifically, status `superseded` renders "This proposal has been superseded — please use the link in your most recent email" and status `accepted` renders "You have already accepted this proposal — your signed copy was emailed to you." Unknown or structurally invalid tokens always return 404, served via a constant-time lookup that is indistinguishable from a token that never existed. This design is secure because meaningful state disclosure (superseded vs. accepted) requires prior possession of a valid 512-bit-entropy token; an attacker who can guess or enumerate tokens is not constrained by the terminal-page message.

**Settings keys:** `settings.deposit`, `settings.reminder_cadence_days`, and `settings.license_number` are registered in TRD-F0's canonical `tenants.settings` envelope. F0 owns that schema; F3 reads from it.

**SQLite compatibility note:** `proposal_status`, `proposal_event_type`, and `lead_status` ENUM columns plus `accepted_ip INET` do not exist natively on SQLite. ORM model strategy: use `sa.Enum(..., native_enum=False)` (stored as VARCHAR on SQLite, native ENUM on PostgreSQL) for all three ENUM types, and `sa.String().with_variant(INET(), "postgresql")` for the INET columns. Tests run on SQLite by default; any test that exercises Postgres-only assertions (RLS, INET operators, partial indexes) must be marked `@pytest.mark.postgres` and run against the Postgres fixture defined in TRD-F4 (see F4 §9 `TENANCY_PG_URL` env switch).

```sql
CREATE TYPE proposal_status AS ENUM (
    'draft',
    'sent',
    'viewed',
    'accepted',
    'declined',
    'revision_requested',
    'superseded'
);

CREATE TABLE IF NOT EXISTS proposals (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id),
    customer_id           INTEGER NOT NULL REFERENCES customers(id),
    property_id           INTEGER NOT NULL REFERENCES properties(id),
    template_id           INTEGER REFERENCES proposal_templates(id),

    -- Version chain
    root_id               INTEGER REFERENCES proposals(id),   -- NULL on v1; set to self after insert; all versions share root_id
    parent_id             INTEGER REFERENCES proposals(id),   -- NULL on v1; points to immediate predecessor
    version_number        INTEGER NOT NULL DEFAULT 1,

    -- Content
    title                 VARCHAR(500) NOT NULL,
    quote_snapshot        JSONB NOT NULL,                      -- frozen estimator output + pricing_config_hash; see §3.3
    selected_tier         VARCHAR(50),                        -- 'good' | 'better' | 'best' | NULL (set at accept time)
    selected_options      JSONB,                              -- client line-item selections captured at accept time

    -- Status machine
    status                proposal_status NOT NULL DEFAULT 'draft',

    -- E-sign fields
    accept_token          VARCHAR(86) NOT NULL UNIQUE,        -- URL-safe base64(64 random bytes) = 86 chars; high-entropy single-version token
    accepted_by_name      VARCHAR(255),                       -- typed name from accept page
    accepted_at           TIMESTAMP,
    accepted_ip           INET,
    accepted_ua           TEXT,
    consent_electronic    BOOLEAN,                            -- TRUE = client checked the ESIGN consent checkbox

    -- PDF delivery
    signed_pdf_gcs        VARCHAR(1000),                     -- gs:// path to the signed-proposal PDF stored after acceptance
    signed_pdf_emailed_at TIMESTAMP,                         -- when the PDF copy was emailed to the client

    -- Audit
    created_by            VARCHAR(255) NOT NULL,              -- email of staff who created it
    sent_at               TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_proposals_tenant     ON proposals(tenant_id);
CREATE INDEX IF NOT EXISTS ix_proposals_customer   ON proposals(customer_id);
CREATE INDEX IF NOT EXISTS ix_proposals_root       ON proposals(root_id);
CREATE INDEX IF NOT EXISTS ix_proposals_token      ON proposals(accept_token);  -- lookup on public accept page
CREATE INDEX IF NOT EXISTS ix_proposals_status     ON proposals(tenant_id, status);
```

**Token invariant:** `accept_token` is unique per row. When a new version is created, the old row's status → `superseded` and its token is never reused. The public accept endpoint does a constant-time token lookup and returns 404 for unknown/invalid tokens (indistinguishable from never-existed); it returns HTTP 200 with a terminal page for tokens in a valid terminal state (`superseded` or `accepted`) — see §1.5 preamble for rationale.

**Snapshot invariant:** `quote_snapshot` is written once at send time and never mutated. It contains: the full estimator output dict, the `pricing_config_hash` (RFC 8785 + SHA-256 of the active PricingConfig at send time), the selected tier options presented, deposit policy (% and/or fixed amount) copied from tenant config at send time. Any edit produces a new version row with a new snapshot.

### 1.6 Stub tables added in this migration

The following minimal stub tables are created in migration 0017. They capture objects that are referenced by proposals at acceptance time or needed for Knowify import. Full build-out is post-F3.

#### `jobs` (stub — created on acceptance)

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    proposal_id INTEGER REFERENCES proposals(id),
    status      VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_jobs_tenant ON jobs(tenant_id);
```

Full job/handoff backend build-out (Knowify integration, activity tracking, SLA timers) is post-F3 and out of scope for this wave.

#### `catalog_items` (stub — Knowify import target)

```sql
CREATE TABLE IF NOT EXISTS catalog_items (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    unit            VARCHAR(50),
    unit_price      NUMERIC(10,2),
    knowify_item_id VARCHAR(100),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_catalog_items_tenant ON catalog_items(tenant_id);
```

#### `tc_versions` (stub — T&C version referenced by proposals/consent)

```sql
CREATE TABLE IF NOT EXISTS tc_versions (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    version_tag VARCHAR(50) NOT NULL,
    content_gcs VARCHAR(1000),
    effective_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_tc_versions_tenant ON tc_versions(tenant_id);
```

`proposal_templates.tc_attachment_gcs` references the GCS path of the active `tc_versions` row for a tenant at template-creation time.

### 1.8 `proposal_events`

Immutable audit log. One row per event — never updated.

```sql
CREATE TYPE proposal_event_type AS ENUM (
    'sent',
    'viewed',
    'accepted',
    'declined',
    'revision_requested',
    'reminder_sent'
);

CREATE TABLE IF NOT EXISTS proposal_events (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    proposal_id   INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    event_type    proposal_event_type NOT NULL,
    occurred_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address    INET,
    user_agent    TEXT,
    actor_email   VARCHAR(255),                -- staff email for staff-triggered events; NULL for client events
    metadata      JSONB                        -- reminder_number, revision_note, etc.
);

CREATE INDEX IF NOT EXISTS ix_events_proposal ON proposal_events(proposal_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_events_tenant   ON proposal_events(tenant_id, event_type);
```

### 1.9 `leads`

Lightweight lead capture — a status field, not a CRM. Converting a lead creates a customer + property.

```sql
CREATE TYPE lead_status AS ENUM (
    'new',
    'contacted',
    'qualified',
    'converted',
    'lost'
);

CREATE TABLE IF NOT EXISTS leads (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
    name          VARCHAR(255) NOT NULL,
    email         VARCHAR(255),
    phone         VARCHAR(50),
    source        VARCHAR(100),               -- 'web_form' | 'referral' | 'manual' | 'knowify_import'
    notes         TEXT,
    status        lead_status NOT NULL DEFAULT 'new',
    converted_customer_id  INTEGER REFERENCES customers(id),  -- set on conversion
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_leads_tenant ON leads(tenant_id, status);
```

---

## 2. Authorization

Extend `core/authz.py` `_MATRIX` — new `quoting_*` actions added to the appropriate roles:

```python
# additions to _MATRIX in core/authz.py
"admin":    {"*"},   # unchanged — covers all quoting_* via wildcard
"web_admin": {
    # existing actions unchanged …
    "quoting_view",
    "quoting_create",
    "quoting_send",
    "quoting_manage_templates",
    "quoting_manage_settings",
},
"sales": {
    # existing actions unchanged …
    "quoting_view",
    "quoting_create",
    "quoting_send",
},
```

`quoting_manage_templates` and `quoting_manage_settings` are `admin` + `web_admin` only. The public accept page endpoints are **unauthenticated** — token-gated, no Firebase token required.

---

## 3. Component Design

### 3.1 Template Engine

Templates are tenant-authored HTML stored in `proposal_templates.html_body`. The rendering pipeline is:

1. Load template HTML from DB (tenant-scoped).
2. Substitute Jinja2 template variables (see §3.2).
3. Inject the tenant `logo_url` (signed GCS URL, 1-hour expiry, resolved at render time — never stored in the snapshot).
4. POST rendered HTML to Gotenberg `/forms/chromium/convert/html` → PDF bytes.
5. If `tc_attachment_gcs` is set, download the PDF from GCS and POST a multi-file merge request to Gotenberg `/forms/pdfengines/merge`.
6. Store resulting PDF in GCS at `tenants/{tenant_id}/proposals/{proposal_id}/v{version}/proposal.pdf`.

#### 3.2 Template Variable Contract

Variables injected at render time. Template authors use `{{ variable }}` syntax.

| Variable | Source | Example |
|---|---|---|
| `proposal.title` | `proposals.title` | "Roof Replacement — 123 Main St" |
| `proposal.date` | `proposals.sent_at` formatted | "July 8, 2026" |
| `proposal.version` | `proposals.version_number` | 2 |
| `customer.name` | `customers.display_name` | "Tim Perkins" |
| `customer.company` | `customers.company_name` | "Perkins Roofing" |
| `property.address` | formatted from `properties.*` | "123 Main St, Miami FL 33101" |
| `property.county` | `properties.county` | "Miami-Dade" |
| `property.code_zone` | `properties.code_zone` | "HVHZ" |
| `quote.roof_type` | `quote_snapshot.roof_type` | "Dimensional Shingle" |
| `quote.num_squares` | `quote_snapshot.num_squares` | 28.0 |
| `quote.good_price` | `quote_snapshot.tiers.good.total` | "$18,400.00" |
| `quote.better_price` | `quote_snapshot.tiers.better.total` | "$21,200.00" |
| `quote.best_price` | `quote_snapshot.tiers.best.total` | "$24,800.00" |
| `quote.line_items` | `quote_snapshot.line_items` list | rendered table |
| `deposit.amount` | computed from snapshot deposit policy | "$4,600.00" |
| `deposit.instructions` | `tenant.deposit_instructions` | "Check payable to Perkins Roofing" |
| `tenant.name` | `tenants.name` | "Perkins Roofing" |
| `tenant.license` | `tenant.settings.license_number` | "CCC1234567" |
| `accept_url` | constructed from `accept_token` | "https://app.perkinsroofing.net/p/{token}" |

Undefined variables render as empty string (Jinja2 `Undefined` = silent). The template editor in Admin provides a live preview using dummy data.

### 3.3 `quote_snapshot` JSONB Schema

Written at send time, immutable. Stores everything needed to regenerate the proposal PDF without touching live pricing config.

```json
{
  "pricing_config_hash": "<RFC8785+SHA256 hex>",
  "sent_at_iso": "2026-07-08T14:30:00Z",
  "roof_type": "dimensional_shingle",
  "region": "HVHZ",
  "num_squares": 28.0,
  "code_zone": "HVHZ",
  "branch": "Miami",
  "tiers": {
    "good":   { "label": "Good",   "description": "…", "total": 18400.00, "line_items": [ … ] },
    "better": { "label": "Better", "description": "…", "total": 21200.00, "line_items": [ … ] },
    "best":   { "label": "Best",   "description": "…", "total": 24800.00, "line_items": [ … ] }
  },
  "optional_items": [
    { "id": "ridge_vent", "label": "Ridge Vent (LF)", "unit_price": 8.50, "qty": 42 }
  ],
  "deposit_policy": {
    "mode": "percent",            
    "value": 50,                  
    "amount": 9200.00,
    "instructions": "Check payable to Perkins Roofing"
  },
  "floors": {
    "min_profit_pct": 13,
    "min_profit_plus_oh_pct": 33
  },
  "estimator_version": "1.0.0"
}
```

**Floor preservation:** the `floors` block is copied from the pricing config at send time so post-acceptance audits can verify the floor was met, even if config changes later.

### 3.4 Revision / Version Chain

- **Edit-after-send** is the only path that creates a new version. Drafts are mutated in place.
- On "Send Revision":
  1. Insert new `proposals` row: `version_number = prev + 1`, `parent_id = prev.id`, `root_id = prev.root_id` (or `prev.id` if prev was v1), new `accept_token`, status = `draft` initially.
  2. Update previous row: `status = 'superseded'`.
  3. `INSERT INTO proposal_events (event_type='sent', …)` for the new version.
  4. Email client: "An updated proposal is ready" → new accept URL. Old URL renders "This proposal has been superseded — please use the link in your most recent email."
- The chain is queryable: `SELECT * FROM proposals WHERE root_id = $1 ORDER BY version_number`.

### 3.5 E-sign Lite

#### Token generation

```python
import secrets, base64

def new_accept_token() -> str:
    raw = secrets.token_bytes(64)          # 512 bits of entropy
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # 86-char URL-safe string
```

Minimum effective entropy: 512 bits. URL path: `/p/{token}` served by a dedicated lightweight FastAPI router (no auth middleware).

#### Accept page flow

1. `GET /p/{token}` → constant-time DB lookup (parameterized query; no timing difference between a token that never existed and one that is unknown/invalid — both return 404). If found and status in (`superseded`): return HTTP 200 with a terminal page: "This proposal has been superseded — please use the link in your most recent email." If found and status `accepted`: return HTTP 200 with a terminal page: "You have already accepted this proposal — your signed copy was emailed to you." If found and status in (`sent`, `viewed`): proceed to render the accept page. All other cases (unknown token, structurally invalid token): 404. **Security rationale:** meaningful state disclosure requires prior possession of a valid 512-bit-entropy token; an attacker cannot distinguish superseded from never-existed without already holding the token.
2. On first view: `UPDATE proposals SET status='viewed' WHERE accept_token=$1 AND status='sent'`; insert `proposal_events(event_type='viewed', ip=…, ua=…)`. Render the accept page HTML (SPA lightweight route — no sidebar, mobile-first layout).
3. Accept page renders: proposal summary + tier selector (radio: good/better/best) + optional line-item checkboxes + total display + ESIGN consent block + typed-name input + "Accept Proposal" button.
4. `POST /p/{token}/accept` body: `{ selected_tier, selected_options, consent_electronic: true, signed_name }`.
   - Validate: token exists + status in (`sent`, `viewed`) + `consent_electronic == true` + `signed_name` non-empty.
   - In a single transaction:
     - `UPDATE proposals SET status='accepted', accepted_by_name=$name, accepted_at=NOW(), accepted_ip=$ip, accepted_ua=$ua, consent_electronic=TRUE, selected_tier=$tier, selected_options=$opts WHERE accept_token=$token AND status IN ('sent','viewed')`.
     - `INSERT INTO proposal_events(event_type='accepted', …)`.
   - Background: generate signed PDF (render template with `selected_tier` filled in → Gotenberg → GCS); email PDF copy to client via Resend; record `signed_pdf_gcs` and `signed_pdf_emailed_at`; notify staff (email: "Proposal accepted by {name}").
5. `POST /p/{token}/decline` — similar: status → `declined`; insert event; notify staff.
6. `POST /p/{token}/revision` — status → `revision_requested`; insert event with `metadata.revision_note`; notify staff.

#### Rate limiting on accept page

F3's real protections against accept-page abuse are: (1) 512-bit token entropy — brute-forcing the token space is not computationally feasible; (2) 404-indistinguishable responses for unknown/invalid tokens — no information leaked to enumerate valid tokens; (3) single-transaction accept — the `UPDATE … WHERE status IN ('sent','viewed') RETURNING id` pattern means only one concurrent POST can win; the second gets a 0-row result and returns 404.

`core.ratelimit.SingleFlightGuard` (cooldown_seconds=5) is used solely as a **double-submit guard** on `POST /p/{token}/accept` — it prevents an accidental double-click from a single browser session. It is **in-process and in-memory**: on autoscaled Cloud Run it does NOT provide cross-instance brute-force protection. Do not claim it prevents distributed attacks.

**Cloudflare WAF rate limiting** (10 accept-page requests/min/IP, block 5 min) is a **hard requirement before public go-live of accept pages** and arrives in F6. F3 may be deployed to preprod without it, but production accept pages must not go live until F6 WAF rules are active.

#### ESIGN / UETA compliance elements

| Element | Implementation |
|---|---|
| Intent | Explicit "Accept Proposal" button action |
| Consent | Required checkbox: "I agree to conduct business electronically per the Electronic Signatures in Global and National Commerce Act (ESIGN) and FL Statute §668" |
| Attribution | `accepted_by_name` (typed) + `accepted_ip` + `accepted_ua` + `accepted_at` |
| Record delivery | Signed PDF copy emailed to `customers.email` via Resend within 60s of accept |
| Retention | `proposal_events` + `proposals.accepted_*` fields + `signed_pdf_gcs` — immutable, never deleted |

The `ESignProvider` interface is a seam for future integration:

```python
# core/esign.py
from abc import ABC, abstractmethod

class ESignProvider(ABC):
    @abstractmethod
    def create_envelope(self, proposal_id: int, signers: list[dict]) -> str:
        """Return envelope/request ID."""

    @abstractmethod
    def get_status(self, envelope_id: str) -> str:
        """Return status string."""

class BuiltinESign(ESignProvider):
    """Our own e-sign-lite flow — no external provider."""
    def create_envelope(self, proposal_id, signers):
        return f"builtin:{proposal_id}"

    def get_status(self, envelope_id):
        return "completed"   # status is in proposals table, not via this interface
```

### 3.6 Gotenberg Service

A dedicated Cloud Run service running the official `gotenberg/chromium` Docker image.

#### Terraform resource (new file `infra/gotenberg.tf`)

```hcl
resource "google_cloud_run_v2_service" "gotenberg" {
  name     = "gotenberg"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"   # no public access

  template {
    containers {
      image = "gotenberg/gotenberg:8"
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      liveness_probe {
        http_get { path = "/health" }
        period_seconds = 30
      }
    }
    scaling { min_instance_count = 0; max_instance_count = 3 }
    service_account = google_service_account.api_sa.email
  }
}

resource "google_cloud_run_v2_service_iam_member" "gotenberg_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.gotenberg.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api_sa.email}"
}

output "gotenberg_url" {
  value = google_cloud_run_v2_service.gotenberg.uri
}
```

#### Python adapter (`adapters/gotenberg.py`)

Uses `email.mime` for correct `multipart/form-data` construction — avoids the byte-splice/string-concat antipattern that can corrupt binary PDF attachment bytes.

```python
"""Gotenberg PDF rendering adapter (I/O — coverage-omitted).
Calls the internal Gotenberg Cloud Run service to convert HTML → PDF.
Auth: OIDC token fetched from the metadata server (Cloud Run identity)."""

import os, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

GOTENBERG_URL = os.getenv("GOTENBERG_URL", "")


def _oidc_token(audience: str) -> str:
    url = (
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts"
        f"/default/identity?audience={audience}"
    )
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()


def _build_multipart(html: str, attachment_pdf_bytes: Optional[bytes]) -> tuple[bytes, str]:
    """Build a multipart/form-data body for Gotenberg.

    Returns (body_bytes, content_type_header_value).
    Uses email.mime for correct boundary handling — never string-concat binary data.
    """
    msg = MIMEMultipart("form-data")

    html_part = MIMEBase("text", "html")
    html_part.add_header("Content-Disposition", 'form-data; name="files"; filename="index.html"')
    html_part.set_payload(html.encode("utf-8"))
    msg.attach(html_part)

    if attachment_pdf_bytes is not None:
        pdf_part = MIMEBase("application", "pdf")
        pdf_part.add_header("Content-Disposition", 'form-data; name="files"; filename="attachment.pdf"')
        pdf_part.set_payload(attachment_pdf_bytes)
        msg.attach(pdf_part)

    # Extract boundary from the generated Content-Type header
    content_type = msg["Content-Type"]  # e.g. 'multipart/form-data; boundary="..."'
    # Serialize to bytes, stripping the MIME envelope headers (keep only body)
    raw = msg.as_bytes()
    body = raw[raw.index(b"\r\n\r\n") + 4:]
    return body, content_type


def html_to_pdf(html: str, attachment_pdf_bytes: Optional[bytes] = None) -> bytes:
    """Render HTML to PDF via Gotenberg. Optionally appends an attachment PDF."""
    token = _oidc_token(GOTENBERG_URL)
    body, content_type = _build_multipart(html, attachment_pdf_bytes)
    endpoint = f"{GOTENBERG_URL}/forms/chromium/convert/html"
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()
```

**Behavioral test requirement (R1):** `scripts/validate_gotenberg.py` must include a test case with a real PDF attachment (a minimal valid PDF fixture, e.g. `tests/fixtures/blank.pdf`). The test asserts the merged response is non-empty valid PDF bytes (starts with `%PDF`) and is larger than the HTML-only response, confirming attachment merge succeeded.

#### Behavioral validation (`scripts/validate_gotenberg.py`)

Required by R1 (adapters are coverage-omitted; behavioral validation compensates). Renders a known HTML fixture and asserts the response is non-empty valid PDF bytes (starts with `%PDF`). Runs in CI as part of the wave gate; can be skipped if `GOTENBERG_URL` is unset (local dev).

### 3.7 Tracking + Reminders

#### Viewed tracking

On `GET /p/{token}`: the server-side view records the event. No pixel / JS beacon needed — the act of fetching the page is the signal.

#### Reminder job (`jobs/reminder_job.py`)

Scheduled via Cloud Scheduler (Terraform-managed, in `infra/gotenberg.tf` or a new `infra/scheduler.tf`). Runs daily.

```python
"""Proposal reminder nudge job.
Selects proposals in 'sent' or 'viewed' status past their reminder threshold
and sends a nudge email. Uses SELECT FOR UPDATE SKIP LOCKED for idempotent
concurrent-safe operation (pattern from publish_job.py)."""
```

Cadence config in `tenants.settings.reminder_cadence_days` (JSONB array, e.g. `[3, 7, 14]`). The job:

1. `SELECT id, tenant_id, accept_token, sent_at FROM proposals WHERE status IN ('sent','viewed') FOR UPDATE SKIP LOCKED`
2. For each: compute days since `sent_at`; check against cadence; count prior `proposal_events WHERE event_type='reminder_sent'` to determine which reminder number is due.
3. If due: send email via Resend; `INSERT INTO proposal_events(event_type='reminder_sent', metadata={"reminder_number": N})`.
4. Idempotency: skip if a `reminder_sent` event with `metadata->>'reminder_number' = N` already exists for this proposal.

**Tenancy note:** The `FOR UPDATE SKIP LOCKED` scan operates on all proposals visible to the current DB session. Pre-F4 (no RLS), the job runs as a platform-scoped session touching all tenants; this is safe because F3 ships before F4's RLS is active. Post-F4, this job must be refactored to use the `for_each_tenant()` wrapper (defined in F5, `core/tenant_loop.py`) so the SKIP LOCKED scan runs inside each tenant's DB context. F5 owns that refactor; this note prevents F5 from having to rediscover the dependency.

Cloud Scheduler Terraform resource:

```hcl
resource "google_cloud_scheduler_job" "proposal_reminders" {
  name             = "proposal-reminders-daily"
  schedule         = "0 9 * * *"              # 9 AM UTC = 5 AM ET
  time_zone        = "UTC"
  attempt_deadline = "300s"
  http_target {
    uri        = "${google_cloud_run_v2_job.api_job.uri}/jobs/reminders"
    http_method = "POST"
    oidc_token { service_account_email = google_service_account.api_sa.email }
  }
}
```

### 3.8 Deposit + Handoff

On proposal acceptance:

1. `deposit_policy` (already frozen in `quote_snapshot`) provides the amount and instructions.
2. Staff email notification includes: "Proposal accepted by {name} on {date}. Deposit due: ${amount}. Instructions: {text}."
3. A `leads` row (if linked) has its `status` updated to `converted` and `converted_customer_id` filled in.
4. No job conversion record in F3 (Tim's job backend is Knowify; integration is a non-goal). The handoff is: email + proposal status = `accepted`.

Deposit policy is per-tenant in `tenants.settings`:

```json
{
  "deposit": {
    "mode": "percent",    // "percent" | "fixed" | "none"
    "value": 50,          // percent (0–100) or dollar amount
    "instructions": "Check payable to Perkins Roofing LLC"
  }
}
```

### 3.9 Knowify Migration Tooling

#### Customer / catalog XLS import (`scripts/import_knowify_xls.py`)

**Dependencies (pinned additions to `app/requirements.txt`, consumed by root Dockerfile):**
- `jinja2` — currently only a transitive dependency; must be pinned explicitly since F3 uses it directly for template rendering in `core/template_render.py`.
- `openpyxl` — absent from requirements; required for XLS import. Must be added (pandas is NOT needed — we parse XLS directly).

Both must be added as explicit pinned entries in `app/requirements.txt`, not left as transitive or conditional. The script:

1. Reads `--customers-xls` file (Knowify's XLS customer export).
2. Maps columns: Name → `display_name`, Company → `company_name`, Email → `email`, Phone → `phone`, Knowify ID → `knowify_customer_id`.
3. Upserts into `customers` (ON CONFLICT on `(tenant_id, knowify_customer_id) DO UPDATE`).
4. Reads `--contacts-sheet` if present: links contacts to customers by Knowify ID.
5. Reads `--properties-sheet` if present: creates `properties` rows; maps county string → code_zone (Broward/Miami-Dade → HVHZ; Palm Beach/Lee/St. Lucie → FBC).
6. Prints a summary: N customers imported, N contacts, N properties, N skipped (missing required fields).
7. Dry-run flag (`--dry-run`) prints plan without writing.

#### Historical PDF archive (`scripts/archive_knowify_pdfs.py`)

One-time script. Given a directory of PDF files (one per historical proposal):

1. Infers customer from filename pattern or a mapping CSV (`--mapping-csv knowify_id,filename`).
2. Looks up `properties.gcs_pdf_prefix` for the matched customer's default property (or uses `--default-prefix tenants/1/properties/0/archive/`).
3. Uploads each PDF to GCS via `google.cloud.storage` (already in use in the project).
4. Updates `properties.gcs_pdf_prefix` if not already set.
5. Produces a log: PDF → GCS path, customer matched, any skips.

No Zapier bridge is created. If Tim wants live overlap with Knowify during transition, that is a separate decision and out of scope for F3.

---

## 4. API Endpoints

All authenticated endpoints use the existing `require_role` dependency from `api/auth.py`. The public accept-page endpoints use a separate `require_valid_token` dependency (no Firebase token).

### 4.1 Authenticated — Quoting section

| Method | Path | Action | Notes |
|---|---|---|---|
| `GET` | `/quoting/customers` | `quoting_view` | List customers (tenant-scoped, paginated) |
| `POST` | `/quoting/customers` | `quoting_create` | Create customer |
| `GET` | `/quoting/customers/{id}` | `quoting_view` | Get customer + contacts + properties |
| `PUT` | `/quoting/customers/{id}` | `quoting_create` | Update customer |
| `POST` | `/quoting/customers/{id}/contacts` | `quoting_create` | Add contact |
| `POST` | `/quoting/customers/{id}/properties` | `quoting_create` | Add property |
| `PUT` | `/quoting/properties/{id}` | `quoting_create` | Update property (incl. code_zone override) |
| `GET` | `/quoting/leads` | `quoting_view` | List leads |
| `POST` | `/quoting/leads` | `quoting_create` | Create lead |
| `PUT` | `/quoting/leads/{id}` | `quoting_create` | Update lead status |
| `POST` | `/quoting/leads/{id}/convert` | `quoting_create` | Convert lead → customer + property |
| `GET` | `/quoting/proposals` | `quoting_view` | List proposals (filterable by status, customer) |
| `POST` | `/quoting/proposals` | `quoting_create` | Create proposal (draft) |
| `GET` | `/quoting/proposals/{id}` | `quoting_view` | Get proposal + events |
| `PUT` | `/quoting/proposals/{id}` | `quoting_create` | Update draft proposal |
| `POST` | `/quoting/proposals/{id}/send` | `quoting_send` | Freeze snapshot → send → email accept link |
| `POST` | `/quoting/proposals/{id}/revise` | `quoting_send` | Create new version (edit-after-send) |
| `GET` | `/quoting/proposals/{id}/chain` | `quoting_view` | Full version chain (root_id query) |
| `GET` | `/quoting/proposals/{id}/pdf` | `quoting_view` | Render + stream current draft PDF (preview) |
| `GET` | `/quoting/templates` | `quoting_view` | List templates for tenant |
| `POST` | `/quoting/templates` | `quoting_manage_templates` | Create template |
| `PUT` | `/quoting/templates/{id}` | `quoting_manage_templates` | Update template |
| `DELETE` | `/quoting/templates/{id}` | `quoting_manage_templates` | Delete (not allowed if used by sent proposals) |
| `POST` | `/quoting/templates/{id}/preview` | `quoting_manage_templates` | Render preview PDF with dummy data |
| `GET` | `/quoting/settings` | `quoting_view` | Get tenant quoting settings (cadence, deposit policy) |
| `PUT` | `/quoting/settings` | `quoting_manage_settings` | Update tenant quoting settings |

### 4.2 Public — Accept page (unauthenticated, token-gated)

Mounted under a separate router with no auth middleware. Rate-limited at the app level via `SingleFlightGuard` (per-token, cooldown_seconds=5); Cloudflare WAF rules added at F6.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/p/{token}` | Render accept page; record `viewed` event on first access; 404 for missing/superseded |
| `POST` | `/p/{token}/accept` | Submit acceptance (tier, options, consent, name); returns 200 + confirmation |
| `POST` | `/p/{token}/decline` | Submit decline + optional note |
| `POST` | `/p/{token}/revision` | Submit revision request + note |

The accept page SPA route (`/p/*`) is a lightweight separate entry point or a public-accessible route in the main SPA with no sidebar rendering.

### 4.3 Internal — Jobs

| Method | Path | Notes |
|---|---|---|
| `POST` | `/jobs/reminders` | Triggered by Cloud Scheduler; runs reminder job |
| `POST` | `/jobs/knowify-import` | Admin-triggered; runs XLS import (staff-only, `quoting_manage_settings`) |

---

## 5. Migrations

New migration file: `infra/migrations/0017_quoting.sql`.

**Dependency order:** requires 0013 (tenants, from F0) + 0014/0015 (pricing_configs / estimates + measurements stub, from F1/F2). This file is 0017 to follow those in sequence.

Following the project convention (idempotent, `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, no destructive DDL):

```sql
-- Wave F3: Quoting / Proposals
-- Migration: 0017_quoting.sql
-- All tables are tenant-scoped (tenant_id FK). RLS added in F4.
-- All CREATE statements are idempotent.
-- Dependency: 0013 (tenants), 0014 (pricing_configs), 0015 (estimates + measurements stub)

DO $$ BEGIN
    CREATE TYPE proposal_status AS ENUM (
        'draft', 'sent', 'viewed', 'accepted', 'declined',
        'revision_requested', 'superseded'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE proposal_event_type AS ENUM (
        'sent', 'viewed', 'accepted', 'declined', 'revision_requested', 'reminder_sent'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE lead_status AS ENUM (
        'new', 'contacted', 'qualified', 'converted', 'lost'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS customers ( … );          -- full DDL from §1.1
CREATE TABLE IF NOT EXISTS contacts  ( … );          -- §1.2
CREATE TABLE IF NOT EXISTS properties( … );          -- §1.3
CREATE TABLE IF NOT EXISTS proposal_templates( … );  -- §1.4
CREATE TABLE IF NOT EXISTS proposals ( … );          -- §1.5
CREATE TABLE IF NOT EXISTS jobs      ( … );          -- §1.6 stub
CREATE TABLE IF NOT EXISTS catalog_items ( … );      -- §1.6 stub
CREATE TABLE IF NOT EXISTS tc_versions   ( … );      -- §1.6 stub
CREATE TABLE IF NOT EXISTS proposal_events( … );     -- §1.8
CREATE TABLE IF NOT EXISTS leads     ( … );          -- §1.9
```

The actual migration file contains the full DDL from §1.1–§1.9 and §1.6 stubs verbatim. Applied via `scripts/apply_migrations_connector.py` (requires Jon's explicit OK per CONTINUATION gotchas).

**ENUM idempotency:** `CREATE TYPE IF NOT EXISTS` is invalid Postgres syntax. All three ENUM types use the `DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL $$ END` block form shown above, which is the correct idempotent pattern for Postgres ENUMs.

---

## 6. TEST PLAN (fail-first; write tests before implementation)

All tests in `tests/` following the project convention. `core/` modules reach 100% coverage; behavioral validation scripts cover adapters.

### 6.1 Snapshot Immutability

**File:** `tests/test_proposal_snapshot.py`

```python
def test_snapshot_frozen_on_send():
    """quote_snapshot must not be mutatable after the proposal is in 'sent' status."""

def test_snapshot_contains_pricing_config_hash():
    """quote_snapshot['pricing_config_hash'] must be present and non-empty."""

def test_snapshot_contains_floor_data():
    """quote_snapshot['floors'] must carry min_profit_pct and min_profit_plus_oh_pct."""

def test_snapshot_preserved_across_versions():
    """New version row has a fresh snapshot; old row's snapshot is unchanged."""
```

### 6.2 Version Chain / Supersede

**File:** `tests/test_proposal_versions.py`

```python
def test_send_creates_first_version():
    """Creating and sending a proposal sets version_number=1, root_id=id, parent_id=NULL."""

def test_revise_creates_new_version():
    """Revising a sent proposal creates version_number=2, parent_id=prev.id, root_id=prev.root_id."""

def test_old_version_status_superseded():
    """After revision, the prior version's status must be 'superseded'."""

def test_old_token_returns_404():
    """The superseded proposal's accept_token must return 404 from the accept endpoint."""

def test_chain_query_returns_all_versions():
    """GET /quoting/proposals/{id}/chain returns all rows for the root_id in version order."""

def test_superseded_cannot_be_accepted():
    """POST /p/{superseded_token}/accept returns 404 (same as missing token)."""
```

### 6.3 Token Entropy + Constant-time + 404-indistinguishability

**File:** `tests/test_accept_token.py`

```python
def test_token_length():
    """new_accept_token() produces an 86-character URL-safe base64 string."""

def test_token_uniqueness():
    """1000 generated tokens have no collisions."""

def test_missing_token_returns_404():
    """GET /p/nonexistent returns 404."""

def test_superseded_token_returns_404():
    """GET /p/{superseded_token} returns 404 — same as missing."""

def test_404_timing_indistinguishable():
    """Response time for missing vs superseded token differs by < 100ms over 50 trials."""

def test_accept_rejects_missing_consent():
    """POST /p/{token}/accept without consent_electronic=True returns 422."""

def test_accept_rejects_empty_name():
    """POST /p/{token}/accept with blank signed_name returns 422."""

def test_double_accept_idempotent():
    """Second POST /p/{token}/accept returns 404 (token already consumed = status 'accepted')."""
```

### 6.4 Consent / Audit Completeness

**File:** `tests/test_esign_audit.py`

```python
def test_accept_records_event():
    """Accepting a proposal inserts a proposal_events row with event_type='accepted'."""

def test_accept_records_ip_ua():
    """proposal_events.accepted row carries ip_address and user_agent."""

def test_accept_stores_consent_flag():
    """proposals.consent_electronic is TRUE after acceptance."""

def test_accept_stores_signed_name():
    """proposals.accepted_by_name matches the submitted signed_name."""

def test_viewed_event_on_first_get():
    """GET /p/{token} inserts a 'viewed' event and transitions status sent→viewed."""

def test_viewed_event_not_duplicated():
    """Subsequent GETs do not insert additional 'viewed' events."""
```

### 6.5 Floor Preservation in Snapshot

**File:** `tests/test_quote_snapshot_floors.py`

```python
def test_floor_min_profit_preserved():
    """quote_snapshot floors.min_profit_pct matches the pricing_config at send time,
    even after the pricing_config is later modified."""

def test_floor_not_recalculated_on_read():
    """Reading a proposal does not recalculate floors from the current config."""
```

### 6.6 Reminder Idempotency

**File:** `tests/test_reminder_job.py`

```python
def test_reminder_not_sent_before_threshold():
    """Proposal sent 1 day ago with cadence=[3,7,14] produces no reminder."""

def test_reminder_sent_at_threshold():
    """Proposal sent 3 days ago produces reminder #1 email."""

def test_reminder_not_duplicated():
    """Running the job twice produces only one reminder_sent event per threshold day."""

def test_reminder_stops_after_acceptance():
    """Accepted proposal receives no further reminders."""

def test_skip_locked_allows_concurrent_runs():
    """Two concurrent job runs do not double-send reminders (SKIP LOCKED behavior)."""
```

### 6.7 XLS Import Golden File

**File:** `tests/test_knowify_import.py`

Fixture: `tests/fixtures/knowify_sample.xlsx` — a minimal 3-row synthetic XLS with known customer names, emails, Knowify IDs, county strings.

```python
def test_import_creates_customers():
    """Import of golden file creates 3 customer rows with correct display_name and knowify_customer_id."""

def test_import_maps_county_to_code_zone():
    """'Miami-Dade' county → HVHZ; 'Palm Beach' county → FBC."""

def test_import_upserts_on_rerun():
    """Running import twice does not duplicate customers (ON CONFLICT upsert)."""

def test_import_dry_run_writes_nothing():
    """--dry-run flag produces output but no DB rows."""

def test_import_skips_missing_name():
    """Rows missing display_name are skipped and counted in the summary."""
```

### 6.8 Behavioral Validation Scripts (R1 — adapters coverage-omitted)

- `scripts/validate_gotenberg.py`: POSTs a minimal HTML fixture to `GOTENBERG_URL`; asserts response starts with `%PDF`; asserts response length > 1024 bytes. Skipped (exit 0) if `GOTENBERG_URL` is unset.
- `scripts/validate_proposal_email.py`: Calls `adapters/resend.py` with a test recipient (env `TEST_EMAIL`); verifies a Resend message ID is returned. Skipped if `RESEND_API_KEY` or `TEST_EMAIL` is unset.
- `scripts/validate_knowify_import.py`: Runs the import script against `tests/fixtures/knowify_sample.xlsx` against a test DB; asserts row counts. Exit 0 = pass.

---

## 7. Implementation Steps (sequenced; slip-rule ordering)

Steps are ordered so the money-path (send → accept → audit) ships before the polish features. If the commercial clock forces a cut, remove steps 8–9 (reminders + leads) first.

### Step 1 — Core models (TDD, always first)

Write failing tests for all model constraints (§6.1–6.5 snapshot/version/token tests). Run: confirm red for the right reason. Then:

- Add `app/models.py` ORM classes: `Customer`, `Contact`, `Property`, `ProposalTemplate`, `Proposal`, `ProposalEvent`, `Lead`.
- `core/esign.py`: `new_accept_token()`, `ESignProvider` interface, `BuiltinESign`.
- `core/authz.py`: add `quoting_*` actions to `_MATRIX`.
- Migration `infra/migrations/0017_quoting.sql`.

Pass tests → green.

### Step 2 — Quote snapshot builder

Write failing tests for snapshot construction (§6.5). Then:

- `core/quoting.py`: `build_quote_snapshot(estimator_output, pricing_config, deposit_policy, tiers) → dict`. Pure function, 100% coverable.
- Unit tests: snapshot immutability, hash presence, floor copy, tier structure.

### Step 3 — Gotenberg adapter + behavioral validation

- `adapters/gotenberg.py` (as per §3.6).
- `scripts/validate_gotenberg.py`.
- Terraform: `infra/gotenberg.tf` (Cloud Run service + IAM invoker binding + `GOTENBERG_URL` output). **Do not deploy yet — commit only.**

### Step 4 — Proposal template renderer

Write failing tests for template rendering (variable substitution, undefined variable silent). Then:

- `core/template_render.py`: `render_proposal_html(template: ProposalTemplate, context: dict) → str`. Uses `jinja2` (pinned in `app/requirements.txt` per §3.9 deps — confirm the pin is present before implementing). Pure function.
- `core/pdf_pipeline.py`: `generate_proposal_pdf(html, attachment_pdf_bytes=None) → bytes` — calls `adapters/gotenberg.html_to_pdf`.

### Step 5 — API routes: authenticated quoting endpoints

- `api/routes/quoting.py`: all endpoints from §4.1 (customers, contacts, properties, leads, proposals, templates, settings).
- Tenant filter on every query: `db.query(Model).filter(Model.tenant_id == current_tenant_id)`.
- Wire into `api/app.py`.

### Step 6 — Send flow + E-sign accept page

Write failing tests for token lookup, viewed event, double-accept, 404-indistinguishability (§6.3–6.4). Then:

- `POST /quoting/proposals/{id}/send`: freeze snapshot, generate token, set status=`sent`, send email (accept link via Resend), insert `proposal_events(type='sent')`.
- `api/routes/accept_page.py`: the `/p/{token}` public router (§4.2).
- `POST /p/{token}/accept`: validation, DB transaction, background PDF generation + email.

### Step 7 — Revision chain

Write failing tests for version chain (§6.2). Then:

- `POST /quoting/proposals/{id}/revise`: creates new version row, supersedes old, sends updated email.
- `GET /quoting/proposals/{id}/chain`.

### Step 8 — Reminders job (slip-able)

Write failing tests (§6.6). Then:

- `jobs/reminder_job.py`.
- Terraform Cloud Scheduler resource (in `infra/gotenberg.tf` or separate `infra/scheduler_quoting.tf`).
- `POST /jobs/reminders` endpoint.

### Step 9 — Leads (slip-able)

- Full leads CRUD + `POST /quoting/leads/{id}/convert`.

### Step 10 — Knowify migration tooling

Write XLS golden-file tests (§6.7). Then:

- `scripts/import_knowify_xls.py`.
- `scripts/archive_knowify_pdfs.py`.
- Fixture file `tests/fixtures/knowify_sample.xlsx`.

### Step 11 — SPA: Quoting section pages

Mobile-first. Pages:

- **Quote list** (`/quoting`) — filterable by status/customer; table with status badges; "New Proposal" button.
- **Proposal builder** (`/quoting/proposals/new`, `/quoting/proposals/{id}`) — customer/property picker, estimator output picker (integrates with F2 estimator API), tier editor (good/better/best), optional items, template selector, send button.
- **Template editor** (`/quoting/templates`, admin only) — HTML editor with live preview (iframe → preview PDF endpoint), variable reference panel.
- **Accept page** (`/p/{token}`) — public, no sidebar, mobile-first: proposal summary, tier radio, optional items, consent checkbox, typed-name input, submit button, confirmation screen.

### Step 12 — Terraform apply + drift check

```bash
cd infra && terraform plan -detailed-exitcode   # must show only additions for gotenberg + scheduler
terraform apply -auto-approve
bash scripts/drift_check.sh                     # must exit 0 after apply
```

### Step 13 — End-to-end exit gate (on a phone)

See §8.

---

## 8. Exit Gate

The wave is not done until this passes end-to-end on a physical mobile device (or BrowserStack mobile emulation at minimum):

1. Staff logs in → navigates to Quoting → creates a customer + property.
2. Creates a proposal, selects good/better/best tiers, picks a template.
3. Clicks "Send Proposal" → confirm email is delivered to a test address with the accept link.
4. Opens the accept link on a phone browser → accept page renders correctly (no horizontal scroll, no tiny text).
5. Selects tier, checks consent, types name, clicks "Accept Proposal".
6. Confirm: `proposals.status = 'accepted'`, `proposals.consent_electronic = TRUE`, `proposals.accepted_by_name` set, `proposal_events` contains `viewed` + `accepted` events.
7. Confirm: signed-PDF copy emailed to the test address within 60 seconds.
8. Confirm: staff receives "Proposal accepted" notification email.
9. Staff creates a revised proposal (revise flow) → old link returns "superseded" message, new link works.

**SDA mirror:** Tim gets 3-day preprod validation access followed by a 14-day acceptance period (per Ez-Bids SDA terms). The preprod environment uses real Gotenberg (Cloud Run) and Resend.

---

## 9. Rollout / Rollback

### Rollout

1. Commit migration `0017_quoting.sql`.
2. Run `terraform apply` for Gotenberg Cloud Run + Cloud Scheduler (R3).
3. Run `scripts/apply_migrations_connector.py` (Jon's explicit OK required).
4. Deploy API + web via `bash scripts/deploy.sh` (clean tree required, R3-ENFORCE).
5. Validate: `scripts/validate_gotenberg.py` + `scripts/validate_proposal_email.py`.
6. Smoke test: create one real draft proposal in preprod.
7. R4: `bash scripts/drift_check.sh` → exit 0.

### Rollback

- API: redeploy previous image tag (`gcloud run services update-traffic api --to-revisions=<prev>=100`).
- Web: Firebase Hosting rollback (`firebase hosting:clone <prev-channel>`).
- Migration: `0017_quoting.sql` is additive only (no DROP, no ALTER of existing columns). New tables can be truncated + dropped if needed without affecting existing functionality. Rollback SQL:
  ```sql
  DROP TABLE IF EXISTS proposal_events CASCADE;
  DROP TABLE IF EXISTS proposals CASCADE;
  DROP TABLE IF EXISTS proposal_templates CASCADE;
  DROP TABLE IF EXISTS leads CASCADE;
  DROP TABLE IF EXISTS contacts CASCADE;
  DROP TABLE IF EXISTS properties CASCADE;
  DROP TABLE IF EXISTS customers CASCADE;
  DROP TYPE IF EXISTS proposal_status;
  DROP TYPE IF EXISTS proposal_event_type;
  DROP TYPE IF EXISTS lead_status;
  ```
- Gotenberg: `terraform destroy -target=google_cloud_run_v2_service.gotenberg` if needed.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Scope gravity** — CRM/payment features requested during build | HIGH | §0 non-goals list is the fence; defer with "F3 scope"; log to backlog |
| **Double-accept race** — two concurrent POSTs to `/p/{token}/accept` | HIGH | Single-transaction UPDATE with `WHERE status IN ('sent','viewed')` + `RETURNING id` — only one wins; other gets 404 |
| **Token brute force** — 86-char URL-safe base64 is 512 bits; not practically feasible at any scale | LOW | 404-indistinguishable responses for unknown tokens; `SingleFlightGuard` for double-submit only; Cloudflare WAF rate limiting at F6 is a hard requirement before public go-live |
| **Gotenberg cold start** — 0 min instances means first PDF takes ~3s | MEDIUM | `min_instance_count=0` acceptable for demo; bump to 1 before client demo if latency is visible |
| **Jinja2 injection** — tenant-authored templates could include malicious JS | MEDIUM | Templates are staff-authored (authenticated admin only); Gotenberg renders in a headless Chromium sandbox; no user-controlled HTML reaches the renderer without admin authorship |
| **Snapshot size** — JSONB snapshot with many line items | LOW | Line items are ~50 bytes each; 50-line proposal ≈ 2.5KB — negligible |
| **jinja2/openpyxl not pinned** | LOW | Both are REQUIRED pinned additions to `app/requirements.txt` per §3.9; add before Step 4 (jinja2) and Step 10 (openpyxl) |
| **Commercial clock slip** | HIGH | Slip rule: cut reminders (Step 8) + leads (Step 9) first; never cut templates/revisions/tiers/e-sign — those are the differentiators |
| **Resend `from` domain** — currently `noreply@perkinsroofing.net` | LOW | Accept-link and signed-PDF emails use the same from; confirm Resend domain is verified for perkinsroofing.net before send |

---

*Document ends. Last updated 2026-07-08.*
