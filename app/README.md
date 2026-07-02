# Perkins Video Intelligence — Production Core (v1 foundation)

Production-shaped application implementing the council-required architecture. Runs in **dev
mode** today (SQLite + cerberus Ollama); **prod** swaps to the client's GCP (Postgres/pgvector
+ Vertex/Anthropic + GCP STT) via env vars only — no code changes to call sites.

## Modules
| File | Responsibility |
|---|---|
| `config.py` | env-driven settings; dev/prod backend switches; pipeline versioning |
| `llm.py` | embeddings + LLM with backend routing (ollama dev → Vertex/Anthropic prod) |
| `models.py` | SQLAlchemy data layer (pg-ready); versioned-artifact + IngestionRun model |
| `transcript.py` | transcript-source abstraction (YouTube captions → GCP STT fallback) |
| `graph.py` | deterministic, versioned Content Graph extraction |
| `ingest.py` | idempotent, resumable, staged ingestion (content-hash + stage status) |
| `store.py` | vector search (numpy dev → pgvector ANN prod) |
| `retrieval.py` | hybrid retrieval (vector + lexical + graph) |
| `answer.py` | grounded "Ask Tim" with abstention + citations |
| `api.py` | FastAPI serving (search/ask/status/ingest); ingest is a Cloud Run Job in prod |

## Dev run
```bash
pip install -r app/requirements.txt
# (uses captions already in poc/data + cerberus for embeddings/LLM)
python3 -c "import json; from app import ingest as I; I.ingest_video('ls9zLWRiDHg', meta=json.load(open('poc/data/ls9zLWRiDHg.info.json')))"
uvicorn app.api:app --reload      # then POST /search /ask, GET /status
```

## What's production-ready here vs remaining
Ready: the architecture + dev-runnable core (abstraction, idempotent/versioned pipeline,
hybrid retrieval, grounded+abstaining answer, API, container, Terraform skeleton).
Remaining (~80–140h, gated on deposit + client GCP): GCP STT backend, pgvector deploy +
HNSW + Alembic, workerized ingest (Cloud Run Jobs/Pub-Sub), YouTube Data API metrics/comments,
OAuth/secrets/IAM, full Terraform, observability + cost-cap enforcement, eval harness, Ask-Tim
widget UI + dashboard. See `../PRODUCTION-BUILD-PLAN.md`.
