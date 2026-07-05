#!/usr/bin/env bash
# Deploy the Perkins v2 platform to the client's GCP (rule R3: reproducible, from git).
# Builds the app image with Cloud Build, pushes to Artifact Registry, and points the Cloud
# Run service + all jobs at it. Idempotent — re-run to ship a new revision.
#   Usage: scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${GOOGLE_CLOUD_PROJECT:-video-archival-and-content-gen}"
REGION="${GCP_REGION:-us-central1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/app/platform:$(git rev-parse --short HEAD)"
CONN="${PROJECT}:${REGION}:${PROJECT}-pg"

echo "== Build + push image via Cloud Build =="
gcloud builds submit --tag "$IMAGE" --project "$PROJECT" .

echo "== Deploy API service (auth-gated FastAPI) =="
gcloud run deploy api --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
  --service-account "api-run-sa@${PROJECT}.iam.gserviceaccount.com" \
  --add-cloudsql-instances "$CONN" \
  --set-env-vars "PERKINS_ENV=prod,GOOGLE_CLOUD_PROJECT=${PROJECT},GCP_REGION=${REGION},EMBED_BACKEND=vertex,LLM_BACKEND=vertex,EMBED_MODEL=gemini-embedding-001,LLM_MODEL=gemini-2.5-flash,DB_URL=postgresql+psycopg://app@/perkins?host=/cloudsql/${CONN}" \
  --allow-unauthenticated --set-secrets INTERNAL_SECRET=internal-secret:latest

# Point each job at the same image with its module entrypoint.
# Terraform defines these 4 jobs (main.tf job_names). --args uses the = form because the
# value begins with '-m' (gcloud would otherwise parse it as a flag).
declare -A JOBS=(
  [ingest]="jobs.ingest_worker" [render]="jobs.render_job"
  [article]="jobs.article_job" [social]="jobs.social_job"
)
JOB_ENV="PERKINS_ENV=prod,GOOGLE_CLOUD_PROJECT=${PROJECT},GCP_REGION=${REGION},EMBED_BACKEND=vertex,LLM_BACKEND=vertex,EMBED_MODEL=gemini-embedding-001,LLM_MODEL=gemini-2.5-flash,DB_URL=postgresql+psycopg://app@/perkins?host=/cloudsql/${CONN}"
for job in "${!JOBS[@]}"; do
  echo "== Deploy job: $job (${JOBS[$job]}) =="
  gcloud run jobs update "$job" --image "$IMAGE" --region "$REGION" --project "$PROJECT" \
    --service-account "jobs-sa@${PROJECT}.iam.gserviceaccount.com" \
    --set-cloudsql-instances "$CONN" \
    --command=python --args="-m,${JOBS[$job]}" \
    --set-env-vars "$JOB_ENV"
done

echo "== Done. API + jobs on image: $IMAGE =="
gcloud run services describe api --region "$REGION" --project "$PROJECT" --format='value(status.url)'
