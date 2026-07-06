# Continuation — 2026-07-06 (PM session)

Branch: `feat/platform-v2` · HEAD at handoff: `41c13e5` · everything below is **committed + deployed**.
Prod project: `video-archival-and-content-gen` · API: https://api-jnr6bsxyea-uc.a.run.app ·
SPA: https://video-archival-and-content-gen.web.app · WP: see `WP_URL` in `.env`.

## Nothing is lost on shutdown
All work is committed and live in the cloud (Cloud Run API+jobs image `41c13e5`, SPA on Firebase,
Cloud Scheduler crons, DB migrations, WordPress edits, terraform state on disk). Only the local
`cloud-sql-proxy` tunnel dies — restart it (see Commands). No LLM batch or deploy is in flight.

## What shipped this session (all deployed)
- **Cloud STT (no cerberus/Whisper).** Transcription reads the archived GCS MP4 → ffmpeg demux to
  16 kHz FLAC → Speech-to-Text v2 **GCS-output batch** (handles up to 8 h; the 97-min podcast
  transcribed: 362 segments). `adapters/stt_gcp.py`, `app/transcript.py` (`STT_BACKEND=gcp`).
- **Auto-draining ingest cron.** Cloud Scheduler `run-ingest` (`* * * * *`) triggers the `ingest`
  Cloud Run Job; single-flight pg advisory lock inside `jobs/ingest_worker.py`; selects only
  not-done videos; gives up after `MAX_TRANSCRIPT_ATTEMPTS=5`. ingest/render jobs = 8Gi / 2h.
- **Re-archive tool** `scripts/rearchive_with_audio.py` (cookies + Chrome UA, needs local `deno`
  for the yt-dlp EJS n-challenge) — fixed the audio-less 2 GB podcast archive.
- **User mgmt:** GSuite invite dropdown, delete/revoke, per-user **signatures**.
- **Comments:** page pagination + **Post-to-YouTube** (`youtube.force-ssl` OAuth, draft-only until a
  refresh token is configured — see `docs/YOUTUBE_REPLY_OAUTH.md`). Crawl now also refreshes
  views/likes/**comment_count** for the archive KPIs.
- **Video Approval:** intro copy + hh:mm:ss editable in/out points. **Sidebar badges** for Video
  Approval + Comments. **Archive:** clips→approval link, inline rename, name-from-YouTube /
  suggest-from-transcript.
- **ClipStudio:** intro/outro are now uploaded **videos** merged via `adapters.ffmpeg.fuse_videos`
  (`POST /clips/upload-brand-video` → `BRAND_INTRO_VIDEO`/`OUTRO_VIDEO`); cards are the fallback.
- **Email:** TinyMCE WYSIWYG (page + `ComposeEmailModal`), save-as-template, insert-signature,
  global `EMAIL_HTML_HEADER`, and `POST /email/draft` (LLM → HTML w/ real `<a>` links, no markdown,
  validate→regenerate loop). `SearchAsk.buildEmailBody` now emits HTML.
- **Articles SEO:** 15 Rank Math checks computed server-side (`core/seo.rank_math_checks`), shown in
  the SEO/AIO panel, and **click-to-fix**: a failing check → `POST /articles/{slug}/fix-seo` re-asks
  Gemini to fix that one issue, re-verifies, updates WP.
- **WordPress author policy:** all posts authored by **Tim Kanak (id 3)**, never Jon Pastore
  (`adapters/wordpress.py` publish/update; `WP_AUTHOR_ID` override). The 6 live posts were reassigned.
- **Scheduling:** published rows link to the live WP post. **Search/Ask:** "Search topics" now hides
  the ask answer. **Logs fixed:** granted `api-run-sa` `roles/logging.viewer` (was the "logs fail to
  pull" cause).
- **IaC discipline:** reconciled the earlier out-of-band drift; added R3-ENFORCE (no direct deploy;
  `scripts/deploy.sh` refuses a dirty tree). `terraform plan` is **clean**.

## Prod migrations already applied (idempotent)
- `ALTER TABLE articles ADD COLUMN focus_keyword VARCHAR`
- `CREATE TABLE user_settings (email VARCHAR PRIMARY KEY, signature TEXT)`

## Outstanding / decisions for next session
1. **Task 27 — DECIDED: refine to a clean 15/15, THEN regenerate all 34 articles + republish.**
   `jobs/regen_articles_seo.py` is written + validated on `wall-flashings` (→100/100, republished) but
   the generator only guarantees **14/15** Rank Math checks — **keyword density** (0.5–1.5%) isn't hit.
   Order of work:
   (a) Make the generation loop pass ALL 15: after generating, run `core.seo.rank_math_failures(...)`
       and refine (density-target the focus keyword into the 0.5–1.5% band) until it returns `[]` —
       wrap `jobs/article_job.generate_scored_article` or add the loop in `regen_articles_seo.py`.
   (b) Verify on one: `LLM_BACKEND=vertex .venv/bin/python -m jobs.regen_articles_seo --slug wall-flashings`
       → `still_failing == {}`.
   (c) Batch all: `LLM_BACKEND=vertex .venv/bin/python -m jobs.regen_articles_seo` (34 articles, ~30-50
       min; republishes the 6 published ones to WordPress as Tim Kanak). Needs proxy + `.env` WP/vertex creds.
   The SEO panel's **click-to-fix** (`POST /articles/{slug}/fix-seo`) remains the per-article manual path.
2. **YouTube reply posting** — not yet live: needs the channel owner (Tim) to mint a
   `youtube.force-ssl` refresh token (`scripts/youtube_oauth_setup.py`) stored as
   `youtube-oauth-refresh-token` + wired into `deploy.sh`/`infra`. See `docs/YOUTUBE_REPLY_OAUTH.md`.
3. **GSuite invite dropdown** — needs a Workspace super-admin to authorize domain-wide delegation
   (`docs/GSUITE_DIRECTORY_SETUP.md`; grant email in `docs/email-grant-superadmin.txt`). Jon's
   super-admin grant may still be pending.
4. **Retire cerberus in IaC** — STT is fully cloud, but `ansible/whisper.yml` still manages the
   (now-unused) cerberus Whisper node, so `drift_check.sh` reports ansible drift/unreachable. Release
   the GPU (`-e dedicate_gpu=false`) and retire the play to make drift_check fully green.
5. **Cosmetic:** `/healthz` returns a Google HTML 404 in prod though it's defined in `api/app.py`
   and every other route works (`/me`→401, all new routes in openapi). Non-functional; low priority.

## Key commands
```bash
# Cloud SQL proxy (needed for any local DB/job work)
/tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &
export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"

# Tests / build / drift
env -u PERKINS_ENV -u DB_URL .venv/bin/python -m pytest tests/ -q -p no:warnings
cd web && npm run build
bash scripts/drift_check.sh              # terraform side is clean; ansible=cerberus (see #4)

# Deploy (R3: commit first — deploy.sh refuses a dirty tree)
bash scripts/deploy.sh                    # API + 4 jobs (image tag = git SHA)
cd web && firebase deploy --only hosting --project video-archival-and-content-gen
cd infra && terraform apply               # infra changes only
```

## Gotchas learned
- `pgrep`-based wait loops self-match (their own cmdline contains the pattern) → zombie waiters.
  Wait on a specific PID (`kill -0 $PID`) instead.
- Speech-to-Text v2 won't decode a muxed video MP4 → must ffmpeg-demux audio first; and long results
  need **GCS output**, not inline.
- yt-dlp from the cloud hits YouTube's bot-check; downloads need cookies + the EJS n-challenge (deno).
  STT sidesteps this by reading the already-archived GCS MP4.
