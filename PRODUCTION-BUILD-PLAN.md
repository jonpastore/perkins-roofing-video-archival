# Production Build Plan — Perkins Video Intelligence (v1)

Derived from the POC + council review (Grok-4 + GPT-5, 2026-06-09). Defines the
**minimal sellable production v1** (the fixed-fee build) and what defers to the retainer.

## Council verdict (key points)
- 43h is **not** realistic for production. Real core v1 = **~80–140h**.
- $8,600 likely **underpriced**; narrow production v1 ≈ $12–18k. → pricing decision for Jon.
- Sell the CORE; defer the 5 other "products" (clip factory, publisher, competitor intel,
  engagement queue, ad ops) to the retainer.

## Minimal sellable v1 (fixed-fee build)
1. **Ingestion** — owned channel, metadata + transcript, **idempotent + resumable**, staged.
2. **Transcript normalization** — source abstraction: YouTube captions → GCP STT fallback;
   normalized schema (segments + words + confidence + source).
3. **Content Graph** — deterministic, schema-validated, **versioned** extraction.
4. **Hybrid retrieval** — lexical (FTS/BM25) + vector (pgvector) + graph rerank, timecoded.
5. **Grounded "Ask Tim"** — citations + **abstention** ("not in Tim's videos") + confidence gate.
6. **Admin/status** — last sync, indexed count, failed stages, reprocess action.
7. **GCP deploy in client account** — Cloud Run (API) + Cloud Run Jobs (ingest) + Cloud SQL
   (pgvector) + GCS + Secret Manager; Terraform; baseline logging/alerts; cost caps.
8. **Eval harness** — 25–50 seed Q's, citation precision, hallucination/abstention checks.

## Deferred to retainer (separate "products")
media archive automation · FAQ bank generation · automated clip factory (title/outro render)
· multi-platform publisher (FB/IG/TT) · competitor intelligence · opt-in comment-engagement
queue · ad-boost optimization · dashboards · monthly reports · YouTube Analytics (OAuth) deep
metrics.

## Non-negotiable architecture (council)
- **Split serving from ingestion** — API service vs Cloud Run Jobs/Pub-Sub workers.
- **Canonical versioned artifact model** — raw meta, raw transcript, normalized transcript,
  graph JSON, chunks, embeddings; refs+hashes in DB, blobs in GCS; `pipeline_version` on
  every derived row → resumability + auditability + cost control (skip unchanged).
- **Transcript-source abstraction** — downstream never cares where the transcript came from.
- **Hybrid retrieval first-class** (not a vector-DB app — the edge is the Content Graph).
- **Eval harness before public release.**
- **Cost guardrails** — per-stage model routing, max videos/hours/tokens per day, dry-run
  cost estimate before full-channel ingest, skip-unchanged.
- **Clean tenancy** — all data/secrets in client's GCP; our access via named IAM; break-glass.
- **Ask widget** — answer only from cited evidence; abstain below confidence threshold.

## Status (updated — autopilot build 2026-06-09)

CODE-COMPLETE & DEV-VERIFIED (`app/`; pytest 5/5; eval run on the 161-video corpus):
- [x] config + model routing (Ollama dev; Vertex/Anthropic backends in llm.py)
- [x] SQLAlchemy data layer, pg-ready; versioned-artifact + IngestionRun model
- [x] transcript-source abstraction (youtube_caption; gcp_stt hook)
- [x] idempotent, staged, versioned, resumable ingestion (content-hash + stage status)
- [x] versioned Content Graph extraction
- [x] hybrid retrieval (vector + lexical + graph)
- [x] grounded answer with abstention + citations
- [x] FastAPI service + `/faq` + Ask-Tim widget mounted at `/widget`
- [x] pgvector code path (store.py) + SQL migration (sql/001_init_pgvector.sql)
- [x] YouTube Data API module — metrics + comments (needs YOUTUBE_API_KEY to run)
- [x] workerized ingestion entrypoint (worker.py — Cloud Run Job / Pub-Sub)
- [x] observability (JSON logs w/ run+video IDs) + cost counters + guardrail
- [x] eval harness + seed set — RAN: answerable conf 0.84 / off-topic 0.68;
      calibrated abstain threshold **0.71** (94% sep); 12/12 cited; 11/12 keyword hit
- [x] pytest suite (search/cross-library/abstention/citations/idempotency) — 5/5 pass
- [x] Terraform (Cloud Run service + job, SAs, scheduler, monitoring, GCS, SQL, Pub/Sub, secret)
- [x] FAQ-bank starter generated via **Hermes → Cloudflare agents** (app/generated/faq_seed.json)

NEEDS CLOUD TO RUN / DEPLOY (gated on deposit + Tim's GCP):
- [ ] apply Terraform → live Cloud SQL/pgvector + HNSW + Alembic wiring
- [ ] GCP STT v2 transcript backend implementation + QA vs captions
- [ ] live YouTube Data API key + quota/retention/ToS matrix + comment persistence
- [ ] OAuth (channel access) + widget auth; Secret Manager wiring
- [ ] Cloud Monitoring dashboards/alerts + budget alert + admin dashboard UI
- [ ] STT-vs-caption eval pass; pgvector load/latency test at scale

## Suggested sequencing (post-deposit)
P1 (deploy core): Terraform + Cloud SQL/pgvector + STT backend + workerized ingest + API → demo.
P2 (trust): eval harness + abstention tuning + observability + cost caps + admin/status.
P3 (widget): Ask-Tim widget + auth → live on perkinsroofing.net.
Retainer: roll out the deferred "products" one at a time.
