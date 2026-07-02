# Terraform skeleton — provisions the platform in the CLIENT's own GCP project.
# (Stub for the production build; gated on deposit + client GCP. Apply post-deposit.)
terraform {
  required_providers { google = { source = "hashicorp/google", version = "~> 5.0" } }
}
variable "project_id" { type = string }
variable "region"     { type = string  default = "us-east1" }

provider "google" { project = var.project_id, region = var.region }

# --- Storage: media archive + audio ---
resource "google_storage_bucket" "media" {
  name          = "${var.project_id}-perkins-media"
  location      = var.region
  force_destroy = false
  lifecycle_rule {                      # cost control: age out cold media to Nearline/Archive
    condition { age = 60 }
    action { type = "SetStorageClass", storage_class = "NEARLINE" }
  }
}

# --- Database: Cloud SQL Postgres (enable pgvector extension via migration) ---
resource "google_sql_database_instance" "pg" {
  name             = "perkins-pg"
  database_version = "POSTGRES_16"
  settings { tier = "db-custom-1-3840" }  # right-size later
  deletion_protection = true
}

# --- Secrets ---
resource "google_secret_manager_secret" "yt_oauth" {
  secret_id = "youtube-oauth"
  replication { auto {} }
}

# --- Async ingestion: Pub/Sub topic feeding a Cloud Run Job ---
resource "google_pubsub_topic" "ingest" { name = "perkins-ingest" }

# --- Service accounts (least privilege) ---
resource "google_service_account" "api" {
  account_id = "perkins-api"; display_name = "Perkins API (Cloud Run)"
}
resource "google_service_account" "worker" {
  account_id = "perkins-worker"; display_name = "Perkins ingest worker (Cloud Run Job)"
}

# --- Online serving: API (Cloud Run service) ---
resource "google_cloud_run_v2_service" "api" {
  name     = "perkins-api"
  location = var.region
  template {
    service_account = google_service_account.api.email
    scaling { min_instance_count = 1, max_instance_count = 4 }
    containers {
      image = "gcr.io/${var.project_id}/perkins:latest"
      env { name = "DB_URL"        value = "postgresql+psycopg://…/perkins" }
      env { name = "EMBED_BACKEND" value = "vertex" }
      env { name = "LLM_BACKEND"   value = "vertex" }
    }
  }
}

# --- Offline ingestion: worker (Cloud Run Job, separate from API) ---
resource "google_cloud_run_v2_job" "ingest" {
  name     = "perkins-ingest"
  location = var.region
  template { template {
    service_account = google_service_account.worker.email
    timeout = "3600s"
    containers {
      image   = "gcr.io/${var.project_id}/perkins:latest"
      command = ["python", "-m", "app.worker"]
    }
  } }
}

# --- Scheduler: poll the channel for new uploads → enqueue ingest ---
resource "google_cloud_scheduler_job" "poll" {
  name     = "perkins-poll"
  schedule = "0 */6 * * *"            # every 6h
  pubsub_target {
    topic_name = google_pubsub_topic.ingest.id
    data       = base64encode("poll")
  }
}

# --- Monitoring: alert on failed ingestion + budget guard ---
resource "google_monitoring_alert_policy" "ingest_failures" {
  display_name = "Perkins ingest failures"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Run Job failures"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_job\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
    }
  }
}

output "media_bucket" { value = google_storage_bucket.media.name }
output "api_url"       { value = google_cloud_run_v2_service.api.uri }
