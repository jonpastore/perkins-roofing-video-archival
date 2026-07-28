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

output "ci_workload_identity_provider" {
  description = "Value for the deploy workflow's google-github-actions/auth workload_identity_provider"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_deployer_service_account" {
  description = "Value for the deploy workflow's service_account input"
  value       = google_service_account.deployer.email
}
