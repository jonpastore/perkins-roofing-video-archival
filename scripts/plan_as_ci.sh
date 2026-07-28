#!/usr/bin/env bash
# Run the deploy workflow's drift gate exactly as the ci-deployer service account sees it.
# Uses a THROWAWAY terraform data dir so it cannot touch the real .terraform/ or state lock.
set -uo pipefail
cd /home/jon/projects/perkins-roofing/video-archival/infra

SA=ci-deployer@video-archival-and-content-gen.iam.gserviceaccount.com

# Impersonate for both the google provider and gcloud-side calls.
export GOOGLE_IMPERSONATE_SERVICE_ACCOUNT="$SA"
export USER_PROJECT_OVERRIDE=true
export GOOGLE_CLOUD_QUOTA_PROJECT=video-archival-and-content-gen

# The CF token: in CI this comes from Secret Manager read BY THE DEPLOYER, so read it the same
# way to prove that grant works too.
# 2>/dev/null, NOT 2>&1: gcloud prints an impersonation WARNING to stderr, and capturing it
# made the "token" 219 chars of prose. CI has no impersonation flag so it never saw this.
CF="$(gcloud secrets versions access latest --secret=cloudflare-api-token \
        --impersonate-service-account="$SA" 2>/dev/null)" || { echo "CF SECRET READ FAILED"; exit 1; }
echo "cf token read as deployer: OK (${#CF} chars)"
export TF_VAR_cloudflare_api_token="$CF"

export TF_DATA_DIR=/tmp/tf_ci_test
rm -rf "$TF_DATA_DIR"
terraform init -input=false -no-color >/tmp/ci_init.log 2>&1 || { tail -20 /tmp/ci_init.log; exit 1; }
echo "init: OK"

terraform plan -input=false -lock=false -detailed-exitcode -no-color >/tmp/ci_plan.log 2>&1
code=$?
echo "plan exit code: $code   (0=clean, 1=error, 2=drift)"
grep -E "^Error:|Error: " /tmp/ci_plan.log | sort -u | head -10
grep -E "Plan:|No changes" /tmp/ci_plan.log | head -3
