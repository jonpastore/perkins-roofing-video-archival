# Artifact Registry for the app container + Cloud Build to produce it.
# (Separate file from main.tf to keep the deploy surface isolated.)

resource "google_project_service" "build_apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firebasehosting.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "app"
  description   = "Perkins v2 platform container image (Cloud Run service + jobs)"
  format        = "DOCKER"
  depends_on    = [google_project_service.build_apis]
}
