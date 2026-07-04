# Production Changes — required config/plugins outside the codebase

Things that must be done on external systems (WordPress, Resend, GCP) for the platform to run in
production. The code is in git + IaC; these are the manual/console steps that can't be codified.

## WordPress (staging → production site)

Current staging = `https://jhk.14f.myftpupload.com` (GoDaddy temp domain). Production = the real
`perkinsroofing.net` WordPress. When switching, update `WP_URL` (site **root**, not `/wp-admin`),
`WP_USER`, `WP_APP_PWD` in `.env` / Secret Manager, then apply ALL of the below on the prod site.

1. **Enable Application Passwords.** Core since WP 5.6; requires HTTPS (prod has it). Some security
   plugins (Wordfence, Solid Security, iThemes) disable it — re-enable "Application Passwords" and
   "REST API" there. Create one under **Users → Profile → Application Passwords** for the API user
   (author/editor role) → that's `WP_APP_PWD` (24 chars; store WITHOUT the display spaces).
2. **Pretty permalinks.** Settings → Permalinks → **Post name** (anything but "Plain"), or `/wp-json/`
   REST routes 404. (Staging fix confirmed this was the issue.)
3. **Install the JSON-LD plugin — BEFORE publishing any articles.** Two forms:
   - **Prod (preferred):** drop `wp-mu-plugin/perkins-jsonld.php` into `wp-content/mu-plugins/`
     (filesystem/SFTP — mu-plugins can't be installed over REST).
   - **No filesystem access:** upload `wp-plugin/perkins-jsonld/` (zip it) via **Plugins → Add New →
     Upload Plugin** and Activate. (On staging this was automated with
     `scripts/wp_install_plugin.py` — Playwright logs into wp-admin and uploads; needs the real
     wp-admin LOGIN password, NOT the application password.)
   - **CRITICAL ORDERING:** the plugin `register_post_meta('_perkins_jsonld')` must be active
     BEFORE articles are published — WordPress **silently drops writes to unregistered meta keys**,
     so any article published before the plugin is active renders NO schema (VideoObject/FAQPage/
     Article) and must be re-published afterward. Install+activate first, then publish.
   - Without the plugin the JSON-LD is stored in post meta but never emitted (WP strips `<script>`
     from post content), so articles lose their schema/AIO signal.
4. **Video embeds (oEmbed).** No plugin needed — WordPress autoembed renders a bare YouTube URL on
   its own line into a player (verified on staging). Just confirm the active theme doesn't strip it.
5. **SEO plugin (P6).** Confirm Yoast or RankMath. Ensure it does NOT emit a *conflicting* Article/
   FAQ schema for our posts (duplicate JSON-LD). Either let our mu-plugin own schema for API-posted
   articles, or disable the plugin's schema on those.
6. **REST API not blocked.** Confirm no security plugin/firewall returns 401/403/404 on
   `/wp-json/wp/v2/*` for Application-Password auth. (GoDaddy Managed WP occasionally strips the
   `Authorization` header — if auth 401s despite a valid app password, add to `.htaccess`:
   `SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1`.)

## Resend (email — blocked until Mon 2026-07-06)

- Add + **verify the `perkinsroofing.net` domain** in Resend (DNS: SPF/DKIM/DMARC). The API key is
  valid but **no domain is verified**, so `/email/send` will fail until this is done. `reply-to` is
  the sending user's own email (replies go to their normal client).

## GCP / infra (mostly IaC already)

- **Container image for Cloud Run Jobs.** The `ingest`/`render`/`article`/`social` jobs + the `api`
  service are placeholder `gcr.io/cloudrun/hello` images in Terraform. Build the app container
  (Dockerfile → Artifact Registry) and set each job's `image` + `command` (`python -m jobs.<mod>` /
  `uvicorn api.app:app`). Currently the bulk ingest runs locally via the Auth Proxy.
- **SA key → Workload Identity.** `infra/vertex-dev-sa.json` is a downloaded key for local dev; prod
  Cloud Run uses the attached `api-run-sa`/`jobs-sa` (no key). Migrate dev to WIF when convenient.
- **DB schema.** App-managed via SQLAlchemy `create_all` (run on job startup / `scripts/db_bootstrap.py`).
  pgvector extension is enabled. `PERKINS_ENV=prod` env var enforces Vertex + Cloud SQL (fail-fast).
- **cerberus GPU** is dedicated to Whisper for the project (`ansible/whisper.yml`, ollama disabled).
  Release with `-e dedicate_gpu=false` when done.

## Source-video archival notes
- All 841 source videos are archived to the private `-media` GCS bucket (`jobs/archive_job.py`),
  browsable + downloadable from the SPA Archive section (V4 signed URLs, 1h TTL; `api-run-sa`
  self-signs via `serviceAccountTokenCreator`). ~full-res MP4s — expect tens–hundreds of GB.
- **Egress is per-download and unbounded by design** (owner chose "archive everything"). There is
  no download rate-limit or audit log yet — if download volume grows, add a `Video`-level download
  audit + consider a rate limit. Storage ≈ $0.02/GB/mo; egress ≈ $0.12/GB on each download.
- The `archive_job` needs adequate ephemeral disk on Cloud Run (peak ~1.5–3× a video's size during
  yt-dlp merge). Locally it runs via the Auth Proxy with owner ADC (the vertex-dev-sa key has no
  storage perms — `run_archive.sh` unsets GOOGLE_APPLICATION_CREDENTIALS for GCS).

## Article engine notes
- Articles publish as **draft** by default (human review) — pass `status="publish"` to go live.
- Video-grounding embeds Tim's real clips (oEmbed player + `?t=` deep-links + VideoObject schema);
  it gets richer as the 841-video ingest completes.
