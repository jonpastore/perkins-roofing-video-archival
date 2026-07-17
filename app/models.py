"""SQLAlchemy data layer. Dev: SQLite (embedding as JSON). Prod: Postgres + pgvector
(swap Chunk.embedding to Vector(3072) + HNSW index via migration). The canonical
versioned-artifact model the council required: every derived row carries a version, and
IngestionRun tracks per-stage status + content_hash for idempotent/resumable ingestion."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

from core.tenant import TenantMixin

from .config import settings

Base = declarative_base()


# ---------------------------------------------------------------------------
# Platform-level: Tenant registry
# ---------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="active")
    settings = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

try:
    from pgvector.sqlalchemy import Vector
    _EMBEDDING = JSON().with_variant(Vector(3072), "postgresql")
except ImportError:
    _EMBEDDING = JSON()

class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    title = Column(String); duration = Column(Float); upload_date = Column(String)
    views = Column(Integer); likes = Column(Integer); comments = Column(Integer)
    url = Column(String)
    archive_uri = Column(String)
    comment_count = Column(Integer)
    last_comment_at = Column(DateTime)
    kpis_polled_at = Column(DateTime)
    last_pulled_at = Column(DateTime)
    clips_generated_at = Column(DateTime)
    comments_crawled_at = Column(DateTime)
    unavailable_since = Column(DateTime, nullable=True)
    hidden_at = Column(DateTime, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_videos_tenant_id", "tenant_id"),)

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    stage = Column(String)
    status = Column(String)
    content_hash = Column(String)
    pipeline_version = Column(String)
    attempts = Column(Integer, default=0)
    last_error = Column(Text)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        Index("ix_run_video_stage", "video_id", "stage"),
        Index("ix_ingestion_runs_tenant_video_stage", "tenant_id", "video_id", "stage"),
    )

class Segment(Base):
    __tablename__ = "segments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    text = Column(Text); start = Column(Float); end = Column(Float)
    source = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_segments_tenant_video", "tenant_id", "video_id"),)

class Word(Base):
    __tablename__ = "words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    word = Column(String); start = Column(Float); confidence = Column(Float)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_words_tenant_video", "tenant_id", "video_id"),)

class GraphNode(Base):
    __tablename__ = "content_graph"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    kind = Column(String)
    label = Column(String); detail = Column(Text); start = Column(Float)
    version = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_content_graph_tenant_video", "tenant_id", "video_id"),)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    text = Column(Text); start = Column(Float); end = Column(Float)
    embedding = Column(_EMBEDDING)
    embed_model = Column(String); version = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_chunks_tenant_video", "tenant_id", "video_id"),)

class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String); subject = Column(String); body = Column(Text)
    created_by = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_email_templates_tenant_id", "tenant_id"),)


class EmailLog(Base, TenantMixin):
    """Audit trail for every outbound email attempt.

    Rows are written by adapters/resend.py for sent, blocked, failed, and
    dry-run attempts. The body is intentionally not stored; subjects/recipients
    are enough for operational audit while limiting PII/content retention.
    """
    __tablename__ = "email_logs"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    provider            = Column(String(50), nullable=False, default="resend")
    send_type           = Column(String(100), nullable=False, default="resend")
    from_email          = Column(String(255), nullable=False)
    to_email            = Column(String(255), nullable=False)
    subject             = Column(Text, nullable=False)
    status              = Column(String(30), nullable=False)
    provider_message_id = Column(String(255), nullable=True)
    error               = Column(Text, nullable=True)
    email_metadata      = Column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)

    __table_args__ = (
        Index("ix_email_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_email_logs_tenant_status", "tenant_id", "status"),
        Index("ix_email_logs_tenant_send_type", "tenant_id", "send_type"),
    )


class AuditLog(Base, TenantMixin):
    """Who did what, when, to which entity, and what happened. Migration 0036.

    Written for EVERY mutating HTTP request by api/audit_mw.py rather than per-route: there
    are 86 mutating endpoints across 25 modules, and per-route calls guarantee the 87th is
    forgotten. Domain code layers semantic rows on top via core.audit.record() where the route
    alone does not say what happened ("proposal.sign" means more than "POST /proposals/3/sign").

    Failed requests are recorded too — an unexplainable 403 is the main thing this is for — so
    rows are written in their own transaction and survive the request's rollback.

    `detail` is redacted before write (core.audit.redact): never passwords, tokens, or request
    bodies. An audit log that leaks credentials is a liability, not a control.
    """
    __tablename__ = "audit_log"

    # BIGSERIAL in Postgres; plain INTEGER on SQLite, which only autoincrements an
    # "INTEGER PRIMARY KEY" — a BIGINT pk silently yields id=NULL and every insert dies with
    # "NOT NULL constraint failed: audit_log.id". Prod looked fine, so only the tests caught it.
    id               = Column(BigInteger().with_variant(Integer, "sqlite"),
                              primary_key=True, autoincrement=True)
    occurred_at      = Column(DateTime, nullable=False, default=_utcnow)

    actor_email      = Column(String(320), nullable=True)
    actor_role       = Column(String(50), nullable=True)
    impersonating    = Column(Boolean, nullable=False, default=False)
    impersonating_as = Column(Integer, nullable=True)

    action           = Column(String(120), nullable=False)
    entity_type      = Column(String(60), nullable=True)
    entity_id        = Column(String(255), nullable=True)

    method           = Column(String(10), nullable=True)
    route            = Column(String(255), nullable=True)
    path             = Column(String(1024), nullable=True)
    status_code      = Column(Integer, nullable=True)
    request_id       = Column(String(64), nullable=True)
    source           = Column(String(20), nullable=False, default="api")

    detail           = Column(JSON().with_variant(JSONB, "postgresql"),
                              nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_log_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_audit_log_tenant_actor", "tenant_id", "actor_email", "occurred_at"),
        Index("ix_audit_log_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_audit_log_tenant_action", "tenant_id", "action", "occurred_at"),
    )


class Cluster(Base):
    __tablename__ = "clusters"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pillar_topic = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    position = Column(Integer, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_clusters_tenant_id", "tenant_id"),)


class Article(Base):
    __tablename__ = "articles"
    slug = Column(String, primary_key=True)
    title = Column(String); meta = Column(Text)
    content_md = Column(Text); faq_json = Column(JSON); jsonld_json = Column(JSON)
    role = Column(String)
    pillar_slug = Column(String)
    wp_post_id = Column(Integer)
    status = Column(String)
    publish_at = Column(DateTime)
    focus_keyword = Column(String)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    priority = Column(Integer, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    generated_at = Column(DateTime, default=_utcnow)
    # Last write, on EVERY path. `onupdate` is SQLAlchemy's, so it fires for any UPDATE from
    # any caller — seven modules write content_md, and a stamp each one has to remember is a
    # stamp six of them will miss. Matches the convention already on six other tables here.
    # generated_at stays what its name says: first generation. Migration 0037.
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_articles_tenant_status", "tenant_id", "status"),)

class ScheduledContent(Base):
    __tablename__ = "scheduled_content"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String)
    ref_id = Column(String)
    publish_at = Column(DateTime)
    status = Column(String, default="scheduled")
    target = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_scheduled_content_tenant_status", "tenant_id", "status"),)

class MiniSeries(Base):
    __tablename__ = "mini_series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    title = Column(String)
    parts_json = Column(JSON)
    approved = Column(Integer, default=0)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_mini_series_tenant_video", "tenant_id", "video_id"),)

class SocialPost(Base):
    __tablename__ = "social_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(Integer, index=True)
    part = Column(Integer)
    platform = Column(String)
    gcs_url = Column(String)
    external_id = Column(String)
    status = Column(String, default="pending")
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("series_id", "part", "platform", name="uq_social_series_part_platform"),
        Index("ix_social_posts_tenant_series", "tenant_id", "series_id"),
    )

class AggregatedTopic(Base):
    __tablename__ = "aggregated_topics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_label = Column(String, nullable=False, index=True)
    num_videos = Column(Integer, nullable=False, default=0)
    total_seconds = Column(Float, nullable=False, default=0.0)
    video_ids = Column(JSON, nullable=False)
    node_ids = Column(JSON, nullable=False)
    version = Column(String, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_aggregated_topics_tenant_id", "tenant_id"),)


class CorsOrigin(Base):
    """Platform-level CORS allow-list — app-owned, no TF resource attribute.
    tenant_id NULL = platform-wide; non-null = tenant-scoped (added at domain onboarding W2).
    RLS-exempt: read before tenant context is resolved; filtered in-process by the middleware.
    """
    __tablename__ = "cors_origins"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    origin     = Column(String, nullable=False, unique=True)
    tenant_id  = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    __table_args__ = (Index("ix_cors_origins_tenant_id", "tenant_id"),)


class PlatformConfig(Base):
    __tablename__ = "platform_config"
    key = Column(String, primary_key=True)
    value = Column(String)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String)


class SecretAudit(Base):
    """Audit log for secret writes via PUT /config/secrets.
    The secret VALUE is never stored here — only metadata.
    """
    __tablename__ = "secret_audit"
    key = Column(String, primary_key=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String)


# ---------------------------------------------------------------------------
# F4b — GCIP identity platform-level models (no TenantMixin; RLS-exempt)
# ---------------------------------------------------------------------------

class TenantGcipMap(Base):
    """Platform tenant -> GCIP tenant mapping. Platform-level, no RLS."""
    __tablename__ = "tenant_gcip_map"
    tenant_id   = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    gcip_tenant = Column(String, nullable=False, unique=True)


class TenantDefaultAdmin(Base):
    """Per-tenant admin email list. F4 is the single owner (TRD-F4 sec 4.4a)."""
    __tablename__ = "tenant_default_admins"
    tenant_id   = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    email       = Column(String, nullable=False, primary_key=True)


class PlatformAdmin(Base):
    """DeGenito staff platform_admin grants (cross-tenant)."""
    __tablename__ = "platform_admins"
    email      = Column(String, primary_key=True)
    granted_by = Column(String, nullable=False)
    granted_at = Column(DateTime, nullable=False, default=_utcnow)


class PlatformAuditLog(Base):
    """Platform-level audit trail: actions ABOUT tenants, or about the platform itself.

    Started as impersonation-only (TRD-F4 §4.4 #3); generalised by migration 0038 to cover the
    admin-portal surface — tenant provisioning/offboarding, platform_admin grants, SSO/IdP
    config, billing plans, feature flags — none of which have a tenant_id.

    Deliberately a SEPARATE table from audit_log rather than a nullable tenant_id on it.
    audit_log is RLS tenant-scoped; a NULL-tenant row fails its policy for everyone, and the
    policy needed to fix that ("... OR platform_scope AND tenant_id IS NULL") would guard the
    schema's most sensitive rows with a GUC the app sets on itself, inside the table every
    tenant reads daily. Table separation makes that leak structurally impossible and matches
    the boundary already drawn here: this table, tenants, platform_admins and
    tenant_offboard_log are RLS-exempt and reachable only via PlatformSessionLocal.

    The two are unioned at the READ layer (GET /audit?scope=all) and correlate on request_id,
    so one request spanning both — a platform admin impersonating a tenant, then editing — is
    still a single story.
    """
    __tablename__ = "platform_audit_log"
    id                   = Column(Integer, primary_key=True, autoincrement=True)
    platform_admin_email = Column(String, nullable=False)
    # Nullable since 0038: impersonation has a target, "create tenant" does not.
    target_tenant_id     = Column(Integer, nullable=True)
    route                = Column(String, nullable=False)
    method               = Column(String, nullable=False)
    occurred_at          = Column(DateTime, nullable=False, default=_utcnow)

    action               = Column(String(120), nullable=True)
    entity_type          = Column(String(60), nullable=True)
    entity_id            = Column(String(255), nullable=True)
    status_code          = Column(Integer, nullable=True)
    request_id           = Column(String(64), nullable=True)
    source               = Column(String(20), nullable=False, default="api")
    path                 = Column(String(1024), nullable=True)
    detail               = Column(JSON().with_variant(JSONB, "postgresql"),
                                  nullable=False, default=dict)

    __table_args__       = (
        Index("ix_platform_audit_log_admin", "platform_admin_email"),
        Index("ix_platform_audit_log_time", "occurred_at"),
        Index("ix_platform_audit_log_action", "action", "occurred_at"),
        Index("ix_platform_audit_log_req", "request_id"),
    )


class IntegrationStatus(Base):
    """Per-integration health status (plan 2026-07-17 Phase 1.2). PLATFORM-LEVEL:
    no RLS (migration 0039; same boundary as tenant_offboard_log — a NULL-tenant
    row is invisible under the standard RLS policy, and shared-integration probes
    run with no tenant GUC). tenant_id NULL = shared integration (knowify, resend,
    wordpress); per-tenant OAuth rows carry tenant_id. Filter in-query. Deliberately
    NOT in core/offboard.py _TENANT_SCOPED_TABLES (shared rows must survive
    offboarding; status strings are not tenant content)."""
    __tablename__ = "integration_status"
    id                   = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id            = Column(Integer, nullable=True)   # NULL = platform-level shared
    integration          = Column(String, nullable=False)
    status               = Column(String, nullable=False, default="unconfigured")
    last_checked         = Column(DateTime)
    last_ok              = Column(DateTime)
    last_error           = Column(Text)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    updated_at           = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        Index("uq_integration_status_tenant", "tenant_id", "integration", unique=True,
              postgresql_where=text("tenant_id IS NOT NULL"),
              sqlite_where=text("tenant_id IS NOT NULL")),
        Index("uq_integration_status_shared", "integration", unique=True,
              postgresql_where=text("tenant_id IS NULL"),
              sqlite_where=text("tenant_id IS NULL")),
    )


class OAuthStateNonce(Base):
    """Single-use OAuth capture-flow nonce (plan Phase 1.5). PLATFORM-LEVEL, no RLS
    (0039): the callback is an unauthenticated browser GET — the signed state plus
    this row ARE the tenant binding. Burned atomically (DELETE ... RETURNING) at the
    callback; expires_at fails closed. Not in _TENANT_SCOPED_TABLES (short-lived)."""
    __tablename__ = "oauth_state_nonces"
    nonce      = Column(String, primary_key=True)
    tenant_id  = Column(Integer, nullable=False)
    platform   = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)


class TenantOffboardLog(Base):
    """Audit trail for tenant offboarding (F5 §9). Platform-level: no tenant_id FK
    (the tenant row may be deleted), no RLS. Created by migration 0019 (F4's 0018
    documented ownership but never shipped the table)."""
    __tablename__ = "tenant_offboard_log"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id     = Column(Integer, nullable=False)
    offboarded_at = Column(DateTime, nullable=False, default=_utcnow)
    offboarded_by = Column(String, nullable=False)
    gcs_prefix    = Column(String, nullable=False)
    row_counts    = Column(JSON, nullable=False)
    status        = Column(String, nullable=False, default="pending")
    __table_args__ = (Index("ix_tenant_offboard_log_tenant_id", "tenant_id"),)


class CommentDraft(Base):
    __tablename__ = "comment_drafts"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    video_id     = Column(String, nullable=False, index=True)
    comment_id   = Column(String, nullable=False)
    platform     = Column(String, nullable=False, server_default="youtube", default="youtube")
    author       = Column(String)
    comment_text = Column(Text, nullable=False)
    published_at = Column(DateTime)
    needs_reply  = Column(Boolean, nullable=False, default=False)
    draft_reply  = Column(Text)
    status       = Column(String, nullable=False, default="pending")
    created_at   = Column(DateTime, default=_utcnow)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "comment_id", name="uq_comment_drafts_tenant_platform_comment"),
        Index("ix_comment_drafts_tenant_status", "tenant_id", "status"),
    )


class UserSetting(Base):
    """Per-user settings (email signature, etc.). email is the PK."""
    __tablename__ = "user_settings"
    email = Column(String, primary_key=True)
    signature = Column(Text, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_user_settings_tenant_id", "tenant_id"),)


class FaqEntry(Base):
    __tablename__ = "faq_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    source_kind = Column(String, nullable=False)
    source_node_id = Column(Integer, nullable=False, unique=True)
    video_id = Column(String, nullable=False, index=True)
    start = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="mined")
    created_at = Column(DateTime, default=_utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        Index("ix_faq_source_node", "source_node_id"),
        Index("ix_faq_entries_tenant_video", "tenant_id", "video_id"),
    )

class PricingConfig(Base):
    """Versioned, immutable per-tenant per-branch pricing configuration rows."""
    __tablename__ = "pricing_configs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    branch       = Column(String, nullable=False)
    version      = Column(Integer, nullable=False)
    label        = Column(String, nullable=True)
    config       = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    config_hash  = Column(String(64), nullable=False)
    is_active    = Column(Boolean, nullable=False, default=False)
    created_at   = Column(DateTime, nullable=False, default=_utcnow)
    created_by   = Column(String, nullable=False)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "branch", "version",
                         name="uq_pricing_configs_tenant_branch_version"),
        Index("ix_pricing_configs_tenant_branch", "tenant_id", "branch"),
        # One ACTIVE config per (tenant, branch); unlimited inactive version history.
        # Partial index (migration 0042) — replaces 0014's UNIQUE(tenant,branch,is_active)
        # which wrongly capped history at 2 rows/branch. The WHERE predicate must be set
        # per-dialect: without sqlite_where it degrades to a plain UNIQUE(tenant,branch)
        # on SQLite and blocks version history in tests.
        Index("uq_pricing_configs_one_active_per_branch", "tenant_id", "branch",
              unique=True, postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


class Estimate(Base):
    """Saved estimate rows — hash columns added in migration 0015."""
    __tablename__ = "estimates"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id           = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    pricing_config_id   = Column(Integer, ForeignKey("pricing_configs.id"), nullable=True)
    pricing_config_hash = Column(String(64), nullable=True)
    branch              = Column(String, nullable=True)
    code_zone           = Column(String, nullable=True)
    county              = Column(String, nullable=True)
    parent_id           = Column(Integer, ForeignKey("estimates.id"), nullable=True)
    root_id             = Column(Integer, ForeignKey("estimates.id"), nullable=True)
    version_number      = Column(Integer, nullable=False, default=1, server_default="1")
    source_proposal_id  = Column(Integer, ForeignKey("proposals.id"), nullable=True)
    input_json          = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    result_json         = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    created_by          = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_estimates_tenant_id", "tenant_id"),
        Index("ix_estimates_root", "root_id"),
        Index("ix_estimates_source_proposal", "source_proposal_id"),
    )


class Measurement(Base):
    """Measurement stub — full model in TRD-F2b. Manual-entry provider for F2.
    Migration 0024 added Solar API columns (address, lat/lng, imagery_*, source_building)."""
    __tablename__ = "measurements"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id         = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    property_id       = Column(Integer, nullable=True)
    provider          = Column(String, nullable=False, default="manual")
    status            = Column(String, nullable=False, default="complete")
    total_sq          = Column(Float, nullable=True)
    hips_lf           = Column(Float, nullable=True)
    ridges_lf         = Column(Float, nullable=True)
    valleys_lf        = Column(Float, nullable=True)
    rakes_lf          = Column(Float, nullable=True)
    eaves_lf          = Column(Float, nullable=True)
    wall_flashings_lf = Column(Float, nullable=True)
    pitch_primary     = Column(Float, nullable=True)
    segments_json     = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    confidence        = Column(Float, nullable=True)
    raw_payload       = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    provenance_note   = Column(String, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=_utcnow)
    created_by        = Column(String, nullable=False)
    # Migration 0024 — Solar API columns (additive, all nullable)
    address           = Column(String, nullable=True)
    latitude          = Column(Float, nullable=True)
    longitude         = Column(Float, nullable=True)
    imagery_date      = Column(String, nullable=True)
    imagery_quality   = Column(String, nullable=True)
    source_building   = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_measurements_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# F3 — Quoting / Proposals
# ---------------------------------------------------------------------------

class Branch(Base, TenantMixin):
    """First-class branches (Zoom 2026-07-17): drives every branch selector; each of
    Tim's companies (Miami/Jupiter/Naples/GC) is a branch; franchisee tenants get their
    own rows. Seeded by migration 0041."""
    __tablename__ = "branches"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String(50), nullable=False)
    name       = Column(String(100), nullable=False)
    active     = Column(Boolean, nullable=False, default=True, server_default="true")
    sort       = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_branches_tenant_key"),
    )


class Customer(Base, TenantMixin):
    __tablename__ = "customers"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    display_name        = Column(String(255), nullable=False)
    company_name        = Column(String(255))
    email               = Column(String(255))
    phone               = Column(String(50))
    knowify_customer_id = Column(String(100))
    # Branch the customer belongs to (branches.key). All Knowify-mirrored customers are
    # Miami until other subscriptions are connected; child assets inherit this.
    branch              = Column(String(50), nullable=False, default="miami", server_default="miami")
    # Mirrors Knowify ObjectState: a client Inactive/Cancelled/Deleted in Knowify is
    # is_active=False here (invoices for inactive clients are still imported/linked).
    is_active           = Column(Boolean, nullable=False, default=True, server_default="true")
    notes               = Column(Text)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    updated_at          = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_customers_tenant", "tenant_id"),
        Index("ix_customers_knowify", "tenant_id", "knowify_customer_id"),
        Index(
            "uq_customers_tenant_knowify", "tenant_id", "knowify_customer_id",
            unique=True, postgresql_where="knowify_customer_id IS NOT NULL",
        ),
    )


class Contact(Base, TenantMixin):
    __tablename__ = "contacts"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(255), nullable=False)
    role        = Column(String(100))
    email       = Column(String(255))
    phone       = Column(String(50))
    is_primary  = Column(Boolean, nullable=False, default=False)
    knowify_contact_id = Column(String(100))
    created_at  = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_contacts_customer", "customer_id"),
        Index("ix_contacts_tenant_knowify", "tenant_id", "knowify_contact_id"),
        Index(
            "uq_contacts_tenant_knowify", "tenant_id", "knowify_contact_id",
            unique=True, postgresql_where="knowify_contact_id IS NOT NULL",
        ),
    )


class Property(Base, TenantMixin):
    __tablename__ = "properties"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    customer_id         = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    street              = Column(String(255), nullable=False)
    city                = Column(String(100), nullable=False)
    state               = Column(String(2), nullable=False, default="FL")
    zip                 = Column(String(10))
    county              = Column(String(100))
    code_zone           = Column(String(10), nullable=False, default="FBC")
    knowify_customer_id = Column(String(100))
    gcs_pdf_prefix      = Column(String(500))
    notes               = Column(Text)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    updated_at          = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_properties_tenant", "tenant_id"),
        Index("ix_properties_customer", "customer_id"),
    )


class ProposalTemplate(Base, TenantMixin):
    __tablename__ = "proposal_templates"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    name               = Column(String(255), nullable=False)
    is_default         = Column(Boolean, nullable=False, default=False)
    html_body          = Column(Text, nullable=False)
    logo_url           = Column(String(1000))
    primary_color      = Column(String(7))
    accent_color       = Column(String(7))
    footer_text        = Column(Text)
    tc_attachment_gcs  = Column(String(1000))
    cover_page_html    = Column(Text)
    created_by         = Column(String(255), nullable=False)
    updated_at         = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_at         = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_templates_tenant", "tenant_id"),
    )


_PROPOSAL_STATUS = SAEnum(
    "draft", "sent", "viewed", "accepted", "declined",
    "revision_requested", "superseded",
    name="proposal_status",
    native_enum=True,
)

_PROPOSAL_EVENT_TYPE = SAEnum(
    "sent", "viewed", "accepted", "declined", "revision_requested", "reminder_sent",
    name="proposal_event_type",
    native_enum=True,
)

_LEAD_STATUS = SAEnum(
    "new", "contacted", "qualified", "converted", "lost",
    name="lead_status",
    native_enum=True,
)

_INET = String().with_variant(INET(), "postgresql")


class Proposal(Base, TenantMixin):
    __tablename__ = "proposals"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    customer_id          = Column(Integer, ForeignKey("customers.id"), nullable=False)
    property_id          = Column(Integer, ForeignKey("properties.id"), nullable=False)
    estimate_id          = Column(Integer, ForeignKey("estimates.id"), nullable=True)
    template_id          = Column(Integer, ForeignKey("proposal_templates.id"))
    root_id              = Column(Integer, ForeignKey("proposals.id"))
    parent_id            = Column(Integer, ForeignKey("proposals.id"))
    version_number       = Column(Integer, nullable=False, default=1)
    title                = Column(String(500), nullable=False)
    quote_snapshot       = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    selected_tier        = Column(String(50))
    selected_options     = Column(JSON().with_variant(JSONB, "postgresql"))
    status               = Column(_PROPOSAL_STATUS, nullable=False, default="draft")
    accept_token         = Column(String(86), nullable=False, unique=True)
    accepted_by_name     = Column(String(255))
    accepted_at          = Column(DateTime)
    accepted_ip          = Column(_INET)
    accepted_ua          = Column(Text)
    consent_electronic   = Column(Boolean)
    signed_pdf_gcs       = Column(String(1000))
    signed_pdf_emailed_at = Column(DateTime)
    created_by           = Column(String(255), nullable=False)
    sent_at              = Column(DateTime)
    created_at           = Column(DateTime, nullable=False, default=_utcnow)
    updated_at           = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_proposals_tenant", "tenant_id"),
        Index("ix_proposals_customer", "customer_id"),
        Index("ix_proposals_estimate", "estimate_id"),
        Index("ix_proposals_root", "root_id"),
        Index("ix_proposals_token", "accept_token"),
        Index("ix_proposals_status", "tenant_id", "status"),
    )


class ProposalEvent(Base, TenantMixin):
    __tablename__ = "proposal_events"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    event_type  = Column(_PROPOSAL_EVENT_TYPE, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=_utcnow)
    ip_address  = Column(_INET)
    user_agent  = Column(Text)
    actor_email     = Column(String(255))
    event_metadata  = Column("metadata", JSON().with_variant(JSONB, "postgresql"))

    __table_args__ = (
        Index("ix_events_proposal", "proposal_id", "occurred_at"),
        Index("ix_events_tenant", "tenant_id", "event_type"),
    )


class Lead(Base, TenantMixin):
    __tablename__ = "leads"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    name                 = Column(String(255), nullable=False)
    email                = Column(String(255))
    phone                = Column(String(50))
    source               = Column(String(100))
    notes                = Column(Text)
    status               = Column(_LEAD_STATUS, nullable=False, default="new")
    converted_customer_id = Column(Integer, ForeignKey("customers.id"))
    created_at           = Column(DateTime, nullable=False, default=_utcnow)
    updated_at           = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_leads_tenant", "tenant_id", "status"),
    )


class Job(Base, TenantMixin):
    __tablename__ = "jobs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id"))
    status      = Column(String(50), nullable=False, default="pending")
    knowify_job_id = Column(String(100), nullable=True)  # Knowify ProjectId crosswalk (migration 0032)
    created_at  = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_jobs_tenant", "tenant_id"),
        Index("ix_jobs_tenant_knowify", "tenant_id", "knowify_job_id"),
        # Partial-unique crosswalk index (migration 0032). The placeholder job uses
        # knowify_job_id='__knowify_placeholder__' so it is covered (not NULL).
        Index(
            "uq_jobs_tenant_knowify",
            "tenant_id", "knowify_job_id",
            unique=True,
            postgresql_where="knowify_job_id IS NOT NULL",
        ),
    )


class CatalogItem(Base, TenantMixin):
    __tablename__ = "catalog_items"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(String(255), nullable=False)
    unit            = Column(String(50))
    unit_price      = Column(Numeric(10, 2))
    knowify_item_id = Column(String(100))
    created_at      = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_catalog_items_tenant", "tenant_id"),
    )


class TcVersion(Base, TenantMixin):
    __tablename__ = "tc_versions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    version_tag  = Column(String(50), nullable=False)
    content_gcs  = Column(String(1000))
    effective_at = Column(DateTime, nullable=False, default=_utcnow)
    created_at   = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_tc_versions_tenant", "tenant_id"),
    )


class AskCache(Base, TenantMixin):
    """Semantic answer cache for /ask.  One row per unique question per tenant.

    Prod: embedding is vector(3072) with an HNSW halfvec index (migration 0025).
    Dev/SQLite: embedding stored as JSON; lookups fall back to exact question_norm match.
    hit_count is incremented on every cache hit (write-through on miss, served on hit).
    """
    __tablename__ = "ask_cache"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    question         = Column(Text, nullable=False)
    question_norm    = Column(Text, nullable=False)
    embedding        = Column(_EMBEDDING)
    answer_json      = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    pipeline_version = Column(String(64), nullable=False, default="")
    hit_count        = Column(Integer, nullable=False, default=0)
    created_at       = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_ask_cache_tenant_norm", "tenant_id", "question_norm"),
    )


class ContractFaqEntry(Base, TenantMixin):
    """Grounded, customer-facing FAQ entries generated from T&C text."""
    __tablename__ = "contract_faq_entries"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    question      = Column(Text, nullable=False)
    answer        = Column(Text)
    quote         = Column(Text)
    status        = Column(String(20), nullable=False, default="draft")
    tc_version_id = Column(Integer, ForeignKey("tc_versions.id"), nullable=True)
    created_at    = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_contract_faq_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# JB4 — Invoicing, milestones & payments (Knowify-replacement billing core)
# Schema layer only: models + migration 0030. Draw math / numbering / ledger
# derivation live in core/invoicing.py + core/milestones.py (later slice).
# Money-critical: authored + reviewed on Claude (plan Principle 2).
# ---------------------------------------------------------------------------

_INVOICE_STATUS = SAEnum(
    "draft", "sent", "viewed", "partially_paid", "paid", "voided",
    name="invoice_status", native_enum=False,
)
_INVOICE_LINE_TYPE = SAEnum(
    "scope", "discount", "addon", "tax", "credit",
    name="invoice_line_type", native_enum=False,
)
_DRAW_STATUS = SAEnum(
    "pending", "invoiced", "paid",
    name="milestone_draw_status", native_enum=False,
)
_PAYMENT_METHOD = SAEnum(
    "check", "ach", "card", "cash", "other",
    name="payment_method", native_enum=False,
)
_QB_SYNC_STATUS = SAEnum(
    "pending", "synced", "error",
    name="qb_sync_status", native_enum=False,
)
_JOB_DOC_STATUS = SAEnum(
    "pending", "approved", "approved_pending_inspection", "denied",
    name="job_doc_status", native_enum=False,
)
_BILLING_EVENT_TYPE = SAEnum(
    "invoice_issued", "invoice_sent", "invoice_voided",
    "payment_recorded", "credit_applied", "draw_created", "qb_synced",
    name="job_billing_event_type", native_enum=False,
)


class Invoice(Base, TenantMixin):
    """One invoice per milestone draw. invoice_number is a per-tenant sequential
    integer (continuing the live Knowify sequence — see TenantInvoiceCounter),
    NULL until issued. All lines on an invoice share the draw's milestone_pct.
    Tax is $0 for FL roofing services but the field is kept for out-of-state tenants."""
    __tablename__ = "invoices"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number   = Column(Integer, nullable=True)
    job_id           = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    customer_id      = Column(Integer, ForeignKey("customers.id"), nullable=False)
    proposal_id      = Column(Integer, ForeignKey("proposals.id"), nullable=True)
    milestone_draw_id = Column(Integer, ForeignKey("milestone_draws.id"), nullable=True)
    status           = Column(_INVOICE_STATUS, nullable=False, default="draft")
    invoice_date     = Column(DateTime, nullable=True)
    due_date         = Column(DateTime, nullable=True)
    milestone_pct    = Column(Numeric(6, 4), nullable=True)
    subtotal         = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount       = Column(Numeric(12, 2), nullable=False, default=0)
    credit_amount    = Column(Numeric(12, 2), nullable=False, default=0)
    total            = Column(Numeric(12, 2), nullable=False, default=0)
    comments         = Column(Text)
    pdf_gcs          = Column(String(1000))
    qb_entity_id     = Column(String(100))
    qb_synced_at     = Column(DateTime)
    qb_sync_status   = Column(_QB_SYNC_STATUS)
    qb_error_message = Column(Text)
    created_by       = Column(String(255), nullable=False)
    created_at       = Column(DateTime, nullable=False, default=_utcnow)
    updated_at       = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    # Knowify crosswalk (migration 0032). knowify_invoice_number is TEXT because
    # Knowify's InvoiceNumber is a user-facing STRING, NOT our integer invoice_number.
    knowify_invoice_id     = Column(String(100), nullable=True)
    knowify_invoice_number = Column(Text, nullable=True)
    source                 = Column(String(30), nullable=False, default="v2")  # 'v2' | 'knowify_import'

    __table_args__ = (
        # Postgres treats NULLs as distinct → many drafts (NULL number) coexist,
        # while issued numbers are unique per tenant. No collision on the Knowify seq.
        UniqueConstraint("tenant_id", "invoice_number", name="uq_invoices_tenant_number"),
        Index("ix_invoices_tenant", "tenant_id"),
        Index("ix_invoices_job", "job_id"),
        Index("ix_invoices_tenant_status", "tenant_id", "status"),
        Index("ix_invoices_tenant_knowify", "tenant_id", "knowify_invoice_id"),
        Index(
            "uq_invoices_tenant_knowify_id", "tenant_id", "knowify_invoice_id",
            unique=True, postgresql_where="knowify_invoice_id IS NOT NULL",
        ),
    )


class InvoiceLine(Base, TenantMixin):
    """One line per scope on an invoice. unit_price = contract_value_for_scope *
    milestone_pct (NEGATIVE for a discount line, same pct as the other lines).
    quantity is always 1 in current practice (lump-sum scope packages)."""
    __tablename__ = "invoice_lines"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id    = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    line_type     = Column(_INVOICE_LINE_TYPE, nullable=False, default="scope")
    description   = Column(Text, nullable=False)
    scope_id      = Column(Integer, nullable=True)  # FK to a job-scope entity (not yet modeled)
    milestone_pct = Column(Numeric(6, 4), nullable=True)
    quantity      = Column(Numeric(10, 2), nullable=False, default=1)
    unit_price    = Column(Numeric(12, 2), nullable=False, default=0)
    subtotal      = Column(Numeric(12, 2), nullable=False, default=0)
    is_optional   = Column(Boolean, nullable=False, default=False)
    sort_order    = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_invoice_lines_invoice", "invoice_id", "sort_order"),
        Index("ix_invoice_lines_tenant", "tenant_id"),
    )


class MilestoneSchedule(Base, TenantMixin):
    """Draw schedule for a job, SNAPSHOTTED from the issued proposal's frozen
    quote_snapshot at creation (plan HIGH-2) — never read from the live template.
    milestones_snapshot is the frozen ordered list; snapshot_hash pins it immutable."""
    __tablename__ = "milestone_schedules"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    job_id              = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    proposal_id         = Column(Integer, ForeignKey("proposals.id"), nullable=True)
    template_id         = Column(Integer, nullable=True)
    milestones_snapshot = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    snapshot_hash       = Column(String(64), nullable=True)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_milestone_schedules_job", "job_id"),
        Index("ix_milestone_schedules_tenant", "tenant_id"),
    )


class MilestoneDraw(Base, TenantMixin):
    """One record per draw per job. invoice_id is set when the draw is invoiced."""
    __tablename__ = "milestone_draws"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    job_id          = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    schedule_id     = Column(Integer, ForeignKey("milestone_schedules.id"), nullable=True)
    sequence_number = Column(Integer, nullable=False)
    milestone_name  = Column(String(255))
    pct_due         = Column(Numeric(6, 4), nullable=False)
    status          = Column(_DRAW_STATUS, nullable=False, default="pending")
    invoice_id      = Column(Integer, nullable=True)  # set on invoice creation (soft ref; avoids FK cycle)
    planned_date    = Column(DateTime)
    actual_date     = Column(DateTime)
    created_at      = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_milestone_draws_job", "job_id", "sequence_number"),
        Index("ix_milestone_draws_tenant", "tenant_id"),
    )


class Payment(Base, TenantMixin):
    """Record-only payment against an invoice (check/ach/card/cash/other + reference).
    Live processor capture is a later slice (plan Shape D1)."""
    __tablename__ = "payments"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id     = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    payment_date   = Column(DateTime, nullable=False, default=_utcnow)
    amount         = Column(Numeric(12, 2), nullable=False)
    method         = Column(_PAYMENT_METHOD, nullable=False, default="check")
    reference      = Column(String(255))
    notes          = Column(Text)
    qb_entity_id   = Column(String(100))
    qb_synced_at   = Column(DateTime)
    qb_sync_status = Column(_QB_SYNC_STATUS)
    knowify_payment_id = Column(String(100), nullable=True)  # Knowify payment crosswalk (migration 0032)
    created_at     = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_payments_invoice", "invoice_id"),
        Index("ix_payments_tenant", "tenant_id"),
        Index("ix_payments_tenant_knowify", "tenant_id", "knowify_payment_id"),
        Index(
            "uq_payments_tenant_knowify_id", "tenant_id", "knowify_payment_id",
            unique=True, postgresql_where="knowify_payment_id IS NOT NULL",
        ),
    )


class Credit(Base, TenantMixin):
    """Customer/job credit, optionally applied to an invoice."""
    __tablename__ = "credits"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    customer_id           = Column(Integer, ForeignKey("customers.id"), nullable=False)
    job_id                = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    amount                = Column(Numeric(12, 2), nullable=False)
    reason                = Column(Text)
    applied_to_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    created_at            = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_credits_customer", "customer_id"),
        Index("ix_credits_tenant", "tenant_id"),
    )


class JobDocument(Base, TenantMixin):
    """HOA/ACC approval (and other pre-work permit docs) as a JOB attribute — the
    302-Ridge ACC letter shape: reference #, HOA/mgmt co, approval date/scope/status,
    permit responsibility, and a final-inspection-required flag."""
    __tablename__ = "job_documents"

    id                        = Column(Integer, primary_key=True, autoincrement=True)
    job_id                    = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    doc_type                  = Column(String(50), nullable=False, default="hoa_acc_approval")
    reference_number          = Column(String(100))
    hoa_name                  = Column(String(255))
    management_company        = Column(String(255))
    approval_date             = Column(DateTime)
    scope_approved            = Column(Text)
    status                    = Column(_JOB_DOC_STATUS, nullable=False, default="pending")
    permit_responsibility     = Column(String(50))  # 'homeowner' | 'contractor'
    final_inspection_required = Column(Boolean, nullable=False, default=False)
    created_at                = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_job_documents_job", "job_id"),
        Index("ix_job_documents_tenant", "tenant_id"),
    )


class JobBillingEvent(Base, TenantMixin):
    """Immutable, append-only billing ledger (plan Principle 2 + Ez-Bids W5 shape).
    Invoice/payment/draw status is DERIVED from these events, never overwritten in
    place. No updated_at by design. idempotency_key makes replays a no-op per tenant."""
    __tablename__ = "job_billing_events"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    job_id          = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    invoice_id      = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    event_type      = Column(_BILLING_EVENT_TYPE, nullable=False)
    payload         = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    idempotency_key = Column(String(255), nullable=True)
    source          = Column(String(50), nullable=False, default="api")
    received_at     = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_billing_events_tenant_idem"),
        Index("ix_billing_events_job", "job_id", "received_at"),
        Index("ix_billing_events_invoice", "invoice_id"),
        Index("ix_billing_events_tenant", "tenant_id"),
    )


class TenantInvoiceCounter(Base):
    """Per-tenant sequential invoice-number counter. next issued = last_number + 1.
    Increment atomically inside the tenant txn (SELECT ... FOR UPDATE then bump).
    Perkins (tenant 1) is seeded in migration 0030 at the live Knowify max
    (18732 as of 2026-07-10) — MUST be re-confirmed against the live max
    immediately before cutover (plan Open Question #3 / Pre-mortem #2)."""
    __tablename__ = "tenant_invoice_counters"

    tenant_id   = Column(Integer, ForeignKey("tenants.id"), primary_key=True)
    last_number = Column(Integer, nullable=False, default=0)
    updated_at  = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# JB1 — Material price-book engine
# Editable catalog (PriceBookItem) + immutable frozen snapshots (PriceBook).
# Hash / freeze logic lives in core/price_book.py (R1 core-coverage target).
# ---------------------------------------------------------------------------

class PriceBookItem(Base, TenantMixin):
    """Editable catalog row for one material / service / system line item.

    unit_price=NULL means not-stocked/price-unknown; never coerce to 0.
    unit_coverage=NULL means not a per-square item (LF accessories, cans, etc.).
    """
    __tablename__ = "price_book_items"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    price_book_id    = Column(Integer, ForeignKey("price_books.id"), nullable=True)
    sku              = Column(String(100), nullable=True)
    name             = Column(String(255), nullable=False)
    unit             = Column(String(50), nullable=True)   # roll|bundle|box|can|sheet|piece|LF|bag|bucket|square|foot
    unit_coverage    = Column(Numeric(10, 4), nullable=True)   # sq per unit; NULL = not a per-sq item
    unit_price       = Column(Numeric(12, 4), nullable=True)   # NULL = not-stocked / unknown
    tax_rate         = Column(Numeric(6, 4), nullable=False, default=Decimal("0.07"))
    waste_rate       = Column(Numeric(6, 4), nullable=False, default=Decimal("0.10"))
    supplier         = Column(String(100), nullable=True)      # ABC_SUPPLY|BEACON|VEREA|…
    roof_system_ids  = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True, default=list)
    knowify_item_id  = Column(String(100), nullable=True)      # Knowify↔item crosswalk
    item_type        = Column(String(30), nullable=True)       # material|system|service

    created_at       = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_price_book_items_tenant", "tenant_id"),
        Index("ix_price_book_items_tenant_knowify", "tenant_id", "knowify_item_id"),
        Index("ix_price_book_items_price_book_id", "price_book_id"),
        # Partial-unique crosswalk index (migration 0032).
        Index(
            "uq_price_book_items_tenant_knowify",
            "tenant_id", "knowify_item_id",
            unique=True,
            postgresql_where="knowify_item_id IS NOT NULL",
        ),
    )


class PriceBook(Base, TenantMixin):
    """Immutable frozen snapshot of price-book items — mirrors PricingConfig versioning.

    Once frozen (is_active=True), items_snapshot and config_hash must never change.
    Edits produce a new version row; the old row is archived.
    """
    __tablename__ = "price_books"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    supplier        = Column(String(100), nullable=False, default="DEFAULT")
    version_number  = Column(Integer, nullable=False)
    label           = Column(String, nullable=True)
    items_snapshot  = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    config_hash     = Column(String(64), nullable=False)
    is_active       = Column(Boolean, nullable=False, default=False)
    created_at      = Column(DateTime, nullable=False, default=_utcnow)
    created_by      = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier", "version_number",
                         name="uq_price_books_tenant_supplier_version"),
        Index("ix_price_books_tenant_supplier", "tenant_id", "supplier"),
    )


# ---------------------------------------------------------------------------
# Knowify data mirror (Wave 1 — migration 0032).
# knowify_sync_state = per-(tenant, entity) watermark + health surface.
# knowify_raw_records = generic lossless JSONB mirror with tombstone columns.
# Sync/promotion logic lives in jobs/knowify_sync.py (later slice).
# ---------------------------------------------------------------------------

class KnowifySyncState(Base, TenantMixin):
    """Per-(tenant, entity) sync watermark + last-run health.

    v1 records health only (full-pull, not watermark-driven): last_high_water is
    recorded for observability and as the seed for a future v2 since= delta pull.
    """
    __tablename__ = "knowify_sync_state"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    entity          = Column(String(50), nullable=False)          # 'invoices','clients',...
    last_high_water = Column(DateTime, nullable=True)             # max updated_at (or created_at) seen
    last_cursor     = Column(String(500), nullable=True)          # opaque next-page cursor if cursor-paged
    last_run_at     = Column(DateTime, nullable=True)
    last_status     = Column(String(30), nullable=False, default="never")  # never|ok|partial|error|auth_error|skipped
    last_error      = Column(Text, nullable=True)
    rows_seen       = Column(Integer, nullable=False, default=0)
    updated_at      = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", name="uq_knowify_sync_state_tenant_entity"),
        Index("ix_knowify_sync_state_tenant", "tenant_id"),
    )


class KnowifyRawRecord(Base, TenantMixin):
    """Generic lossless mirror of one Knowify record.

    is_present=FALSE + deleted_at set = tombstoned (absent from the last full pull
    or explicitly Cancelled/Deleted upstream). content_hash gates re-writes so an
    unchanged payload produces zero writes.
    """
    __tablename__ = "knowify_raw_records"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    entity       = Column(String(50), nullable=False)
    knowify_id   = Column(String(100), nullable=False)            # the record's id in Knowify
    payload      = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    content_hash = Column(String(64), nullable=False)            # sha256 of canonicalized payload
    high_water   = Column(DateTime, nullable=True)               # record's updated_at (v2 incremental seed)
    is_present   = Column(Boolean, nullable=False, default=True)  # FALSE = absent from last full pull
    deleted_at   = Column(DateTime, nullable=True)               # when tombstoned
    fetched_at   = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", "knowify_id", name="uq_knowify_raw_tenant_entity_id"),
        Index("ix_knowify_raw_tenant_entity", "tenant_id", "entity"),
        Index("ix_knowify_raw_high_water", "tenant_id", "entity", "high_water"),
    )


engine = create_engine(settings.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)

# Wire the RLS after_begin event onto SessionLocal (F4a).
# Every session from SessionLocal issues SET LOCAL app.tenant_id immediately
# after BEGIN, sourcing the value from session.info["tenant_id"] (populated
# from verified token claims only — never from headers or request body).
# The event is a no-op on SQLite (dialect guard in core/tenant.py) so existing
# SQLite-based tests continue to run without stamping session.info.
from core.tenant import register_tenant_session_events  # noqa: E402

# strict=True (C1 Part 2, the tenant-2 gate): every tenant SessionLocal session on
# Postgres MUST carry session.info["tenant_id"] (stamped from verified claims via
# get_db_session, or by for_each_tenant / a job's stamped session) or
# session.info["platform_scope"]=True — an unstamped session now RAISES instead of
# silently defaulting to tenant 1. All request-path and job-path call sites were
# migrated (Part 1: routes, d9e2e5b; Part 2: retrieval chain, tenant enumeration,
# job sessions). Remaining bare sites are dev/validation scripts (scripts/*,
# app/eval.py, the legacy app/api.py POC) which run on SQLite where the event
# no-ops — on prod Postgres they fail closed, which is intended.
# RLS (NOSUPERUSER NOBYPASSRLS role + 29 FORCED tables) remains the primary guard;
# strict converts "wrong default" into "loud failure" so tenant #2 can onboard.
register_tenant_session_events(SessionLocal, strict=True)

# Before/after capture for every audited business object (migration 0036). Attached to the
# session rather than to routes: the "before" values only exist during flush, and there are 86
# mutating endpoints — per-route snapshots would cover the ones someone remembered, and the
# revert you need would be the one that was missed.
from core.audit_orm import register_change_tracking  # noqa: E402

register_change_tracking(SessionLocal)

# Platform-scoped session factory — no after_begin tenant GUC hook.
# Used exclusively by endpoints that touch RLS-exempt platform-level tables
# (tenants, tenant_gcip_map, tenant_default_admins, platform_admins, platform_audit_log).
# Do NOT use for any endpoint that reads tenant-scoped data.
PlatformSessionLocal = sessionmaker(bind=engine, future=True)


@event.listens_for(Tenant.__table__, "after_create")
def _seed_perkins_tenant(target, connection, **kw):
    """Seed Perkins as tenant 1 immediately after the tenants table is created."""
    row = {"id": 1, "name": "Perkins Roofing", "slug": "perkins", "status": "active", "settings": {}}
    if connection.dialect.name == "sqlite":
        connection.execute(target.insert().prefix_with("OR IGNORE"), row)
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        connection.execute(
            pg_insert(target).values(**row).on_conflict_do_nothing(index_elements=["id"])
        )


@event.listens_for(Branch.__table__, "after_create")
def _seed_default_branches(target, connection, **kw):
    """Seed tenant 1 branches on fresh DBs (dev/SQLite tests; prod uses migration 0041)."""
    rows = [
        {"tenant_id": 1, "key": "miami", "name": "Miami", "sort": 1, "active": True},
        {"tenant_id": 1, "key": "jupiter", "name": "Jupiter", "sort": 2, "active": True},
        {"tenant_id": 1, "key": "naples", "name": "Naples", "sort": 3, "active": True},
        {"tenant_id": 1, "key": "gc", "name": "GC", "sort": 4, "active": True},
    ]
    if connection.dialect.name == "sqlite":
        connection.execute(target.insert().prefix_with("OR IGNORE"), rows)
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        for row in rows:
            connection.execute(
                pg_insert(target).values(**row).on_conflict_do_nothing(
                    index_elements=["tenant_id", "key"])
            )


# H2 (R2 #321 review): runtime init_db()/create_all (app/ingest.py + several jobs) can
# create a model-first tenant table BEFORE its migration lands — without this hook that
# table would have NO RLS (cross-tenant window until the .sql applies). At CREATE TABLE
# time, apply ENABLE/FORCE + the standard NULLIF-GUC isolation policy to every table
# carrying a tenant_id column. Migrations stay the source of truth for existing tables
# (the hook only fires for tables create_all actually creates); policy name is suffixed
# "_auto" so it coexists with (ORs with) the identical per-table migration policies.
def _rls_on_create(target, connection, **kw):
    if connection.dialect.name != "postgresql":
        return
    from sqlalchemy import text as _text
    guc = "NULLIF(current_setting('app.tenant_id', true), '')::int"
    connection.execute(_text(f'ALTER TABLE {target.name} ENABLE ROW LEVEL SECURITY'))
    connection.execute(_text(f'ALTER TABLE {target.name} FORCE ROW LEVEL SECURITY'))
    connection.execute(_text(
        f"CREATE POLICY tenant_isolation_auto ON {target.name} "
        f"USING (tenant_id = {guc}) WITH CHECK (tenant_id = {guc})"
    ))


# Platform-level tables that carry a tenant_id column but are NOT tenant-scoped:
# they must stay RLS-EXEMPT (reachable via PlatformSessionLocal; shared/NULL-tenant
# rows and cross-tenant reads are intentional). Without this, _rls_on_create would
# FORCE-RLS them and every NULL-tenant / no-GUC insert would be denied (migration
# 0039 tables hit exactly that). Mirrors the tenant_offboard_log platform-level
# precedent (app/models.py IntegrationStatus/OAuthStateNonce docstrings).
_RLS_EXEMPT_PLATFORM_TABLES = {
    "tenants",
    "tenant_offboard_log",
    "integration_status",
    "oauth_state_nonces",
}

for _t in Base.metadata.tables.values():
    if "tenant_id" in _t.columns and _t.name not in _RLS_EXEMPT_PLATFORM_TABLES:
        event.listens_for(_t, "after_create")(_rls_on_create)


def init_db():
    Base.metadata.create_all(engine)
