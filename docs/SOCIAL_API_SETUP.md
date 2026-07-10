# Getting Social Platform Posting Live — Step-by-Step Setup Guide

**State as of 2026-07-10:** Code paths exist (`adapters/meta_ig.py`, `adapters/tiktok.py`,
`jobs/social_job.py`) and the Secret Manager containers exist, but **all four primary secrets are
EMPTY** (`meta-app-secret`, `meta-system-user-token`, `tiktok-client-secret`,
`tiktok-refresh-token`). The clicking below unlocks them in the right sequence.
The review timelines are fixed regardless of how fast you click — start them in parallel.

---

## Platform setup order (recommended)

Start these in parallel on day one — they all have review/audit wait times that run concurrently:

1. **Instagram + Facebook Reels + Threads** — one Meta app unlocks all three
2. **TikTok** — audit takes 2–6 weeks; submit it immediately
3. **LinkedIn** — partner review takes 2–4 weeks; apply now, implement later
4. **YouTube Shorts** — quota increase takes 1–6 weeks; request it before you need it
5. **Pinterest** — no upfront partner review; do after the above

---

## Instagram (via Meta) — ~45 min setup + up to a few days of review

### Prerequisites checklist

Before you open any developer portal, have all of these ready:

- [ ] The Perkins Instagram account converted to a **Business account** (Instagram app → Profile → Edit Profile → Switch to Professional Account → Business)
- [ ] A **Facebook Page** for Perkins Roofing linked to that Instagram account (Page Settings → Instagram → Connect Account)
- [ ] Admin access on a **Meta Business Manager** (`business.facebook.com`) that owns that Facebook Page — if one doesn't exist yet, create it and add the Page as an asset
- [ ] A business document ready for Business Verification (utility bill, business license, or bank statement showing the registered business name and address) — this is the multi-day gate
- [ ] The Perkins website privacy policy URL (e.g. `https://perkinsroofing.net/privacy`)

### Step-by-step

**1. Create the Meta app**

Go to `developers.facebook.com` → **My Apps** → **Create App**. When asked to select a use case, choose **"Other"** (note: as of 2026, Meta removed the old discrete "Business" app type; you pick a use case instead, and the underlying app type is still referred to as "Business" in their docs — choose "Other" if you don't see a direct IG option). Name it "Perkins Content Platform" and attach it to the Perkins Business Manager account.

**2. Add the required products**

Inside the app dashboard, go to **Add Product** and add both:
- **Instagram Graph API** (the publishing-capable API for Business accounts)
- **Facebook Login for Business** (required for system user token generation)

**3. Store the App Secret**

App dashboard → **App settings → Basic** → copy the **App ID** (non-secret; goes in `.env` as `META_APP_ID`) and the **App Secret**:

```bash
printf '%s' '<APP_SECRET>' | gcloud secrets versions add meta-app-secret \
  --data-file=- --project=video-archival-and-content-gen
```

**4. Business Verification (the multi-day gate)**

`business.facebook.com` → **Business settings → Security center → Start verification**. Upload the business document. Meta typically completes this in 1–5 business days. You cannot generate a never-expiring system user token on a Business account's assets until this is done.

**5. Create the System User and generate the token**

Once the Business Manager is verified:

`business.facebook.com` → **Business settings → Users → System users** → **Add** → name it "perkins-publisher", role **Admin**.

On the system user page → **Add assets**: add the Facebook Page and the Instagram account with **Full Control**.

→ **Generate new token**: select your app, set expiration to **Never**, and check these scopes:
- `instagram_basic`
- `instagram_content_publish`
- `instagram_business_basic`
- `instagram_business_content_publish`
- `pages_read_engagement`
- `pages_manage_posts` ← needed for Facebook Reels (adds no extra review burden here)
- `business_management`

Store the token:

```bash
printf '%s' '<SYSTEM_USER_TOKEN>' | gcloud secrets versions add meta-system-user-token \
  --data-file=- --project=video-archival-and-content-gen
```

**6. Get the Instagram Business Account ID**

With the token stored, tell Claude "meta secrets stored" — I'll fetch `GET /me/accounts?fields=instagram_business_account` automatically and drop `IG_USER_ID` into `.env`.

**7. App review for `instagram_content_publish`**

For a System User operating on assets owned by the same verified Business Manager, `instagram_content_publish` goes live in production **without submitting an individual scope review**, as long as Business Verification (step 4) is complete. If Meta prompts for additional review, they ask for: a screencast of the posting flow end-to-end, a working privacy policy URL, and a description of the use case (publishing our own company's video content to our own account).

**Typical timeline:** Business Verification = 1–5 days. Token usable for your own assets immediately after.

**#1 rejection / block reason:** Attempting to use `instagram_content_publish` on a personal Instagram account or before Business Manager verification completes. Keep everything tied to the Business account linked to the verified BM.

**8. Page Publishing Authorization (if prompted)**

If Meta shows a warning about "Page Publishing Authorization (PPA)," complete it in Business settings → Pages → select the page → Publishing Authorization. It's a 2-minute one-time step.

---

## Facebook Reels — no separate app needed (add scope, same token)

The system user token from the Instagram setup above also covers Facebook Reels. You already requested `pages_manage_posts` in step 5.

**Endpoint:** `POST https://graph.facebook.com/v25.0/{page_id}/video_reels`
**Upload host:** `rupload.facebook.com/video-upload/v25.0/{video_id}` (separate upload call, then publish)

**Format requirements (verified from Meta docs, v25.0):**
- Container: MP4 (recommended)
- Codec: H.264, H.265, VP9, or AV1
- Audio: AAC Low Complexity, 128 kbps+, stereo, 48 kHz
- Aspect ratio: 9:16
- Resolution: 1080×1920 recommended; minimum 540×960
- Duration: 3–90 seconds
- Frame rate: 24–60 fps

**Token type:** You need a **Page access token**, not a User token. Exchange the system user token for a page token via `GET /{page-id}?fields=access_token` using the system user token. This is what the adapter needs to call the Reels endpoint.

**No additional review** beyond what you did for Instagram — same app, same BM verification.

---

## Threads — additive to the same Meta app

Threads uses a **separate Threads use case** on your Meta app, which generates a second App ID and App Secret. You can add this use case to the same app you created above.

**1. Add Threads use case**

In your existing app dashboard → **Add use case** → **Threads API**. This creates a distinct credential set (Threads App ID / Threads App Secret) from the Instagram App ID.

**2. Required scopes**

- `threads_basic` — required for all endpoints
- `threads_content_publish` — required for posting

**3. Publishing flow (two-step)**

Step A — Create a media container:
`POST https://graph.threads.net/v1.0/{threads-user-id}/threads`
with `media_type=VIDEO` and `video_url=<publicly accessible URL>`.

Step B — Publish the container (after it finishes processing, poll status):
`POST https://graph.threads.net/v1.0/{threads-user-id}/threads_publish`
with the container ID from Step A.

**Video hosting requirement:** The video file must be at a **publicly accessible HTTPS URL** at the time of the container creation call — not a direct upload. Use a GCS public URL or a short-lived signed URL. GCS signed URLs work but must not expire before Threads fetches them (give at least 10 minutes of headroom).

**Video format:** MP4 or MOV, up to 5 minutes.

**Rate limit:** 250 posts per 24-hour period per user (verified from official Threads docs).

**Tokens:** Threads uses its own short-lived (1 hour) or long-lived (60 days, refreshable) OAuth tokens — separate from the Instagram system user token. You'll do a one-time Threads OAuth for the Perkins Threads account; I'll handle the token exchange once the Threads app credentials are configured.

**Review:** Same Meta app review as Instagram — no separate audit needed if the IG review already cleared.

---

## TikTok — ~45 min setup + **2–6 week audit** (submit immediately)

### Prerequisites checklist

- [ ] The Perkins TikTok account login
- [ ] A deployed privacy policy URL at `perkinsroofing.net/privacy` (must be live and crawlable)
- [ ] A working demo of your posting flow (OAuth → video upload → post) to screencast for the audit
- [ ] A redirect URI under a domain you control (e.g. `https://perkinsroofing.net/auth/tiktok/callback`) — can be a simple landing page; just needs to receive the `?code=` parameter

### Step-by-step

**1. Register as a developer**

Go to `developers.tiktok.com` → log in with the Perkins TikTok account → navigate to **Manage Apps** (top nav) → **Register Your App**.

**2. Create the app and add Content Posting API**

Fill in the app details — name, icon, description. Under **Products**, add **Content Posting API**. In the Content Posting API configuration, enable **Direct Post** (this is what allows public video posting, as opposed to draft-only).

**3. Store the Client Secret**

From the app dashboard, copy the **Client Key** (non-secret → `.env` as `TIKTOK_CLIENT_KEY`) and **Client Secret**:

```bash
printf '%s' '<CLIENT_SECRET>' | gcloud secrets versions add tiktok-client-secret \
  --data-file=- --project=video-archival-and-content-gen
```

**4. Configure the redirect URI**

In app settings, add your redirect URI (e.g. `https://perkinsroofing.net/auth/tiktok/callback`). TikTok does not allow `localhost` for production apps — the redirect must be a deployed HTTPS endpoint. I can wire up a lightweight callback handler on Cloud Run if you don't have one.

**5. Submit the audit (do this BEFORE testing — sets the clock running)**

In the app dashboard → **Audit** → submit. What TikTok reviews and what causes rejection:

- **Demo video (hardest requirement):** Record a screencast showing the full flow — OAuth login by the TikTok user, your app's upload UI, and a real video being posted. Every requested scope (`video.publish`) must appear in the screencast performing an actual action against a real TikTok account. A UI that only shows a button but doesn't complete a real post fails.
- **UI requirements TikTok verifies in the screencast:**
  - Before every post, your app must display the creator's **username and avatar** (fetched via the Query Creator Info endpoint — not hardcoded)
  - A **privacy level selector** must be visible before posting (options: public, friends, private)
  - **Duet, stitch, and comment** setting controls must be exposed per-post
  - These are hard requirements, not optional UX — TikTok rejects submissions where these are missing or mocked
- **Privacy policy:** Must be a live, accessible URL describing TikTok data use
- **Use case description:** Frame it as "publishing our own roofing company's produced video clips to our own TikTok account, human-reviewed before each post"
- Apps that look like internal tools or demos without a real deployed product get rejected — have a working OAuth flow live on the domain

**Timeline:** Clean first-pass audits: ~1–2 weeks. If feedback is requested, each round adds 2–3 weeks. Plan for 2–6 weeks total.

**#1 rejection reason:** Missing scope coverage in the demo screencast — each scope must be demonstrated with a real, live post, not a mock UI.

**6. OAuth consent (one-time, after audit clears for public posting)**

While the audit is pending, unaudited posts go out as **private-only** — perfect for testing. I'll generate the OAuth authorize URL:

```
https://www.tiktok.com/v2/auth/authorize/?client_key=<CLIENT_KEY>
  &scope=video.publish
  &response_type=code
  &redirect_uri=<REDIRECT_URI>
  &state=<random>
```

You approve in the browser, the redirect gives `?code=`, and I exchange it for the refresh token:

```bash
printf '%s' '<REFRESH_TOKEN>' | gcloud secrets versions add tiktok-refresh-token \
  --data-file=- --project=video-archival-and-content-gen
```

`TIKTOK_OPEN_ID` comes back in the same exchange and goes to `.env`.

**7. Activate**

Tell Claude "tiktok secrets stored" → I redeploy and run a draft-post smoke (private until the audit clears, public after).

---

## YouTube Shorts upload — ~2 days implementation + **1–6 week quota approval**

### Prerequisites checklist

- [ ] A Google Cloud project already exists (we have `video-archival-and-content-gen`)
- [ ] Check whether the existing YouTube OAuth app (`youtube_stats.py`, `youtube_comments.py`) already has `youtube.upload` scope — if so, skip the consent screen re-verification
- [ ] A live privacy policy URL and terms of service URL for the quota increase form
- [ ] Demo account credentials (a Google account with a YouTube channel where you can show the upload flow)

### Step-by-step

**1. Enable the upload scope**

In Google Cloud Console → **APIs & Services → Credentials** → your existing OAuth 2.0 Client ID → verify that `https://www.googleapis.com/auth/youtube.upload` is in the authorized scopes. If not, add it and re-do the consent flow.

**Important:** If the OAuth consent screen is in "Testing" mode (limited to 100 test users), and you want to post to the real Perkins channel, you need to publish the consent screen. Google then requires **OAuth verification** of the app. This is separate from quota increase and takes ~1 week.

**2. Shorts detection — no special endpoint**

YouTube auto-classifies a video as a Short when it is ≤60 seconds AND 9:16 aspect ratio. Adding `#Shorts` to the title or description forces classification if the aspect ratio is correct. No separate Shorts API exists — it's the standard `videos.insert` endpoint.

**Required scope:** `https://www.googleapis.com/auth/youtube.upload`

**3. Default quota and current cost (updated December 2025)**

- Default daily budget: **10,000 units** (shared pool for reads/searches)
- `videos.insert` cost: **~100 units per call** (reduced from 1,600 in December 2025) AND goes into its own dedicated daily upload bucket (~100 upload calls/day) separate from the shared pool — uploads no longer compete with your read/search quota.
- Practical without an increase: ~100 Shorts uploads per day before needing more quota.

**4. Request a quota increase (submit before you need it)**

Go to `console.cloud.google.com` → **APIs & Services → YouTube Data API v3 → Quotas → Request quota increase**. What the form asks for:

- Organization legal name, website, address, size
- Privacy policy URL and ToS URL (with screenshots showing where they're linked from the homepage)
- Demo account credentials with full feature access so Google can test the upload flow
- Google Cloud project numbers
- Use case description (roofing company publishing its own produced content to its own channel)
- OAuth flow screenshot showing the `youtube.upload` scope grant
- Upload interface screenshots

**Timeline:** Google's form says "incomplete submissions cause delays" but does not publish a target. Community-reported range is **1–6 weeks**; Google may send follow-up questions. Submit this before you launch, not after.

**#1 rejection risk:** Applying for a quota increase before you have real, live usage data. Google's recommended path: stay inside the default quota for the first month with real posts, then apply with actual usage metrics attached to the request.

---

## LinkedIn — apply now, implement in 2–4 weeks

### Prerequisites checklist

- [ ] A legal registered business entity (Perkins Roofing as a real company — not a personal name)
- [ ] Business email, registered address, business website, live privacy policy URL
- [ ] LinkedIn Company Page for Perkins Roofing (or a client company page if this is a multi-tenant platform)

### Application process

**1. Create a LinkedIn developer app**

Go to `developer.linkedin.com` → **Create App** → attach to the Perkins Roofing LinkedIn Company Page. Add the **Community Management API** product.

**2. Complete the Development tier access form**

In the developer portal → **My Apps → [your app] → Products → Community Management API** → complete the access request form with: business email, legal name, registered address, website, privacy policy URL, and use case description ("automated video publishing to a roofing company's LinkedIn organization page").

LinkedIn's Development tier grants immediate API access with a **100 API calls/day ceiling** and a **12-month testing window**. This is sufficient to build and test the adapter.

**3. Required scopes**

For posting video to an organization page:
- `w_organization_social` — post on behalf of the organization (requires company page admin role)
- `w_member_social` — post on behalf of a member (if doing member posts)

For video upload specifically, use the **Videos API** (replaces the deprecated Assets API as of 2026):

**4. Video upload flow (3 steps, verified from LinkedIn docs as of 2026-06)**

Step 1 — Initialize upload:
```
POST https://api.linkedin.com/rest/videos?action=initializeUpload
Headers: Linkedin-Version: 202606, X-Restli-Protocol-Version: 2.0.0
Body: { "initializeUploadRequest": { "owner": "urn:li:organization:<ORG_ID>", "fileSizeBytes": <size> } }
```
Response gives you `uploadInstructions` (array of part URLs) and an `uploadToken`.

Step 2 — Upload the video file (chunked, 4 MB parts via PUT to each upload URL). Collect the ETag from each response.

Step 3 — Finalize:
```
POST https://api.linkedin.com/rest/videos?action=finalizeUpload
Body: { "finalizeUploadRequest": { "video": "<video-urn>", "uploadToken": "", "uploadedPartIds": ["<etag1>", ...] } }
```

**Video format (verified from LinkedIn docs):**
- Format: MP4
- Duration: 3 seconds–30 minutes
- File size: 75 KB–500 MB
- Aspect ratio: 9:16 for feed video (standard LinkedIn video ad spec)

**5. Apply for Standard tier when ready to go live**

Standard tier (production, no call limits) requires: a screen recording of your app in action, test credentials for the LinkedIn reviewer, and completion of the Standard tier access form. Timeline: LinkedIn reviews applications but publishes no SLA; plan for 2–4 weeks.

**#1 rejection reason:** Applying for Standard tier before having a working, deployed integration with real usage on Development tier. Build it first.

---

## Pinterest — ~2 days implementation, no partner gating

### Prerequisites checklist

- [ ] A Pinterest Business account for Perkins Roofing (create free at `business.pinterest.com`)
- [ ] Live privacy policy URL

### Step-by-step

**1. Create the app**

Go to `developers.pinterest.com` → **My apps → Create app**. Fill in the app name, description, and privacy policy URL. New apps start in **Trial mode** (limited to the app owner's account only; 1,000 requests/day across all endpoints).

**2. Required scopes**

- `pins:write` — create and update pins
- `pins:read` — read pin data
- `boards:read` — needed to specify target board when creating a pin
- `user_accounts:read` — basic user profile access

**3. OAuth2 flow**

Authorization Code grant (required — Client Credentials flow cannot create pins on a user's behalf). Standard OAuth2 redirect flow; Pinterest issues access tokens and continuous refresh tokens.

**Token expiry:** Access tokens expire in **30 days** (2,592,000 seconds). Refresh tokens expire in **60 days** but are **indefinitely refreshable** — refresh before expiry to maintain uninterrupted access.

**4. Video pin creation (multi-step)**

Video upload is asynchronous:
1. Upload the video file to Pinterest's media upload endpoint → receive a `media_id`
2. Poll the media status until processing is complete
3. Create the pin: `POST /v5/pins` with `board_id` and `media_source: { source_type: "video_id", cover_image_url: "...", media_id: "<media_id>" }`

**5. Submitting for Standard (Trial → Standard review)**

To post on behalf of users other than yourself, submit your app for the **Standard tier review** — Pinterest asks for a demo video of the posting flow. For single-account use (Perkins only), Trial mode is sufficient and you can skip this step.

**#1 gotcha:** Trial mode is per-app-owner only. If you're posting to Perkins' Pinterest from your own developer account, you'll need the Standard review to use Perkins' account via OAuth.

---

## Why not Playwright with your account creds

Offered, considered, and worth avoiding: both portals sit behind 2FA + bot detection, and the actual gates (Meta business verification, TikTok audit, LinkedIn Standard tier) are human review queues that automation cannot accelerate. The clicking above is ~30–45 min per platform; the reviews run on their own clock either way. Where automation helps: everything after the secrets exist — ID lookups, token exchanges, refresh plumbing, smoke tests, and all ongoing posting.

---

## Secret storage reference

All secrets use the same pattern — pipe without a trailing newline:

```bash
printf '%s' '<VALUE>' | gcloud secrets versions add <SECRET_NAME> \
  --data-file=- --project=video-archival-and-content-gen
```

| Secret name | What goes in it |
|---|---|
| `meta-app-secret` | Meta App Secret from App settings → Basic |
| `meta-system-user-token` | Never-expiring system user token from Business Manager |
| `tiktok-client-secret` | TikTok Client Secret from app dashboard |
| `tiktok-refresh-token` | TikTok refresh token from OAuth exchange |

Non-secret IDs (not in Secret Manager — put in `.env` or Cloud Run env vars):

| Variable | Where to find it |
|---|---|
| `META_APP_ID` | Meta App settings → Basic |
| `IG_USER_ID` | Claude fetches via Graph API once token is stored |
| `TIKTOK_CLIENT_KEY` | TikTok app dashboard |
| `TIKTOK_OPEN_ID` | Returned in TikTok OAuth exchange |

---

## Expansion order (from `docs/research/2026-07-10-social-platform-matrix.md`)

Priority order for adapter implementation after IG/TT:

1. **Facebook Reels** — same Meta app + token, add `/{page-id}/video_reels` endpoint (~1 day)
2. **Threads** — same Meta app, add Threads use case, add adapter (~1.5 days)
3. **YouTube Shorts** — new adapter using existing GCP OAuth (~2 days + quota increase lead time)
4. **LinkedIn** — implement against Development tier while Standard review runs (~3 days code)
5. **Pinterest** — clean API, no partner friction (~2 days)

Skipping **X/Twitter** (pay-per-use pricing hostile to automation: ~$0.015 per post, ~$0.20 per post with URL) and **Bluesky** (minimal roofing audience, no official SDK, 50 MB video limit).

---

## Discrepancies vs. `docs/research/2026-07-10-social-platform-matrix.md`

The following items in the matrix doc differ from official docs verified July 2026. The matrix doc is not edited (per instructions); discrepancies are noted here:

1. **LinkedIn file size:** Matrix says "up to 5 GB." LinkedIn Videos API docs (li-lms-2026-06) say max **500 MB**. Use 500 MB as the hard limit.

2. **LinkedIn duration:** Matrix says "3 seconds–10 minutes." Official LinkedIn Videos API docs say "3 seconds–30 minutes" for non-CTV video. The 30-minute figure is from the current docs.

3. **LinkedIn permissions:** Matrix lists `rw_organization_admin` as required. Current LinkedIn Videos API docs (2026-06) list `w_organization_social` and `w_member_social` as the relevant permissions — `rw_organization_admin` is not listed for video posting. Use `w_organization_social` for org page posts.

4. **YouTube `videos.insert` quota cost:** Matrix does not mention this cost. As of December 4, 2025, `videos.insert` costs ~100 units (down from ~1,600) and draws from a dedicated upload bucket separate from the shared 10,000-unit daily pool. Practical effect: ~100 uploads/day before needing a quota increase, and uploads no longer compete with your reads/searches.

5. **Pinterest token expiry:** Matrix says "60-day expiration, indefinitely refreshable" — this describes the **refresh token**. The **access token** expires in 30 days (2,592,000 seconds). Both are correct but refer to different tokens; the matrix conflates them.

6. **TikTok audit timeline:** Matrix is silent on timeline. Community-verified range in 2026 is 2–6 weeks; first-pass cleans can complete in 1–2 weeks if the screencast covers all scope requirements.
