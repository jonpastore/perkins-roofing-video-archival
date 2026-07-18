#!/usr/bin/env bash
# Per-wave drift check (rule R4): infrastructure + host config must match git.
# Exit 0 = no drift. Non-zero = drift detected (someone deployed out-of-band, or a wave's
# apply hasn't been run). Fix drift by codifying reality in git and re-applying — never by hand.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

echo "== Terraform (GCP) drift =="
# The cloudflare provider needs a real token to read the zone; without it terraform falls back
# to the format-valid placeholder (variables.tf) and `plan` ERRORs on the zone data source —
# which used to mask ALL terraform drift as a creds error. Inject it from Secret Manager.
if [ -z "${TF_VAR_cloudflare_api_token:-}" ]; then
  export TF_VAR_cloudflare_api_token="$(gcloud secrets versions access latest --secret=cloudflare-api-token 2>/dev/null || true)"
fi
if ( cd "$ROOT/infra" && terraform init -input=false >/dev/null 2>&1 ); then
  ( cd "$ROOT/infra" && terraform plan -input=false -detailed-exitcode >/dev/null 2>&1 )
  case $? in
    0) echo "  terraform: no drift (plan clean)";;
    2) echo "  terraform: DRIFT — plan shows changes (run 'terraform apply' or reconcile)"; fail=1;;
    *) echo "  terraform: plan ERROR (check creds/ADC)"; fail=1;;
  esac
else
  echo "  terraform: init failed"; fail=1
fi

echo "== Ansible (cerberus host) drift =="
if ( cd "$ROOT/ansible" && "$ROOT/.venv/bin/ansible-playbook" whisper.yml --check 2>/dev/null | grep -q 'changed=0' ); then
  echo "  ansible: no drift (--check changed=0)"
else
  echo "  ansible: DRIFT or unreachable — run 'ansible-playbook whisper.yml'"; fail=1
fi

[ "$fail" -eq 0 ] && echo "DRIFT CHECK: clean" || echo "DRIFT CHECK: DRIFT DETECTED"
exit "$fail"
