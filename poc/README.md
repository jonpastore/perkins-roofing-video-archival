# Perkins Video Intelligence — Local POC

Proof-of-concept of the production pipeline, built to validate the approach cheaply before
deploying to the client's cloud. Runs on free/local compute only.

## What it proves
Full chain on a real Perkins video: **ingest → timed transcript (sentence + word) →
Content Graph → embeddings → semantic timecoded search → grounded RAG answer** with
`youtu.be/<id>?t=` deep links.

## Stack (POC stand-ins → production)
| POC (dev only) | Production (client's own GCP) |
|---|---|
| `yt-dlp` + YouTube word-level `json3` auto-captions | yt-dlp + managed Speech-to-Text v2 (word + confidence) |
| cerberus Ollama: `nomic-embed-text` (768d) + `qwen3.6:27b` | Vertex AI / Anthropic + embeddings |
| SQLite + numpy cosine | Cloud SQL Postgres + pgvector |

> NOTE: cerberus is OUR dev box, never part of the client architecture. This POC only proves
> pipeline shape + data model. The client build runs entirely in the client's own GCP account.

## Run
```bash
pip install --break-system-packages yt-dlp numpy requests
python3 poc.py all ls9zLWRiDHg      # ingest + build + demo (a Tile Roof Estimate video)
python3 poc.py search "clay tiles"
python3 poc.py ask "What are red flags in a tile roof estimate?"
```

## Result on test video `ls9zLWRiDHg` ("Tile Roof Estimate Red Flags", 10 min)
- 237 sentences, 1,568 word-level timestamps, 40 embedded chunks, 32 Content-Graph items.
- **Key finding:** naive vector RAG *whiffed* on "red flags in a tile estimate" (it matched the
  intro/outro that literally say "red flags"). Fusing the **deterministic Content Graph**
  (objections/claims/CTAs) into retrieval produced **8 accurate, citeable red flags**. This is
  direct evidence for the Content-Graph-as-differentiator thesis in the proposal.

## Known POC limitations (by design)
- Auto-captions, not STT → no per-word confidence scores (production STT provides them).
- SQLite/numpy instead of pgvector; single video; no comments/metrics ingestion yet.
- LLM extraction quality varies (mistral occasionally mistranscribes product names, e.g.
  "Tmax/T+ underlayment"); production uses higher-grade models + STT.
