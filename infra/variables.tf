variable "project_id" {
  type        = string
  description = "GCP project ID (billing already linked)"
  default     = "video-archival-and-content-gen"
}

variable "region" {
  type        = string
  description = "GCP region for all regional resources"
  default     = "us-central1"
}

variable "billing_account" {
  type        = string
  description = "GCP billing account ID (format: XXXXXX-XXXXXX-XXXXXX). Fill this in to enable the budget alert. Leave empty to skip the budget resource."
  default     = ""
}

variable "budget_amount" {
  type        = number
  description = "Monthly spend cap in USD before the alert fires"
  default     = 200
}

variable "alert_email" {
  type        = string
  description = "Email address to notify when the budget threshold is hit"
  default     = ""
}

variable "extra_auth_domains" {
  type        = list(string)
  description = "Additional Firebase Auth authorized domains (e.g. app.perkinsroofing.net once the SPA is on a custom domain)"
  default     = ["perkins.degenito.ai"]
}

variable "google_idp_client_id" {
  type        = string
  description = "OAuth client ID for Google sign-in (created by Jon in the console). Empty = Google IdP not provisioned yet."
  default     = ""
}

variable "google_idp_client_secret" {
  type        = string
  description = "OAuth client secret for Google sign-in. Pair with google_idp_client_id."
  default     = ""
  sensitive   = true
}
