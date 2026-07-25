# Enabling the GCP spend panel (BigQuery billing export)

The Platform Status dashboard shows *"Enable BigQuery billing export and set BILLING_BQ_TABLE
(format: project.dataset.table)"* because `GET /admin/metrics/gcp-spend` returns
`{configured: false}` whenever `BILLING_BQ_TABLE` is unset (`api/routes/admin_metrics.py`).
Two things are needed: the export has to exist in BigQuery, and the API has to be told its table.

## What the API actually queries

```sql
SELECT service.description AS service_description, SUM(cost) AS cost, currency
FROM `<BILLING_BQ_TABLE>`
WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
GROUP BY service_description, currency
ORDER BY cost DESC
LIMIT 500
```

So the table must be a **standard usage cost export** (it needs `service.description`, `cost`,
`currency`, `usage_start_time`). The *detailed* export has those columns too and works; the
*pricing* export does NOT and will error.

## Step 1 — turn on the export (console only, ~2 min)

This cannot be done with `gcloud` — billing export is console-only, and it needs **Billing
Account Administrator** on the billing account, not just project access.

1. https://console.cloud.google.com/billing → pick the billing account paying for
   `video-archival-and-content-gen`
2. **Billing export** → **BigQuery export** tab → **Edit settings** under *Standard usage cost*
3. Project: `video-archival-and-content-gen`; Dataset: create one named `billing_export`
   (location **US** — must match where you query from)
4. Save.

⚠️ **Data starts flowing from the moment you enable it — the export is not backfilled.** The
panel stays empty for roughly a day, then fills forward. There is no way to get last month's
spend into it retroactively.

## Step 2 — find the table name

```bash
bq ls --project_id=video-archival-and-content-gen billing_export
```

It will be `gcp_billing_export_v1_<BILLING_ACCOUNT_ID>` with the dashes in the account id
replaced by underscores, e.g.
`video-archival-and-content-gen.billing_export.gcp_billing_export_v1_01ABCD_2EFGHI_3JKLMN`.

## Step 3 — grant the API's service account read access

The API runs as its attached Cloud Run service account. It needs to run BigQuery jobs and read
the dataset:

```bash
SA="$(gcloud run services describe api --region us-central1 \
      --format='value(spec.template.spec.serviceAccountName)')"

gcloud projects add-iam-policy-binding video-archival-and-content-gen \
  --member="serviceAccount:${SA}" --role=roles/bigquery.jobUser

bq add-iam-policy-binding \
  --member="serviceAccount:${SA}" --role=roles/bigquery.dataViewer \
  --dataset video-archival-and-content-gen:billing_export
```

`bigquery.jobUser` is on the *project* (queries are jobs); `dataViewer` is on the *dataset*.
Missing either shows up as `{configured: true, error: "..."}` in the panel rather than a blank
state, which is the quickest way to tell this step was skipped.

## Step 4 — set BILLING_BQ_TABLE and redeploy

It is a non-secret identifier, so it belongs in the deploy env alongside the other config vars —
not Secret Manager. Add it to `BASE_ENV` in `scripts/deploy.sh`:

```
BILLING_BQ_TABLE=video-archival-and-content-gen.billing_export.gcp_billing_export_v1_<ACCOUNT_ID>
```

then `bash scripts/deploy.sh`. Putting it in the script (not a one-off `gcloud run services
update`) is what keeps R3 true — git stays the source of truth and the next deploy will not
silently drop it.

## Step 5 — verify

```bash
TOKEN=...   # admin ID token, e.g. via scripts/prod_smoke.py's mint-and-exchange
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api-jnr6bsxyea-uc.a.run.app/admin/metrics/gcp-spend?days=30" | jq
```

- `{"configured": false, ...}` → env var not set, or the deploy did not pick it up
- `{"configured": true, "error": "..."}` → env var set but the query failed (IAM, wrong export
  type, or dataset in a different region)
- `{"configured": true, "window_days": 30, ...}` with service rows → done; the dashboard panel
  will render the same data

## One caveat about what the number means

The export bills by **usage_start_time**, so the panel is a usage-window figure, not an invoice
figure — it will not tie exactly to the monthly invoice (credits, taxes and adjustments land
differently). Fine for watching cost trends, wrong for reconciling a bill.
