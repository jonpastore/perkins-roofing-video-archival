# Cloudflare Onboarding Runbook — perkinsroofing.net (Wave F6)

This is the sequenced apply runbook for Jon. Each step must be verified before proceeding to the next. Email must never break.

---

## Prerequisites (before any Terraform work)

- Cloudflare account created; `perkinsroofing.net` zone added (Cloudflare assigns a zone ID and two NS records)
- Cloudflare API token created with scopes: **Zone:Edit**, **DNS:Edit**, **Firewall:Edit** for `perkinsroofing.net`
- Firebase Hosting custom domain (`app.perkinsroofing.net`) added in the Firebase console → Hosting → Add custom domain (triggers TXT verification + managed cert provisioning); record the Firebase Hosting target URL (e.g. `video-archival-and-content-gen.web.app`)

---

## Step 1 — Add Cloudflare API token to Secret Manager

```bash
# Paste the token value when prompted
echo -n "$CF_TOKEN" | gcloud secrets versions add cloudflare-api-token \
  --project=video-archival-and-content-gen \
  --data-file=-
```

The Secret Manager container (`cloudflare-api-token`) is already created by Terraform. This step adds the secret value without putting it in Terraform state or git.

---

## Step 2 — Populate Terraform variables

Export before running any `terraform` command:

```bash
export TF_VAR_cloudflare_zone_id="<zone_id_from_cf_dashboard>"
export TF_VAR_cloudflare_api_token="<token_value>"
```

Or add to a non-committed `infra/terraform.tfvars` (already in `.gitignore`):

```hcl
cloudflare_zone_id   = "<zone_id>"
cloudflare_api_token = "<token_value>"
```

---

## Step 3 — Scan existing DNS records (CRITICAL — do before NS change)

```bash
CF_ZONE_ID="$TF_VAR_cloudflare_zone_id"
CF_TOKEN="$TF_VAR_cloudflare_api_token"

curl -s "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records?per_page=100" \
  -H "Authorization: Bearer ${CF_TOKEN}" \
  | jq '.result[] | {id,type,name,content,priority}'
```

For every record returned, add an import command below and update the corresponding `content =` placeholder in `cloudflare.tf` with the actual value.

---

## Step 4 — Import existing DNS records into Terraform state

Run one import per record discovered in Step 3. The format is `<zone_id>/<record_id>`.

```bash
# MX records (use actual record IDs from Step 3)
terraform import 'cloudflare_record.mx_primary[0]'  "${CF_ZONE_ID}/<mx_primary_record_id>"
terraform import 'cloudflare_record.mx_alt1[0]'     "${CF_ZONE_ID}/<mx_alt1_record_id>"
terraform import 'cloudflare_record.mx_alt2[0]'     "${CF_ZONE_ID}/<mx_alt2_record_id>"
terraform import 'cloudflare_record.mx_alt3[0]'     "${CF_ZONE_ID}/<mx_alt3_record_id>"
terraform import 'cloudflare_record.mx_alt4[0]'     "${CF_ZONE_ID}/<mx_alt4_record_id>"

# TXT records
terraform import 'cloudflare_record.txt_spf[0]'     "${CF_ZONE_ID}/<spf_record_id>"
terraform import 'cloudflare_record.txt_dkim[0]'    "${CF_ZONE_ID}/<dkim_record_id>"

# Add additional import lines for any other records found in Step 3
# (A records for existing website, Search Console TXT, etc.)
```

After all imports, run `terraform plan` and confirm the plan shows no destructive changes to MX/SPF/DKIM records. If any record shows a destroy+create, fix the `content =` value in `cloudflare.tf` to match what Cloudflare already holds before proceeding.

---

## Step 5 — Update Firebase Hosting CNAME target

Edit `infra/cloudflare.tf` line for `cloudflare_record.app_cname` if the Firebase Hosting target differs from `video-archival-and-content-gen.web.app`. Then run:

```bash
terraform apply -target='cloudflare_record.app_cname[0]' \
                -target='cloudflare_zone_settings_override.perkinsroofing[0]' \
                -target='cloudflare_ruleset.waf_rate_limits[0]' \
                -target='cloudflare_ruleset.waf_block_internal[0]' \
                -target='cloudflare_ruleset.origin_routing[0]'
```

This applies the non-DNS-record CF resources (TLS mode, WAF, routing rules, app CNAME) without touching the imported MX/SPF/DKIM records yet. Verify WAF rules are visible in the Cloudflare dashboard.

---

## Step 6 — Verify email is safe before NS cutover

Query the Cloudflare nameservers (NOT the current Tucows NS) to confirm all mail records are present:

```bash
# Get the Cloudflare NS pair from the dashboard (e.g. alice.ns.cloudflare.com)
CF_NS="alice.ns.cloudflare.com"

dig MX perkinsroofing.net @${CF_NS}
dig TXT perkinsroofing.net @${CF_NS}                          # SPF
dig TXT google._domainkey.perkinsroofing.net @${CF_NS}        # DKIM
```

All five MX records, SPF TXT, and DKIM TXT must resolve correctly before proceeding. Send a test email to a Gmail account and confirm delivery.

---

## Step 7 — NS cutover at Tucows (Jon + Amber action)

Change the nameservers for `perkinsroofing.net` at Tucows to the two Cloudflare NS records shown in the Cloudflare dashboard. This requires Amber's action.

- Propagation: up to 48 hours; typically 30 minutes for most resolvers
- Monitor with: `dig NS perkinsroofing.net` until Cloudflare NS appear
- After propagation: send another test email and confirm delivery

---

## Step 8 — Full terraform apply (after NS propagation confirmed)

```bash
cd infra
terraform apply
```

This applies all remaining resources including the Cloud Run domain mapping (which triggers Cloud Run cert provisioning for `app.perkinsroofing.net`).

---

## Step 9 — Add `app.perkinsroofing.net` to Firebase Auth authorized domains

The `extra_auth_domains` variable in `variables.tf` already includes `perkins.degenito.ai`. Add the new domain:

```hcl
# infra/variables.tf — update default
extra_auth_domains = ["perkins.degenito.ai", "app.perkinsroofing.net"]
```

Then `terraform apply` to update `google_identity_platform_config.auth`.

---

## Step 10 — Verify end-to-end

```bash
# SPA loads over HTTPS
curl -I https://app.perkinsroofing.net/

# API routes through CF to Cloud Run
curl -I https://app.perkinsroofing.net/api/health

# WAF blocks 21st auth request (test in staging — do not hammer prod)
# Rate limit rule: 20 req/60s per IP on /api/auth paths

# TLS grade
# Visit https://www.ssllabs.com/ssltest/analyze.html?d=app.perkinsroofing.net
```

---

## Post-F6 hardening (Cloud Armor — not active yet)

Cloud Armor (`google_compute_security_policy.cf_allowlist`) is count-guarded behind `var.cloud_armor_enabled = false`. It requires a GFE Load Balancer in front of Cloud Run, which is a separate future wave. To activate once the LB exists:

1. Set `cloud_armor_enabled = true` in `terraform.tfvars`
2. Attach the security policy to the backend service resource
3. `terraform apply`
4. Verify Cloud Run only receives traffic from Cloudflare IP ranges

The IP lists (`cloudflare_ipv4_ranges`, `cloudflare_ipv6_ranges`) in `variables.tf` are pinned to the known-good CF ranges as of 2026. Check [https://www.cloudflare.com/ips-v4](https://www.cloudflare.com/ips-v4) and [https://www.cloudflare.com/ips-v6](https://www.cloudflare.com/ips-v6) when updating.

---

## Rollback

| What | How | Time |
|---|---|---|
| WAF rules | `terraform apply` with `enabled = false` on affected rules | Instant |
| `app` CNAME | `terraform destroy -target='cloudflare_record.app_cname[0]'` | <5 min CF propagation |
| NS cutover | Revert Tucows to original NS; contact Amber | Up to 48 hrs propagation |
| Provisioning endpoint | Set `PROVISIONING_ENABLED=false` env var on Cloud Run revision | No code deploy needed |
