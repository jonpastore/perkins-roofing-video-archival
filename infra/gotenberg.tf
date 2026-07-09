# ---------------------------------------------------------------------------
# Gotenberg PDF rendering service (Wave F3)
#
# Internal-only Cloud Run v2 service running the official Gotenberg image.
# Invoked by the API service (api_run_sa) to convert HTML → PDF for proposals.
# No public ingress — all traffic must originate from within the VPC / Cloud Run.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "gotenberg" {
  name     = "gotenberg"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.api_run_sa.email

    scaling {
      # Scale-to-zero when idle; burst up to 3 for concurrent proposal renders.
      # min_instance_count omitted — GCP treats explicit 0 as null (perpetual diff).
      max_instance_count = 3
    }

    containers {
      # Pinned to Gotenberg 8 (Chromium-based HTML→PDF).
      # Update the tag here and re-apply when a new minor/patch is available.
      image = "gotenberg/gotenberg:8"

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    # client/client_version are gcloud-set metadata; ignore to keep drift checks clean.
    ignore_changes = [
      client,
      client_version,
    ]
  }
}

# Grant the API service account permission to invoke Gotenberg.
# Gotenberg has no public ingress; this IAM binding is the only admission path.
resource "google_cloud_run_v2_service_iam_member" "gotenberg_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.gotenberg.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api_run_sa.email}"
}

output "gotenberg_url" {
  description = "Internal Cloud Run URL for the Gotenberg PDF rendering service. After terraform apply, export this value into GOTENBERG_URL before running scripts/deploy.sh: export GOTENBERG_URL=$(terraform output -raw gotenberg_url)"
  value       = google_cloud_run_v2_service.gotenberg.uri
}

# ---------------------------------------------------------------------------
# Cloud Scheduler — daily proposal reminder nudge job (Wave F3)
#
# Hits /internal/proposal-reminders on the API service (INTERNAL_SECRET + OIDC).
# Cadence: 09:00 UTC = 05:00 ET (before business hours).
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "proposal_reminders" {
  name             = "proposal-reminders-daily"
  region           = var.region
  schedule         = "0 9 * * *"
  time_zone        = "UTC"
  attempt_deadline = "300s"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/proposal-reminders"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_service.api]
}
