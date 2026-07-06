#!/usr/bin/env bash
# Deploy the Perkins v2 platform to the client's GCP (rule R3: reproducible, from git).
# Builds the app image with Cloud Build, pushes to Artifact Registry, and points the Cloud
# Run service + all jobs at it. Idempotent — re-run to ship a new revision.
#   Usage: scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# R3-ENFORCE: no direct deploy. The image is tagged with the git SHA (below), so deploying a dirty
# tree would ship code that isn't in git. Refuse — commit first. (Infra changes go via terraform,
# never gcloud-by-hand; see docs/ENGINEERING_RULES.md R3.)
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree is dirty. Commit (or stash) before deploying — the image is tagged" >&2
  echo "       with the git SHA, so a deploy must correspond to committed code (R3-ENFORCE)." >&2
  git status --short >&2
  exit 1
fi

# Non-secret config comes from the local .env at deploy time (URLs, public client id,
# owner channel). Sensitive creds live in Secret Manager and are injected via --set-secrets
# below — resettable in the Config UI (which writes new secret versions); new revisions read
# ':latest'. WP_URL/WP_USER are not secrets (a site URL + username), so they stay env vars.
set -a; [ -f .env ] && source .env; set +a

PROJECT="${GOOGLE_CLOUD_PROJECT:-video-archival-and-content-gen}"
REGION="${GCP_REGION:-us-central1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/app/platform:$(git rev-parse --short HEAD)"
CONN="${PROJECT}:${REGION}:${PROJECT}-pg"

# Env built with a '|' delimiter (gcloud ^|^ form) so values with commas/@/() survive intact.
# DB_URL keeps its inner '=' (gcloud splits key=value on the first '=').
BASE_ENV="PERKINS_ENV=prod|GOOGLE_CLOUD_PROJECT=${PROJECT}|GCP_REGION=${REGION}|EMBED_BACKEND=vertex|LLM_BACKEND=vertex|EMBED_MODEL=gemini-embedding-001|LLM_MODEL=gemini-2.5-flash|DB_URL=postgresql+psycopg://app@/perkins?host=/cloudsql/${CONN}"
CFG_ENV="WP_URL=${WP_URL:-}|WP_USER=${WP_USER:-}|OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID:-}|YT_OWNER_CHANNEL_ID=${YT_OWNER_CHANNEL_ID:-}"

# Vault-backed secrets (resettable in the Config UI). One source of truth: Secret Manager.
SECRETS="INTERNAL_SECRET=internal-secret:latest,PGPASSWORD=db-password:latest,WP_APP_PWD=wordpress-app-password:latest,RESEND_API_KEY=resend-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest,SERPER_API_KEY=serper-api-key:latest,WHISPER_TOKEN=whisper-token:latest,OAUTH_CLIENT_SECRET=google-idp-client-secret:latest"

echo "== Build + push image via Cloud Build =="
gcloud builds submit --tag "$IMAGE" --project "$PROJECT" .

echo "== Deploy API service (auth-gated FastAPI) =="
gcloud run deploy api --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
  --service-account "api-run-sa@${PROJECT}.iam.gserviceaccount.com" \
  --timeout 900 --cpu 2 --memory 1Gi \
  --add-cloudsql-instances "$CONN" \
  --set-env-vars "^|^${BASE_ENV}|${CFG_ENV}" \
  --allow-unauthenticated --set-secrets "$SECRETS"

# Point each job at the same image with its module entrypoint.
# Terraform defines these 4 jobs (main.tf job_names). --args uses the = form because the
# value begins with '-m' (gcloud would otherwise parse it as a flag).
declare -A JOBS=(
  [ingest]="jobs.ingest_worker" [render]="jobs.render_job"
  [article]="jobs.article_job" [social]="jobs.social_job"
)
for job in "${!JOBS[@]}"; do
  echo "== Deploy job: $job (${JOBS[$job]}) =="
  gcloud run jobs update "$job" --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
    --service-account "jobs-sa@${PROJECT}.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --command=python --args="-m,${JOBS[$job]}" \
    --set-env-vars "^|^${BASE_ENV}|${CFG_ENV}" \
    --set-secrets "$SECRETS"
done

echo "== Done. API + jobs on image: $IMAGE =="
gcloud run services describe api --region "$REGION" --project "$PROJECT" --format='value(status.url)'
