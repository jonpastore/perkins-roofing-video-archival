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

## Step 2 — get the refresh token (run locally, sign in as the channel owner)

```bash
export OAUTH_CLIENT_ID=...          # from .env / Secret Manager
export OAUTH_CLIENT_SECRET=...
.venv/bin/python scripts/youtube_oauth_setup.py
```

It opens a browser, the channel owner consents to the `youtube.force-ssl` scope, and it prints
the **refresh token**. Copy it.

## Step 3 — store it as a secret + wire it into the API (IaC)

The secret **container** is Terraform-owned (R3-ENFORCE): `youtube-oauth-refresh-token` is already
in the `secret_ids` set in `infra/main.tf` — run `terraform apply` if it doesn't exist yet.
Then add the **value** (a data operation, allowed outside Terraform):

```bash
PROJECT=video-archival-and-content-gen
printf '%s' '<REFRESH_TOKEN>' | gcloud secrets versions add youtube-oauth-refresh-token --data-file=- --project="$PROJECT"
```

Finally, in `scripts/deploy.sh`, uncomment the prepared
`YOUTUBE_OAUTH_REFRESH_TOKEN=youtube-oauth-refresh-token:latest` SECRETS line (kept commented
until the version exists — Cloud Run refuses a `:latest` ref on an empty secret) and deploy.
`OAUTH_CLIENT_ID/SECRET` are already injected.

Redeploy the API. `GET /comments/reply-config` will return `oauth_configured: true` and the
**Post to YouTube** button lights up.

## Notes
- Refresh tokens don't expire unless revoked or unused for 6 months; store it only in Secret Manager.
- The reply is posted to the top-level comment (`CommentDraft.comment_id` is the thread id, which
  equals the parent comment id).
- Rate limits: YouTube comment inserts consume ~50 quota units each; the default 10k/day budget is
  ample for reply volumes.
