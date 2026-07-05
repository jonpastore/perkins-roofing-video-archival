#!/usr/bin/env bash
# Archive all source videos to the private media GCS bucket (jobs.archive_job) via the local
# Cloud SQL Auth Proxy. GCS uses ADC (owner locally / jobs-sa in Cloud Run) — the vertex-dev-sa
# key has no storage perms, so it must NOT be set here.
#   Usage: scripts/run_archive.sh [limit]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
unset GOOGLE_APPLICATION_CREDENTIALS
# deno on PATH (yt-dlp EJS n-challenge solver) + browser cookies clear YouTube's bot-check.
export PATH="$HOME/.deno/bin:$PATH"
export COOKIES_FROM_BROWSER="${COOKIES_FROM_BROWSER:-chrome}"
export YTDLP_SLEEP="${YTDLP_SLEEP:-5}"
export FFMPEG_BIN="$(.venv/bin/python -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')"
PW="$(gcloud secrets versions access latest --secret=db-password)"
export DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
exec .venv/bin/python -m jobs.archive_job "$@"
