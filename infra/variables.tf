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
