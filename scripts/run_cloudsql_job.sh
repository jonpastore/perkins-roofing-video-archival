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
# WordPress app password, same rule as the DB password: Secret Manager at runtime, never in
# .env. Without it adapters.wordpress._auth() raises KeyError, jobs.regen_articles_seo swallows
# it as "WP republish failed", and the DB updates while WordPress silently does not.
export WP_APP_PWD="$(gcloud secrets versions access latest --secret=wordpress-app-password)"
# Vertex SA key from Secret Manager (deepsec M1 — no long-lived key on disk).
export GOOGLE_APPLICATION_CREDENTIALS="$(scripts/fetch_vertex_sa.sh)"
export PERKINS_ENV=prod
exec .venv/bin/python -m "$@"
