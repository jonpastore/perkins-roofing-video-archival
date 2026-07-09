#!/usr/bin/env bash
# Fetch the Vertex dev SA key from Secret Manager to a unique temp file and print
# its path (deepsec M1 — no long-lived SA key stored in the repo tree). Callers do:
#   export GOOGLE_APPLICATION_CREDENTIALS="$(scripts/fetch_vertex_sa.sh)"
# The prod Cloud Run services do NOT use this — they run as their attached SA. This
# is a local-dev/ops convenience only. Prefer ADC (gcloud auth application-default
# login) where it has the needed Vertex perms; use this when a keyed SA is required.
set -euo pipefail
f="$(mktemp /tmp/vertex-dev-sa.XXXXXX.json)"
gcloud secrets versions access latest --secret=vertex-dev-sa-key \
  --project "${GOOGLE_CLOUD_PROJECT:-video-archival-and-content-gen}" > "$f"
echo "$f"
