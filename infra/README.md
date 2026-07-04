# infra/ — Perkins Roofing v2 Platform Terraform

Provisions the full v2 platform in the client's GCP project (`video-archival-and-content-gen`).
All AI spend, data, and secrets live in Tim's GCP — no DeGenito-owned keys in the prod path.

## Prerequisites before applying

| # | Prereq | Status |
|---|--------|--------|
| P1 | GCP billing confirmed on `video-archival-and-content-gen` | Needed before `apply` |
| P2 | Meta + TikTok app registration complete | Needed for social secrets |
| P3 | All credentials collected → ready to load into Secret Manager | Needed for `bootstrap.sh` step 7 |
| P4 | Resend account + DNS verified | Needed for email secrets |

## Files

| File | Purpose |
|------|---------|
| `main.tf` | All GCP resources (APIs, SAs, IAM, SQL, GCS, Cloud Run, Scheduler, Secrets, Budget) |
| `variables.tf` | Input variables with defaults |
| `outputs.tf` | Key resource identifiers after apply |
| `bootstrap.sh` | One-time post-billing runbook (init → plan → apply → pgvector → secrets) |

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `project_id` | `video-archival-and-content-gen` | GCP project ID |
| `region` | `us-central1` | GCP region |
| `billing_account` | `""` | Billing account ID (format `XXXXXX-XXXXXX-XXXXXX`). Leave empty to skip budget alert. |
| `budget_amount` | `200` | Monthly spend cap in USD |
| `alert_email` | `""` | Email for budget notifications |

## Resources provisioned

### APIs enabled (idempotent)
`aiplatform`, `speech`, `sqladmin`, `run`, `secretmanager`, `cloudscheduler`, `storage`, `iam`

### Service accounts + IAM
| SA | Roles |
|----|-------|
| `api-run-sa` | `aiplatform.user`, `cloudsql.client`, `secretmanager.secretAccessor`, `storage.objectViewer` |
| `jobs-sa` | `aiplatform.user`, `speech.client`*, `cloudsql.client`, `storage.objectAdmin`, `secretmanager.secretAccessor` |
| `scheduler-sa` | `run.invoker` |

*`roles/speech.client` — if unavailable in a future provider version, replace with `roles/serviceusage.serviceUsageConsumer` and grant speech access via a custom role.

### Cloud SQL
- Postgres 16, `db-custom-1-3840` (1 vCPU / 3.75 GB), private IP only
- Database: `perkins`
- **pgvector** is enabled post-provision — NOT a Cloud SQL flag. Run in psql:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
  Then apply the HNSW index migration (`migrations/versions/0001_embedding_3072.sql`).

### GCS buckets
| Bucket | Access | Purpose |
|--------|--------|---------|
| `video-archival-and-content-gen-media` | Private | Raw video, audio, ffmpeg artifacts |
| `video-archival-and-content-gen-reels` | **Public-read** | Rendered 9:16 reels for IG/TikTok public URLs |

### Cloud Run
- **Service `api`**: placeholder image `gcr.io/cloudrun/hello` — replace at Wave 1 deploy
- **Jobs** `ingest`, `render`, `article`, `social`: placeholder image — replace at Wave 1 deploy

### Cloud Scheduler
- `promote-scheduled-content`: fires every 15 minutes (`*/15 * * * *`), POSTs to `api/internal/promote` via OIDC

### Secret Manager (containers only — no versions created by Terraform)
`youtube-api-key`, `serper-api-key`, `resend-api-key`, `wordpress-app-password`,
`meta-app-secret`, `meta-system-user-token`, `tiktok-client-secret`, `tiktok-refresh-token`

Populate values via `bootstrap.sh` step 7.

### Billing budget alert
Declared with `count = var.billing_account != "" ? 1 : 0`. Set `billing_account` to activate.
Thresholds at 50% / 90% / 100% of `budget_amount` (default $200/month).

## Usage

```bash
# Offline validation (no GCP credentials needed)
cd infra/
terraform init -backend=false
terraform validate

# Full provision (after P1 billing confirmed)
cp .env.template .env   # fill in real secret values
./bootstrap.sh
```

## After apply — manual steps

1. Enable pgvector: `gcloud sql connect video-archival-and-content-gen-pg --user=postgres --database=perkins` → `CREATE EXTENSION IF NOT EXISTS vector;`
2. Apply `migrations/versions/0001_embedding_3072.sql` (3072-dim HNSW index).
3. Build and push real API + jobs container images; update Cloud Run service/jobs.
4. Configure Firebase Auth project + custom claims (`admin` / `sales`).
5. Set `billing_account` variable and re-apply to activate the budget alert.
