"""SQLAlchemy data layer. Dev: SQLite (embedding as JSON). Prod: Postgres + pgvector
(swap Chunk.embedding to Vector(3072) + HNSW index via migration). The canonical
versioned-artifact model the council required: every derived row carries a version, and
IngestionRun tracks per-stage status + content_hash for idempotent/resumable ingestion."""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
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
    """Audit log for every platform_admin impersonation request (TRD-F4 sec 4.4 #3)."""
    __tablename__ = "platform_audit_log"
    id                   = Column(Integer, primary_key=True, autoincrement=True)
    platform_admin_email = Column(String, nullable=False)
    target_tenant_id     = Column(Integer, nullable=False)
    route                = Column(String, nullable=False)
    method               = Column(String, nullable=False)
    occurred_at          = Column(DateTime, nullable=False, default=_utcnow)
    __table_args__       = (Index("ix_platform_audit_log_admin", "platform_admin_email"),)


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
    author       = Column(String)
    comment_text = Column(Text, nullable=False)
    published_at = Column(DateTime)
    needs_reply  = Column(Boolean, nullable=False, default=False)
    draft_reply  = Column(Text)
    status       = Column(String, nullable=False, default="pending")
    created_at   = Column(DateTime, default=_utcnow)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("comment_id", name="uq_comment_drafts_comment_id"),
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
    input_json          = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    result_json         = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    created_by          = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_estimates_tenant_id", "tenant_id"),
    )


class Measurement(Base):
    """Measurement stub — full model in TRD-F2b. Manual-entry provider for F2."""
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

    __table_args__ = (
        Index("ix_measurements_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# F3 — Quoting / Proposals
# ---------------------------------------------------------------------------

class Customer(Base, TenantMixin):
    __tablename__ = "customers"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    display_name        = Column(String(255), nullable=False)
    company_name        = Column(String(255))
    email               = Column(String(255))
    phone               = Column(String(50))
    knowify_customer_id = Column(String(100))
    notes               = Column(Text)
    created_at          = Column(DateTime, nullable=False, default=_utcnow)
    updated_at          = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_customers_tenant", "tenant_id"),
        Index("ix_customers_knowify", "tenant_id", "knowify_customer_id"),
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
    created_at  = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_contacts_customer", "customer_id"),
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
    native_enum=False,
)

_PROPOSAL_EVENT_TYPE = SAEnum(
    "sent", "viewed", "accepted", "declined", "revision_requested", "reminder_sent",
    name="proposal_event_type",
    native_enum=False,
)

_LEAD_STATUS = SAEnum(
    "new", "contacted", "qualified", "converted", "lost",
    name="lead_status",
    native_enum=False,
)

_INET = String().with_variant(INET(), "postgresql")


class Proposal(Base, TenantMixin):
    __tablename__ = "proposals"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    customer_id          = Column(Integer, ForeignKey("customers.id"), nullable=False)
    property_id          = Column(Integer, ForeignKey("properties.id"), nullable=False)
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
    created_at  = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_jobs_tenant", "tenant_id"),
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


engine = create_engine(settings.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)

# Wire the RLS after_begin event onto SessionLocal (F4a).
# Every session from SessionLocal issues SET LOCAL app.tenant_id immediately
# after BEGIN, sourcing the value from session.info["tenant_id"] (populated
# from verified token claims only — never from headers or request body).
# The event is a no-op on SQLite (dialect guard in core/tenant.py) so existing
# SQLite-based tests continue to run without stamping session.info.
from core.tenant import register_tenant_session_events  # noqa: E402

# strict=False: 124 bare SessionLocal() call sites across api/jobs/scripts (counted
# 2026-07-09) predate F4 and don't stamp session.info["tenant_id"] yet. In the
# single-tenant world that exists today they default to tenant 1 with a CRITICAL log
# naming the caller (F4 -> pre-tenant-2 transition contract; see core/tenant.py).
# Migrated endpoints use get_db_session (api/auth.py) which stamps the verified tenant.
#
# ISOLATION IS ALREADY ENFORCED without strict=True: the prod app role is
# NOSUPERUSER NOBYPASSRLS and 29 tables are RLS-FORCED, so every statement is
# filtered by app.tenant_id (which the after_begin event always sets — to the
# stamped tenant, or to 1 for unstamped sessions). strict=True only converts the
# unstamped-default into a hard raise; flipping it REQUIRES migrating all 124 sites
# first (else they 500), so it stays False until that refactor lands before tenant #2.
# refuse_to_serve was flipped True (api/app.py) now that the role is verified hardened.
register_tenant_session_events(SessionLocal, strict=False)

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


def init_db():
    Base.metadata.create_all(engine)
