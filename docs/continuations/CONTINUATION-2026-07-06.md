# Perkins v2 Platform — Continuation (2026-07-06)

Resume after a very large build+harden session on branch **`feat/platform-v2`** (not pushed).
Previous handoff: `docs/continuations/CONTINUATION-2026-07-05.md` (archived 2026-07-08). Everything below is current
as of commit **`2ff19cb`**, which is the **live** API image and SPA.

---

## ⚡ RESUME QUICK-START (read first)

**1. Auth — two credentials, don't cross them.**
- **gcloud / Secret Manager / Cloud Scheduler / deploys** need Jon's **Owner ADC**. `.env` sets
  `GOOGLE_APPLICATION_CREDENTIALS=infra/vertex-dev-sa.json` (a READ-ONLY SA) — if you `source .env`,
  **`unset GOOGLE_APPLICATION_CREDENTIALS`** before gcloud, or you get 403s (that SA can't write
  secrets / describe run). Then `export CLOUDSDK_AUTH_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)`.
- **Vertex / DB jobs** (article gen, crawls, embeds) DO want `GOOGLE_APPLICATION_CREDENTIALS=infra/vertex-dev-sa.json`.
- **ADC expires** mid-session (403 on writes, or gcloud "Reauthentication failed"). Fix: ask Jon to run
  `!gcloud auth application-default login` (and `!gcloud auth login`). It also kills the cloud-sql-proxy → restart it.
- **DB:** `DB_URL=$(cat /tmp/perkins_dburl.txt)` (postgres via proxy). Proxy binary `/tmp/cloud-sql-proxy`;
  start: `env -u GOOGLE_APPLICATION_CREDENTIALS /tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432` (run_in_background).

**2. Deploy (R3):** API+jobs `unset GOOGLE_APPLICATION_CREDENTIALS; export CLOUDSDK_AUTH_ACCESS_TOKEN=...; bash scripts/deploy.sh`
(sources `.env`, injects vault secrets). SPA `cd web && npm run build && firebase deploy --only hosting --project video-archival-and-content-gen`.
**⚠️ GATE ON `npm run build`, NOT `tsc --noEmit`** — a stale-bundle bug hid ALL frontend work for
hours because `npm run build` was failing (unused var / arg-count) while `tsc --noEmit` passed and
`build && firebase deploy` silently short-circuited. Migrations: strip `--` comment lines before
splitting on `;` (see `scripts/apply_migrations.sh`); apply via proxy + `DB_URL`, not `gcloud secrets`.

**3. Secrets are in the VAULT now** (`deploy.sh --set-secrets` from Secret Manager: wordpress-app-password,
resend/youtube/serper/whisper-token, google-idp-client-secret, internal-secret, db-password). Resettable in
the Config UI (`google-cloud-secret-manager` is bundled). Non-secret env: WP_URL, WP_USER, OAUTH_CLIENT_ID,
YT_OWNER_CHANNEL_ID. To (re)populate a secret from `.env`: REST `…/secrets/<id>:addVersion` with the Owner token.

---

## 🚨 TOP REMAINING TASK — the ingest QUEUE has no automatic trigger

**Symptom Jon hit:** re-queuing a video (Dashboard "Retry" → sets an `ingestion_runs` row to
`status='pending'`) does **nothing** — the video sits forever. Stuck now: **`WLX7kUWleto`**, stage
`transcript`, pending since 2026-07-06 03:13 (the only pending run).

**Root cause:** the `ingest` Cloud Run **Job** (`jobs.ingest_worker`) is what drains pending runs, but
**nothing executes it automatically** — `gcloud run jobs executions list --job=ingest` is **empty**.
There are Cloud Scheduler jobs for promote/social/crawl-comments but **none for ingest** (or render/article).
Initial archival ran the job manually. So the queue never advances on its own.

**Fix (next session):** add an automatic trigger for the ingest job. Two shapes:
- A **Cloud Scheduler → Cloud Run Job execution** (`run.googleapis.com/.../jobs/ingest:run`, OAuth
  scheduler-sa), e.g. every 15–30 min; OR
- An `/internal/ingest` endpoint (INTERNAL_SECRET-gated, like `/internal/crawl-comments`) that runs a
  bounded `jobs.ingest_worker` batch, + a scheduler (simplest, matches the pattern already in `api/app.py`
  + `infra/main.tf`). Consider the same for `render`/`article` if those queues also need draining.
- **Caveat:** stage `transcript` needs **Whisper on cerberus** (`ansible/whisper.yml`). The GPU was
  reclaimed for local-LLM priming earlier (now abandoned — everything's on Vertex). Verify Whisper is back
  (`ansible-playbook local_llm.yml -e reclaim_gpu_from_whisper=false && ansible-playbook whisper.yml`) or the
  ingest will trigger but fail transcription. `WHISPER_URL=http://cerberus-ai:9000/asr` in `.env`.

---

## ✅ Comment-crawl cron — DONE & verified end-to-end
- `crawl-comments` scheduler ENABLED `0 */2 * * *` → `POST /internal/crawl-comments` (INTERNAL_SECRET
  header) → **HTTP 200 confirmed in Cloud Logging**. Rotating crawler picks least-recently-crawled videos
  (`videos.comments_crawled_at` nulls-first, migration 0009), 15 videos/15 drafts per run → sweeps all 841
  over ~5 days then refreshes. Race-safe upsert (SAVEPOINT). Draftbench fills the **Comments** tab.
- **Bonus fix:** promote/social schedulers were silently 403ing (`_require_internal` needs the
  `X-Internal-Secret` header they never sent) — added the header via gcloud + Terraform. Scheduled article
  promotion + reel publishing work now.

## ✅ What else shipped this session (all live on `2ff19cb`)
- **The stale-SPA bug** — fixed the failing `npm run build`; Comments/Logs/dashboard-KPIs/spinners/WP-links
  finally deployed (they were invisible before). **Hard-refresh the app.**
- **Publishing fixed** — deployed API now has WP creds (vault); WordPress REST health check = 200; stuck
  "published-but-not-pushed" articles re-published (WP #7896/#7897). WP post numbers link (draft→editor,
  published→live post).
- **Articles**: generation loop provably reaches SEO/AIO **100** (deterministic guarantees for
  title/keyword/answer-first/headings + markdown→HTML + placeholder detection + Article/BreadcrumbList/
  FAQPage/VideoObject JSON-LD); **all 34 articles at 100**.
- **FAQ**: concise `link {n}`-cited answers; **semantic consolidation 5,227→4,541** (near-dupes folded,
  citations merged); coverage/count is a **live/dynamic** query (`status!='duplicate'`). Answer backlog
  still grinding on Vertex (**3,930 answered**, resumable via `jobs.prime_backlog --answers`).
- **Multi-source topic reels** (12 proposals in Video Approval). **Dashboard** KPIs clickable + queue panel.
  **Content Opportunities** aggregated + paginated + generated-filter + cluster modal. **Clip Studio** brand
  intro/outro upload, clip tracking, preselect-from-Archive. **Video Approval** descriptive titles + real
  offsets. **Scheduling** clean names + title links. **Users** shows tim/amber. **Config** health checks
  (all 8 green) + prod domain. **Archive** KPIs (views/likes/comments/last-comment), filters (length/date/
  clips/articles/social), backfill + check-new buttons, pencil→Clip Studio. **Logs** admin tab (Cloud Logging).
  **Comments** tab (crawl→draft). Animated spinners everywhere.
- **Security (deepsec scan + fixes)**: article XSS (DOMPurify sink + bleach-on-write), single-flight
  rate-guards on crawl/backfill/poll-kpis, WP_URL SSRF validation, logs admin-only + secret redaction,
  generic client errors, constant-time internal-secret compare, Firebase web key env-ified.

## 📋 Other open items (non-blocking)
- **FAQ answer backlog** finishing on Vertex → then re-run `POST /faq/publish-wordpress` (page 7895) to
  refresh the site FAQ with the full consolidated set.
- **Firebase web key** — Jon: API-restrict it to Identity Toolkit in the GCP console (console action; it's a
  public web key, low risk, but tidy it).
- **R4 drift**: several infra changes were applied via gcloud (secret versions, reels-bucket IAM, the 3
  schedulers) AND written to `infra/main.tf` — a `terraform plan` may show them as already-present or need a
  one-time `terraform import` of the gcloud-created `crawl-comments` scheduler. Reconcile when convenient.
- **External blockers** (not ours): Meta/TikTok social creds; Google Workspace admin consent for org-directory
  user autocomplete; Resend domain verify.

## 📚 Where things live
Rules `docs/ENGINEERING_RULES.md`; specs/plans `docs/superpowers/{specs,plans}/`; backlog `docs/BACKLOG.md`;
handoffs `docs/continuations/`. Jobs: `jobs/` (crawl_comments, poll_archive_kpis, backfill_archive,
consolidate_faqs, prime_backlog, upgrade_articles, propose_topic_series, ingest_worker). Scheduler + jobs +
secrets IaC in `infra/main.tf`; runtime deploy in `scripts/deploy.sh`.

---
*Continuation-doc archive directive: performed 2026-07-08 — `CONTINUATION-2026-07-05.md` moved to
`docs/continuations/`; top level holds 2026-07-06, 2026-07-06-pm, 2026-07-08.*
