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
    # STT backend — 'gcp' (Cloud Speech-to-Text v2, fully cloud, default) | 'whisper' (dev cerberus)
    STT_BACKEND = os.getenv("STT_BACKEND", "gcp")
    DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "poc", "data"))

    # Pipeline versioning (stamped on every derived artifact for resumability/audit)
    PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "v1")
    GRAPH_VERSION    = os.getenv("GRAPH_VERSION", "v1")
    CHUNK_SIZE       = int(os.getenv("CHUNK_SIZE", "6"))

    # Retrieval / answer
    ABSTAIN_THRESHOLD = float(os.getenv("ABSTAIN_THRESHOLD", "0.71"))  # calibrated via app.eval (94% sep)

    # WordPress integration
    WP_URL = os.getenv("WP_URL", "").rstrip("/")

    # Production site domain — used for canonical URLs and OpenGraph tags.
    # Default matches the Firebase Hosting / Cloud Run production domain.
    PROD_DOMAIN = os.getenv("PROD_DOMAIN", "perkins.degenito.ai")

    # Cost guardrails
    MAX_VIDEOS_PER_RUN = int(os.getenv("MAX_VIDEOS_PER_RUN", "500"))

    # Browser origins allowed to call the API (SPA). Comma-separated env override.
    CORS_ORIGINS = tuple(
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "https://video-archival-and-content-gen.web.app,"
            "https://video-archival-and-content-gen.firebaseapp.com,"
            "https://perkins.degenito.ai,"
            "http://localhost:5173",
        ).split(",")
        if o.strip()
    )

    # Brand intro/outro videos — gs:// URIs for brand video segments prepended/appended to every
    # rendered reel.  When either is empty the existing generated-card path is used instead.
    BRAND_INTRO_VIDEO = os.getenv("BRAND_INTRO_VIDEO", "")
    BRAND_OUTRO_VIDEO = os.getenv("BRAND_OUTRO_VIDEO", "")

    # Emails that are admin-by-default (no per-user grant needed). Comma-separated env override.
    DEFAULT_ADMINS = frozenset(
        e.strip().lower()
        for e in os.getenv(
            "DEFAULT_ADMINS",
            "jon@perkinsroofing.net,tim@perkinsroofing.net,amber@perkinsroofing.net",
        ).split(",")
        if e.strip()
    )

settings = Settings()

# Prod fail-fast (tenancy guard): a prod deploy must use Vertex + Cloud SQL, never the dev
# cerberus/ollama box or local sqlite. Set PERKINS_ENV=prod on Cloud Run.
if os.getenv("PERKINS_ENV") == "prod":
    if settings.EMBED_BACKEND != "vertex" or settings.LLM_BACKEND != "vertex":
        raise RuntimeError("prod requires EMBED_BACKEND=LLM_BACKEND=vertex (no dev ollama)")
    if settings.DB_URL.startswith("sqlite"):
        raise RuntimeError("prod requires Postgres/Cloud SQL, not sqlite")
