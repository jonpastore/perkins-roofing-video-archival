---
name: verify-reproducible-from-git
description: Check that a change can be reproduced from a fresh clone — no config, state, or credential that exists only on one machine. Run before any commit that touches infra/, scripts/deploy.sh, or CI.
allowed-tools: [Read, Grep, Bash]
---

R3 says git is the source of truth. On 2026-07-28 that turned out to be false in four separate
places, and each one was found the expensive way — by a failed deploy, or by a plan that proposed
deleting production DNS. Every instance had the same shape:

> Something the deploy needs lives ONLY on one laptop, so it works there and nowhere else.

This skill is that check, run before the commit instead of after.

## The four that actually happened

| what | consequence if not caught |
|---|---|
| `.env` held `WP_URL`, `WP_USER`, `OAUTH_CLIENT_ID` | CI deploy sets them to `""` — these go into `--set-env-vars`, which OVERWRITES prod config with empty strings |
| `terraform.tfvars` held `cloudflare_zone_id` | every Cloudflare resource is count-guarded on it, so a plan elsewhere proposed **destroying all 15** — DNS, MX, SPF, DKIM, DMARC, WAF |
| terraform state was a local file | CI planned to **create all 146 resources** on top of the live ones; losing the laptop loses the map to every resource |
| `SQUARES_API_KEY` was a plain env var from `.env` | shipped blank from any other machine |

## Run these

```bash
# 1. What does deploy.sh read that a fresh clone would not have?
grep -oE '\$\{[A-Z_]+[:-]*[^}]*\}' scripts/deploy.sh | grep -oE '[A-Z_]{3,}' | sort -u
#    Every name here must be in infra/deploy.config.env (non-secret) or --set-secrets (secret).
#    A `${VAR:-}` default is NOT safety: empty overwrites prod.

# 2. Does terraform depend on an untracked file?
git status --ignored --porcelain infra/ | grep '^!!' | grep -E '\.tfvars$|\.auto\.tfvars$|\.env$'
#    Non-secret inputs belong in infra/perkins.auto.tfvars (committed).
#    Secrets belong in Secret Manager, injected as TF_VAR_* at plan time.

# 3. Is state remote?
grep -A 3 'backend "gcs"' infra/backend.tf   # must exist; a local terraform.tfstate is a red flag

# 4. THE REAL TEST — plan as the CI identity, not as yourself.
bash scripts/plan_as_ci.sh      # impersonates ci-deployer; expects "plan exit code: 0"
```

Step 4 is the one that matters. A plan that is clean as an owner and dirty as `ci-deployer`
means the config depends on your personal access. Each missing permission used to cost a full
push→CI→deploy cycle (~10 min); impersonation finds them all locally in one pass.

## When a plan proposes DESTROY, stop

Never "just apply". A count-guarded resource plans as destroy the moment its guard variable goes
missing, and the guard variable going missing is exactly the failure this skill looks for. Find
the missing input first.

## Deliberate deviations from generic advice

Standard guidance says gitignore `*.tfvars` and `*.auto.tfvars`. We commit
`infra/perkins.auto.tfvars` **on purpose** — it holds only the zone id and the PUBLIC DKIM value
(already published in DNS; terraform declares both `sensitive = false`). The rule exists to keep
secrets out of git, and the Cloudflare API token still lives in Secret Manager. Keeping the
non-secrets out cost us a plan that would have deleted their email routing.
