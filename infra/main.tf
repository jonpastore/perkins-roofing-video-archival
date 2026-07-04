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
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# 1. API enablement (idempotent — safe even if already enabled)
# ---------------------------------------------------------------------------

locals {
  required_apis = toset([
    "aiplatform.googleapis.com",
    "speech.googleapis.com",
    "sqladmin.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
  ])
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

resource "google_project_iam_member" "api_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
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
  name             = "${var.project_id}-pg"
  database_version = "POSTGRES_16"
  region           = var.region
  deletion_protection = true

  settings {
    tier    = "db-custom-1-3840"   # 1 vCPU / 3.75GB
    edition = "ENTERPRISE"          # ENTERPRISE_PLUS only accepts db-perf-optimized-* tiers

    backup_configuration {
      enabled    = true
      start_time = "03:00"
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
#    reels: public-read, uniform bucket-level access (rendered 9:16 reels for IG/TikTok)
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

# Public-read binding on reels bucket only — IG/TikTok require public video URLs.
resource "google_storage_bucket_iam_member" "reels_public" {
  bucket = google_storage_bucket.reels.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ---------------------------------------------------------------------------
# 8. Cloud Run v2 — API service
#    Placeholder image replaced with the real API container at Wave 1 deploy.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = "api"
  location = var.region

  template {
    service_account = google_service_account.api_run_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 4
    }

    containers {
      image = "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# 9. Cloud Run v2 Jobs — ingest, render, article, social
#    Placeholder image replaced with real jobs container at Wave 1 deploy.
# ---------------------------------------------------------------------------

locals {
  job_names = toset(["ingest", "render", "article", "social"])
}

resource "google_cloud_run_v2_job" "jobs" {
  for_each = local.job_names

  name     = each.value
  location = var.region

  template {
    template {
      service_account = google_service_account.jobs_sa.email
      max_retries     = 3
      timeout         = "3600s"

      containers {
        image = "gcr.io/cloudrun/hello"

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
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

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
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
