# NON-SECRET terraform inputs, COMMITTED so a plan is reproducible from git alone (R3).
#
# These lived only in infra/terraform.tfvars, which is gitignored. Terraform auto-loads that file
# locally, so plans looked clean on one laptop — but anywhere else cloudflare_zone_id defaulted to
# "" and every CF resource is count-guarded on it. The CI plan therefore proposed
# DESTROYING ALL 15 CLOUDFLARE RESOURCES: every DNS record, MX, SPF, DKIM, DMARC and the WAF
# ruleset for perkinsroofing.net. An apply without that file would have taken out their email.
#
# Neither value is a secret, and terraform declares both sensitive = false:
#   - the zone id is an identifier that appears in Cloudflare API URLs
#   - the DKIM value is the PUBLIC key, already published at google._domainkey.perkinsroofing.net
# The Cloudflare API TOKEN is NOT here — it stays in Secret Manager, injected as
# TF_VAR_cloudflare_api_token at plan/apply time.
#
# *.auto.tfvars is loaded automatically, so this needs no -var-file flag.

cloudflare_zone_id = "730729a1b3ac1d718727a0fccc07933b"
google_dkim_key    = "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAlN0ipWhTgUUhnM5i/G9DGKPT4FzyPSdDrXIXUf3ZTp/MMem6k61rFXCmwyjDSbwuZmymI7vBloGz1F/4m0n3GK7vWkV/Bi62vEpcDMXIGw8KD+x6s3bRba517f9bzwAJ8tSyX5kSxBW4ecEWjw0pZWSs6ja/MlwDBxIirY7kVpE6VHQOhweooEJ5LEQTiwsBrgDkIhmakh3wY7XAj0Ul8G9rnHnHFyL73L27ip2R/IKcPbpWUDj+LrcUPYe5ljbLJdETjvFVi0eetJq9ivqPDMZNQwPXqnaNNqf+aiQfg88/Wtb8EnLxl1eioBysM5QZt2yCpC+dxEn+vElpwzDGeQIDAQAB"
