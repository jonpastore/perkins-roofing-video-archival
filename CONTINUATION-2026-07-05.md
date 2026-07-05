# Perkins v2 Platform — Continuation (2026-07-05)

Resume handoff for the Perkins Roofing video-archival platform. Everything below is current as of
commit `27235ce` on branch **`feat/platform-v2`** (not pushed; 18 commits ahead of `main`).

---

## ▶️ NEXT TASKS (what to do when you resume — in order)

1. **DNS + deploy the SPA on `perkins.degenito.ai`.**
   - The SPA is live on Firebase Hosting at `https://video-archival-and-content-gen.web.app`. Point
     the custom domain **`perkins.degenito.ai`** at it.
   - `degenito.ai` is on **Cloudflare**. Get the DeGenito Cloudflare API token from **1Password**
     (`op` CLI is installed) — retrieve it and, since it's a secret, prompt Jon to approve/confirm
     via a GUI elevator (`pkexec`/`zenity` — Jon can't use `! sudo`, no TTY). Then:
     - Add the custom domain in Firebase Hosting: `firebase hosting:sites` / console →
       Add custom domain `perkins.degenito.ai` → Firebase gives a TXT (verification) + the target.
     - Create the Cloudflare DNS record (CNAME `perkins` → the Firebase target, DNS-only/grey-cloud
       so Firebase can issue the cert) via the Cloudflare API with the 1Password token.
     - Add `perkins.degenito.ai` to `infra/variables.tf` `extra_auth_domains` (Firebase Auth
       authorized domains) → `terraform apply`.
     - Rebuild the SPA with `VITE_API_BASE` unchanged (Cloud Run URL) and redeploy hosting.

2. **Set up OAuth (Google sign-in) so login works.** (Full steps: `docs/PRODUCTION_CHANGES.md` →
   "ACTIVATE LOGIN".) Summary:
   - Console → APIs & Services → **OAuth consent screen** (External, "Perkins Console", support email).
   - **Credentials → Create OAuth client ID → Web app.** Authorized JS origins:
     `https://video-archival-and-content-gen.web.app` AND `https://perkins.degenito.ai`.
   - Put client id/secret into `infra/terraform.tfvars` as `google_idp_client_id` /
     `google_idp_client_secret` → `terraform apply` (flips the count-guarded Google IdP on).
   - NOTE: the OAuth consent screen creation may need Jon in the console (consent config isn't
     cleanly automatable). Prompt Jon if so, or drive via API where possible.

3. **Seed the default admins.** After each signs in ONCE at the SPA (creates their Firebase user):
   ```
   .venv/bin/python scripts/grant_role.py grant jon@perkinsroofing.net   admin
   .venv/bin/python scripts/grant_role.py grant tim@perkinsroofing.net   admin
   .venv/bin/python scripts/grant_role.py grant amber@perkinsroofing.net admin
   ```
   (grant_role uses firebase-admin + owner ADC. A user must sign in once before a role can be set —
   deny-by-default means no-role users can't do anything.) Consider a bootstrap: if these three can't
   pre-register, document that they sign in first, then run the grants.

4. **Visual inspection of the UI.** Once login works, open `https://perkins.degenito.ai` (or the
   `.web.app` URL), sign in as jon@perkinsroofing.net (admin), and walk the console: Search/Ask,
   Archive (browse + download), Email compose, Articles, Scheduling, Video Approval, /status. Use the
   `run`/screenshot skill or Playwright to capture the authed views and verify each renders + calls
   the API (the API is `--allow-unauthenticated` at GCP IAM, Firebase-auth enforced in-app, so the
   browser reaches it fine).

---

## ✅ CURRENT STATE — what's built & deployed

**All 5 waves + source-video archival + Firebase auth are built, architect+critic-reviewed (every
wave, all HIGH/critical fixed), and DEPLOYED.** 433 tests, 99.78% core coverage, drift-clean.

| Layer | State | URL / detail |
|---|---|---|
| API (Cloud Run) | ✅ live | `https://api-981279422576.us-central1.run.app` (image `platform:3c29c92`) |
| SPA (Firebase Hosting) | ✅ live | `https://video-archival-and-content-gen.web.app` |
| Cloud SQL + pgvector | ✅ live | instance `...-pg`, db `perkins`, 3072-dim |
| Cloud Run Jobs (ingest/render/article/social) | ✅ on real image | `python -m jobs.<mod>` |
| Firebase Auth | ✅ provisioned | Identity Platform; **login needs OAuth client (task 2)** |
| 4 Cloud Run jobs, buckets, secrets, IAM, schedulers | ✅ Terraform, drift-clean | `infra/` |

**GCP project:** `video-archival-and-content-gen` (billing linked). **Region:** us-central1.

### The 5 waves (all done)
- **W0 Foundation:** core/adapters/api/jobs split, Vertex Gemini backend (`gemini-2.5-flash` +
  `gemini-embedding-001` 3072-dim), Firebase-auth FastAPI dependency, CI (97% gate), SPA shell, Terraform.
- **W1 Data:** full-channel enumerate, local Whisper STT (cerberus) + VAD, resumable ingest, 3072 embed.
- **W2 Content:** email (Gemini proofread + Resend), **article engine (seo-aio prompt IP port, Vertex,
  Serper, WordPress publish) with VIDEO-GROUNDING** (embeds Tim's real clips + VideoObject JSON-LD),
  scheduler. Live-verified: article w/ embedded YouTube player + schema on WP staging.
- **W3 Video:** mini-series planner, ffmpeg render (9:16 1080×1920), admin approval, reels→scheduled_content.
- **W4 Social:** IG Reels + TikTok publishers (behind interfaces; **creds land Mon 2026-07-06**);
  private reels served via short-TTL signed URLs.
- **Archival (Jon-requested):** all 841 source MP4s → private media bucket; SPA Archive page + signed download.

---

## ⏳ BACKGROUND JOBS (running locally via Cloud SQL Auth Proxy on :5432)
- **Ingest:** ~793/841 transcripts, ~752 embedded — nearly done.
- **Archive:** ~115/841 (climbing) — the YouTube **n-challenge was SOLVED** (`--remote-components
  ejs:github` + deno + cookies; see `adapters/yt_dlp.pull_video` + `scripts/run_archive.sh`).
- Check progress: `scripts/run_cloudsql_job.sh` pattern, or query Cloud SQL (see commands below).
- **If the proxy/jobs died** (machine reboot / `/clear` doesn't kill them, but verify): restart the
  Auth Proxy (`/tmp/cloud-sql-proxy <conn> --port 5432` in background) then re-run
  `scripts/run_archive.sh` and the ingest worker. Both are idempotent/resumable.
- **On ingest completion:** build the HNSW index + run the retrieval eval on the full corpus.

**Check state:**
```
PW=$(gcloud secrets versions access latest --secret=db-password)
DB="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
DBURL="$DB" .venv/bin/python -c "import os;from sqlalchemy import create_engine,text;c=create_engine(os.environ['DBURL']).connect();print('archived',c.execute(text('select count(*) from videos where archive_uri is not null')).scalar(),'| transcripts',c.execute(text(\"select count(*) from ingestion_runs where stage='transcript' and status='done'\")).scalar(),'| embedded',c.execute(text('select count(distinct video_id) from chunks')).scalar())"
```

---

## 🔑 KEY FACTS / GOTCHAS
- **Auth model:** Google sign-in (Firebase) → ID token → API verifies → `role` custom claim (admin|sales)
  → `core.authz` deny-by-default. Roles set via `scripts/grant_role.py`. `/internal/*` cron routes
  guarded by `INTERNAL_SECRET` header (in Secret Manager), NOT GCP IAM.
- **Deploy:** `scripts/deploy.sh` (Cloud Build → Artifact Registry → Cloud Run service + 4 jobs).
  `Dockerfile` = v2 (api.app + job entrypoints + ffmpeg). SPA: `cd web && npm run build && firebase
  deploy --only hosting`. Firebase web config in `web/.env` (gitignored; API key is public-safe).
- **Whisper:** faster-whisper on **cerberus** (RTX 5090, dedicated via `ansible/whisper.yml`), systemd
  `whisper-perkins`, token in `/etc/whisper-perkins.env`. WHISPER_URL in `.env`.
- **Creds in `.env`** (gitignored): Serper ✓, WordPress ✓ (WP_APP_PWD), Resend key (domain unverified),
  YouTube, GCP. Social (Meta/TikTok) empty until Monday. `infra/vertex-dev-sa.json` = local Vertex key.
- **Engineering rules (BINDING — `docs/ENGINEERING_RULES.md`):** R1 ≥97% core coverage + I/O
  validation; R2 architect+critic review every wave; R3 100% IaC (Terraform+Ansible), no manual deploys;
  R4 per-wave `scripts/drift_check.sh`; R5 Ansible for non-Terraform. **Follow these for any new work.**
- **Terraform ADC must be `jon@perkinsroofing.net`:** `gcloud auth application-default login` if apply
  fails with permission errors. `provider "google"` has `user_project_override=true`.
- **`gcloud`/`firebase` CLIs** auth via the jon@perkinsroofing.net account/ADC. `op` (1Password) installed.

## 📋 PENDING (external, mostly Jon/Monday)
- **Mon 2026-07-06:** Meta + TikTok app-review creds → flip social live. Resend domain verify (email send).
- **TikTok media domain:** reels need `media.perkinsroofing.net` (Cloud CDN over reels bucket) — TikTok
  can't verify `storage.googleapis.com`. IG works with signed URLs. (`docs/PRODUCTION_CHANGES.md`.)
- **WordPress:** move from staging `jhk.14f.myftpupload.com` → `perkinsroofing.net`; install the JSON-LD
  mu-plugin BEFORE publishing (WP drops unregistered meta writes). `wp-plugin/` is the uploadable form.
- **Minor:** eval harness (`app/eval.py`) not CI-wired; SA-key → Workload Identity.

## 📚 Where things live
- Waves/specs: `docs/superpowers/{specs,plans}/`. Rules: `docs/ENGINEERING_RULES.md`. Prod steps:
  `docs/PRODUCTION_CHANGES.md`. Backlog: `docs/BACKLOG.md` (B1 new-video monitoring, B2 ToS-safe
  comment-answer queue). Secrets runbook: `infra/SECRETS.md`.

---
*Continuation-doc archive directive: this is the first top-level `CONTINUATION-*.md`; none to archive
(keep ≤3 at top level, older ones → `docs/continuations/`). Perform on the next continuation.*
