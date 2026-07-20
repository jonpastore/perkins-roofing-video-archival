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
  description = "Email address for budget + Cloud Monitoring alert notifications. Empty disables all alert policies + the notification channel (count=0)."
  default     = "dmarc@perkinsroofing.net"
}

variable "extra_auth_domains" {
  type        = list(string)
  description = "Additional Firebase Auth authorized domains (e.g. app.perkinsroofing.net once the SPA is on a custom domain)"
  default     = ["perkins.degenito.ai", "app.perkinsroofing.net"]
}

variable "google_idp_client_id" {
  type        = string
  description = "OAuth client ID for Google sign-in. Public identifier (safe in git), not a secret. Empty = Google IdP not provisioned. Paired secret lives in Secret Manager (google-idp-client-secret)."
  default     = "981279422576-afa5jspjffd447puojs40m3f6s9qcra9.apps.googleusercontent.com"
}

# ---------------------------------------------------------------------------
# Cloudflare — Wave F6
# All CF variables default to "" / [] / false so `terraform validate` passes
# with nothing set (count-guards on CF resources make them zero-count).
# Populate via TF_VAR_* or a non-committed terraform.tfvars before applying.
# ---------------------------------------------------------------------------

variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare zone ID for perkinsroofing.net. Found in the Cloudflare dashboard → Overview → right sidebar. Empty = CF resources not provisioned (count-guarded)."
  default     = ""
  sensitive   = false
}

variable "cloudflare_api_token" {
  type        = string
  description = "Cloudflare API token with Zone:Edit + DNS:Edit + Firewall:Edit scopes for perkinsroofing.net. Stored in Secret Manager (cloudflare-api-token); injected via TF_VAR_cloudflare_api_token at plan/apply time. Never commit to git."
  # Format-valid placeholder (NOT a real token): the cloudflare provider validates the
  # api_token charset eagerly and errors on an empty string, which blocked `terraform plan`
  # (and the R4 drift check) even though every CF resource is count-guarded off until
  # cloudflare_zone_id is set. The placeholder satisfies provider config while CF is disabled;
  # the real token overrides via TF_VAR_cloudflare_api_token when CF is activated.
  default   = "placeholder_unused_until_cloudflare_zone_id_is_set_0000"
  sensitive = true
}

variable "cloudflare_rate_limiting_enabled" {
  type        = bool
  description = "Provision the waf_rate_limits ruleset. Requires a PAID Cloudflare plan — the Free plan caps rate-limit rules at period=10s and 1 rule, so the IaC (period=60 × 3 rules) hard-fails on apply. Default false so drift_check is clean on Free; flip to true once the plan is upgraded (pending Jon's pay determination)."
  default     = false
}

variable "cloudflare_origin_routing_enabled" {
  type        = bool
  description = "Provision the origin_routing ruleset (CF zone → Cloud Run origin rewrite). Off by default: the app reaches the API via the direct run.app URL today, so this is unused, and creating it changes live routing on the zone. Enable + confirm-then-apply only when routing perkinsroofing.net through CF to the origin."
  default     = false
}

variable "cloudflare_ipv4_ranges" {
  type        = list(string)
  description = "Cloudflare IPv4 CIDR ranges for the Cloud Armor origin allowlist. Source: https://www.cloudflare.com/ips-v4 — update when CF publishes changes. Used only when cloud_armor_enabled = true."
  default = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
  ]
}

variable "cloudflare_ipv6_ranges" {
  type        = list(string)
  description = "Cloudflare IPv6 CIDR ranges for the Cloud Armor origin allowlist. Source: https://www.cloudflare.com/ips-v6 — update when CF publishes changes. Used only when cloud_armor_enabled = true."
  default = [
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
  ]
}

variable "cloud_armor_enabled" {
  type        = bool
  description = "Enable the Cloud Armor CF-IP allowlist security policy. Requires a GFE Load Balancer in front of Cloud Run (post-F6 hardening task). Keep false until the LB is provisioned."
  default     = false
}

variable "google_dkim_key" {
  type        = string
  description = "Google Workspace DKIM TXT value (v=DKIM1; k=rsa; p=...) from Admin console -> Gmail -> Authenticate email. Empty = google._domainkey record not created (count-guarded)."
  default     = ""
  sensitive   = false
}
