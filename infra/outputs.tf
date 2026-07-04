output "api_url" {
  description = "Cloud Run API service URL"
  value       = google_cloud_run_v2_service.api.uri
}

output "media_bucket" {
  description = "GCS bucket name for private media storage"
  value       = google_storage_bucket.media.name
}

output "reels_bucket" {
  description = "GCS bucket name for public-read rendered reels (IG/TikTok)"
  value       = google_storage_bucket.reels.name
}

output "sql_instance_connection_name" {
  description = "Cloud SQL instance connection name (used by Cloud SQL Auth Proxy)"
  value       = google_sql_database_instance.pg.connection_name
}

output "api_run_sa_email" {
  description = "Service account email for the Cloud Run API service"
  value       = google_service_account.api_run_sa.email
}

output "jobs_sa_email" {
  description = "Service account email for Cloud Run Jobs"
  value       = google_service_account.jobs_sa.email
}

output "scheduler_sa_email" {
  description = "Service account email for Cloud Scheduler OIDC"
  value       = google_service_account.scheduler_sa.email
}

output "secret_names" {
  description = "Secret Manager secret IDs created (populate values via bootstrap.sh)"
  value       = [for s in google_secret_manager_secret.secrets : s.secret_id]
}
