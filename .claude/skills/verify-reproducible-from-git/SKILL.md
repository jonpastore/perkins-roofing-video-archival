---
name: verify-reproducible-from-git
description: Check that a change can be reproduced from a fresh clone — no config, state, credential, or runtime dependency that exists only on one machine. Run before any commit that touches infra/, scripts/deploy.sh, CI, the Dockerfile, app/requirements.txt, or that schedules a job which was previously only ever run by hand.
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

## The image is part of "from git" too

The four above are all deploy INPUTS — config, state, credentials. On 2026-07-28 the same shape
appeared twice more in a place this skill did not look: **runtime dependencies inside the
container image**. Both worked on a laptop and nowhere else, and both surfaced only when a job
that had always been run by hand was finally scheduled.

| what | consequence |
|---|---|
| `yt-dlp` absent from `app/requirements.txt` | `adapters/yt_dlp.py` runs `python -m yt_dlp`; every caller dies with ModuleNotFoundError in-image. Latent in render/archive for months because both import it lazily INSIDE a function |
| `deno` absent from the `Dockerfile` | yt-dlp needs a JS runtime for YouTube's n-challenge (`--remote-components ejs:github`). Without it 15/15 downloads exited 1 — while the job still reported success |

```bash
# 5. Every external binary the code shells out to must be installed in the image.
grep -rhoE '"[a-z0-9_-]{3,}"' --include='*.py' adapters/ | sort -u > /tmp/argv0
grep -nE 'apt-get install|^COPY --from=' Dockerfile
#    Cross-check anything invoked via subprocess against those lines. `which X` on your box
#    proves nothing — that is the whole failure mode.

# 6. Every `python -m X` must be a package in app/requirements.txt (the Dockerfile installs
#    that file and nothing else).
grep -rhoE '"-m", "([a-z0-9_]+)"|-m [a-z0-9_]+' --include='*.py' adapters/ jobs/ | sort -u
grep -c . app/requirements.txt
```

The cheap definitive test is a probe image — it takes seconds and does not need the real build:

```dockerfile
FROM python:3.12-slim
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
RUN deno --version          # fails the build if the COPY path or tag is wrong
```

**Corollary: a job that catches per-item errors must not exit 0 when EVERY item failed.**
`archive_job` reported `{'archived': 0, 'errored': 15}` and `exit(0)`, so Cloud Run showed green
and would have every night. If the code swallows failures per item, escalate on total failure.

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
