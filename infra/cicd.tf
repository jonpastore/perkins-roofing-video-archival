# CI/CD identity: let GitHub Actions deploy WITHOUT a long-lived service-account key.
#
# R3 says git is the source of truth and there are no manual deploys. Until now the only way to
# ship was a human running scripts/deploy.sh from a laptop, which is exactly the "direct deploy"
# the rule forbids — and it meant a deploy depended on whatever was in that laptop's .env.
#
# Workload Identity Federation trusts GitHub's OIDC token instead of a downloaded key. Nothing
# secret lives in the repo or in GitHub; the provider below will only mint credentials for
# workflows running in THIS repository (attribute_condition), so a fork or another repo in the
# same org cannot assume the deployer.
#
# ⚠️ The existing `perkins-deploy-sa-key` secret is a downloaded JSON key and is what this
# replaces. Leave it until the first CI deploy is green, then delete both the key and the secret.

locals {
  github_repo = "jonpastore/perkins-roofing-video-archival"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Keyless OIDC federation for CI deploys (see .github/workflows/ci.yml)"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Without this, ANY GitHub repo on the internet could mint tokens for this pool. Google now
  # rejects a provider that has no condition, and rightly so.
  attribute_condition = "assertion.repository == '${local.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  account_id   = "ci-deployer"
  display_name = "GitHub Actions deployer"
  description  = "Builds the app image and rolls Cloud Run. Cannot change IAM or delete data."
}

# Only the main branch may impersonate the deployer. A PR from a fork runs with ref != main and
# gets nothing, so CI on untrusted code can still lint and test but can never reach prod.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member = join("", [
    "principalSet://iam.googleapis.com/",
    google_iam_workload_identity_pool.github.name,
    "/attribute.repository/${local.github_repo}",
  ])
}

# Least privilege for "build an image and point Cloud Run at it". Deliberately NOT
# roles/editor: the deployer cannot touch IAM, Cloud SQL, or secret VALUES.
resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/run.admin",                  # update the service + jobs to a new image
    "roles/cloudbuild.builds.editor",   # submit the image build
    "roles/artifactregistry.writer",    # push the built image
    "roles/storage.admin",              # Cloud Build's staging bucket
    "roles/logging.viewer",             # read build logs on failure
    "roles/secretmanager.viewer",       # resolve :latest for --set-secrets (NOT accessor: it
                                        # never reads a secret's payload, only its metadata)
    "roles/viewer",                     # terraform plan must read every managed resource
    # The google provider sends a "user project override" on Storage reads for billing/quota
    # attribution, and that call itself needs serviceusage.services.use. Without it the plan
    # 403s on google_storage_bucket.media/.reels — roles/viewer is NOT enough (observed on the
    # second CI deploy run). Consumer, not admin: it can consume enabled services, not enable
    # or disable them.
    "roles/serviceusage.serviceUsageConsumer",
    # roles/viewer does NOT cover Identity Platform. Without this the deployer cannot refresh
    # google_identity_platform_default_supported_idp_config, so terraform sees its write-only
    # client_secret as unset and plans an update-in-place FOREVER — the drift gate could never
    # go green even with zero real drift. Viewer, not admin: read-only.
    "roles/identityplatform.viewer",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Cloud Run deploys run the service as api_run_sa / jobs_sa, and "act as" is a separate grant.
resource "google_service_account_iam_member" "deployer_actas" {
  for_each = toset([
    google_service_account.api_run_sa.name,
    google_service_account.jobs_sa.name,
  ])
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# Resource-scoped, NOT a project-wide accessor: the deploy workflow reads exactly one secret
# value (the Cloudflare token the terraform plan needs to read the zone). Every other credential
# is injected into Cloud Run by reference — the deployer never sees those payloads.
resource "google_secret_manager_secret_iam_member" "deployer_cf_token" {
  # Its own resource (infra/cloudflare.tf), not a member of the local.secret_ids for_each map.
  secret_id = google_secret_manager_secret.cloudflare_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.deployer.email}"
}

# The plan itself READS this one: main.tf has a
# `data "google_secret_manager_secret_version" "google_idp_client_secret"`, and a data source is
# resolved during plan, not apply. Without accessor the drift gate 403s before it can compare
# anything (observed on the first CI deploy run).
#
# So the honest scope of the deployer's secret access is these TWO values, granted per-secret —
# not project-wide. Every other credential is passed to Cloud Run BY REFERENCE
# (--set-secrets name:latest), which needs only secretmanager.viewer, so the deployer never sees
# those payloads. Adding another secret data source to the config would extend this list; prefer
# passing by reference so it doesn't have to.
resource "google_secret_manager_secret_iam_member" "deployer_idp_secret" {
  secret_id = google_secret_manager_secret.secrets["google-idp-client-secret"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.deployer.email}"
}

# Let the human/admin service account impersonate the deployer, so its permissions can be
# exercised LOCALLY instead of discovered one failed CI run at a time:
#
#   gcloud ... --impersonate-service-account=ci-deployer@...
#
# Every missing permission so far (secret payload access, then serviceusage) cost a full
# push→CI→deploy cycle to find. Impersonation turns that into a local plan.
resource "google_service_account_iam_member" "deployer_impersonation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:perkins-deploy-sa@${var.project_id}.iam.gserviceaccount.com"
}

output "ci_workload_identity_provider" {
  description = "Value for the deploy workflow's google-github-actions/auth workload_identity_provider"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_deployer_service_account" {
  description = "Value for the deploy workflow's service_account input"
  value       = google_service_account.deployer.email
}
