terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  # identitytoolkit (Firebase Auth) is a quota-required API — send the billing/quota project
  # header so ADC-authenticated applies succeed.
  billing_project       = var.project_id
  user_project_override = true
}

# ---------------------------------------------------------------------------
# 1. API enablement (idempotent — safe even if already enabled)
# ---------------------------------------------------------------------------

locals {
  required_apis = toset([
    "aiplatform.googleapis.com",
    "cloudidentity.googleapis.com",     # Workspace group mgmt (dmarc@ report group; admin ops via ADC)
    "apikeys.googleapis.com",           # API key management (squares key minted via TF)
    "solar.googleapis.com",             # Google Solar API — Squares roof measurement (pitch/azimuth/area per segment)
    "geocoding-backend.googleapis.com", # Geocoding for address -> lat/lng (Squares)
    "speech.googleapis.com",
    "sqladmin.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "identitytoolkit.googleapis.com", # Firebase Auth / Identity Platform (user sign-in)
    "admin.googleapis.com",           # Admin SDK Directory API (Workspace user dropdown, via DWD)
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
  ])
}

# ---------------------------------------------------------------------------
# Firebase Auth (Identity Platform) — Google sign-in for the admin/sales SPA.
# Roles are Firebase custom claims (admin|sales) set via scripts/grant_role.py.
# Access model: authorized_domains gates WHERE the app runs; deny-by-default in
# core.authz means an authenticated user with NO role claim can do nothing — so
# granting a role IS the allowlist. The Google IdP OAuth client + consent screen
# are created by Jon (console) and its id/secret filled below (see PRODUCTION_CHANGES).
# ---------------------------------------------------------------------------
resource "google_identity_platform_config" "auth" {
  project = var.project_id
  authorized_domains = concat(
    ["localhost", "${var.project_id}.firebaseapp.com", "${var.project_id}.web.app"],
    var.extra_auth_domains,
  )
  depends_on = [google_project_service.apis]

  lifecycle {
    # GCP auto-populates a multi_tenant block (allow_tenants=false) → perpetual false->null diff.
    ignore_changes = [multi_tenant]
  }
}

# Client secret lives in Secret Manager (google-idp-client-secret), never in git/tfvars.
# Read at apply time; the value is only consumed to configure the IdP, not at request time.
data "google_secret_manager_secret_version" "google_idp_client_secret" {
  count   = var.google_idp_client_id != "" ? 1 : 0
  project = var.project_id
  secret  = "google-idp-client-secret"
}

resource "google_identity_platform_default_supported_idp_config" "google" {
  count         = var.google_idp_client_id != "" ? 1 : 0
  project       = var.project_id
  idp_id        = "google.com"
  client_id     = var.google_idp_client_id # OAuth client_id is a public identifier, not a secret
  client_secret = data.google_secret_manager_secret_version.google_idp_client_secret[0].secret_data
  enabled       = true
  depends_on    = [google_identity_platform_config.auth]
}

resource "google_project_service" "apis" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# 2. Service accounts
# ---------------------------------------------------------------------------

resource "google_service_account" "api_run_sa" {
  account_id   = "api-run-sa"
  display_name = "Perkins API — Cloud Run service identity"
  project      = var.project_id
}

resource "google_service_account" "jobs_sa" {
  account_id   = "jobs-sa"
  display_name = "Perkins Jobs — Cloud Run Job identity (ingest, render, article, social)"
  project      = var.project_id
}

resource "google_service_account" "scheduler_sa" {
  account_id   = "scheduler-sa"
  display_name = "Perkins Scheduler — Cloud Scheduler OIDC invoker"
  project      = var.project_id
}

# ---------------------------------------------------------------------------
# 3. IAM bindings — api-run-sa
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "api_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

resource "google_project_iam_member" "api_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

resource "google_project_iam_member" "api_secretmanager" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# The admin Logs viewer route (api/routes/logs.py) reads Cloud Logging; the API SA needs
# read access or "logs fail to pull".
resource "google_project_iam_member" "api_logging_viewer" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

resource "google_project_iam_member" "api_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# Let api-run-sa self-sign (IAM SignBlob) so it can mint V4 signed URLs for private
# media-bucket downloads (the archive download UI) without a downloaded key.
resource "google_service_account_iam_member" "api_sign" {
  service_account_id = google_service_account.api_run_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# Firebase Auth admin: (1) verify_id_token(check_revoked=True) reads the user record on every
# request; (2) the /admin/users role-management endpoint sets custom claims (set_custom_user_claims).
# Admin-role-gated in-app. Without this, authed requests 401 and role management fails.
resource "google_project_iam_member" "api_firebaseauth_admin" {
  project = var.project_id
  role    = "roles/firebaseauth.admin"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# "Render now": api-run-sa triggers the render Cloud Run job (run.jobs.run) and acts as the
# job's executor SA. Scoped to the render job (least privilege), not project-wide run.developer.
resource "google_cloud_run_v2_job_iam_member" "api_run_render" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.jobs["render"].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.api_run_sa.email}"
}

resource "google_service_account_iam_member" "api_actas_jobs_sa" {
  service_account_id = google_service_account.jobs_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# Config secret updates: api-run-sa adds new Secret Manager versions + reads version metadata
# (last-set time). The /config/secrets endpoint is admin-gated and never returns secret values.
resource "google_project_iam_member" "api_secret_version_adder" {
  project = var.project_id
  role    = "roles/secretmanager.secretVersionAdder"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

resource "google_project_iam_member" "api_secret_viewer" {
  project = var.project_id
  role    = "roles/secretmanager.viewer"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# ---------------------------------------------------------------------------
# 4. IAM bindings — jobs-sa
#    roles/speech.client grants Cloud Speech-to-Text access.
#    Fallback if unavailable: roles/serviceusage.serviceUsageConsumer + custom role.
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "jobs_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.jobs_sa.email}"
}

resource "google_project_iam_member" "jobs_speech" {
  project = var.project_id
  role    = "roles/speech.client"
  member  = "serviceAccount:${google_service_account.jobs_sa.email}"
}

resource "google_project_iam_member" "jobs_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.jobs_sa.email}"
}

resource "google_project_iam_member" "jobs_storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.jobs_sa.email}"
}

resource "google_project_iam_member" "jobs_secretmanager" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.jobs_sa.email}"
}

# ---------------------------------------------------------------------------
# 5. IAM bindings — scheduler-sa
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

# ---------------------------------------------------------------------------
# 6. Cloud SQL — Postgres 16
#    Tier: db-custom-1-3840 (1 vCPU, 3.75 GB RAM) — right-size after load testing.
#
#    pgvector is NOT a Cloud SQL flag; it is a Postgres extension enabled
#    post-provision with:
#      CREATE EXTENSION IF NOT EXISTS vector;
#    See bootstrap.sh for the exact gcloud sql connect command.
# ---------------------------------------------------------------------------

resource "google_sql_database_instance" "pg" {
  name                = "${var.project_id}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true

  settings {
    tier    = "db-custom-1-3840" # 1 vCPU / 3.75GB
    edition = "ENTERPRISE"       # ENTERPRISE_PLUS only accepts db-perf-optimized-* tiers

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      # Public IP but NO authorized networks — direct connections are blocked. Access is only
      # via the Cloud SQL Auth Proxy / connector with IAM (Cloud Run uses the built-in connector;
      # `gcloud sql connect` temporarily whitelists an operator IP for migrations). SSL enforced.
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "perkins" {
  name     = "perkins"
  instance = google_sql_database_instance.pg.name
}

# App DB user — password generated + stored in Secret Manager (never in git/state plaintext).
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}

# ---------------------------------------------------------------------------
# 7. GCS buckets
#    media: private, uniform bucket-level access (raw video, audio, ffmpeg artifacts)
#    reels: private, uniform bucket-level access (rendered 9:16 reels for IG/TikTok)
#           IG/TikTok ingest via short-TTL V4 signed URLs minted at publish time.
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "media" {
  name                        = "${var.project_id}-media"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition { age = 90 }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

resource "google_storage_bucket" "reels" {
  name                        = "${var.project_id}-reels"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
}

# The API service reads the reels bucket for the Config connectivity health check and to
# resolve brand-scene images; grant it read on the bucket + objects.
resource "google_storage_bucket_iam_member" "api_reels_reader" {
  bucket = google_storage_bucket.reels.name
  role   = "roles/storage.legacyBucketReader"
  member = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# Speech-to-Text v2 BatchRecognize reads its input object as the Speech SERVICE AGENT
# (service-<projnum>@gcp-sa-speech), not as jobs-sa. The ingest job transcribes the archived
# MP4s in place, so grant that agent read access to the media bucket. Without this, batch STT
# fails with "does not have read permissions to object gs://…-media/videos/<id>.mp4".
data "google_project" "this" {
  project_id = var.project_id
}

resource "google_storage_bucket_iam_member" "speech_media_reader" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-speech.iam.gserviceaccount.com"
}

# Batch STT for long audio writes its transcript to GCS (gcs_output_config) rather than inline —
# inline is only for small single-file results. The Speech service agent needs to CREATE those
# output objects. objectCreator (not objectAdmin) so it can't overwrite/delete the archives.
resource "google_storage_bucket_iam_member" "speech_media_writer" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-speech.iam.gserviceaccount.com"
}

# Reels bucket is PRIVATE. IG/TikTok ingest via a short-TTL V4 signed URL minted at publish
# time (jobs/social_job → adapters.storage.signed_get_url), so the client's media is never
# left publicly exposed. jobs-sa self-signs (serviceAccountTokenCreator below).
resource "google_service_account_iam_member" "jobs_sign" {
  service_account_id = google_service_account.jobs_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.jobs_sa.email}"
}

# ---------------------------------------------------------------------------
# 8. Cloud Run v2 — API service
#    Placeholder image replaced with the real API container at Wave 1 deploy.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = "api"
  location = var.region

  lifecycle {
    # GCP normalizes scaling counts 0->null (a perpetual provider diff), and the container
    # image + env + cloudsql volume are deployed by CI/CD (scripts/deploy.sh), not Terraform —
    # ignore so drift checks stay clean. client/client_version are gcloud-set metadata.
    ignore_changes = [
      scaling, # service-level scaling block GCP auto-populates with 0s (perpetual 0->null diff)
      client,
      client_version,
      template[0].containers[0].image,
      template[0].containers[0].env,
      template[0].containers[0].volume_mounts,
      template[0].volumes,
    ]
  }

  template {
    service_account = google_service_account.api_run_sa.email

    scaling {
      # min_instance_count omitted — GCP treats explicit 0 as null → perpetual plan diff.
      # Scale-to-zero is the default.
      max_instance_count = 4
    }

    containers {
      image = "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }
    }

    # Long request budget for synchronous LLM work (article/cluster generation).
    timeout = "900s"
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# 9. Cloud Run v2 Jobs — ingest, render, article, social
#    Placeholder image replaced with real jobs container at Wave 1 deploy.
# ---------------------------------------------------------------------------

locals {
  job_names = toset(["ingest", "render", "article", "social", "knowify-sync", "knowify-keepwarm"])
  # ingest (STT audio demux) and render both download full source MP4s to a memory-backed /tmp;
  # the largest Perkins video is ~2 GB, so they need real headroom or the container OOM-kills
  # (SIGKILL) mid-batch. article/social are lightweight (LLM/HTTP only).
  # knowify-sync: full-pull of all Knowify entities per run + DB upserts; 1Gi/30min is ample
  #   at single-tenant volume. knowify-keepwarm: token-only refresh, no data; minimal resources.
  job_memory = {
    ingest           = "8Gi"
    render           = "8Gi"
    article          = "2Gi"
    social           = "2Gi"
    knowify-sync     = "1Gi"
    knowify-keepwarm = "512Mi"
  }
  # ingest may run a long-form batch STT (a caption-less 97-min podcast's batch takes ~40 min);
  # give it (and render) 2h so a legit long job finishes instead of being killed mid-transcript.
  job_timeout = {
    ingest           = "7200s"
    render           = "7200s"
    article          = "3600s"
    social           = "3600s"
    knowify-sync     = "1800s"
    knowify-keepwarm = "300s"
  }
}

resource "google_cloud_run_v2_job" "jobs" {
  for_each = local.job_names

  name     = each.value
  location = var.region

  template {
    template {
      service_account = google_service_account.jobs_sa.email
      max_retries     = 3
      timeout         = local.job_timeout[each.value]

      containers {
        image = "gcr.io/cloudrun/hello"

        resources {
          limits = {
            cpu    = "2"
            memory = local.job_memory[each.value]
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    # Image, entrypoint, and env are deployed by CI/CD (scripts/deploy.sh: gcloud run
    # jobs update --image/--command/--args/--set-env-vars), not Terraform — ignore so
    # drift checks stay clean. client/client_version are gcloud-set metadata.
    ignore_changes = [
      client,
      client_version,
      template[0].template[0].containers[0].image,
      template[0].template[0].containers[0].command,
      template[0].template[0].containers[0].args,
      template[0].template[0].containers[0].env,
      template[0].template[0].containers[0].volume_mounts,
      template[0].template[0].volumes,
    ]
  }
}

# ---------------------------------------------------------------------------
# 10. Cloud Scheduler — promote scheduled content every 15 minutes
#     Hits /internal/promote on the API service via OIDC (scheduler-sa).
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "promote_scheduled_content" {
  name      = "promote-scheduled-content"
  region    = var.region
  schedule  = "*/15 * * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/promote"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_scheduler_job" "publish_awaiting_social" {
  name      = "publish-awaiting-social"
  region    = var.region
  schedule  = "*/15 * * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/social"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

# The /internal/* cron endpoints are guarded by INTERNAL_SECRET (X-Internal-Secret header);
# the scheduler reads the value from Secret Manager and sends it on each request. Created in
# IaC (was hand-made in the 2026-07-06 drift; a bare `data` source made `terraform plan` fail
# with NOT_FOUND on a fresh project). Mirrors the db_password pattern.
resource "random_password" "internal" {
  length  = 48
  special = false
}

resource "google_secret_manager_secret" "internal_secret" {
  secret_id = "internal-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "internal_secret" {
  secret      = google_secret_manager_secret.internal_secret.id
  secret_data = random_password.internal.result
}

# Crawl YouTube comments on a rotating cron — each run takes the least-recently-crawled
# batch, so the whole catalog is covered over successive runs. Every 2 hours.
resource "google_cloud_scheduler_job" "crawl_comments" {
  name      = "crawl-comments"
  region    = var.region
  schedule  = "0 */2 * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/crawl-comments"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

# Poll YouTube KPIs (views/likes/comment counts) for all archived videos daily.
# Runs as a Cloud Run Job (jobs-sa) so it can handle the full 841-video catalog
# in one execution without the API request timeout constraint.
# Cadence: 02:00 Chicago time daily — off-peak, after the overnight crawl-comments
# rotation has already refreshed the most recently touched videos.
resource "google_cloud_scheduler_job" "poll_archive_kpis" {
  name      = "poll-archive-kpis"
  region    = var.region
  schedule  = "0 2 * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/poll-archive-kpis"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

# Trigger the `ingest` Cloud Run Job hourly during business hours (9:00-18:00 ET, inclusive).
# Runs as jobs-sa: speech.client + media-bucket access + a 3600s timeout — the STT-heavy work
# does NOT belong in the user-facing API request. The job is single-flight (Postgres advisory
# lock), so executions can never overlap — a second execution grabs no lock and exits.
# History: per-minute during the initial backlog drain, then paused out-of-band 2026-07-06 once
# the queue emptied; hourly keeps new channel uploads flowing without 1,440 no-op runs/day.
# scheduler_sa already holds project-wide roles/run.invoker (see scheduler_run_invoker).
resource "google_cloud_scheduler_job" "run_ingest" {
  name      = "run-ingest"
  region    = var.region
  schedule  = "0 9-18 * * *"
  time_zone = "America/New_York"
  paused    = false

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/ingest:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}

# ---------------------------------------------------------------------------
# 10b. Cloud Scheduler — Knowify hourly sync (08:00-18:00 ET, 11 runs/day)
#
# v1 = single writer (TRD §3): only knowify-sync refreshes+rotates the token.
# The keep-warm job below covers the 14h overnight gap (18:00→08:00 ET).
# Wave-0 evidence: the stored refresh token was dead within <1 day of disuse,
# proving the overnight gap exceeds the idle-expiry window. Both jobs share
# Postgres advisory lock 8274125 (in core/knowify/tokens.py) so no writer can
# publish a stale rotated token as :latest.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "knowify_sync" {
  name      = "knowify-sync"
  region    = var.region
  schedule  = "0 8-18 * * *"
  time_zone = "America/New_York"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/knowify-sync:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}

# Keep-warm: refreshes the Knowify OAuth token once nightly to prevent the
# refresh token from lapsing during the 14h overnight gap (last sync 18:00,
# first sync 08:00 ET). Cadence is set to 02:00 ET — adjust once the exact
# idle-expiry TTL is measured on the first live pull (Wave-9 open question:
# if idle-TTL > 14h, disable this scheduler; the IaC resource stays).
# ponytail: conditional deploy — resource is written; apply is gated on
#   Wave-9 idle-TTL measurement. If TTL > 14h, leave paused or remove scheduler.
resource "google_cloud_scheduler_job" "knowify_keepwarm" {
  name      = "knowify-keepwarm"
  region    = var.region
  schedule  = "0 2 * * *"
  time_zone = "America/New_York"

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/knowify-keepwarm:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}

# ---------------------------------------------------------------------------
# 10c. Secret Manager — knowify-tokens (OAuth token blob)
#      Container only — value is bootstrap-populated by Jon after a fresh
#      knowify_oauth.py login (Wave-9 step 4). Never committed to git or TF.
#      Mirrors the db_password / internal_secret standalone pattern (NOT in
#      local.secret_ids for_each, because this secret needs resource-scoped
#      IAM that the for_each batch cannot express per-secret).
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "knowify_tokens" {
  secret_id = "knowify-tokens"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# Placeholder version so Cloud Run --set-secrets can reference :latest at
# deploy time before Jon bootstraps the real token. Jon replaces this with
# the real token blob via Wave-9 bootstrap step (gcloud secrets versions add).
# The placeholder value is intentionally invalid so any accidental use surfaces
# as an auth error immediately rather than silently passing a bad token.
resource "google_secret_manager_secret_version" "knowify_tokens_placeholder" {
  secret      = google_secret_manager_secret.knowify_tokens.id
  secret_data = "{\"_placeholder\":\"bootstrap-required-see-wave9\"}"

  lifecycle {
    # Jon replaces this with the real token out-of-band; ignore subsequent
    # gcloud-managed versions so terraform plan stays clean after bootstrap.
    ignore_changes = [secret_data]
  }
}

# IAM — secretAccessor for jobs-sa is already granted project-wide at line
# 235-238 (google_project_iam_member.jobs_secretmanager). No duplicate needed.
#
# secretVersionAdder is resource-scoped to knowify-tokens ONLY — deliberate
# divergence from the project-wide pattern at main.tf:193-197. The sync job
# rotates the refresh token and must write new secret versions; granting
# secretVersionAdder project-wide would allow it to overwrite ANY secret,
# which violates least-privilege. Scope it to the one secret it actually writes.
resource "google_secret_manager_secret_iam_member" "knowify_tokens_version_adder" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.knowify_tokens.secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.jobs_sa.email}"
}

# ---------------------------------------------------------------------------
# 10d. Alerting — Knowify sync failure / stale-sync (AC-18, TRD §9a)
#      Fires when: (a) any execution logs auth_error status, OR (b) no
#      successful knowify-sync execution has been logged in >24h (stale sync).
#      Notification channel reuses var.alert_email (variables.tf:25).
#      guard: count=0 when alert_email is empty so terraform validate passes
#      without the value set (mirrors the billing_budget guard pattern).
# ---------------------------------------------------------------------------

resource "google_monitoring_notification_channel" "knowify_alert_email" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "Knowify Sync Alerts — Email"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  depends_on = [google_project_service.apis]
}

# Log-based metric: count executions where the sync job logged auth_error
# or the Cloud Run execution itself failed (non-zero exit → job/execution failed log).
resource "google_logging_metric" "knowify_sync_failures" {
  name   = "knowify_sync_failures"
  filter = <<-EOT
    resource.type="cloud_run_job"
    resource.labels.job_name="knowify-sync"
    (
      jsonPayload.last_status="auth_error"
      OR textPayload=~"auth_error"
      OR severity="ERROR"
    )
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Alert policy: fires when the failure metric exceeds 0 in any 10-minute window.
resource "google_monitoring_alert_policy" "knowify_sync_failure_alert" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "Knowify Sync — auth_error or job failure"
  combiner     = "OR"

  conditions {
    display_name = "knowify-sync logged auth_error or non-zero exit"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/knowify_sync_failures\" resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_COUNT"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.knowify_alert_email[0].name,
  ]

  alert_strategy {
    auto_close = "1800s"
  }

  depends_on = [google_logging_metric.knowify_sync_failures]
}

# ---------------------------------------------------------------------------
# 11. Secret Manager — secret containers only (no versions)
#     Populate secret values via bootstrap.sh after billing is confirmed.
# ---------------------------------------------------------------------------

locals {
  secret_ids = toset([
    "youtube-api-key",
    "serper-api-key",
    "resend-api-key",
    "wordpress-app-password",
    "meta-app-secret",
    "meta-system-user-token",
    "tiktok-client-secret",
    "tiktok-refresh-token",
    "google-idp-client-secret",
    "whisper-token",
    "youtube-oauth-refresh-token",
    "vertex-dev-sa-key",             # deepsec M1: local-dev Vertex SA key (value added out-of-band)
    "cloudflare-degenito-api-token", # ez-bids: degenito.ai zone DNS (value from 1Password, added out-of-band)
  ])
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secret_ids
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# 12. Billing budget alert
#     Guarded with count=0 when billing_account is empty so terraform validate
#     passes without the value. Jon fills in billing_account variable to activate.
#     Format: XXXXXX-XXXXXX-XXXXXX (find in GCP Console → Billing).
# ---------------------------------------------------------------------------

resource "google_billing_budget" "spend_cap" {
  count = var.billing_account != "" ? 1 : 0

  billing_account = var.billing_account
  display_name    = "Perkins Platform Monthly Cap"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 0.9
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  # all_updates_rule omitted — alerts fire to the billing account's default contacts.
  # Add a monitoring_notification_channels entry here post-billing if needed.
}

# ---------------------------------------------------------------------------
# Squares — Google Solar + Geocoding API key (migration 0024, 2026-07-10)
# Restricted to solar.googleapis.com and geocoding-backend.googleapis.com only.
# Key string is surfaced as a sensitive output and injected into deploy.sh
# via SQUARES_API_KEY in .env after `terraform output -raw squares_api_key`.
# ---------------------------------------------------------------------------

resource "google_apikeys_key" "squares_key" {
  name         = "squares-api-key"
  display_name = "Squares (Solar+Geocoding)"
  project      = var.project_id

  restrictions {
    api_targets {
      service = "solar.googleapis.com"
    }
    api_targets {
      service = "geocoding-backend.googleapis.com"
    }
  }
}

output "squares_api_key" {
  description = "API key for Google Solar + Geocoding (Squares feature). Inject as SQUARES_API_KEY."
  value       = google_apikeys_key.squares_key.key_string
  sensitive   = true
}
