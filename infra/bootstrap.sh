#!/usr/bin/env bash
# bootstrap.sh — Perkins Roofing v2 platform post-provision runbook
#
# Run this ONCE after:
#   P1: GCP billing confirmed on project video-archival-and-content-gen
#   P3: All credentials collected and written to infra/.env (see template below)
#
# Usage:
#   cd infra/
#   cp .env.template .env        # fill in real values
#   chmod +x bootstrap.sh
#   ./bootstrap.sh
#
# .env template (create infra/.env — git-ignored):
#   YOUTUBE_API_KEY=...
#   SERPER_API_KEY=...
#   RESEND_API_KEY=...
#   WORDPRESS_APP_PASSWORD=...
#   META_APP_SECRET=...
#   META_SYSTEM_USER_TOKEN=...
#   TIKTOK_CLIENT_SECRET=...
#   TIKTOK_REFRESH_TOKEN=...
#   BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX   # optional — enables budget alert

set -euo pipefail

PROJECT_ID="video-archival-and-content-gen"
REGION="us-central1"
DB_INSTANCE="${PROJECT_ID}-pg"
DB_NAME="perkins"

echo "==> Step 1: Set active GCP project"
gcloud config set project "${PROJECT_ID}"

echo "==> Step 2: Verify billing is active"
gcloud beta billing projects describe "${PROJECT_ID}" | grep billingEnabled

echo "==> Step 3: Terraform init"
terraform init

echo "==> Step 4: Terraform plan"
# Pass billing_account if set in environment
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"
if [[ -n "${BILLING_ACCOUNT}" ]]; then
  terraform plan -var="billing_account=${BILLING_ACCOUNT}"
else
  terraform plan
fi

echo ""
echo "==> Review the plan above. Press Enter to apply, or Ctrl-C to abort."
read -r

echo "==> Step 5: Terraform apply"
if [[ -n "${BILLING_ACCOUNT}" ]]; then
  terraform apply -auto-approve -var="billing_account=${BILLING_ACCOUNT}"
else
  terraform apply -auto-approve
fi

echo "==> Step 6: Enable pgvector extension in Cloud SQL"
echo "    Connecting to Cloud SQL instance ${DB_INSTANCE} ..."
echo "    When the psql prompt appears, run:"
echo "      CREATE EXTENSION IF NOT EXISTS vector;"
echo "      \\q"
echo ""
echo "    Then run the HNSW index migration from:"
echo "      migrations/versions/0001_embedding_3072.sql"
echo ""
gcloud sql connect "${DB_INSTANCE}" --user=postgres --database="${DB_NAME}"

echo "==> Step 7: Populate Secret Manager secrets from .env"
if [[ ! -f ".env" ]]; then
  echo "ERROR: infra/.env not found. Create it from the template in this script's header."
  exit 1
fi

# Map of env var name -> Secret Manager secret ID
declare -A SECRET_MAP=(
  [YOUTUBE_API_KEY]="youtube-api-key"
  [SERPER_API_KEY]="serper-api-key"
  [RESEND_API_KEY]="resend-api-key"
  [WORDPRESS_APP_PASSWORD]="wordpress-app-password"
  [META_APP_SECRET]="meta-app-secret"
  [META_SYSTEM_USER_TOKEN]="meta-system-user-token"
  [TIKTOK_CLIENT_SECRET]="tiktok-client-secret"
  [TIKTOK_REFRESH_TOKEN]="tiktok-refresh-token"
)

# Source the .env (only exports the vars we use; does not leak to calling shell)
set -a
# shellcheck source=.env
source .env
set +a

for env_var in "${!SECRET_MAP[@]}"; do
  secret_id="${SECRET_MAP[$env_var]}"
  value="${!env_var:-}"

  if [[ -z "${value}" ]]; then
    echo "  SKIP ${secret_id} — ${env_var} not set in .env"
    continue
  fi

  echo "  Uploading ${secret_id} ..."
  printf '%s' "${value}" \
    | gcloud secrets versions add "${secret_id}" \
        --project="${PROJECT_ID}" \
        --data-file=-

  echo "  OK: ${secret_id}"
done

echo ""
echo "==> Bootstrap complete."
echo "    Next steps:"
echo "    1. Run the 0001_embedding_3072.sql migration if not done in Step 6."
echo "    2. Build and push the real API + jobs container images."
echo "    3. Re-deploy Cloud Run service/jobs with the real images."
echo "    4. Configure Firebase Auth project and set custom claims."
