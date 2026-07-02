"""Central config. Dev defaults to SQLite + cerberus Ollama; prod overrides via env to
Cloud SQL Postgres/pgvector + Vertex/Anthropic. cerberus is DEV-ONLY (our box)."""
import os

class Settings:
    # Data layer — sqlite for dev, postgresql+psycopg://… (with pgvector) for prod
    DB_URL = os.getenv("DB_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "dev.db"))

    # Model backends — 'ollama' (dev/cerberus) | 'vertex' | 'anthropic' (prod, see llm.py)
    EMBED_BACKEND = os.getenv("EMBED_BACKEND", "ollama")
    LLM_BACKEND   = os.getenv("LLM_BACKEND", "ollama")
    OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://cerberus-ai:11434")  # DEV ONLY
    EMBED_MODEL   = os.getenv("EMBED_MODEL", "nomic-embed-text")
    LLM_MODEL     = os.getenv("LLM_MODEL", "mistral-small3.2:24b")

    # Transcript source policy — 'caption_first' (use YouTube captions, STT fallback) | 'stt_only'
    TRANSCRIPT_POLICY = os.getenv("TRANSCRIPT_POLICY", "caption_first")
    DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "poc", "data"))

    # Pipeline versioning (stamped on every derived artifact for resumability/audit)
    PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "v1")
    GRAPH_VERSION    = os.getenv("GRAPH_VERSION", "v1")
    CHUNK_SIZE       = int(os.getenv("CHUNK_SIZE", "6"))

    # Retrieval / answer
    ABSTAIN_THRESHOLD = float(os.getenv("ABSTAIN_THRESHOLD", "0.71"))  # calibrated via app.eval (94% sep)

    # Cost guardrails
    MAX_VIDEOS_PER_RUN = int(os.getenv("MAX_VIDEOS_PER_RUN", "500"))

settings = Settings()
