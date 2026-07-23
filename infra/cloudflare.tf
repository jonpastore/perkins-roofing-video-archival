# ---------------------------------------------------------------------------
# Cloudflare edge — Wave F6
#
# Manages: zone config, DNS records, TLS mode, WAF rate-limit ruleset,
#          Cloud Run domain mapping, Cloud Armor CF-IP allowlist (gated),
#          and the Secret Manager container for the Cloudflare API token.
#
# COUNT-GUARD PATTERN: every Cloudflare resource uses
#   count = var.cloudflare_zone_id != "" ? 1 : 0
# This lets `terraform validate` pass with no credentials set. Resources
# become active only after Jon populates cloudflare_zone_id (and
# cloudflare_api_token is injected via TF_VAR_cloudflare_api_token or
# the Secret Manager data source in scripts/deploy.sh).
#
# EXIT GATE (F3 hard dependency):
#   The proposal accept-page rate-limit rule (/p/*/accept) is a hard
#   requirement from TRD-F3 §3.5. The F3 accept pages MUST NOT go live in
#   production until this ruleset is applied and verified. See §11 of TRD-F6.
#
# APPLY ORDER (Jon executes DNS steps; Terraform handles the rest):
#   See CLOUDFLARE_RUNBOOK.md in this directory for the full sequenced runbook.
# ---------------------------------------------------------------------------

# Cloudflare provider is declared in main.tf's required_providers block.
# See the required_providers diff note at the bottom of this file.

provider "cloudflare" {
  # Token injected at plan/apply time via TF_VAR_cloudflare_api_token or
  # scripts/deploy.sh reading from Secret Manager. Never committed to git.
  api_token = var.cloudflare_api_token
}

# ---------------------------------------------------------------------------
# 1. Zone data source
#    The zone already exists in Cloudflare (created when Jon adds the domain).
#    We reference it by ID rather than importing the zone object itself, to
#    avoid Terraform trying to manage zone creation.
# ---------------------------------------------------------------------------

data "cloudflare_zone" "perkinsroofing" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
}

# ---------------------------------------------------------------------------
# 2. DNS records
#
# IMPORT SEQUENCE (§2.1 — must be done before NS cutover):
#
#   Step A — scan existing records via the Cloudflare API to get record IDs:
#     curl -s "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records" \
#          -H "Authorization: Bearer ${CF_TOKEN}" | jq '.result[] | {id,type,name,content}'
#
#   Step B — import each record into Terraform state using its ID:
#     terraform import cloudflare_record.mx_primary    "<zone_id>/<record_id>"
#     terraform import cloudflare_record.mx_alt1       "<zone_id>/<record_id>"
#     terraform import cloudflare_record.mx_alt2       "<zone_id>/<record_id>"
#     terraform import cloudflare_record.mx_alt3       "<zone_id>/<record_id>"
#     terraform import cloudflare_record.mx_alt4       "<zone_id>/<record_id>"
#     terraform import cloudflare_record.txt_spf       "<zone_id>/<record_id>"
#     terraform import cloudflare_record.txt_dkim      "<zone_id>/<record_id>"
#     # ...add an import line per record discovered in Step A
#
#   Step C — verify completeness before NS change:
#     dig MX perkinsroofing.net @<cloudflare-assigned-ns1>
#     dig TXT perkinsroofing.net @<cloudflare-assigned-ns1>   # check SPF
#     dig TXT google._domainkey.perkinsroofing.net @<cloudflare-assigned-ns1>
#
#   DO NOT enable proxy (proxied = true) on MX/SPF/DKIM records or on any
#   record for infrastructure not under our control. Only app.perkinsroofing.net
#   gets the orange cloud.
#
# The resource blocks below are scaffolds. Fill in actual values from Step A
# before running `terraform import`. The record IDs are UUIDs from the CF API.
# ---------------------------------------------------------------------------

# Google Workspace MX records — DNS-only (proxied = false), import before NS change
resource "cloudflare_dns_record" "mx_primary" {
  count    = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id  = var.cloudflare_zone_id
  name     = "perkinsroofing.net"
  type     = "MX"
  content  = "aspmx.l.google.com"
  ttl      = 3600
  proxied  = false
  priority = 1
}

resource "cloudflare_dns_record" "mx_alt1" {
  count    = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id  = var.cloudflare_zone_id
  name     = "perkinsroofing.net"
  type     = "MX"
  content  = "alt1.aspmx.l.google.com"
  ttl      = 3600
  proxied  = false
  priority = 5
}

resource "cloudflare_dns_record" "mx_alt2" {
  count    = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id  = var.cloudflare_zone_id
  name     = "perkinsroofing.net"
  type     = "MX"
  content  = "alt2.aspmx.l.google.com"
  ttl      = 3600
  proxied  = false
  priority = 5
}

resource "cloudflare_dns_record" "mx_alt3" {
  count    = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id  = var.cloudflare_zone_id
  name     = "perkinsroofing.net"
  type     = "MX"
  content  = "alt3.aspmx.l.google.com"
  ttl      = 3600
  proxied  = false
  priority = 10
}

resource "cloudflare_dns_record" "mx_alt4" {
  count    = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id  = var.cloudflare_zone_id
  name     = "perkinsroofing.net"
  type     = "MX"
  content  = "alt4.aspmx.l.google.com"
  ttl      = 3600
  proxied  = false
  priority = 10
}

# SPF — DNS-only; update value to match the real record from Step A
resource "cloudflare_dns_record" "txt_spf" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "perkinsroofing.net"
  type    = "TXT"
  # Matches the live record (imported 2026-07-10). servers.mcsv.net = Mailchimp
  # (active: k2/k3 DKIM CNAMEs exist).
  #
  # secureserver.net = GoDaddy. KEEP IT. 2026-07-14: the "old site contact form?"
  # guess is real — perkinsroofing.net / www still resolve to 160.153.0.31, which
  # is GoDaddy shared hosting. Only `app` is ours. Dropping this include risks
  # silently breaking mail the marketing site sends.
  # 14 DMARC aggregate reports (199 msgs, Jul 10-14) show ZERO GoDaddy-range
  # senders — but that is 4 days of a low-volume domain, not proof: a contact
  # form can trivially send nothing for 4 days. Remove only after the site is off
  # GoDaddy, or after a long report window plus a direct check of the form.
  content = "v=spf1 include:_spf.google.com include:servers.mcsv.net include:secureserver.net ~all"
  ttl     = 3600
  proxied = false
}

# Google Workspace DKIM — GATED until the key exists. Google's DKIM key must be
# GENERATED in the Admin console (Apps -> Google Workspace -> Gmail -> Authenticate
# email -> Generate new record, 2048-bit) and "Start authentication" clicked; then
# set var.google_dkim_key to the full TXT value ("v=DKIM1; k=rsa; p=...") and apply.
resource "cloudflare_dns_record" "txt_dkim" {
  count   = var.cloudflare_zone_id != "" && var.google_dkim_key != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "google._domainkey.perkinsroofing.net"
  type    = "TXT"
  content = var.google_dkim_key
  ttl     = 3600
  proxied = false
}

# DMARC — p=reject since 2026-07-17 (was p=quarantine 2026-07-10..17). Evidence
# for the flip (28 aggregate reports, 528 msgs, Jul 10-16): 515 aligned-pass /
# 13 fail = 97.5%, and ALL 13 failures were dkim=fail+spf=fail spoofing from
# bare VPS/cloud IPs (202.95.15.94 x8, AWS, GCP, Orange) — zero legit senders
# failing. rua reports to dmarc@perkinsroofing.net
# (create the group in Google Admin if it doesn't exist yet).
#
# ruf (forensic) + rua (aggregate) REMOVED 2026-07-23 (Jon: stop the dmarc
# notices; only actionable email). p=reject is live and healthy, so the daily
# aggregate digests are diagnostics nobody reads — receivers stop sending them
# when the rua tag is gone. Enforcement (p=reject) is unaffected: the policy
# works with zero reporting. If a legit-mail delivery problem ever needs
# investigating, re-add `rua=mailto:dmarc@perkinsroofing.net; ` temporarily —
# reports resume within ~a day.
resource "cloudflare_dns_record" "txt_dmarc" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "_dmarc.perkinsroofing.net"
  type    = "TXT"
  content = "v=DMARC1; p=reject; adkim=r; aspf=r"
  ttl     = 3600
  proxied = false
}

# TLS-RPT — receivers report inbound SMTP TLS negotiation failures to dmarc@.
# Reporting only: no enforcement, so this cannot affect mail delivery. Stands
# alone (does not require MTA-STS); it is the visibility half of the pair.
# MTA-STS itself is NOT provisioned — see the MTA-STS note below.
# TLS-RPT record REMOVED 2026-07-23 (Jon: only actionable email) — same
# diagnostics-nobody-reads class as the DMARC rua reports; without MTA-STS
# enforce mode it informed nothing. Re-add alongside MTA-STS if that ships.

# ---------------------------------------------------------------------------
# MTA-STS — DEFERRED, blocked on two things only Jon can provision:
#
#   1. var.cloudflare_account_id — not declared anywhere yet (the zone is
#      referenced by zone_id; Workers are an ACCOUNT-scoped resource).
#   2. An API token carrying Account -> Workers Scripts:Edit. The current token
#      (see var.cloudflare_api_token) is Zone:Edit + DNS:Edit + Firewall:Edit,
#      which cannot deploy a Worker.
#
# Why a Worker at all: RFC 8461 §3.3 requires the policy be fetched from
# https://mta-sts.perkinsroofing.net/.well-known/mta-sts.txt over valid TLS and
# forbids following 3xx redirects — so a CF Redirect Rule cannot serve it. The
# origin site is GoDaddy shared hosting (160.153.0.31) and is not ours to use.
#
# Worth questioning before building it: in `mode: testing` MTA-STS enforces
# nothing and only produces reports — which txt_tlsrpt above already delivers.
# The payoff arrives at `mode: enforce`, which is also where misconfiguration
# starts bouncing inbound mail. Decide deliberately; don't build it by reflex.
# ---------------------------------------------------------------------------

# app.perkinsroofing.net — proxied (orange cloud); points to Firebase Hosting.
# CF Transform Rule (§ below) splits /api/* traffic to Cloud Run at the edge.
# Enable proxy only AFTER NS propagation is confirmed and Firebase cert is
# provisioned (see CLOUDFLARE_RUNBOOK.md step 6).
resource "cloudflare_dns_record" "app_cname" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "app.perkinsroofing.net"
  type    = "CNAME"
  # Firebase Hosting custom domain (registered via the Hosting API 2026-07-10;
  # Firebase's requiredDnsUpdates asks for exactly this CNAME — ownership +
  # cert provisioning ride on it). proxied MUST stay false until the Firebase
  # cert is ACTIVE, and stays false until the H1 edge wave flips it together
  # with the transform/WAF rules (CLOUDFLARE_RUNBOOK.md step 6).
  content = "${var.project_id}.web.app"
  proxied = false
  ttl     = 3600
}

# ---------------------------------------------------------------------------
# 3. TLS — Full (strict)
#    Requires a valid cert at origin. Firebase Hosting and Cloud Run both
#    provision managed certs automatically for custom domain mappings.
# ---------------------------------------------------------------------------

# v5: zone_settings_override is gone — each setting is its own cloudflare_zone_setting resource.
# This also fixes the v4 perpetual-diff (the monolithic settings block re-diffed true_client_ip_header
# every plan). SSL=strict + always_use_https + min_tls_version were previously applied via the CF API.
resource "cloudflare_zone_setting" "ssl" {
  count      = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id    = var.cloudflare_zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "always_use_https" {
  count      = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "min_tls_version" {
  count      = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = "1.2"
}

# ---------------------------------------------------------------------------
# 4. Origin routing — Transform Rules (§2.2)
#
#    Both targets share the single app.perkinsroofing.net CNAME. The CF
#    Transform Rule rewrites the Host header so the origin knows which
#    backend to use:
#      /api/* → Cloud Run API URI (api.run.app host)
#      /*     → Firebase Hosting (default; CNAME already points there)
#
#    NOTE: Cloud Run domain mappings map the entire subdomain, not a path
#    prefix (see TRD-F6 §14 unresolved Q4). The /api/* split MUST happen
#    here at the CF edge via a Transform Rule rewriting the Host header to
#    the Cloud Run *.run.app URI, not via a Cloud Run domain mapping.
#    The google_cloud_run_domain_mapping resource below is still created so
#    Cloud Run provisions a managed cert for the domain; CF routes to the
#    *.run.app origin URL directly in the Transform Rule.
# ---------------------------------------------------------------------------

resource "cloudflare_ruleset" "origin_routing" {
  # Off by default (var default false): unused today (app hits run.app directly) and creating it
  # changes live zone routing. Enable + confirm-then-apply only when routing CF -> Cloud Run origin.
  count   = var.cloudflare_zone_id != "" && var.cloudflare_origin_routing_enabled ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "perkins-origin-routing"
  kind    = "zone"
  phase   = "http_request_transform"

  rules = [{
    description = "Route /api/* to Cloud Run API origin"
    expression  = "(http.host eq \"app.perkinsroofing.net\" and starts_with(http.request.uri.path, \"/api/\"))"
    action      = "rewrite"
    action_parameters = {
      headers = {
        "Host" = {
          operation = "set"
          value     = replace(google_cloud_run_v2_service.api.uri, "https://", "")
        }
      }
    }
    enabled = true
  }]
}

# ---------------------------------------------------------------------------
# 5. WAF rate-limit ruleset (§2.4)
#
#    Three rules (ordered by priority — most specific first):
#      a. Auth endpoints      — 20 req/min/IP, block 10 min
#      b. Proposal accept     — 10 req/min/IP, block 5 min  ← F3 hard dep
#      c. API general         — 300 req/min/IP, block 2 min
#
#    EXIT GATE: rule (b) must be active and verified before the F3 accept
#    pages go live in production. See TRD-F6 §11 and TRD-F3 §3.5.
# ---------------------------------------------------------------------------

resource "cloudflare_ruleset" "waf_rate_limits" {
  # Off by default (var default false): requires a PAID plan. Free plan caps rate-limit rules at
  # period=10s and 1 rule, so this (period=60 × 3) hard-fails on apply. Flip the var true after
  # the plan upgrade (pending Jon's pay determination).
  count   = var.cloudflare_zone_id != "" && var.cloudflare_rate_limiting_enabled ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "perkins-rate-limits"
  kind    = "zone"
  phase   = "http_ratelimit"

  # Rule order within a phase ruleset follows the order of rules[] entries. Most-specific first.
  rules = [
    {
      description = "Auth endpoint rate limit"
      expression  = "(http.request.uri.path contains \"/api/auth\" or http.request.uri.path contains \"/__/auth\")"
      action      = "block"
      ratelimit = {
        characteristics     = ["ip.src"]
        period              = 60
        requests_per_period = 20
        mitigation_timeout  = 600
      }
      enabled = true
    },
    {
      # F3 EXIT GATE — proposal accept-page brute-force protection (e-sign).
      # This rule is a hard requirement from TRD-F3 §3.5 (deferred to F6).
      # Do NOT remove or disable this rule without a corresponding F3 re-review.
      description = "Proposal accept page rate limit (e-sign)"
      expression  = "http.request.uri.path contains \"/accept\""
      action      = "block"
      ratelimit = {
        characteristics     = ["ip.src"]
        period              = 60
        requests_per_period = 10
        mitigation_timeout  = 300
      }
      enabled = true
    },
    {
      description = "API general rate limit"
      expression  = "http.request.uri.path contains \"/api/\""
      action      = "block"
      ratelimit = {
        characteristics     = ["ip.src"]
        period              = 60
        requests_per_period = 300
        mitigation_timeout  = 120
      }
      enabled = true
    },
  ]
}

# WAF custom rule: block /internal/* at the edge for all non-platform_admin
# sessions. Defense-in-depth — FastAPI also enforces platform_admin role on
# every /internal route. Both layers are required (TRD-F6 §3.4).
resource "cloudflare_ruleset" "waf_block_internal" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = "perkins-block-internal-routes"
  kind    = "zone"
  phase   = "http_request_firewall_custom"

  rules = [{
    description = "Block /internal/* routes at edge (defense-in-depth; FastAPI also enforces platform_admin)"
    # Blocks all unauthenticated access to /internal paths at the CF edge.
    # Authenticated platform_admin requests carry a session cookie that CF passes
    # through; the FastAPI layer is the authoritative enforcement point.
    expression = "starts_with(http.request.uri.path, \"/internal/\")"
    action     = "block"
    enabled    = true
  }]
}

# ---------------------------------------------------------------------------
# 6. Cloud Run domain mapping (§2.2 / §7.4)
#
#    Maps app.perkinsroofing.net to the API Cloud Run service so Cloud Run
#    provisions a managed TLS cert for the subdomain. CF routes /api/* traffic
#    to the *.run.app origin URI directly (Transform Rule above); this mapping
#    is what triggers cert provisioning.
#
#    Note: Cloud Run domain mappings are v1 resources; use google_cloud_run_domain_mapping
#    (not v2). Requires the Cloud Run API and the domain to be verified in GCP.
# ---------------------------------------------------------------------------

# REMOVED 2026-07-18 — vestigial, never-Ready, unroutable. app.perkinsroofing.net is served by
# Firebase Hosting (app_cname -> ${project}.web.app) and the SPA calls the API at the direct
# *.run.app URL (web/.env VITE_API_BASE), so nothing ever routed through this Cloud Run mapping.
# Cloud Run reported status Ready=False with two blockers: (1) "Caller is not authorized to
# administer the domain ... verify ownership via Webmaster Central" (a HUMAN Search Console step),
# and (2) "Certificate will not be provisioned unless the domain is made routable" — which it never
# can be, because the hostname points at Firebase by design. Verifying ownership would NOT make the
# mapping work; the resource was pure drift. Re-add ONLY if the CF-edge design is activated
# (app.perkinsroofing.net proxied through Cloudflare with a Transform Rule splitting /api/* to the
# Cloud Run origin — see cloudflare_ruleset.origin_routing, currently gated off).

# ---------------------------------------------------------------------------
# 7. Secret Manager container for Cloudflare API token (§7.6)
#
#    The secret container is Terraformed; the secret VALUE is added manually
#    by Jon via:
#      gcloud secrets versions add cloudflare-api-token --data-file=<(echo -n "$CF_TOKEN")
#    The value is never stored in Terraform state.
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "cloudflare_token" {
  secret_id = "cloudflare-api-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# 8. Cloud Armor CF-IP allowlist (§2.5) — GATED / COUNT-GUARDED
#
#    Restricts the Cloud Run origin to accept traffic only from Cloudflare
#    IP ranges. CURRENTLY INACTIVE because Cloud Armor requires a GFE Load
#    Balancer in front of Cloud Run (current topology: direct Cloud Run, no LB).
#
#    To activate post-F6 when an LB is added:
#      1. Set var.cloud_armor_enabled = true in terraform.tfvars
#      2. Attach the security policy to the backend service:
#           google_compute_backend_service.api.security_policy = google_compute_security_policy.cf_allowlist[0].id
#      3. `terraform apply`
#      4. Verify Cloud Run only receives traffic from CF IP ranges
#
#    Cloudflare IPv4 ranges: https://www.cloudflare.com/ips-v4
#    Cloudflare IPv6 ranges: https://www.cloudflare.com/ips-v6
#    Update cadence: CF IP ranges change rarely; pin to a known-good list.
#    When CF publishes a change, update var.cloudflare_ipv4_ranges and apply.
# ---------------------------------------------------------------------------

resource "google_compute_security_policy" "cf_allowlist" {
  # Gated: inactive until a GFE LB fronts Cloud Run (post-F6 hardening task).
  count = var.cloud_armor_enabled ? 1 : 0

  name        = "cloudflare-origin-allowlist"
  description = "Allow only Cloudflare IP ranges to reach the Cloud Run origin (post-F6 hardening, requires LB)"

  dynamic "rule" {
    for_each = { for idx, cidr in var.cloudflare_ipv4_ranges : idx => cidr }
    content {
      action   = "allow"
      priority = 1000 + rule.key
      match {
        versioned_expr = "SRC_IPS_V1"
        config {
          src_ip_ranges = [rule.value]
        }
      }
      description = "Allow Cloudflare IPv4 range: ${rule.value}"
    }
  }

  dynamic "rule" {
    for_each = { for idx, cidr in var.cloudflare_ipv6_ranges : idx => cidr }
    content {
      action   = "allow"
      priority = 2000 + rule.key
      match {
        versioned_expr = "SRC_IPS_V1"
        config {
          src_ip_ranges = [rule.value]
        }
      }
      description = "Allow Cloudflare IPv6 range: ${rule.value}"
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 2147483647
    description = "Default deny — block all non-Cloudflare traffic"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "cloudflare_zone_id" {
  description = "Cloudflare zone ID for perkinsroofing.net (echo-back for scripts)"
  value       = var.cloudflare_zone_id != "" ? var.cloudflare_zone_id : "(not configured)"
}
