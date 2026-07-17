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
GOTENBERG_URL="${GOTENBERG_URL:-$(cd infra && terraform output -raw gotenberg_url 2>/dev/null || true)}"
SIGN_PUBLIC_URL="${SIGN_PUBLIC_URL:-https://sign.perkinsroofing.net}"
# OAuth self-service capture (connections.py): consent redirects come back to the API.
# The SAME URL must be registered as an authorized redirect URI on the Google OAuth
# client (<OAUTH_CLIENT_ID>) as {OAUTH_REDIRECT_BASE}/oauth/{platform}/callback.
OAUTH_REDIRECT_BASE="${OAUTH_REDIRECT_BASE:-https://api-jnr6bsxyea-uc.a.run.app}"

# Env built with a '|' delimiter (gcloud ^|^ form) so values with commas/@/() survive intact.
# DB_URL keeps its inner '=' (gcloud splits key=value on the first '=').
BASE_ENV="PERKINS_ENV=prod|GOOGLE_CLOUD_PROJECT=${PROJECT}|GCP_REGION=${REGION}|EMBED_BACKEND=vertex|LLM_BACKEND=vertex|EMBED_MODEL=gemini-embedding-001|LLM_MODEL=gemini-2.5-flash|DB_URL=postgresql+psycopg://app@/perkins?host=/cloudsql/${CONN}|WORKSPACE_ADMIN_SUBJECT=jon@perkinsroofing.net|WORKSPACE_DOMAIN=perkinsroofing.net"
# W0: WP_URL/YT_OWNER_CHANNEL_ID/WORKSPACE_ADMIN_SUBJECT are kept here as env fallbacks while
# existing pipeline consumers (articles, faq, scheduling, jobs) still read os.environ. Full
# per-tenant migration (Tenant.settings.integrations) is deferred to a later wave. The proposals
# accept-link email (proposals.py) already reads from Tenant.settings.integrations exclusively.
CFG_ENV="WP_URL=${WP_URL:-}|WP_USER=${WP_USER:-}|OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID:-}|YT_OWNER_CHANNEL_ID=${YT_OWNER_CHANNEL_ID:-}|SQUARES_API_KEY=${SQUARES_API_KEY:-}|GOTENBERG_URL=${GOTENBERG_URL:-}|SIGN_PUBLIC_URL=${SIGN_PUBLIC_URL:-}|OAUTH_REDIRECT_BASE=${OAUTH_REDIRECT_BASE:-}|EMAIL_SEND_MODE=${EMAIL_SEND_MODE:-test}|EMAIL_TEST_RECIPIENT_ALLOWLIST=${EMAIL_TEST_RECIPIENT_ALLOWLIST:-jpastore79@gmail.com,@degenito.ai,@perkinsroofing.net}"

# Vault-backed secrets (resettable in the Config UI). One source of truth: Secret Manager.
SECRETS="INTERNAL_SECRET=internal-secret:latest,PGPASSWORD=db-password:latest,WP_APP_PWD=wordpress-app-password:latest,RESEND_API_KEY=resend-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest,SERPER_API_KEY=serper-api-key:latest,WHISPER_TOKEN=whisper-token:latest,OAUTH_CLIENT_SECRET=google-idp-client-secret:latest,OAUTH_STATE_HMAC_KEY=oauth-state-hmac:latest"
# YouTube reply posting (docs/YOUTUBE_REPLY_OAUTH.md): refresh token minted by Jon and
# stored 2026-07-10 (Cloud Run refuses a :latest ref on an empty secret — version exists).
SECRETS="${SECRETS},YOUTUBE_OAUTH_REFRESH_TOKEN=youtube-oauth-refresh-token:latest"
# Knowify OAuth token blob (Wave 8). Bootstrap-populated by Jon in Wave-9 step 4;
# a placeholder version exists so :latest resolves at deploy time.
SECRETS="${SECRETS},KNOWIFY_TOKENS_SECRET=knowify-tokens:latest"
# Clip Studio b-roll (adapters/pexels.py). Same pattern as YOUTUBE_API_KEY/etc above:
# the secret container has no version until Jon adds the real key out-of-band
# (gcloud secrets versions add pexels-api-key --data-file=-) — deploy will fail to
# resolve ":latest" until that's done, same as any other pre-bootstrap secret here.
SECRETS="${SECRETS},PEXELS_API_KEY=pexels-api-key:latest"

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
# Terraform defines these 6 jobs (main.tf job_names). --args uses the = form because the
# value begins with '-m' (gcloud would otherwise parse it as a flag).
declare -A JOBS=(
  [ingest]="jobs.ingest_worker" [render]="jobs.render_job"
  [article]="jobs.article_job"  [social]="jobs.social_job"
  # knowify-sync: full hourly Knowify mirror (08:00-18:00 ET). Runs KNOWIFY_PULL_MODE=mcp
  # (REST /oauth 500s); reads the knowify-mcp-tokens secret via the SM API (jobs-sa has a
  # project-wide accessor — no --set-secrets mount needed).
  [knowify-sync]="jobs.knowify_sync"
  # knowify-keepwarm: token-only refresh covering the 14h overnight gap. --refresh-only
  # mode skips data fetch; both jobs share advisory lock 8274125 (core/knowify/tokens.py)
  # so parallel refresh+rotate+write is race-free. Deploy conditional on Wave-9 idle-TTL
  # measurement (if TTL > 14h, disable the knowify-keepwarm Cloud Scheduler instead).
  [knowify-keepwarm]="jobs.knowify_sync"
)
for job in "${!JOBS[@]}"; do
  # knowify-keepwarm passes an extra --refresh-only flag to skip data sync.
  if [[ "$job" == "knowify-keepwarm" ]]; then
    ARGS="-m,jobs.knowify_sync,--refresh-only"
  else
    ARGS="-m,${JOBS[$job]}"
  fi
  # Knowify jobs pull/refresh via the MCP transport (REST /oauth is broken). Both sync
  # and keepwarm honor KNOWIFY_PULL_MODE=mcp (keepwarm -> mcp_refresh_only).
  JOB_ENV="^|^${BASE_ENV}|${CFG_ENV}"
  if [[ "$job" == knowify-* ]]; then
    JOB_ENV="${JOB_ENV}|KNOWIFY_PULL_MODE=mcp"
  fi
  echo "== Deploy job: $job =="
  gcloud run jobs update "$job" --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
    --service-account "jobs-sa@${PROJECT}.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --command=python --args="$ARGS" \
    --set-env-vars "$JOB_ENV" \
    --set-secrets "$SECRETS"
done

echo "== Done. API + jobs on image: $IMAGE =="
gcloud run services describe api --region "$REGION" --project "$PROJECT" --format='value(status.url)'
