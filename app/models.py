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
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

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
    # naive UTC — datetime.utcnow() is deprecated (removed in a future Python) and returns a
    # naive value inconsistently; this matches the naive-UTC convention used elsewhere.
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Embedding column is dialect-conditional: real pgvector Vector(3072) on Postgres (prod),
# JSON list on SQLite (dev). gemini-embedding-001 is 3072-dim — never mixed with other models.
try:
    from pgvector.sqlalchemy import Vector
    _EMBEDDING = JSON().with_variant(Vector(3072), "postgresql")
except ImportError:  # dev/sqlite has no pgvector installed
    _EMBEDDING = JSON()

class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    title = Column(String); duration = Column(Float); upload_date = Column(String)
    views = Column(Integer); likes = Column(Integer); comments = Column(Integer)
    url = Column(String)
    archive_uri = Column(String)      # gs:// URI of the archived source MP4 in the media bucket
    # KPI columns (populated by jobs/poll_archive_kpis.py)
    comment_count = Column(Integer)
    last_comment_at = Column(DateTime)
    kpis_polled_at = Column(DateTime)
    # Pull-tracking columns (populated by jobs/backfill_archive.py)
    last_pulled_at = Column(DateTime)
    # Clip-generation timestamp (set when MiniSeries rows are produced)
    clips_generated_at = Column(DateTime)
    # Comment-crawl rotation timestamp (jobs/crawl_comments.py; cron rotates least-recent first)
    comments_crawled_at = Column(DateTime)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_videos_tenant_id", "tenant_id"),)

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    stage = Column(String)            # transcript | graph | embed
    status = Column(String)           # pending | done | error
    content_hash = Column(String)     # skip-unchanged guard
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
    source = Column(String)           # youtube_caption | gcp_stt
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
    kind = Column(String)             # topics | claims | objections | ctas
    label = Column(String); detail = Column(Text); start = Column(Float)
    version = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_content_graph_tenant_video", "tenant_id", "video_id"),)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    text = Column(Text); start = Column(Float); end = Column(Float)
    embedding = Column(_EMBEDDING)    # pgvector Vector(3072) on Postgres, JSON on SQLite
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
    status = Column(String, nullable=False, default="pending")  # pending | active | complete
    position = Column(Integer, nullable=False)  # activation order (ascending)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_clusters_tenant_id", "tenant_id"),)


class Article(Base):
    __tablename__ = "articles"
    slug = Column(String, primary_key=True)
    title = Column(String); meta = Column(Text)
    content_md = Column(Text); faq_json = Column(JSON); jsonld_json = Column(JSON)
    role = Column(String)             # pillar | support | cluster | standalone
    pillar_slug = Column(String)
    wp_post_id = Column(Integer)
    status = Column(String)           # draft | scheduled | published | blocked
    publish_at = Column(DateTime)
    focus_keyword = Column(String)    # Rank Math SEO focus keyword
    # Publish-pipeline columns (Track D)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    priority = Column(Integer, nullable=True)   # lower = higher priority within cluster
    scheduled_at = Column(DateTime, nullable=True)  # when to drip this article
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_articles_tenant_status", "tenant_id", "status"),)

class ScheduledContent(Base):
    __tablename__ = "scheduled_content"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String)             # article | reel
    ref_id = Column(String)
    publish_at = Column(DateTime)
    status = Column(String, default="scheduled")  # scheduled | published | error
    target = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_scheduled_content_tenant_status", "tenant_id", "status"),)

class MiniSeries(Base):
    __tablename__ = "mini_series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    title = Column(String)
    parts_json = Column(JSON)         # [{title, start, end}] proposed clip in/out points
    approved = Column(Integer, default=0)  # 0 pending | 1 admin-approved
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_mini_series_tenant_video", "tenant_id", "video_id"),)

class SocialPost(Base):
    __tablename__ = "social_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(Integer, index=True)
    part = Column(Integer)
    platform = Column(String)         # instagram | tiktok
    gcs_url = Column(String)          # gs:// URI of the private reel object
    external_id = Column(String)      # returned post id (idempotency)
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
    video_ids = Column(JSON, nullable=False)   # list[str]
    node_ids = Column(JSON, nullable=False)    # list[int]
    version = Column(String, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (Index("ix_aggregated_topics_tenant_id", "tenant_id"),)


class PlatformConfig(Base):
    __tablename__ = "platform_config"
    key = Column(String, primary_key=True)
    value = Column(String)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String)  # email from auth claims


class SecretAudit(Base):
    """Audit log for secret writes via PUT /config/secrets.

    Records WHO last set each Secret Manager secret through the UI.
    The secret VALUE is never stored here — only metadata.
    """
    __tablename__ = "secret_audit"
    key = Column(String, primary_key=True)  # secret id (e.g. "youtube-api-key")
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String)  # email from auth claims

class CommentDraft(Base):
    __tablename__ = "comment_drafts"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    video_id     = Column(String, nullable=False, index=True)
    comment_id   = Column(String, nullable=False)  # YouTube comment ID — unique
    author       = Column(String)
    comment_text = Column(Text, nullable=False)
    published_at = Column(DateTime)
    needs_reply  = Column(Boolean, nullable=False, default=False)
    draft_reply  = Column(Text)
    status       = Column(String, nullable=False, default="pending")  # pending|drafted|ready|dismissed
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
    source_kind = Column(String, nullable=False)   # claim | objection
    source_node_id = Column(Integer, nullable=False, unique=True)  # FK to content_graph.id (tagging)
    video_id = Column(String, nullable=False, index=True)
    start = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="mined")  # mined | answered
    created_at = Column(DateTime, default=_utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    __table_args__ = (
        Index("ix_faq_source_node", "source_node_id"),
        Index("ix_faq_entries_tenant_video", "tenant_id", "video_id"),
    )

class PricingConfig(Base):
    """Versioned, immutable per-tenant per-branch pricing configuration rows.

    Immutability contract: rows are never UPDATEd except to flip is_active.
    Every config edit creates a new row with version = MAX(version)+1 for that
    (tenant_id, branch). Activation sets is_active=TRUE on the new row and
    FALSE on the prior active row in one deferred transaction.
    The UNIQUE(tenant_id, branch, is_active) constraint with DEFERRABLE INITIALLY
    DEFERRED (Postgres-side, in migration 0014) enforces one active row per branch.
    """
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


engine = create_engine(settings.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)


@event.listens_for(Tenant.__table__, "after_create")
def _seed_perkins_tenant(target, connection, **kw):
    """Seed Perkins as tenant 1 immediately after the tenants table is created.

    Idempotent on both SQLite (INSERT OR IGNORE) and Postgres (ON CONFLICT DO NOTHING).
    Explicit id=1 ensures the Perkins row is always tenant 1 on any dialect.
    Mirrored by the INSERT ... ON CONFLICT seed in infra/migrations/0013_thin_tenancy.sql
    (the prod path) — keep both in sync.
    """
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
