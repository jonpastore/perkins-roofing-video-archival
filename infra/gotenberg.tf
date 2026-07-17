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
  # Service-to-service calls from the API run at the public *.run.app hostname (no VPC
  # connector), so INTERNAL_ONLY returned a GFE 404. Ingress is ALL but IAM still gates
  # every request — only api_run_sa holds roles/run.invoker (binding below), so this is
  # authenticated-only, not public.
  ingress = "INGRESS_TRAFFIC_ALL"

  # Stateless HTML→PDF render service — no data to protect, and the provider default
  # of true blocks recreating a tainted/failed revision. Safe to allow deletion.
  deletion_protection = false

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

      # Gotenberg listens on 3000 by default (it does NOT read Cloud Run's PORT=8080),
      # so Cloud Run must route + health-check the container's real port or the revision
      # fails to start. Point Cloud Run at 3000.
      ports {
        container_port = 3000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      liveness_probe {
        http_get {
          path = "/health"
          # Gotenberg listens on 3000; without this the probe defaults to $PORT (8080)
          # and never succeeds.
          port = 3000
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    # client/client_version are gcloud-set metadata; ignore to keep drift checks clean.
    # NOTE: Cloud Run returns scaling.{manual,min}_instance_count = 0 for these unset
    # fields, so `terraform plan` shows a harmless perpetual "0 -> null" in-place diff on
    # this service. It cannot be applied away (GCP always reports 0) and nested-path
    # ignore_changes is unsupported here — treat this one gotenberg in-place change as
    # expected/benign in the R4 drift check.
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

resource "google_cloud_run_v2_service_iam_member" "gotenberg_jobs_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.gotenberg.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.jobs_sa.email}"
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

  # DISABLED 2026-07-14: proposal reminder emails are turned off pending review of
  # outbound customer email. Re-enable by setting paused = false (and confirm the
  # EMAIL_SEND_MODE gate on the api service is configured as intended).
  paused = true

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
