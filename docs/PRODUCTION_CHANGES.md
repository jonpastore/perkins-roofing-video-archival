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

## Authentication (Firebase Auth / Identity Platform)
Provisioned via Terraform (Identity Platform config + identitytoolkit API). Remaining steps that
can't be Terraformed:
1. **Google sign-in OAuth client (Jon, console).** APIs & Services → Credentials → create an OAuth
   2.0 Client (Web) + configure the OAuth consent screen. Put its client id/secret into
   `google_idp_client_id` / `google_idp_client_secret` TF vars (or `terraform.tfvars`) and re-apply
   to enable Google as a sign-in provider. Until then the Identity Platform config exists but Google
   sign-in isn't wired.
2. **Register a Firebase Web App** to get the SPA config: `firebase apps:create web perkins-spa`
   (or console) → copy apiKey/authDomain/projectId into `web/.env` as `VITE_FIREBASE_API_KEY`,
   `VITE_FIREBASE_AUTH_DOMAIN` (`<project>.firebaseapp.com`), `VITE_FIREBASE_PROJECT_ID`.
3. **Assign roles** with `scripts/grant_role.py grant <email> admin|sales` (needs firebase-admin +
   owner ADC). A user must sign in once (so the Firebase record exists) before a role can be granted.
   Deny-by-default means a signed-in user with no role can do nothing — granting a role IS the allowlist.
4. **Authorized domains**: add the SPA's production domain to `extra_auth_domains` TF var when it moves
   off localhost / `<project>.web.app`.

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

## Deployment (Cloud Run + SPA)
- **App image:** `scripts/deploy.sh` builds via Cloud Build → Artifact Registry (`infra/registry.tf`)
  and points the Cloud Run `api` service + all 5 jobs at it. Re-run to ship a new revision. Until run,
  Cloud Run serves the placeholder `gcr.io/cloudrun/hello` image.
- **SPA:** `web/` → `npm run build` → Firebase Hosting. Custom domain **app.perkinsroofing.net** needs:
  a Firebase Hosting site + a DNS record (A/CNAME) pointing the subdomain at Firebase (console gives the
  exact record). Set `VITE_API_BASE` to the Cloud Run api URL + the `VITE_FIREBASE_*` values first.

## TikTok reel hosting — BLOCKER (owner action, connects to the domain)
TikTok `PULL_FROM_URL` requires the video host to be a **domain the client owns and verifies** (DNS TXT
URL-prefix). A signed `storage.googleapis.com` URL **cannot be TikTok-verified** (Google's domain), so
TikTok publishing will be rejected even post-audit. Instagram has no such requirement (signed URLs work).
**Fix for TikTok:** serve reels from a client-owned domain — e.g. **media.perkinsroofing.net** fronted by
Cloud CDN over the reels bucket (or a domain-mapped bucket) — then verify that prefix in the TikTok portal.
This is a Monday P2/P3 task alongside the app-review creds. Recommend pairing it with the app.perkinsroofing.net
DNS setup.

## Article engine notes
- Articles publish as **draft** by default (human review) — pass `status="publish"` to go live.
- Video-grounding embeds Tim's real clips (oEmbed player + `?t=` deep-links + VideoObject schema);
  it gets richer as the 841-video ingest completes.
