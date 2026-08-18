# Enabling direct YouTube reply posting (Comments tab)

The Comments tab drafts replies with an API key (read-only). **Posting** a reply to YouTube
requires OAuth as the **channel owner** with scope `https://www.googleapis.com/auth/youtube.force-ssl`
— an API key cannot post. Until this is configured, the UI stays in draft/copy mode; once a
refresh token is set, a **Post to YouTube** button appears and `POST /comments/{id}/post` works.

## What's needed (one-time)

1. An OAuth **client** (we reuse the existing `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET`).
2. A **refresh token** for the Perkins YouTube channel owner, obtained via a one-time consent
   with the `youtube.force-ssl` scope, stored as `YOUTUBE_OAUTH_REFRESH_TOKEN`.

The token must be minted by whoever owns/manages the Perkins **YouTube channel** (e.g. Tim) —
it posts *as that account*.

## Step 1 — allow the scope + a Desktop redirect on the OAuth client

In Google Cloud Console → **APIs & Services → Credentials**, open the OAuth client for
`OAUTH_CLIENT_ID`. Ensure **YouTube Data API v3** is enabled for the project
(APIs & Services → Library → "YouTube Data API v3" → Enable). Add
`http://localhost:8765/` as an authorized redirect URI (used by the helper below).

## Step 2 — mint and vault (verify first, R12)

Sign in as the Perkins channel owner. The helper exchanges the code, checks
`channels?mine=true` is `UChJZpBYXOuR0j1EHJugv5hg`, then writes Secret Manager.
A failed check does not overwrite `:latest`.

```bash
export OAUTH_CLIENT_ID=... OAUTH_CLIENT_SECRET=... GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen
.venv/bin/python -m jobs.youtube_relogin --prompt          # vaulted Google login after success
.venv/bin/python -m jobs.youtube_relogin --headed          # if Google blocks headless / 2FA
.venv/bin/python -m jobs.youtube_relogin --api-key         # rotate youtube-api-key the same way
```

Dashboard **Data sources → YouTube → Log in** is the same verify-then-vault on the
OAuth callback. `scripts/youtube_oauth_setup.py` still prints a token for emergencies;
do not `gcloud secrets versions add` an unverified paste.

## Step 3 — secret container is Terraform-owned (R3)

`youtube-oauth-refresh-token` and `youtube-login` are in `infra/main.tf` `secret_ids`.
`scripts/deploy.sh` already mounts `YOUTUBE_OAUTH_REFRESH_TOKEN=youtube-oauth-refresh-token:latest`.

Redeploy the API. `GET /comments/reply-config` will return `oauth_configured: true` and the
**Post to YouTube** button lights up.

## Notes
- Refresh tokens don't expire unless revoked or unused for 6 months; store it only in Secret Manager.
- The reply is posted to the top-level comment (`CommentDraft.comment_id` is the thread id, which
  equals the parent comment id).
- Rate limits: YouTube comment inserts consume ~50 quota units each; the default 10k/day budget is
  ample for reply volumes.
