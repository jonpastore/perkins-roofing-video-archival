# Secrets & Credentials Runbook

Every external credential the platform needs, where to get it, and which wave it unblocks.
GCP service accounts are **created by Terraform** (`infra/main.tf`) — don't hand-make them.
Load the third-party values below into **Secret Manager** (Terraform declares the secret slots; you supply the values).

## GCP (only billing is manual)

| Item | Who | Notes |
|---|---|---|
| Project on `perkinsroofing.net` + **enable billing** | Jon (Workspace admin) | **P1 — blocks all cloud.** Highest-leverage action. |
| `api-run-sa`, `jobs-sa`, `scheduler-sa` | Terraform | Least-priv roles; see Foundation Task 10. |
| APIs (aiplatform, speech, sqladmin, run, secretmanager, cloudscheduler, storage) | Terraform | Enabled on `apply` (needs billing). |
| *(optional)* `vertex-dev-sa` JSON key (`roles/aiplatform.user`) | Jon | Lets Claude validate the Gemini adapter live pre-build. Still needs billing on. Keyless WIF is the cleaner long-term path. |

## Secret Manager values (you obtain, then load)

| Secret name | Wave | How to obtain |
|---|---|---|
| `youtube-api-key` | W1 | Existing (1Password). yt-dlp needs none. |
| `whisper-url` (+ token) | W1 | faster-whisper `/asr` on cerberus — confirm reachable or stand up. |
| `resend-api-key` | W2 | Resend account + verify `perkinsroofing.net` DNS (P4). |
| `wordpress-app-password` | W2 | WP → Users → Application Passwords for an author/editor. Staging creds exist; prod on confirm. Confirm Yoast/RankMath (P6). |
| `serper-api-key` | W2 | serper.dev — SERP + People-Also-Ask for articles. |
| `meta-app-id`, `meta-app-secret`, `meta-system-user-token` | W4 | Meta app + **System User token** (permanent) w/ Advanced Access to `instagram_content_publish` + `instagram_basic` + `pages_read_engagement`. **App Review + Business Verification + screencast.** Start Mon 2026-07-06 (P2). |
| `tiktok-client-key`, `tiktok-client-secret`, `tiktok-access-token`, `tiktok-refresh-token`, `tiktok-open-id` | W4 | TikTok for Developers app + Content Posting API product, scope `video.publish`, **domain/URL-prefix verification (DNS TXT)** on the GCS reel host, **app audit**. Start Mon 2026-07-06 (P2). |

## Not creds (content prereqs)
- **P5** — named article author (name/title/bio/LinkedIn) for E-E-A-T.
- Music-clean title/closing screens (licensed source audio gets flagged on IG/TikTok).

## Unblock order
1. **P1 project + billing** → W1 + W3 + live Vertex validation.
2. *(optional)* `vertex-dev-sa` key → prove the Gemini adapter this week.
3. Serper + Resend + WP app-password → W2 the moment Foundation lands.
4. Start Meta + TikTok registration **Mon 2026-07-06** → W4 (review-gated regardless).
