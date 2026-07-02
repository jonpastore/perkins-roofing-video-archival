"""SQLAlchemy data layer. Dev: SQLite (embedding as JSON). Prod: Postgres + pgvector
(swap Chunk.embedding to Vector(768) + HNSW index via Alembic migration). The canonical
versioned-artifact model the council required: every derived row carries a version, and
IngestionRun tracks per-stage status + content_hash for idempotent/resumable ingestion."""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, JSON, DateTime, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

Base = declarative_base()

class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    title = Column(String); duration = Column(Float); upload_date = Column(String)
    views = Column(Integer); likes = Column(Integer); comments = Column(Integer)
    url = Column(String)

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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    embedding = Column(JSON)          # PROD: pgvector Vector(768) + HNSW index
    embed_model = Column(String); version = Column(String)

engine = create_engine(settings.DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)

def init_db():
    Base.metadata.create_all(engine)
