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
# infra/deploy.config.env holds the NON-SECRET values and is committed, so a deploy is
# reproducible from git alone (R3) — CI has no .env. A local .env is sourced second so a
# developer can still override for their own environment.
set -a
source infra/deploy.config.env
[ -f .env ] && source .env
set +a

# Fail loudly rather than shipping blanks. These land in --set-env-vars, so an empty value
# doesn't "keep the old setting", it OVERWRITES prod's config with "". That is precisely what a
# CI deploy would have done before deploy.config.env existed.
for _required in WP_URL WP_USER OAUTH_CLIENT_ID SIGN_PUBLIC_URL OAUTH_REDIRECT_BASE EMAIL_SEND_MODE; do
  if [ -z "${!_required:-}" ]; then
    echo "ERROR: ${_required} is empty. Deploying would blank it in prod." >&2
    echo "       Set it in infra/deploy.config.env (non-secret) or your local .env." >&2
    exit 1
  fi
done

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
# LLM_BACKEND=vertex (flipped BACK 2026-07-23pm, Jon's go): measured Vertex-only generation
# at ~$30-60/3k articles (batch/standard) vs the ~$145 CF-draft+Vertex-validate split, and CF
# free tier walls at ~1-2 articles/day (10k neurons) with a 24k-ctx ceiling. Gemini 2.5 Flash:
# 1M-ctx, one provider, cheaper. EMBED_BACKEND stays vertex (3072-dim pgvector index). The
# CLOUDFLARE_API_TOKEN secret is left wired below so a flip back to cloudflare is env-only.
BASE_ENV="PERKINS_ENV=prod|GOOGLE_CLOUD_PROJECT=${PROJECT}|GCP_REGION=${REGION}|EMBED_BACKEND=vertex|LLM_BACKEND=vertex|EMBED_MODEL=gemini-embedding-001|LLM_MODEL=gemini-2.5-flash|DB_URL=postgresql+psycopg://app@/perkins?host=/cloudsql/${CONN}|WORKSPACE_ADMIN_SUBJECT=jon@perkinsroofing.net|WORKSPACE_DOMAIN=perkinsroofing.net"
# W0: WP_URL/YT_OWNER_CHANNEL_ID/WORKSPACE_ADMIN_SUBJECT are kept here as env fallbacks while
# existing pipeline consumers (articles, faq, scheduling, jobs) still read os.environ. Full
# per-tenant migration (Tenant.settings.integrations) is deferred to a later wave. The proposals
# accept-link email (proposals.py) already reads from Tenant.settings.integrations exclusively.
CFG_ENV="WP_URL=${WP_URL:-}|WP_USER=${WP_USER:-}|OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID:-}|YT_OWNER_CHANNEL_ID=${YT_OWNER_CHANNEL_ID:-}|GOTENBERG_URL=${GOTENBERG_URL:-}|SIGN_PUBLIC_URL=${SIGN_PUBLIC_URL:-}|OAUTH_REDIRECT_BASE=${OAUTH_REDIRECT_BASE:-}|EMAIL_SEND_MODE=${EMAIL_SEND_MODE:-test}|EMAIL_TEST_RECIPIENT_ALLOWLIST=${EMAIL_TEST_RECIPIENT_ALLOWLIST:-jpastore79@gmail.com,@degenito.ai,@perkinsroofing.net}"

# Vault-backed secrets (resettable in the Config UI). One source of truth: Secret Manager.
SECRETS="INTERNAL_SECRET=internal-secret:latest,PGPASSWORD=db-password:latest,WP_APP_PWD=wordpress-app-password:latest,RESEND_API_KEY=resend-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest,SERPER_API_KEY=serper-api-key:latest,WHISPER_TOKEN=whisper-token:latest,OAUTH_CLIENT_SECRET=google-idp-client-secret:latest,OAUTH_STATE_HMAC_KEY=oauth-state-hmac:latest"
# YouTube reply posting (docs/YOUTUBE_REPLY_OAUTH.md): refresh token minted by Jon and
# stored 2026-07-10 (Cloud Run refuses a :latest ref on an empty secret — version exists).
SECRETS="${SECRETS},YOUTUBE_OAUTH_REFRESH_TOKEN=youtube-oauth-refresh-token:latest"
# Knowify OAuth token blob (Wave 8). Bootstrap-populated by Jon in Wave-9 step 4;
# a placeholder version exists so :latest resolves at deploy time.
SECRETS="${SECRETS},KNOWIFY_TOKENS_SECRET=knowify-tokens:latest"
# Cloudflare Workers-AI (adapters/llm.CloudflareLLM) — the prod article generator since the
# 2026-07-23 flip. Same token as the terraform CF provider (Secret Manager cloudflare-api-token).
SECRETS="${SECRETS},CLOUDFLARE_API_TOKEN=cloudflare-api-token:latest"
# Clip Studio b-roll (adapters/pexels.py). Same pattern as YOUTUBE_API_KEY/etc above:
# the secret container has no version until Jon adds the real key out-of-band
# (gcloud secrets versions add pexels-api-key --data-file=-) — deploy will fail to
# resolve ":latest" until that's done, same as any other pre-bootstrap secret here.
SECRETS="${SECRETS},PEXELS_API_KEY=pexels-api-key:latest"
# SquareQuote API key. Was a plain env var read from an untracked .env, so any deploy from a
# machine without that file shipped it blank. Injected like every other credential now.
SECRETS="${SECRETS},SQUARES_API_KEY=squares-api-key:latest"
# CompanyCam (adapters/companycam.py). The bearer token is live as of 2026-07-28 — an
# APPLICATION KEY (tied to the registered OAuth app "Perkins Platform (DeGenito)", Read &
# Write, no expiry), NOT a Personal Access Token, so it does not die with an individual's
# user account. Verified against the live API: /v2/projects, /projects/{id}/photos and
# /projects/{id}/videos all 200.
SECRETS="${SECRETS},COMPANYCAM_PAT=companycam-pat:latest"
# COMPANYCAM_WEBHOOK_SECRET is deliberately still NOT wired: that container has no version,
# and a versionless secret in --set-secrets fails EVERY deploy, including unrelated ones.
# Add it here only once `gcloud secrets versions add companycam-webhook-secret` has run.
# companycam-client-id / -client-secret are stored but not injected either — nothing uses the
# authorization-code flow yet; they exist so the app can be moved onto it without re-issuing.

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
# Terraform defines these 7 jobs (main.tf job_names). --args uses the = form because the
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
  # enumerate-channel: the ONLY thing that adds new Video rows. ingest advances existing rows
  # only, so without this the catalog silently freezes at whatever was last seeded.
  [enumerate-channel]="jobs.enumerate_channel"
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
