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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

Base = declarative_base()


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
    __table_args__ = (Index("ix_run_video_stage", "video_id", "stage"),)

class Segment(Base):
    __tablename__ = "segments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    text = Column(Text); start = Column(Float); end = Column(Float)
    source = Column(String)           # youtube_caption | gcp_stt

class Word(Base):
    __tablename__ = "words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    word = Column(String); start = Column(Float); confidence = Column(Float)

class GraphNode(Base):
    __tablename__ = "content_graph"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    kind = Column(String)             # topics | claims | objections | ctas
    label = Column(String); detail = Column(Text); start = Column(Float)
    version = Column(String)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    text = Column(Text); start = Column(Float); end = Column(Float)
    embedding = Column(_EMBEDDING)    # pgvector Vector(3072) on Postgres, JSON on SQLite
    embed_model = Column(String); version = Column(String)

class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String); subject = Column(String); body = Column(Text)
    created_by = Column(String)

class Article(Base):
    __tablename__ = "articles"
    slug = Column(String, primary_key=True)
    title = Column(String); meta = Column(Text)
    content_md = Column(Text); faq_json = Column(JSON); jsonld_json = Column(JSON)
    role = Column(String)             # pillar | cluster | standalone
    pillar_slug = Column(String)
    wp_post_id = Column(Integer)
    status = Column(String)           # draft | scheduled | published
    publish_at = Column(DateTime)
    focus_keyword = Column(String)    # Rank Math SEO focus keyword

class ScheduledContent(Base):
    __tablename__ = "scheduled_content"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String)             # article | reel
    ref_id = Column(String)
    publish_at = Column(DateTime)
    status = Column(String, default="scheduled")  # scheduled | published | error
    target = Column(String)

class MiniSeries(Base):
    __tablename__ = "mini_series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, index=True)
    title = Column(String)
    parts_json = Column(JSON)         # [{title, start, end}] proposed clip in/out points
    approved = Column(Integer, default=0)  # 0 pending | 1 admin-approved

class SocialPost(Base):
    __tablename__ = "social_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(Integer, index=True)
    part = Column(Integer)
    platform = Column(String)         # instagram | tiktok
    gcs_url = Column(String)          # gs:// URI of the private reel object
    external_id = Column(String)      # returned post id (idempotency)
    status = Column(String, default="pending")
    __table_args__ = (
        UniqueConstraint("series_id", "part", "platform", name="uq_social_series_part_platform"),
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
    __table_args__ = (UniqueConstraint("comment_id", name="uq_comment_drafts_comment_id"),)


class UserSetting(Base):
    """Per-user settings (email signature, etc.). email is the PK."""
    __tablename__ = "user_settings"
    email = Column(String, primary_key=True)
    signature = Column(Text, nullable=True)


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
    __table_args__ = (Index("ix_faq_source_node", "source_node_id"),)

engine = create_engine(settings.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)

def init_db():
    Base.metadata.create_all(engine)
