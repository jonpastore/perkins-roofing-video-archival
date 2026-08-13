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
      version = "~> 5.0"
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
    # #444 — both are prerequisites for google_billing_budget.spend_cap below, and BOTH were
    # missing, which is why that resource has never created anything: `gcloud billing accounts
    # list` fails with SERVICE_DISABLED, so nobody could even read the account id the budget needs.
    "cloudbilling.googleapis.com",   # read the billing account; required to fill var.billing_account
    "billingbudgets.googleapis.com", # the budget + threshold rules themselves
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

  lifecycle {
    # client_secret is WRITE-ONLY: the Identity Platform API never returns it (verified — a GET
    # on defaultSupportedIdpConfigs/google.com responds 200 with only name/enabled/clientId). So
    # terraform cannot confirm the applied value and, depending on which identity refreshes,
    # plans a perpetual "update in-place" that no apply ever settles. That made the CI drift gate
    # unpassable while real infra matched git exactly.
    #
    # ⚠️ TRADE-OFF: rotating google-idp-client-secret in Secret Manager will NOT be pushed by a
    # normal apply any more. After a rotation, force it explicitly:
    #   terraform apply -replace='google_identity_platform_default_supported_idp_config.google[0]'
    ignore_changes = [client_secret]
  }
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

# Deploy/ops identity — non-expiring, used from the workstation so terraform/deploy
# never depend on Jon's interactive Google login (which the Workspace reauth policy
# expires and refuses to refresh non-interactively). Bootstrapped via gcloud
# 2026-07-17 then imported into state (owner-scoped per Jon's call — "fast" over
# least-privilege). Its JSON key is backed up in the perkins-deploy-sa-key secret;
# the key value is NEVER in git. To rotate: mint a new key, update the secret, and
# re-activate (gcloud auth activate-service-account).
resource "google_service_account" "deploy_sa" {
  account_id   = "perkins-deploy-sa"
  display_name = "Perkins deploy/ops SA (non-expiring; owner-scoped per Jon 2026-07-17)"
  project      = var.project_id
}

resource "google_project_iam_member" "deploy_sa_owner" {
  project = var.project_id
  role    = "roles/owner"
  member  = "serviceAccount:${google_service_account.deploy_sa.email}"
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

# "Sync now": api-run-sa triggers the knowify-sync Cloud Run job (POST /knowify/sync-now).
# Without this the :run call 403s (api-run-sa had run.developer on render ONLY). Scoped to
# the knowify-sync job — least privilege, mirrors api_run_render above.
resource "google_cloud_run_v2_job_iam_member" "api_run_knowify_sync" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.jobs["knowify-sync"].name
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

# Admin metrics — GCP spend widget reads the BigQuery billing export.
# roles/bigquery.jobUser lets api-run-sa run BQ queries (required for client.query()).
# NOTE: dataset-level roles/bigquery.dataViewer must also be granted on the billing
# export dataset out-of-band (gcloud bigquery datasets add-iam-policy-binding or console)
# since Terraform cannot manage a dataset in a different project (billing exports land in
# the project's own dataset, but billing export setup is console-side).
# roles/billing.viewer is NOT needed — BQ export reads work with jobUser + dataViewer only.
resource "google_project_iam_member" "api_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.api_run_sa.email}"
}

# Data read is deliberately NOT granted project-wide (roles/bigquery.dataViewer at the
# project level would let api-run-sa read EVERY dataset — over-broad). Grant dataViewer
# on the billing-export DATASET ONLY, out-of-band, at the same time you enable the export
# and set BILLING_BQ_TABLE (both are console-side steps Terraform can't manage here):
#   bq add-iam-policy-binding \
#     --member=serviceAccount:api-run-sa@${var.project_id}.iam.gserviceaccount.com \
#     --role=roles/bigquery.dataViewer  PROJECT:BILLING_DATASET
# Until then the GCP-spend widget returns {configured:false} and needs no read grant.

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

    # A session that BEGINs and then goes idle holds its locks and pins the vacuum horizon for
    # as long as it lives. On 2026-07-29 three such sessions sat idle-in-transaction for over an
    # hour holding locks on `videos`; a routine `ALTER TABLE videos` then queued behind them,
    # and every subsequent reader queued behind the ALTER — a self-inflicted outage from a job
    # that had already finished. Postgres kills them for us: 5 minutes is far longer than any
    # legitimate transaction here (jobs commit per item; the long work is network I/O that must
    # happen OUTSIDE a transaction), so anything hitting this is a leak worth failing.
    database_flags {
      name  = "idle_in_transaction_session_timeout"
      value = "300000" # ms
    }

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

# POST /clips/upload-brand-video WRITES brand/{intro,outro}_video.mp4 into this bucket, and the
# API service account had read access only — so the endpoint returned 502 "GCS upload failed" on
# every attempt since it shipped. Josh hit it 2026-08-11; BRAND_INTRO_VIDEO/BRAND_OUTRO_VIDEO had
# never been set and gs://…-reels/brand/ was empty, so it had never once succeeded. Not drift: the
# feature was built without the grant it needs.
#
# objectAdmin, not objectCreator, because the endpoint OVERWRITES a fixed key on every upload and
# replacing an existing object needs delete. Scoped by IAM condition to the `brand/` prefix so the
# API still cannot touch the rendered reels this bucket exists to hold — the same least-privilege
# reasoning as speech_media_writer above, which takes objectCreator precisely so it cannot
# overwrite the archives.
resource "google_storage_bucket_iam_member" "api_reels_brand_writer" {
  bucket = google_storage_bucket.reels.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api_run_sa.email}"

  condition {
    title       = "brand_objects_only"
    description = "Only the brand intro/outro videos and scene images, never the rendered reels"
    expression  = "resource.name.startsWith(\"projects/_/buckets/${google_storage_bucket.reels.name}/objects/brand/\")"
  }
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
  job_names = toset(["ingest", "render", "article", "social", "knowify-sync", "knowify-keepwarm",
  "enumerate-channel", "archive", "companycam-sync", "salinity-sweep"])
  # ingest (STT audio demux) and render both download full source MP4s to a memory-backed /tmp;
  # the largest Perkins video is ~2 GB, so they need real headroom or the container OOM-kills
  # (SIGKILL) mid-batch. article/social are lightweight (LLM/HTTP only).
  # knowify-sync: full-pull of all Knowify entities per run + DB upserts; 1Gi/30min is ample
  #   at single-tenant volume. knowify-keepwarm: token-only refresh, no data; minimal resources.
  job_memory = {
    # salinity-sweep: a slice of USGS gauge readings per run, JSON only, no media.
    salinity-sweep   = "512Mi"
    ingest           = "8Gi"
    render           = "8Gi"
    article          = "2Gi"
    social           = "2Gi"
    knowify-sync     = "1Gi"
    knowify-keepwarm = "512Mi"
    # enumerate-channel: yt-dlp flat-playlist over the channel tabs + Video upserts. No media
    # download (that is ingest's job), so it stays light.
    enumerate-channel = "1Gi"
    # archive downloads full source MP4s to a memory-backed /tmp, same as ingest/render —
    # the largest Perkins video is ~2 GB, so it needs the same headroom or it OOM-kills.
    archive = "8Gi"
    # companycam-sync mirrors METADATA only (urls, coordinates, the internal flag) — the media
    # itself stays on CompanyCam's CDN and is never downloaded here, so this stays light even
    # though the account holds thousands of photos.
    companycam-sync = "1Gi"
  }
  # ingest may run a long-form batch STT (a caption-less 97-min podcast's batch takes ~40 min);
  # give it (and render) 2h so a legit long job finishes instead of being killed mid-transcript.
  job_timeout = {
    # salinity-sweep: 1/24th of ~64 gauges with a 1s courtesy pause between chunks. Seconds of
    # work; the timeout only has to survive a slow upstream.
    salinity-sweep   = "900s"
    ingest           = "7200s"
    render           = "7200s"
    article          = "3600s"
    social           = "3600s"
    knowify-sync     = "1800s"
    knowify-keepwarm = "300s"
    # Three channel tabs, ~900 entries, flat-playlist only — minutes, not hours.
    enumerate-channel = "1800s"
    archive           = "7200s"
    # The FIRST run is a full backfill of 3,684 projects x 2 paginated endpoints (~7,400
    # requests) — the 50-project figure this was originally sized for was the pagination bug
    # in adapters/companycam._get_all, not the real account. Later runs skip every project
    # whose CompanyCam updated_at has not moved (migration 0049), so steady state is one
    # project listing. 2h covers the backfill; a run that needs longer should fail loudly.
    companycam-sync = "7200s"
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
# 9c. Cloud Scheduler — salinity sweep, hourly
#
#     Jon, 2026-07-31: "poll all of the data from all sensors every day ... spread out the requests
#     over the day and hit them all as a background service on continuous run." One schedule, not
#     24: the job reads the UTC hour and takes slice (hour % 24) itself, so every gauge is
#     refreshed once a day at a few requests an hour instead of one daily burst.
#
#     Readings feed the BUILD of the warranty tool's tidal layer, never a runtime lookup, so no
#     browser ever calls USGS and nothing about a person is recorded.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "salinity_sweep" {
  name        = "salinity-sweep"
  region      = var.region
  description = "Refresh 1/24 of the USGS salinity gauges (warranty tool tidal layer)"
  schedule    = "17 * * * *" # :17 to stay clear of the other jobs' top-of-hour bunching
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count = 2
  }

  http_target {
    http_method = "POST"
    uri = format(
      "https://%s-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/%s/jobs/%s:run",
      var.region, var.project_id, google_cloud_run_v2_job.jobs["salinity-sweep"].name
    )

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
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
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

# Daily article generation. Nothing created content before this — the fourteen existing
# schedulers only MOVE content that already exists, which is why the catalogue sat at 473
# articles with nothing new (Jon, 2026-08-13: "we should be publishing daily").
#
# 09:10 America/Chicago: after run-ingest starts at 09:00, so a topic aggregated from this
# morning's ingest is eligible the same day, and hours before anyone reviews drafts.
# Generation is compliance-gated and publishes DRAFTS with a paced ScheduledContent go-live —
# promote-scheduled-content does the releasing, so there is still exactly one publish path.
resource "google_cloud_scheduler_job" "generate_daily_content" {
  name      = "generate-daily-content"
  region    = var.region
  schedule  = "10 9 * * *"
  time_zone = "America/Chicago"

  # An article campaign loops against the compliance gate; the default 180s deadline would
  # abandon the HTTP call mid-generation. The job holds an advisory lock, so an abandoned
  # request cannot be double-started by the next day's run either way.
  attempt_deadline = "1800s"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/daily-content"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

# Daily portfolio readiness scan. READ-ONLY BY DESIGN — it reports which projects could be built
# and what blocks the rest; it never publishes. A portfolio page needs recorded client permission
# (permission_property/photos/video, all defaulting to false) and human-selected photos, and
# neither is something a cron may supply about a customer's house. See jobs/portfolio_scan_job.
#
# 07:30, after companycam-sync at 06:00 — so the scan reads media mirrored this morning.
resource "google_cloud_scheduler_job" "portfolio_scan" {
  name      = "portfolio-scan-daily"
  region    = var.region
  schedule  = "30 7 * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/portfolio-scan"
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
# Probe shared platform integrations (wordpress/resend/knowify/youtube_reply) every 30 min
# and persist health status onto `integration_status` (plan Phase 1.4). Alert email on
# transition-to-broken is sent by the job itself via adapters/resend.py; this scheduler only
# owns the cadence + the request auth (X-Internal-Secret, mirrors every other /internal/* job).
resource "google_cloud_scheduler_job" "integration_health" {
  name      = "integration-health"
  region    = var.region
  schedule  = "*/30 * * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/integration-health"
    http_method = "POST"
    headers     = { "X-Internal-Secret" = google_secret_manager_secret_version.internal_secret.secret_data }

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  depends_on = [google_project_service.apis]
}

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

# Daily safety-net sweep: re-submit the site root + recently-published article URLs to
# IndexNow + the Google Indexing API. The primary submission path fires on every publish
# (jobs/promote_job.py); this only re-covers a submission that failed there (see
# jobs/search_indexing_job.py). Toggle: platform_config/env SEARCH_INDEXING_ENABLED.
resource "google_cloud_scheduler_job" "search_indexing_daily" {
  name      = "search-indexing-daily"
  region    = var.region
  schedule  = "0 8 * * *"
  time_zone = "America/Chicago"

  http_target {
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/search-indexing"
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
# the queue emptied; hourly drains the pending queue without 1,440 no-op runs/day.
# NOTE: this job does NOT discover new uploads — it only advances videos already in the table
# (jobs/ingest_worker.py selects rows whose stages aren't all done). An earlier version of this
# comment claimed it "keeps new channel uploads flowing", which was wrong and cost 25 days of
# missed videos: enumerate-channel below is what actually adds rows.
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

# Discover NEW channel uploads and upsert Video rows (jobs/enumerate_channel.py).
# This is the only thing that adds rows; run-ingest above merely advances rows that exist.
# The enumerator was written and committed but never given a Cloud Run Job or a schedule, so
# the catalog froze at its seed date: by 2026-07-28 the channel had 863 videos and the DB 841,
# with the newest row dated 2026-07-03 — 15 uploads missed, including two that day.
# 07:00 ET, i.e. BEFORE the 09:00-18:00 ingest window, so a video found in the morning is
# transcribed the same day rather than waiting for the next one.
resource "google_cloud_scheduler_job" "enumerate_channel" {
  name      = "enumerate-channel"
  region    = var.region
  schedule  = "0 7 * * *"
  time_zone = "America/New_York"
  paused    = false

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/enumerate-channel:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}

# Archive newly-discovered videos to the media bucket (jobs/archive_job.py).
#
# This is the third link in the catalogue chain and, like the other two, existed as a script
# that nothing ever ran: enumerate-channel finds a video, backfill_metadata dates it, and then
# it STOPS — adapters/stt_gcp.py raises "no archive_uri for {id}; run archive_job before STT",
# so an un-archived video can never be transcribed and never reaches article grounding. All 15
# videos discovered on 2026-07-28 were in exactly that state.
#
# Inherently incremental: the job filters Video.archive_uri IS NULL, so a run with nothing new
# does nothing. 07:30 ET, i.e. after enumerate-channel at 07:00, so the morning's finds are
# archived the same day and ingest (09:00-18:00) can transcribe them.
resource "google_cloud_scheduler_job" "archive" {
  name      = "archive"
  region    = var.region
  schedule  = "30 7 * * *"
  time_zone = "America/New_York"
  paused    = false

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/archive:run"
    http_method = "POST"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job.jobs]
}

# Mirror CompanyCam photos AND videos (jobs/companycam_sync.py).
#
# The same failure as enumerate-channel/archive above: the job was written, the application key
# went live 2026-07-28, and nothing ever ran it — companycam_photos sat at 0 rows while
# adapters.companycam.list_videos existed and was called by nothing. Meanwhile the account holds
# real project media (measured 2026-07-29 over 25 of 50 projects: 2,554 photos, 234 videos, 20 of
# the 25 with video), which is the source for project-page galleries. YouTube is NOT: the channel
# is topic content, so there is no key that joins a channel video to a property.
#
# 06:00 ET — before the content chain (enumerate 07:00 / archive 07:30) so a gallery built later
# in the day sees the morning's uploads. Metadata only; media stays on CompanyCam's CDN.
resource "google_cloud_scheduler_job" "companycam_sync" {
  name      = "companycam-sync"
  region    = var.region
  schedule  = "0 6 * * *"
  time_zone = "America/New_York"
  paused    = false

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/companycam-sync:run"
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

  # Paused 2026-07-23 (Jon): Knowify's server-side OAuth bug (RFC 8707 resource
  # param 500s token minting — ticket open with Knowify support) makes every run
  # exit 1 with auth_error, which flapped the failed-execution alert ~2 emails/hr.
  # Unpause when Knowify confirms the fix; the job + alert policy stay intact.
  paused = true

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
# 10c-mcp. Secret Manager — knowify-mcp-tokens (MCP OAuth token blob, STOPGAP)
#      knowify-sync runs with KNOWIFY_PULL_MODE=mcp because REST /oauth 500s on the
#      RFC 8707 resource binding (Wave-0). This secret holds the Claude Code MCP token
#      blob (camelCase: accessToken/refreshToken/clientId/expiresAt), bootstrap-populated
#      by Jon out-of-band (gcloud secrets versions add) — never committed to git/TF.
#      Mirrors the knowify-tokens standalone pattern above.
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "knowify_mcp_tokens" {
  secret_id = "knowify-mcp-tokens"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# Placeholder version so deploy can reference :latest before Jon bootstraps the real
# token. Intentionally invalid (no expiresAt) so any accidental use forces a refresh /
# surfaces as auth_error rather than silently passing a bad token.
resource "google_secret_manager_secret_version" "knowify_mcp_tokens_placeholder" {
  secret      = google_secret_manager_secret.knowify_mcp_tokens.id
  secret_data = "{\"_placeholder\":\"bootstrap-required-mcp-stopgap\"}"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# secretVersionAdder resource-scoped to knowify-mcp-tokens ONLY — the sync/keepwarm jobs
# rotate the single-use MCP refresh token and must write new versions. Same least-privilege
# reasoning as knowify_tokens_version_adder above (never grant project-wide).
resource "google_secret_manager_secret_iam_member" "knowify_mcp_tokens_version_adder" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.knowify_mcp_tokens.secret_id
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
# 10e. Alerting — Integration Health scheduler execution failure (job-liveness layer,
#      plan Phase 1.4 / Option C). This is the layer Cloud Monitoring owns: the SCHEDULER
#      failing to reach the endpoint (5xx / timeout), NOT the business-status alarm (that's
#      the app's own transition-to-broken email in jobs/integration_health_job.py). Reuses
#      the existing knowify_alert_email notification channel (same var.alert_email
#      recipient) rather than provisioning a second identical channel.
#      guard: count=0 when alert_email is empty, same pattern as 10d above.
# ---------------------------------------------------------------------------

resource "google_logging_metric" "integration_health_failures" {
  name   = "integration_health_failures"
  filter = <<-EOT
    resource.type="cloud_scheduler_job"
    resource.labels.job_id="integration-health"
    severity>=ERROR
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "integration_health_failure_alert" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "Integration Health — scheduler execution failure (5xx)"
  combiner     = "OR"

  conditions {
    display_name = "integration-health scheduler job failed"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/integration_health_failures\" resource.type=\"cloud_scheduler_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "1800s"
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

  depends_on = [google_logging_metric.integration_health_failures]
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
    "pexels-api-key",                # Clip Studio b-roll (adapters/pexels.py, PEXELS_API_KEY): no
    # value here — Jon adds the real key out-of-band via
    # `gcloud secrets versions add pexels-api-key --data-file=-`,
    # never in git/tfvars.
    "oauth-state-hmac",      # OAuth capture-flow state HMAC key (core/oauth_state.py): value out-of-band.
    "perkins-deploy-sa-key", # perkins-deploy-sa JSON key backup (bootstrapped 2026-07-17): value out-of-band.
    "companycam-pat",        # CompanyCam bearer token used by adapters/companycam.py. NOTE: despite
    # the container name this now holds an APPLICATION KEY, not a Personal
    # Access Token. CompanyCam offers both; the app key is tied to a
    # registered OAuth application ("Perkins Platform (DeGenito)", app 16351,
    # Read & Write, no expiry) rather than to Charles Mejia's user, so it
    # survives that person leaving. Issued 2026-07-28. The container name is
    # kept because GCP secrets cannot be renamed and the value is referenced
    # as COMPANYCAM_PAT in deploy.sh.
    "companycam-webhook-secret", # CompanyCam webhook signature secret: value out-of-band once issued.
    "companycam-client-id",      # OAuth app credentials for the same application. Not needed for the
    "companycam-client-secret",  # bearer-token calls we make today; required if/when we move to the
    # authorization-code flow (the app is a confidential client).
    # "youtube-cookies" was DELETED 2026-07-29. Cookies never fixed the bot-block — 15/15
    # downloads still failed from Cloud Run with the jar verified loaded, because the block is
    # on the egress IP (see wireguard-configs below). Nothing mounted it any more, and a YouTube
    # jar is a full Google session (SID/SAPISID are .google.com-scoped, so it authenticates
    # Gmail/Drive/Cloud Console too) — not worth storing for a measured non-fix. If it is ever
    # needed again, scripts/extract_youtube_cookies.py recreates it.
    "wireguard-configs", # Bundle of WireGuard client configs for yt-dlp egress (archive/render).
    # YouTube bot-blocks datacenter IPs: 15/15 downloads failed from Cloud Run
    # with cookies verified loaded, so it is the IP, not the identity. Downloads
    # go out through a USERSPACE tunnel (core/wireproxy.py) — kernel WireGuard
    # needs TUN + NET_ADMIN, which Cloud Run does not grant.
    # Several configs in one file because a blocked exit is STICKY per config:
    # reconnecting one config gave the same blocked IP 5/5, while other configs
    # landed in a different range and worked 3/3. adapters.yt_dlp rotates.
    # ⚠️ Contains WireGuard PRIVATE KEYS. Expect to refresh it — VPN ranges get
    # blocked over time, and exhaustion fails the job loudly by design.
    "squares-api-key", # SquareQuote API key. Was a PLAIN env var sourced from a laptop's
    # untracked .env, so a deploy from anywhere else silently shipped it
    # blank — and CI has no .env at all. Moved here 2026-07-28 so the
    # value is injected via --set-secrets like every other credential.
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

# ⚠️ THIS RESOURCE HAS NEVER EXISTED. var.billing_account defaults to "", so count is 0 and there
# is NO spend alerting on this project at all — verified 2026-08-02: `terraform state list` has no
# budget, and `gcloud billing accounts list` cannot even read the account (Cloud Billing API was
# disabled; now enabled above).
#
# Two things are still needed and NEITHER is a code change, which is why #444 is not a
# code-only task:
#   1. var.billing_account set in infra/perkins.auto.tfvars (committed) — needs the account id,
#      readable once the API above is applied.
#
# BOTH ARE NOW DONE and the budget is LIVE (created 2026-08-02, id ...fac2760b81e4). The account
# id came from `gcloud billing projects describe` — the PROJECT's billing linkage, a project-level
# read — and is set in perkins.auto.tfvars.
#
# ⚠️ A NOTE ON WHAT THE PERMISSION ERRORS DO AND DO NOT MEAN. perkins-deploy-sa CANNOT run
# `gcloud billing accounts list` (returns 0 items) or `gcloud billing budgets list` (403), and I
# read that as "the SA has no billing rights, so a billing admin must grant them". That was wrong:
# those two commands need billing.accounts.list / billing.budgets.list, and the SA has neither —
# but it DOES have budgets.create/get, which is all terraform uses. The apply succeeded on the
# first attempt. Do not re-derive a blocker from those errors; check terraform state instead.
resource "google_billing_budget" "spend_cap" {
  count = var.billing_account != "" ? 1 : 0

  billing_account = var.billing_account
  display_name    = "Perkins Platform Monthly Cap"

  budget_filter {
    # PROJECT NUMBER, not the id. The API normalises "projects/<id>" to "projects/<number>" on
    # read, so writing the id here produces a diff that never converges — terraform rewrites it
    # every plan and R4's drift gate fails forever on a budget that is in fact correct. Measured:
    # the first apply created the budget and the very next plan wanted to change it back.
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_amount)
    }
  }

  # 50 / 80 / 90 / 95 (#444). Was 50/90/100: the 100% rule fires only once the cap is already
  # spent, which is a receipt rather than a warning, and the gap from 50 to 90 is where an
  # unattended job would run. 95 replaces it so the last alert still leaves room to act.
  dynamic "threshold_rules" {
    for_each = [0.5, 0.8, 0.9, 0.95]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
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
