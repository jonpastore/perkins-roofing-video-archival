#!/usr/bin/env bash
# Run an enumerate/ingest/embed job against Cloud SQL via the local Auth Proxy
# (must be listening on 127.0.0.1:5432). Vertex + Whisper creds come from .env; the DB
# password is read from Secret Manager at runtime (never stored in a committed file).
#   Usage: scripts/run_cloudsql_job.sh jobs.enumerate_channel
#          scripts/run_cloudsql_job.sh jobs.ingest_worker 3
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
PW="$(gcloud secrets versions access latest --secret=db-password)"
export DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
export EMBED_BACKEND=vertex LLM_BACKEND=vertex
export GOOGLE_APPLICATION_CREDENTIALS="infra/vertex-dev-sa.json"
export PERKINS_ENV=prod
exec .venv/bin/python -m "$@"
