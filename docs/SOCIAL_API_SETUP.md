# Getting Instagram + TikTok posting live (and what's next)

State as of 2026-07-10: the code paths exist (`adapters/meta_ig.py`, `adapters/tiktok.py`,
`jobs/social_job.py`) and the Secret Manager containers exist, but **all four secrets are
EMPTY** (`meta-app-secret`, `meta-system-user-token`, `tiktok-client-secret`,
`tiktok-refresh-token`) — IG/TikTok posting has never run against live credentials.
Having the account logins (Jon has them) is step zero; the real gates are developer-app
creation and each platform's review process, which are human/business-verification steps
no automation can skip.

## Instagram (via Meta) — ~30 min of clicking + up to a few days of review

Prereqs: the Perkins Instagram account must be a **Business account** linked to a
**Facebook Page**, and you need admin on the **Meta Business Manager** that owns that Page.

1. developers.facebook.com → Create App → type **Business** → name "Perkins Content Platform",
   attach it to the Perkins Business Manager.
2. In the app: add products **Instagram Graph API** and **Facebook Login for Business**.
3. App settings → Basic: copy **App ID** (goes to `.env` `META_APP_ID` — non-secret) and
   **App Secret** → store it:
   `printf '%s' '<APP_SECRET>' | gcloud secrets versions add meta-app-secret --data-file=- --project=video-archival-and-content-gen`
4. business.facebook.com → Business settings → Users → **System users** → Add
   ("perkins-publisher", Admin) → **Add assets**: the Facebook Page + the Instagram account,
   with full control → **Generate new token**: select the app, check scopes
   `instagram_basic, instagram_content_publish, pages_read_engagement, business_management`,
   token expiration **never** → store it:
   `printf '%s' '<TOKEN>' | gcloud secrets versions add meta-system-user-token --data-file=- --project=video-archival-and-content-gen`
5. `IG_USER_ID` (.env): the Instagram Business Account ID — Graph Explorer
   `GET me/accounts?fields=instagram_business_account` with the token, or I can fetch it
   once the token is stored.
6. **App Review**: for a system-user token on assets your own Business owns,
   `instagram_content_publish` works in "Live" mode without full review once the Business
   is **verified** (Business settings → Security center → Start verification — needs a
   business document; this is the multi-day part if Perkins' Business Manager was never verified).
7. Tell Claude "meta secrets stored" → I redeploy and run a draft-post smoke.

Bonus: the SAME app + token unlock **Facebook Reels** and **Threads** posting (the two
next platforms on the research build order) — no second app needed, just extra scopes
(`pages_manage_posts` for Reels; Threads uses its own token flow off the same app).

## TikTok — ~30 min of clicking + a content-posting audit (days to ~2 weeks)

1. developers.tiktok.com → register as developer (use the Perkins TikTok login) →
   **Manage apps → Create app** ("Perkins Content Platform").
2. Add the **Content Posting API** product to the app. Fill the required app details
   (icon, description, ToS/privacy URLs — use perkinsroofing.net pages).
3. Copy **Client key** (.env `TIKTOK_CLIENT_KEY` — non-secret) and **Client secret** →
   `printf '%s' '<CLIENT_SECRET>' | gcloud secrets versions add tiktok-client-secret --data-file=- --project=video-archival-and-content-gen`
4. **Audit**: TikTok requires a Content Posting API audit before posts go public
   (unaudited apps can only post as private/draft). Submit the audit from the app page —
   describe the use case as "publishing our own roofing company's produced clips to our
   own account, human-reviewed." This is the long pole.
5. OAuth consent (one-time, as the TikTok account): I'll generate the authorize URL
   (scopes `video.publish,video.upload`), you approve in the browser, the redirect gives
   a code, I exchange it for the **refresh token** →
   `printf '%s' '<REFRESH_TOKEN>' | gcloud secrets versions add tiktok-refresh-token --data-file=- --project=video-archival-and-content-gen`
   (`TIKTOK_OPEN_ID` comes back in the same exchange; goes to .env.)
6. Tell Claude "tiktok secrets stored" → redeploy + draft-post smoke (private until the
   audit clears, public after).

## Why not Playwright with your account creds

Offered, considered, and worth avoiding: both portals sit behind 2FA + bot detection, and
the actual gates (Meta business verification, TikTok audit) are human review queues that
automation cannot accelerate. The clicking above is ~30 min per platform; the reviews run
on their own clock either way. Where I CAN automate: everything after the secrets exist
(ID lookups, token exchanges, refresh plumbing, smokes).

## After IG/TT: the expansion order (from docs/research/2026-07-10-social-platform-matrix.md)

YouTube Shorts upload (needs a quota-increase request) → Facebook Reels (same Meta app) →
Threads (same Meta app) → LinkedIn (**start the Community Management API partner
application now** — 2-4 week review) → Pinterest. Skipping X (pay-per-use pricing is
hostile: ~$0.20/post with a URL) and Bluesky (no roofing audience).
