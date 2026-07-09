# Domain-Driven Design — Perkins Full-Funnel Platform

**Date:** 2026-07-08  
**Status:** DRAFT (R2 fixes applied — pending Jon approval) — binding shared language for all waves F0–F6  
**Grounding:** full-funnel plan v2 · CONTINUATION-2026-07-08 · phase-2 spec · Ez-Bids legal/Exhibit B+C · Knowify teardown · SquareQuote review · app/models.py · core/estimator.py · core/publish_planner.py · core/content_safety.py

---

## 0. Architecture orientation

The platform is a **modular monolith**, not microservices. The layering is:

```
core/          Pure domain logic — no I/O, no ORM, fully unit-testable.
               The only layer with ≥97% / 100% coverage enforcement (R1).
adapters/      Ports to the outside world (GCP, social APIs, Solar API,
               Gotenberg, SquareQuote, Secret Manager, …). Each adapter
               implements a domain interface; swappable without touching core/.
api/           Application layer — FastAPI routes. Orchestrates core + adapters.
               No domain logic lives here.
jobs/          Background jobs (Cloud Run Jobs, Cloud Scheduler). Same rule:
               orchestrate, never own domain logic.
app/models.py  SQLAlchemy ORM — the persistence projection of domain aggregates.
               It is NOT the domain model; it is a map from aggregates to rows.
```

Future extraction seams are called out per bounded context below. Nothing is microservices-ready today — the seams exist so extraction never requires a domain rewrite.

---

## 1. Bounded Contexts

### 1.1 Tenancy / Identity

**Purpose.** The upstream context for the entire platform. Resolves which tenant owns a request, enforces that no query runs without a tenant context, and manages user identity, roles, and cross-tenant provisioning.

**Core invariants.**
- No query executes outside a tenant context post-F4. The RLS session pattern (`SET LOCAL app.tenant_id`) is the enforcement mechanism; ORM-level tenant filtering is belt-and-suspenders. Both must be present.
- Perkins is Tenant 1, backfilled by migration. The project-level Firebase Auth pool maps to Tenant 1 without a GCIP tenant claim; all new licensees get a real GCIP tenant.
- `platform_admin` is the only cross-tenant role. It is available only to DeGenito-internal users. No other role can see or act across tenant boundaries.
- A tenant deletion cascade is scoped: RLS-scoped data delete + GCS prefix delete + audit record. It never touches another tenant's data.
- No query may bypass RLS. The app database role is non-superuser with no `BYPASSRLS`. This is enforced in migration and verified by CI grep blocking raw `text()`/`execute()` outside approved modules.

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `Tenant` | `Tenant` | Owns `settings JSONB` (per-tenant config), status, and the GCIP tenant reference. No tenant data crosses this root. |
| `User` | `User` | Belongs to exactly one tenant (except `platform_admin`). Owns roles + invite status. Carries `is_default_admin` flag (delete-protected). |
| `Role` | Value object on User | Roles are a closed enum (`admin`, `web_admin`, `sales`, `platform_admin`, plus section-scoped: `kb_*`, `marketing_*`, `estimating_*`, `quoting_*`, `admin_*`). No `Role` entity — role assignment is a property of the user aggregate. |

**Entities vs value objects.**
- Entities: `Tenant`, `User`.
- Value objects: `Role` (closed enum), `TenantSlug` (unique normalized string, immutable once set), `GCIPTenantRef` (opaque string from Identity Platform).

**Domain events.**
- `TenantProvisioned` — new licensee seeded with default configs.
- `UserInvited` — invite link created (role + tenant context stamped at creation, not acceptance).
- `UserActivated` — invite accepted, GCIP account linked.
- `TenantOffboarded` — cascade delete completed + audit record written.

**Mapping to current code.**
- `app/models.py`: no `Tenant` or `User` model yet — these are F0/F4 additions. The `UserSetting` model (email signature) is a thin slice of User that will be subsumed.
- `api/routes/users.py` (`api/users.py` in listing): the existing Users API is the application surface; `core/authz.py` holds role logic. Both map to this context.
- F0 adds `tenants` table + `tenant_id` FK. F4 adds RLS + GCIP upgrade + platform_admin. The `DEFAULT_ADMINS` config is the interim per-tenant admin guard.

**Future extraction seam.** Tenancy/Identity could become a separate auth service if the platform grows to hundreds of tenants and needs its own SSO admin UI. Today it stays in the monolith; the seam is `core/authz.py` + a clean `TenantResolver` port in `adapters/`.

---

### 1.2 Corpus / Knowledge Base

**Purpose.** Ingests, stores, and retrieves the video corpus. The corpus is the raw material every other context draws from — content generation retrieves chunks, estimating pulls claim/objection nodes, the FAQ mines graph nodes. This context owns the content, not the presentation.

**Core invariants.**
- A `Chunk` belongs to exactly one `Video`. Embeddings are 3072-dimensional (Gemini embedding-001); no mixed-model embeddings are stored in the same index. The `embed_model` column enforces this.
- `IngestionRun` stages (`transcript → graph → embed`) are idempotent via `content_hash`. Re-running ingestion on unchanged content is a no-op.
- The corpus is read-only from all other contexts. No other context writes to `chunks`, `segments`, `words`, or `content_graph`.
- `FaqEntry` rows are mined from `GraphNode` records (claims/objections) and belong to this context. Their status lifecycle (`mined → answered`) is owned here.
- Vector retrieval is tenant-scoped post-F4. The HNSW index is shared; RLS + ORM filter enforce per-tenant visibility. If tenant count or corpora grow, partition `chunks` by `tenant_id` (planned lever, not v1).

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `Video` | `Video` | Owns the archive URI, KPI snapshots, pull-tracking timestamps, and clip-generation status. All derived content (segments, words, graph nodes, chunks) reference video_id but do not compose into this aggregate — they are their own projections. |
| `IngestionRun` | `IngestionRun` | Tracks per-stage ingestion state independently. Separating it from `Video` keeps the ingestion state machine from polluting the video entity. |
| `ContentGraph` | `GraphNode` | The knowledge graph extracted from transcripts (topics, claims, objections, CTAs). Root is the individual node; the collection is queried by video or kind. No single aggregate root owns the whole graph — it is navigated by query, not traversal. |
| `Chunk` | `Chunk` | The retrieval unit. Carries embedding + version. Not composed into Video because embedding models may be updated independently of video metadata. |
| `FaqEntry` | `FaqEntry` | Mined from graph nodes; lifecycle ends at `answered`. References `source_node_id` (not composed — graph nodes are in a sibling aggregate). |

**Entities vs value objects.**
- Entities: `Video`, `IngestionRun`, `GraphNode`, `Chunk`, `FaqEntry`.
- Value objects: `ArchiveURI` (gs:// string, immutable once set), `ContentHash` (SHA-256 of transcript content), `EmbedModel` (string tag, e.g. `gemini-embedding-001`), `IngestionStage` (enum: transcript / graph / embed), `GraphNodeKind` (enum: topics / claims / objections / ctas).

**Domain events.**
- `VideoIngested` — all three stages complete for a video.
- `GraphExtracted` — `graph` stage done; downstream can mine FAQ candidates.
- `ChunkEmbedded` — embedding stored; vector search available for this video.
- `FaqAnswered` — FAQ entry status transitions to `answered`.

**Mapping to current code.**
- `app/models.py`: `Video`, `IngestionRun`, `Segment`, `Word`, `GraphNode`, `Chunk`, `AggregatedTopic`, `FaqEntry` all belong here.
- `core/chunking.py`, `core/graph.py`, `core/retrieval.py`, `core/answer.py`, `core/faq_consolidate.py`, `core/enumerate.py` are the domain logic for this context.
- `adapters/archive.py` (GCS), STT adapters, Whisper — these are the ports.
- `AggregatedTopic` is a read model / materialized view over `GraphNode` — it belongs here but is a query projection, not an aggregate in its own right.

**Future extraction seam.** The corpus + vector index is the most likely candidate for extraction to a dedicated retrieval service (if pgvector at scale becomes a bottleneck). The clean seam is `core/retrieval.py` + a `CorpusPort` interface.

---

### 1.3 Content / Marketing

**Purpose.** Produces, reviews, schedules, and distributes marketing content — short-form clips, articles, social captions, avatar scripts, and the pillar/cluster publish pipeline. It consumes the corpus (retrieval from 1.2) and produces publishable artifacts gated by the content safety subsystem.

**Core invariants.**
- No artifact publishes without passing the two-layer safety gate (denylist + LLM judge). Fail-closed: a denylist-clean artifact without a configured judge does NOT pass. This is `core/content_safety.gate()`'s explicit design.
- `MiniSeries` clips require admin approval (`approved = 1`) before distribution. The approval step is not bypassable from the distribution path.
- The `Caption Contract v5` is the single JSON schema for all clip captions. The parser in `core/caption_output.py` accepts v3 as a fallback during migration only; new generation always targets v5.
- Distribution is per-tenant with per-tenant social credentials (stored in Secret Manager under `tenants/{id}/…`). No tenant's credentials are accessible to another tenant.
- OAuth tokens for social platforms are stored and refreshed per-tenant. A token expiry does not block the platform; the publish job retries and notifies.
- The `drip throttle` (seed % + always-full pipeline) is controlled by `core/publish_planner.py`. The seed percentage is configurable per-tenant in Admin → Marketing config. No engagement-simulation of any kind is permitted.
- Brand kit (logo, colors, fonts, intro/outro, voice samples) is per-tenant config, not hardcoded.

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `MiniSeries` | `MiniSeries` | Owns proposed clip in/out points and approval status. Clips are derived from a Video but become independent publishable artifacts once approved. |
| `SocialPost` | `SocialPost` | One per (series, part, platform). Owns publish status and external platform ID. Uniqueness constraint enforces idempotency. |
| `Article` | `Article` | Owns the full content lifecycle: draft → scheduled → published → blocked. Carries cluster reference, priority, SEO metadata, FAQ JSON, JSON-LD. |
| `Cluster` | `Cluster` | Owns the pillar/cluster activation sequence (pending → active → complete). Its position drives the drip ordering. |
| `ScheduledContent` | `ScheduledContent` | A thin scheduling envelope (kind + ref_id + publish_at) decoupled from the content type. Allows uniform scheduling across articles and reels. |

**Entities vs value objects.**
- Entities: `MiniSeries`, `SocialPost`, `Article`, `Cluster`, `ScheduledContent`, `EmailTemplate`.
- Value objects: `BrandKit` (logo URL, color palette, fonts, intro/outro GCS URIs — JSONB on Tenant), `CaptionOutput` (parsed v5 JSON struct from `core/caption_output.py`), `SafetyVerdict` (`GateResult` from content_safety), `PillarRole` (enum: pillar / support), `PublishStatus` (enum: draft / scheduled / published / blocked), `SocialPlatform` (enum: tiktok / instagram / youtube / facebook / linkedin / x / pinterest), `DripThrottle` (seed_pct + target_in_flight pair, stored in tenant Marketing config).
- `CommentDraft` is an entity in this context (it is owned by the Content/Marketing workflow, not by the corpus — it is a reply-drafting artifact, not a corpus record).

**Domain events.**
- `ClipRendered` — `MiniSeries` clip processed through Track A (reframe, captions, music, fx).
- `ClipApproved` — admin approval; clip enters distribution queue.
- `ContentPublished` — `SocialPost` or `Article` successfully published to a platform/channel.
- `ContentBlocked` — safety gate FAIL; artifact flagged for human review.
- `PillarSeeded` — seed publish batch dispatched for a new active cluster.
- `ClusterCompleted` — all articles in a cluster published; next cluster activates.
- `CaptionContractViolation` — generated caption fails v5 schema parse (logged, triggers regeneration).

**Mapping to current code.**
- `app/models.py`: `MiniSeries`, `SocialPost`, `Article`, `Cluster`, `ScheduledContent`, `EmailTemplate`, `CommentDraft` — all this context.
- `core/`: `clip_select.py`, `captions.py`, `caption_output.py`, `reframe.py`, `clip_fx.py`, `music_mix.py`, `broll.py`, `speech_cleanup.py`, `audio_filter.py`, `publish_planner.py`, `publish_dispatch.py`, `social.py`, `content_safety.py`, `avatar_script.py`, `article_plan.py`, `article_prompt.py`, `seo.py`, `serp_analysis.py`, `jsonld.py`, `scheduler.py`, `render_spec.py`, `vad.py`, `comments.py`, `email_proof.py`.
- `adapters/`: distribution adapters (`meta_ig.py`, `tiktok.py`, `youtube_comments.py`, etc.), safety adapter (`safety.py`), avatar adapters (HeyGen/ElevenLabs mocks).
- Gap: `PlatformConfig` (in `app/models.py`) is used as a catch-all for platform-wide settings. Post-F0, per-tenant Marketing config (brand kit, seed %, caption prompts, social creds) moves to `Tenant.settings JSONB` + Secret Manager. The current flat `PlatformConfig` is a monolith-era artifact that F5 replaces with tenant-scoped config.

**Future extraction seam.** The rendering pipeline (Track A — reframe/captions/music/fx) is the most I/O-heavy subsystem and the natural first extraction candidate (to a dedicated Cloud Run Job with its own queue). The seam is already present: `core/render_spec.py` + job-level orchestration in `jobs/`.

---

### 1.4 Pricing / Estimating

**Purpose.** Maintains versioned pricing configurations and computes reproducible, auditable estimates. The pricing engine is pure and deterministic: given the same config + inputs, it always produces the same output. Config changes produce new versions; estimates reference config by hash, never by live state.

**Core invariants.**
- Every estimate is reproducible from its `pricing_config_hash`. The hash is RFC 8785 JSON-Canonical + SHA-256 of the active `PricingConfig`. If config changes after a quote is sent, the estimate is still reproducible by re-running with the archived config snapshot.
- Profit floors are computed on tagged cost categories. The 13% profit floor and 33% profit+OH floor are only correctly computable when line items carry `CostCategory` tags (Labor / Materials / Equipment / Sub / Misc / Overhead / Profit). The current `core/estimator.py` uses a simplified denominator — this is the F2 delta to fix.
- `PricingConfig` is immutable once published. A config edit creates a new version; old versions are retained for audit. An estimate's `pricing_config_hash` is a pointer to the exact version used.
- `code_zone` (HVHZ vs FBC) is a property of a `Property`, not of a branch. It is overridable per quote. Mixed-tier applies per slope/line when a property sits in an unusual zone. This means `code_zone` must travel with the measurement inputs, not be resolved at the branch level.
- The five golden files (Exhibit C) are permanent CI fixtures. The engine must reproduce them within ±$0.01 or ±0.01% using both manual entry and measurement-fed inputs. Failing any golden file is a CI hard stop.
- Commission is computed as a percentage of profit dollars only — not of revenue. Commission rates differ by slope type: sloped = 10%, low-slope = 15%. (Sloped-HVHZ rate is an open item pending Tim confirmation.)
- The `MeasurementProvider` is a port, not a dependency. The estimating engine takes a `Measurement` value object as input; it does not call Solar API or SquareQuote directly. The adapter layer injects measurement data.

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `PricingConfig` | `PricingConfig` | Versioned, immutable once published. Owns all rate tables (base costs, overhead, profit scale, adders, PM matrix, dumpster rules, tax flags) as JSONB per tenant per branch. Its hash is the audit anchor for all estimates. Separate from `Estimate` because configs evolve on their own lifecycle. |
| `Estimate` | `Estimate` | The computed result of running the engine against a config snapshot + measurement inputs. References `pricing_config_hash` (not the live config). Owns itemized line items with cost-category tags. Never mutated after computation — a revised estimate is a new `Estimate`. |
| `Branch` | `Branch` | Owns the default `code_zone` and the association to a `PricingConfig` version. Miami / Jupiter / Naples are the initial branch set. A branch is a tenant-level concept (different tenants may have different branch sets). |

**Entities vs value objects.**
- Entities: `PricingConfig`, `Estimate`, `Branch`.
- Value objects: `ConfigHash` (RFC 8785 canonical SHA-256, immutable string), `CostCategory` (enum literals: `Labor` / `Materials` / `Equipment` / `Sub` / `Misc` / `OH` / `Profit`; insulation excludes `Profit` only; tapered insulation excludes `OH` + `Profit` — floor-exemption VO semantics), `RoofSection` (slope type + area in squares + code_zone), `SlidingScaleProfit` (the per-sq profit derived from the num_squares lookup — a computed VO, not stored separately), `ProfitFloor` (13% profit / 33% profit+OH pair, evaluated at estimate time), `CommissionRate` (enum: sloped=10% / low-slope=15%; HVHZ-sloped rate config-driven pending Tim), `Money` (amount + currency, USD only in v1 — no multi-currency), `LineItem` (description + amount + CostCategory tag, immutable once computed).
- `QuoteInput` (in `core/estimator.py`) is the current implementation of the inputs value object — it will be promoted to a proper domain type as the config-driven engine lands in F2.

**Domain events.**
- `PricingConfigPublished` — new config version active; hash computed and stored.
- `EstimateComputed` — estimate produced; config_hash stamped; line items with category tags recorded.
- `GoldenFileValidated` — CI: estimate matches Exhibit C ±$0.01 (fires per golden file, five total).
- `PricingConfigSuperseded` — old config version archived; new version active (old estimates unaffected).

**Mapping to current code.**
- `app/models.py`: no `PricingConfig`, `Estimate`, or `Branch` models yet — F2 additions. `PlatformConfig` holds flat key/value pairs and will not serve as a pricing config; F2 introduces the proper model.
- `core/estimator.py`: the engine logic. Currently uses hardcoded rate tables (constants at module top). F2 moves these into versioned `PricingConfig` JSONB rows; the `estimate()` function signature becomes `estimate(config: PricingConfig, input: QuoteInput) → Estimate`. The self-check and margin logic carry over.
- `api/routes/estimator.py`: application surface. Currently accepts `QuoteInput` directly; F2 adds config resolution + hash stamping.
- Gap: `PM_INCENTIVE` is a flat dict (`{"residential": 150, "commercial": 300}`); Exhibit B specifies a zone×job-size matrix. F2 replaces this with the matrix. `TILE_DUMPSTER` is opt-in; Exhibit B specifies threshold-count auto-trigger. Both are F2 delta fixes.
- Gap: `margin_ok` in `estimate()` uses only the profit floor, not the profit+OH floor, because OH is not currently separated from base cost. The CostCategory tag system in F2 fixes this.
- Gap: low-slope category (TPO/coatings/silicone/BUR/insulation/deck types) is not yet in the engine. F2 adds the second Exhibit B sheet.

**Future extraction seam.** The pricing engine + config store is the natural candidate for a standalone pricing microservice if the platform licenses to many tenants with divergent pricing structures. The seam is `core/estimator.py` (pure function) + `PricingConfigPort` in adapters. No extraction in v1.

---

### 1.5 Quoting / Proposal

**Purpose.** Converts an estimate into a formatted proposal, manages the proposal lifecycle (draft → sent → viewed → accepted | declined | revision_requested), handles e-sign, deposit acknowledgment, and job handoff. This is the commercial deliverable of F3 and the Knowify displacement.

**Core invariants.**
- A sent proposal version is immutable. Once a proposal transitions to `sent`, its `quote_snapshot` JSONB cannot change. A revision is a new version linked by `parent_id` (and optionally `root_id` for the chain head) with a monotone `version_number`; the old version transitions to `superseded` and its accept link returns HTTP 200 with a terminal "proposal updated" page — not 404. Unknown/non-existent tokens return 404-indistinguishable.
- `quote_snapshot` is a frozen copy of the estimate at send time, not a live reference. If pricing config changes after sending, the sent proposal is unaffected. The `pricing_config_hash` is embedded in the snapshot for audit.
- Accept tokens are high-entropy, single-version, and single-use. A token is bound to a specific proposal version. Once used (accepted or declined), it cannot be reused. Superseded versions invalidate their tokens immediately.
- The e-sign flow requires explicit consent. The client must check the "consent to electronic business" checkbox before the typed-name accept step. The audit trail records: IP, User-Agent, timestamp of view, timestamp of accept, consent flag, typed name. This satisfies ESIGN/UETA requirements (intent, consent, attribution, record delivery).
- A signed PDF copy is emailed to the client on acceptance. The PDF is produced by Gotenberg from the proposal HTML template. This delivery record is part of the ESIGN audit trail.
- No proposal is payable through the platform in v1. The deposit field records the amount and payment instructions; no payment gateway is integrated. This is a hard non-goal.
- Tiered/optional pricing (good-better-best + optional line items) is client-selectable on the accept page, not pre-selected by the sales rep. The client's selection is stamped in the acceptance event.
- `leads` are a lightweight status — source + conversion state — not a CRM. A lead converts to a `Customer` + `Property` pair. No lead management beyond source tracking and convert-to-customer.

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `Proposal` | `Proposal` | The core aggregate. Owns version chain (parent_id), status, quote_snapshot, template reference, accept_token, audit fields, and deposit info. `ProposalEvent` records are part of this aggregate — they are the internal event log, not projections. The proposal owns its history. |
| `Customer` | `Customer` | Owns contact info and the optional `knowify_customer_id` for migration. Has many `Properties`. Boundary is at Customer because a customer may have multiple properties and proposals. |
| `Property` | `Property` | Owns the address and `code_zone` override. Belongs to a Customer. `code_zone` on Property is the canonical source for estimating — it can differ from the Branch default. |
| `ProposalTemplate` | `ProposalTemplate` | Tenant-owned HTML template (logo, colors, cover, T&C, attachments). Self-serve editable. Multiple templates per tenant. Separate aggregate because templates evolve independently of proposals that reference them. |
| `Lead` | `Lead` | Lightweight: source, status (new / contacted / converted / lost), FK to Customer on conversion. Not a CRM record — no activity log, no notes, no contact history. |

**Entities vs value objects.**
- Entities: `Proposal`, `Customer`, `Property`, `ProposalTemplate`, `Lead`, `ProposalEvent`.
- Value objects: `QuoteSnapshot` (frozen JSONB copy of an `Estimate` at send time, includes `pricing_config_hash`), `AcceptToken` (512-bit random token via `secrets.token_bytes(64)`, ~86-char URL-safe base64, single-use, version-bound — bound to one `version_number` in the `root_id`/`parent_id`/`version_number` chain), `ESignRecord` (IP + UA + view_at + accept_at + consent_flag + typed_name — immutable once written), `DepositTerms` (amount or percentage + payment instructions — stored on Proposal, not computed), `ProposalStatus` (enum: draft / sent / viewed / accepted / declined / revision_requested / superseded), `ProposalVersion` (integer, monotone within a parent chain), `TierSelection` (client's good-better-best choice + selected optional line items, recorded in acceptance event), `KnowifyCustomerId` (opaque string, nullable — migration artifact).
- Note on Proposal vs Quote vs Estimate (see Glossary): an `Estimate` (Pricing/Estimating context) is the computed cost build-up. A `Quote` is the informal term for the estimate as presented during the sales discussion. A `Proposal` is the formal versioned document sent to the client for acceptance. In code, `quote_snapshot` is the frozen estimate embedded in a Proposal. "Quote" never refers to a separate data entity — it is a colloquial name for an estimate in the sales context.

**Domain events.**
- `ProposalDrafted` — proposal created from estimate; template applied; status = draft.
- `ProposalSent` — proposal version frozen; accept token minted; client notification sent; status = sent.
- `ProposalViewed` — client opened accept page; view timestamp recorded in audit trail.
- `ProposalAccepted` — client completed e-sign flow; tier selection recorded; signed PDF emailed; status = accepted; deposit terms surfaced.
- `ProposalDeclined` — client declined; status = declined; token invalidated.
- `ProposalRevisionRequested` — client or sales rep requests revision; old version → superseded; new draft version created with parent_id link.
- `LeadConverted` — lead status → converted; Customer + Property records created.
- `DepositAcknowledged` — rep records that deposit has been received (manual step in v1); proposal → job handoff triggered.
- `JobHandoffTriggered` — accepted + deposit acknowledged → job status set; optional Knowify notification if bridge configured.

**Mapping to current code.**
- `app/models.py`: no `Proposal`, `Customer`, `Property`, `Lead`, or `ProposalTemplate` models yet — F3 additions.
- No `core/` module for quoting yet — F3 introduces `core/proposal.py` (version chain logic, token minting, e-sign record assembly, tier selection) and `core/proposal_pdf.py` (Gotenberg integration via adapter).
- `api/routes/estimator.py` is the closest existing surface; it becomes a read dependency (estimate → quote_snapshot) for the quoting flow.
- The Gotenberg adapter (`adapters/gotenberg.py`) is a new F3 port.
- Gap: the Knowify bridge (optional Zapier-equivalent on job handoff) is noted as optional in F3 — not in core scope, only if Tim wants overlap.

**Future extraction seam.** The Proposal aggregate is the most likely candidate for extraction to a document service (for multi-region or regulated-storage requirements). The accept page is already stateless (token-based, no login) — it maps cleanly to a separate route. No extraction in v1.

---

### 1.6 Measurement

**Purpose.** Provides roof measurement data (area in squares, linear elements, slope/pitch, azimuth) as a value object to the Pricing/Estimating context. Measurement is a supporting context — it has no business rules of its own, but it gates the accuracy of every automated estimate.

**Core invariants.**
- Manual entry is a first-class, clearly labeled fallback. It is never silently substituted. Exhibit C Scenario 5 (manual-entry golden file) must pass identically to the automated-measurement golden files.
- The Solar API is the primary measurement provider in production. Raw Google Earth imagery scraping is prohibited (Google ToS). The Solar API is the ToS-clean path to Google's imagery + DSM.
- `MeasurementProvider` is a port (adapter interface), not a hardcoded dependency. The estimating engine calls the port; the adapter decides which provider fulfills the request (Solar API, SquareQuote when restored, manual entry). Swapping providers does not touch `core/`.
- Measurement data from Solar API is per-segment (each roof segment has its own pitch/azimuth/area). The engine aggregates segments into the `Measurement` value object; mixed-pitch roofs carry per-segment detail.
- SquareQuote (DeGenitoAI/eaglepoint ml-service) is noted as a secondary provider but its LiDAR/PDAL path is dropped by locked architecture decision — LiDAR is not a correctable issue, it is permanently out of scope. The only upgrade path beyond Solar API + manual entry is paid oblique-imagery when that becomes available. SquareQuote is NOT merged into this repo; if reintroduced it would be called via B2B API as an external adapter only.
- Measurement results are cached per property+provider to avoid redundant API calls. Cache invalidation is on property address change or explicit refresh.

**Aggregates.**

| Aggregate | Root | Boundary rationale |
|---|---|---|
| `MeasurementRequest` | `MeasurementRequest` | Tracks a measurement job: property address, provider, status (queued / in_progress / complete / failed), result. Async by default (Solar API p95 latency is non-trivial). Separate from Estimate because a measurement may be requested before an estimate is built, and the same measurement may feed multiple estimates. |

**Entities vs value objects.**
- Entities: `MeasurementRequest`.
- Value objects: `Measurement` (total_squares, hips_lf, ridges_lf, valleys_lf, rakes_lf, eaves_lf, wall_flashings_lf, per_segment: list[MeasurementSegment] — immutable once produced), `MeasurementSegment` (area_sq, pitch, azimuth — per-segment detail from Solar API), `MeasurementSource` (enum: solar_api / squarequote / manual), `PropertyAddress` (street, city, state, zip — normalized form used as cache key).
- `Measurement` is consumed by Pricing/Estimating as an input value object. The Estimating context does not know which provider produced it; it only sees the typed `Measurement` VO.

**Domain events.**
- `MeasurementCaptured` — provider returned data; `Measurement` VO assembled; result stored on request.
- `MeasurementFailed` — provider returned error or timed out; manual entry prompt surfaced to user.
- `ManualMeasurementEntered` — user submitted manual values; `Measurement` VO assembled with `source = manual`.

**Mapping to current code.**
- `app/models.py`: no `MeasurementRequest` model yet — F2b addition.
- `core/`: no measurement module yet. F2b introduces `core/measurement.py` (pure aggregation logic: Solar API segment → `Measurement` VO) with 100% coverage.
- `adapters/`: F2b introduces `adapters/solar_api.py` (Google Solar API) + `adapters/squarequote.py` (SquareQuote B2B API, mocked until fixed and API key lands). The SquareQuote ml-service is at `~/projects/eaglepoint` — do NOT import its source into this repo.
- Gap: the current `core/estimator.py` takes `QuoteInput` with `num_squares` as a flat float. F2 + F2b replace this with a `Measurement` VO input path alongside the manual override path.

**Future extraction seam.** Measurement is already structured as a port — it is trivially extractable to a standalone measurement service (which SquareQuote already approximates). The seam is `adapters/solar_api.py` + `MeasurementProvider` protocol.

---

## 2. Ubiquitous Language Glossary

Alphabetized. Each term is followed by the context(s) it belongs to and a one-sentence definition.

**Accept Token** *(Quoting/Proposal)* — A 512-bit random token (`secrets.token_bytes(64)` encoded as ~86-char URL-safe base64), single-use and version-bound, embedded in the proposal accept link; invalidated on use or supersession. Generation is owned by TRD-F3.

**AIO (AI Overview)** *(Content/Marketing)* — A Google Search feature that surfaces a synthesized answer at the top of results; targeted by FAQ schema + 40–60 word answer blocks on articles.

**Archive URI** *(Corpus/KB)* — The `gs://` URI of a video's source MP4 in the GCS media bucket; immutable once set.

**Article** *(Content/Marketing)* — A long-form SEO content piece belonging to a pillar or cluster; has a role (pillar / support), lifecycle status, and structured FAQ + JSON-LD metadata.

**Azimuth** *(Measurement)* — The compass bearing of a roof segment's slope direction, as reported by the Solar API; used with pitch to compute solar exposure and material selection logic.

**Branch** *(Pricing/Estimating)* — A geographic pricing unit (Miami / Jupiter / Naples); each branch has a default code_zone and an associated PricingConfig version. Distinct from a company branch — it is a pricing configuration partition.

**Brand Kit** *(Content/Marketing)* — Per-tenant config: logo, color palette, fonts, intro/outro GCS URIs, voice samples. Stored in `Tenant.settings JSONB`; drives all content generation and clip rendering.

**Caption Contract v5** *(Content/Marketing)* — The current JSON schema for clip captions, defining structure, platform targets, hook line, hashtags, and compliance flags. v3 is accepted as a fallback during migration only.

**Chunk** *(Corpus/KB)* — The retrieval unit for vector search; a fixed-size segment of transcript text with a 3072-dimensional Gemini embedding. Each chunk belongs to exactly one video.

**Cluster** *(Content/Marketing)* — A group of articles organized around one pillar topic, with a lifecycle (pending → active → complete) and an activation position. The pillar article publishes before its supporting articles.

**Code Zone** *(Pricing/Estimating, Measurement)* — The building-code jurisdiction of a property: `HVHZ` (Miami-Dade + Broward) or `FBC` (Palm Beach, Lee, St. Lucie and other Florida counties). Stored on Property; overridable per quote; drives the pricing config variant applied to each line item.

**Commission** *(Pricing/Estimating)* — Sales representative compensation computed as profit_dollars × rate (sloped = 10%, low-slope = 15%; HVHZ-sloped rate is config-driven pending Tim confirmation); not a percentage of revenue or project total.

**Commission Basis** *(Pricing/Estimating)* — The dollar amount on which commission is calculated: profit dollars only (the Profit-tagged line items from the estimate), never the full project total or revenue. Commission = profit_dollars × rate (sloped = 10%, low-slope = 15%; HVHZ-sloped rate is config-driven pending Tim confirmation).

**Config Hash** *(Pricing/Estimating)* — RFC 8785 JSON-Canonical + SHA-256 of a PricingConfig; stamped on every estimate and embedded in every QuoteSnapshot; enables exact reproducibility of any historical estimate.

**Corpus** *(Corpus/KB)* — The full collection of ingested videos, their transcripts, graph nodes, and embeddings; the raw material for all content generation and retrieval.

**Cost Category** *(Pricing/Estimating)* — One of seven tags on a line item, using these exact enum literals: `Labor` / `Materials` / `Equipment` / `Sub` / `Misc` / `OH` (Overhead) / `Profit`. Required for correct floor computation — the 13% profit floor applies to `Profit`-tagged dollars; the 33% floor applies to `Profit` + `OH` dollars. Insulation line items exclude `Profit` only (floor-exemption VO semantics); tapered insulation excludes both `OH` and `Profit`.

**Customer** *(Quoting/Proposal)* — A person or company with one or more properties who is the recipient of proposals. Has contacts; optionally carries a `knowify_customer_id` for migration.

**Deposit** *(Quoting/Proposal)* — The amount (percentage or fixed) due from the client on proposal acceptance, with payment instructions. Recorded on the Proposal; no payment processing in v1.

**Drip Throttle** *(Content/Marketing)* — The pair of settings controlling the publish pipeline: seed_pct (fraction published immediately on cluster activation) and target_in_flight (concurrent articles being published). Both are per-tenant Admin → Marketing config.

**E-Sign Record** *(Quoting/Proposal)* — The immutable audit record of a client's proposal acceptance: IP, User-Agent, view timestamp, accept timestamp, consent flag, and typed name. Satisfies ESIGN/UETA.

**Estimate** *(Pricing/Estimating)* — The computed, itemized cost build-up for a roofing job, produced by the pricing engine from a PricingConfig + measurement inputs. Immutable once computed; a revision produces a new Estimate. Not the same as a Quote or Proposal — see those terms.

**FBC (Florida Building Code)** *(Pricing/Estimating, Measurement)* — The building code baseline applicable to Palm Beach, Lee, St. Lucie, and most other Florida counties outside the HVHZ; drives a distinct set of base costs and OH rates.

**Floor (13% / 33%)** *(Pricing/Estimating)* — Minimum margin constraints from Exhibit B: profit dollars must be ≥13% of project total; profit + overhead dollars must be ≥33% of project total. Correctly computable only when line items carry CostCategory tags.

**Golden File** *(Pricing/Estimating)* — One of five canonical Exhibit C quote scenarios (498-SQ low-slope HVHZ · 15-SQ low-slope FBC · 28-SQ sloped HVHZ · 28-SQ sloped FBC · 41.5-SQ standing-seam FBC) that the engine must reproduce ±$0.01 or ±0.01%. Permanent CI fixtures.

**Good-Better-Best** *(Quoting/Proposal)* — Tiered pricing presented on the proposal accept page; client selects one tier and optionally opts into add-on line items. A key differentiator over Knowify.

**HVHZ (High-Velocity Hurricane Zone)** *(Pricing/Estimating, Measurement)* — Miami-Dade and Broward counties; the most stringent wind-resistance code zone in Florida. Carries its own base costs, overhead, and code requirements distinct from FBC.

**Handoff** *(Quoting/Proposal)* — The transition from accepted proposal to active job, triggered after deposit acknowledgment. In v1, handoff sets a job status flag and optionally notifies Knowify.

**Ingestion Run** *(Corpus/KB)* — A per-video, per-stage (transcript / graph / embed) execution record; idempotent via content_hash; the mechanism for resumable/retry ingestion.

**Job Handoff** — see Handoff.

**Lead** *(Quoting/Proposal)* — A lightweight source-tracking record (not a CRM); converts to a Customer + Property pair when qualified.

**Low-Slope** *(Pricing/Estimating)* — Roof category covering TPO, coatings (silicone, elastomeric), BUR, and related systems; has its own Exhibit B rate tables, insulation tiers, deck types, and commission rate (15%). Distinct from `sloped` (tile/shingle/metal).

**Measurement** *(Measurement)* — The value object representing measured roof quantities: total_squares, hips/ridges/valleys/rakes/eaves/wall_flashings in linear feet, and per-segment pitch/azimuth/area. Produced by a MeasurementProvider; consumed by the estimating engine.

**Measurement Provider** *(Measurement)* — The port interface (adapter pattern) through which the estimating context receives measurement data. Implementations: Solar API adapter, SquareQuote adapter, manual-entry adapter.

**Measurement Segment** *(Measurement)* — A single roof plane as reported by the Solar API: area in squares, pitch (rise/run), and azimuth. Multiple segments compose into a Measurement VO.

**Mini Series** *(Content/Marketing)* — A set of proposed short-form clips derived from a single video, with in/out points for each part. Requires admin approval before entering the distribution queue.

**Money** *(Pricing/Estimating)* — A value object representing a monetary amount in USD. Currency is always USD in v1; never stored as a raw float without unit context.

**Pillar** *(Content/Marketing)* — The primary article in a cluster; covers the broadest keyword for that topic. Publishes before its supporting articles; activation of its cluster sets status to active.

**pitch** *(Measurement, Pricing/Estimating)* — The slope of a roof plane expressed as rise:run (e.g., 7/12). The Solar API reports pitch per segment. The estimating engine applies pitch adders for tile roofs at ≥7/12 pitch.

**Platform Admin** *(Tenancy/Identity)* — The cross-tenant provisioning role, available only to DeGenito-internal users. Provisions new tenants, seeds configs, and manages GCIP tenant assignments. Distinct from `admin` (tenant-scoped role).

**Pricing Config** *(Pricing/Estimating)* — A versioned, immutable JSONB document containing all rate tables for a given tenant + branch: base costs, overhead, profit scale, adders, PM incentive matrix, dumpster thresholds, tax flags. Edited in Admin → Estimating; each save produces a new version.

**Proposal** *(Quoting/Proposal)* — The formal versioned document sent to a client for acceptance. Wraps a QuoteSnapshot with a template, version chain, and e-sign infrastructure. Not the same as an Estimate (the computation) or a Quote (informal term).

**Quote** *(colloquial)* — Informal term for an Estimate as presented during a sales discussion. In data: `quote_snapshot` is the frozen Estimate embedded in a Proposal. "Quote" is never a distinct data entity.

**Quote Snapshot** *(Quoting/Proposal)* — A frozen JSONB copy of an Estimate at the time a Proposal is sent; includes the pricing_config_hash. Immutable once the proposal is sent.

**Revision** *(Quoting/Proposal)* — A new Proposal version created when a client requests changes to a sent proposal; the prior version transitions to `superseded` and its accept token is invalidated.

**RLS (Row-Level Security)** *(Tenancy/Identity)* — PostgreSQL row-level security policy enforcing `tenant_id = current_setting('app.tenant_id')` on every tenant-scoped table. The suspenders in the belt-and-suspenders tenant isolation.

**Roof Section** *(Pricing/Estimating)* — A value object representing a portion of a roof job: slope type (sloped / low-slope), area in squares, and code_zone. Used when a job has mixed slopes or mixed code zones.

**Safety Gate** *(Content/Marketing)* — The two-layer pre-publish check in `core/content_safety.py`: (1) fast denylist/regex for crude terms; (2) LLM-judge rubric scoring professional/on-brand/safe. Fail-closed: no judge wired = FAIL.

**Seed Percent** *(Content/Marketing)* — The fraction of a newly activated cluster's articles published immediately (vs. dripped). Default 55%; configurable per-tenant in Admin → Marketing.

**Sliding Scale** *(Pricing/Estimating)* — The profit-per-square lookup table keyed by total number of squares: larger jobs earn less profit per square (economies of scale). From Exhibit B: 1 sq=$400, 4=$200, … 30+=$100. Lower-inclusive/upper-exclusive boundary rule pending Tim confirmation (open item).

**Social Post** *(Content/Marketing)* — One distribution record per (MiniSeries, part, platform). Owns publish status and external platform ID. Uniqueness constraint enforces idempotency.

**Square (SQ)** *(Pricing/Estimating, Measurement)* — The roofing unit of area: 1 square = 100 square feet. All area measurements are expressed in squares.

**Supersede** *(Quoting/Proposal)* — The act of replacing a sent proposal version with a revision; the superseded version's accept token is invalidated immediately and its accept link returns HTTP 200 with a terminal "This proposal has been updated — contact the contractor for the new link" page. Unknown/non-existent tokens return 404-indistinguishable.

**Tapered Insulation** *(Pricing/Estimating)* — A low-slope roofing material with specific Exhibit B cost rules: no overhead or profit added (Exhibit B markup exemption). Must be tagged with appropriate CostCategory to compute floors correctly.

**Tear-off** *(Pricing/Estimating)* — Removal of the existing roof system before installation. Triggers a per-square demo adder: tile tear-off = $40/sq, metal tear-off = $60/sq, shingle tear-off = $0.

**Tenant** *(Tenancy/Identity)* — A licensee of the platform; each tenant has isolated data, per-tenant pricing configs, per-tenant social credentials, per-tenant brand kit. Perkins is Tenant 1.

**Tier** — see Good-Better-Best.

**Usage Metering** *(Tenancy/Identity)* — Per-tenant counters for LLM tokens, STT minutes, and render minutes, emitted on the structured-log path. The future billing story for licensees; costs nothing to record now.

---

## 3. Context Map

### 3.1 Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tenancy / Identity                           │
│           (upstream of ALL — tenant context required)           │
└──────────────────────────┬──────────────────────────────────────┘
              upstream (Tenancy provides tenant_id;
              all other contexts conform)
     ┌─────────┬────────────┼────────────┬──────────┐
     ▼         ▼            ▼            ▼          ▼
  Corpus/   Content/    Pricing/     Quoting/  Measurement
    KB      Marketing   Estimating   Proposal
     │         │            ▲            ▲          │
     │ retrieval│            │            │          │
     │ (ACL)   │            │            │ Measurement VO
     └─────────►            │            │ (port)
   Content/Marketing        │            │          │
   calls corpus via         │            └──────────┘
   RetrievalPort            │    Estimating→Quoting:
   (anti-corruption         │    QuoteSnapshot (frozen copy,
    layer on read path)     │    not live reference)
                            │
              PricingConfig + Estimate
              referenced by hash in QuoteSnapshot
```

### 3.2 Integration seams — named precisely

**Estimating → Quoting via QuoteSnapshot.**
When a Proposal is drafted, the current Estimate is serialized to `quote_snapshot` JSONB (a frozen copy, including `pricing_config_hash`). The Quoting context does not hold a live reference to the Estimate or PricingConfig. If pricing changes after sending, the sent proposal is unaffected. This is a customer/supplier relationship where Estimating is upstream; Quoting consumes a snapshot.

**Measurement → Estimating via MeasurementProvider port.**
The estimating engine accepts a `Measurement` value object. It never calls Solar API or SquareQuote directly. The `MeasurementProvider` port is in `adapters/`; the engine in `core/estimator.py` takes `Measurement` as an input parameter. This is a ports-and-adapters (hexagonal) seam, not a context dependency.

**Tenancy is upstream of everything.**
Every other context receives `tenant_id` from the Tenancy context via the session pattern (`SET LOCAL app.tenant_id` in a SQLAlchemy after-begin event). No context resolves tenant identity itself. This is a conformist relationship — all downstream contexts adopt the Tenancy model without translation.

**Content/Marketing → Corpus/KB via RetrievalPort (ACL).**
Content generation (articles, clip selection, avatar scripts) calls into the Corpus via a `RetrievalPort` interface that returns `Chunk` lists. Content/Marketing does not write to the Corpus. The ACL prevents Corpus internals (embedding model, ingestion run state) from leaking into the Content domain. In code: `core/retrieval.py` is the Corpus side; the Content modules call it via dependency injection.

**External ports and ACLs.**

| External system | Context | Adapter | Notes |
|---|---|---|---|
| Google Solar API | Measurement | `adapters/solar_api.py` (F2b) | Primary measurement provider; ToS-clean |
| SquareQuote B2B API | Measurement | `adapters/squarequote.py` (dropped — LiDAR path removed by locked decision) | LiDAR/PDAL permanently out of scope; Solar API + manual entry are the only providers. Paid oblique-imagery is the only future upgrade path. Do NOT import eaglepoint source. |
| Gotenberg | Quoting/Proposal | `adapters/gotenberg.py` (F3) | HTML→PDF; Cloud Run IAM-locked |
| GCIP (Firebase Auth) | Tenancy/Identity | `adapters/gcip.py` (F4) | Token verification + tenant resolution |
| Social platform APIs | Content/Marketing | `adapters/meta_ig.py`, `tiktok.py`, `youtube_comments.py`, etc. | Per-platform OAuth; per-tenant creds from Secret Manager |
| HeyGen | Content/Marketing | `adapters/heygen.py` (F5, mocked) | Avatar video generation |
| ElevenLabs | Content/Marketing | `adapters/elevenlabs.py` (F5, mocked) | Voice clone + TTS |
| Knowify | Quoting/Proposal | Optional Zapier bridge on job handoff | One-way; XLS import for customer/catalog migration; no proposal API |
| GCS | Corpus/KB, Content/Marketing | `adapters/archive.py` | Media bucket; per-tenant prefixes `tenants/{id}/…` |
| Secret Manager | Tenancy/Identity | GCP client (all adapters that need creds) | Per-tenant social + API creds under `tenants/{id}/…` |
| Vertex AI / Gemini | Corpus/KB, Content/Marketing | LLM call wrappers | Embedding-001 (3072-dim) for corpus; generative models for content |

### 3.3 Shared kernel

There is one shared kernel: the `Money` value object (amount in USD cents as int) and the `TenantId` scalar. These are used across Pricing/Estimating, Quoting/Proposal, and Tenancy. They are defined once in a shared `core/types.py` (to be created in F0) and imported where needed. No other cross-context sharing is permitted without explicit justification.

---

## 4. Architecture notes

### Modular monolith, not microservices

Every context maps to modules within a single deployable unit (Cloud Run API + Cloud Run Jobs). The directory layout enforces the context boundaries:

```
core/estimator.py          → Pricing/Estimating domain logic
core/proposal.py           → Quoting/Proposal domain logic (F3)
core/measurement.py        → Measurement domain logic (F2b)
core/publish_planner.py    → Content/Marketing pipeline logic
core/content_safety.py     → Content/Marketing safety gate
core/retrieval.py          → Corpus/KB retrieval
core/authz.py              → Tenancy/Identity role enforcement
adapters/solar_api.py      → Measurement port impl
adapters/gotenberg.py      → Quoting/Proposal port impl
adapters/distribution/*    → Content/Marketing port impls
api/routes/estimator.py    → Pricing/Estimating app surface
api/routes/proposals.py    → Quoting/Proposal app surface (F3)
jobs/publish_job.py        → Content/Marketing job surface
jobs/distribute_job.py     → Content/Marketing job surface
```

The context boundary is enforced by discipline (code review, R2 architect review) not by process isolation. A module in `core/estimator.py` must not import from `core/proposal.py` — the dependency arrow always points from application layer down to domain, and cross-context calls in `core/` are prohibited. Cross-context data transfer uses value objects passed through the application layer.

### Where future extraction seams are

If the platform grows to warrant microservice extraction, the seams are:

1. **Measurement service** — `core/measurement.py` + `adapters/solar_api.py` + `adapters/squarequote.py`. The SquareQuote ml-service at `~/projects/eaglepoint` already approximates this shape. Clean boundary: `MeasurementProvider` port.
2. **Rendering pipeline** — Track A (reframe/captions/music/fx/b-roll). Already jobs-based; extraction = give it its own Cloud Run service + queue. Seam: `core/render_spec.py` + job interface.
3. **Corpus / retrieval** — `core/retrieval.py` + pgvector index. Extraction warranted if tenant count drives HNSW index partitioning past what a single Cloud SQL instance handles cleanly.
4. **Tenancy / Identity** — `core/authz.py` + GCIP. Extraction if multi-region or per-tenant SSO admin UI is needed.
5. **Proposal / document service** — `core/proposal.py` + Gotenberg adapter. Extraction if regulated storage (SOC2, HIPAA) is ever required for signed documents.

None of these are v1 concerns. The seams exist so extraction never requires a domain rewrite — only a deployment change and a port swap.

---

## 5. Modeling tensions found

The following places in the current code fight the target domain model. Each will be closed by the wave noted.

1. **`core/estimator.py` rate tables are hardcoded constants, not config.** The `BASE_COST_LM`, `OVERHEAD`, `PROFIT_SCALE` dicts are module-level constants. The target model has these in a versioned, admin-editable `PricingConfig` aggregate. Until F2, any pricing change requires a code deploy. The `estimate()` function signature (`QuoteInput → dict`) also needs to become `estimate(config: PricingConfig, input: QuoteInput) → Estimate`. **Closed by F2.**

2. **`margin_ok` uses wrong denominator.** The current engine computes `profit_pct = profit_dollars / project_total`, which approximates the 13% floor but cannot compute the 33% profit+OH floor because overhead is baked into `BASE_COST_LM` (not separately tagged). The target model requires CostCategory-tagged line items. **Closed by F2 (cost-category tags).**

3. **`app/models.py` has no tenant scope.** Every table is global. The entire model is a pre-F0 flat schema. Post-F0, every tenant-scoped table carries `tenant_id` FK. Post-F4, every table has an RLS policy. The current code would silently leak data between tenants if a second tenant were onboarded today. **Closed by F0 (FK) + F4 (RLS).**

4. **`PlatformConfig` is a global key/value store.** It is used for settings that in the target model are per-tenant (`brand kit`, `caption prompts`, `social creds`, `seed %`, `abstain threshold`). Post-F5, per-tenant config lives in `Tenant.settings JSONB`; `PlatformConfig` becomes platform-wide-only (non-tenant settings). **Closed by F5.**

5. **`SocialPost` has no tenant_id.** It references `series_id` (a `MiniSeries` ID) which itself has no tenant_id today. The entire social distribution path is currently single-tenant by assumption. **Closed by F0 (add tenant_id to all tables) + F5 (per-tenant social creds wired).**

6. **`MiniSeries.parts_json` is untyped JSON.** The clip in/out point structure is a free-form JSON blob. The target model has this as a typed value object (`RenderSpec` or similar) in `core/render_spec.py`. The path to typed render specs is already partially built (`core/render_spec.py` exists) but the ORM model has not caught up. **Closed by F5 (Clip Studio wiring).**

7. **No `Proposal`, `Customer`, `Property`, `Lead`, or `PricingConfig` in `app/models.py`.** These are the core F3 and F2 aggregates. The current model has no representation of the quoting domain. **Closed by F2 (PricingConfig) + F3 (quoting models).**

8. **`QuoteInput` in `core/estimator.py` takes `num_squares: float` as a flat scalar.** The target model has `Measurement` as the input VO (with per-segment detail). The flat scalar is the manual-entry fallback. Both paths need to be first-class and explicitly labeled. **Closed by F2b (Measurement VO + MeasurementProvider port).**
