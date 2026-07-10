# Social Platform Publishing Matrix — 2026-07-10

Research date: 2026-07-10. Sources: repurpose.io, tooljunction.io, Meta developer docs, LinkedIn Microsoft Learn, X API pricing guides, Pinterest developer docs, Snapchat business help, Threads API docs.

---

## 1. Our Current Adapters

From `adapters/` directory listing:

| Adapter | File | Status |
|---|---|---|
| YouTube (stats/comments) | `youtube_stats.py`, `youtube_comments.py` | Read-only — no upload adapter |
| Instagram / Meta | `meta_ig.py` | Have |
| TikTok | `tiktok.py` | Have |
| WordPress | `wordpress.py` | Have |
| B-roll providers | `broll_providers.py` | Have (stub) |
| ElevenLabs | `elevenlabs.py` | Have |
| HeyGen | `heygen.py` | Have |
| FFmpeg | `ffmpeg.py` | Have |
| GCP / storage | `storage.py`, `gcip.py`, `stt_gcp.py` | Have |

**Gaps vs. repurpose.io:** Facebook Pages/Reels, LinkedIn, X/Twitter, Pinterest, Snapchat, Threads, Bluesky, YouTube Shorts upload.

`render_part` targets `instagram,tiktok` by default (`_DEFAULT_PLATFORM`).

---

## 2. Repurpose.io Platform Coverage

Source: tooljunction.io/ai-tools/repurpose-io, repurpose.io

### Sources (where original content originates)
YouTube, TikTok, Facebook Live, Twitch, Podcast hosts, Google Drive, Dropbox

### Destinations (where content is republished)
YouTube (Shorts), TikTok, Instagram (Reels + Feed), Facebook (Pages + Reels), LinkedIn, X (Twitter), Pinterest, Snapchat, Bluesky, Amazon, Twitch

**They support 13+ platform connections.**

### Their pricing (for context — annual billing only)
| Plan | Cost | Accounts/platform | Videos/mo |
|---|---|---|---|
| Free | $0 | 1 | 10 total lifetime |
| Starter | $349/yr (~$29/mo) | 3 | 5,000 |
| Pro | $790/yr (~$66/mo) | 10 | Unlimited |
| Agency | $1,790/yr (~$149/mo) | Expanded | Unlimited |

Repurpose.io does **no content creation or editing** — it's pure distribution and reformatting. Our stack already does editing; we just need the distribution layer.

---

## 3. Platform-by-Platform Gap Analysis

For each platform repurpose.io supports that we don't yet have an adapter for:

### Facebook Pages / Reels

| Attribute | Detail |
|---|---|
| Official video API | Yes — Meta Graph API v25.0 (Feb 2026) |
| Auth model | OAuth2, Authorization Code flow |
| Required permissions | `pages_manage_posts`, `pages_manage_engagement`, `pages_manage_metadata` |
| App review required | Yes — Business Verification (legal docs, 2–5 business days) |
| Reel format | MP4 only, 9:16, 3–90 seconds, min 720p, H.264 + AAC |
| Rate limits | Depends on app tier; standard Graph API limits apply (~200 calls/hr per user token) |
| Gotchas | Long-lived page tokens expire every 60 days — need refresh flow. Our `meta_ig.py` adapter likely already handles this; check if it covers Page tokens vs. User tokens. |
| Effort | Low — our meta_ig.py already handles Meta OAuth. Add `/{page-id}/video_reels` endpoint. ~1–2 days. |

### LinkedIn

| Attribute | Detail |
|---|---|
| Official video API | Yes — Community Management API (LinkedIn Marketing Developer Platform) |
| Auth model | OAuth2, Authorization Code flow |
| Access requirement | LinkedIn Partner review required for full Community Management API. Development tier available immediately for testing (12-month window with call limits). Standard (production) requires vetting + use-case review. |
| Required permissions | `w_member_social`, `r_organization_social`, `rw_organization_admin` for org pages |
| Video format | MP4, H.264, AAC, 3 seconds–10 minutes, up to 5GB, max 4096×2304 |
| Rate limits | 100 API calls/day on Development tier; unrestricted on Standard |
| Gotchas | Access is gated behind Partner status — not self-serve for production. Application process: submit use case, integration description, expected API usage. Timeline 2–4 weeks typically. Video upload uses a 3-step chunked upload flow (registerUpload → binary upload → complete). |
| Effort | Medium — need LinkedIn Partner application first. API wiring after approval ~3 days. Total wall-clock: 2–4 weeks gating. |

### X / Twitter

| Attribute | Detail |
|---|---|
| Official video API | Yes — v2 Media Upload API |
| Auth model | OAuth2 (preferred) or OAuth 1.0a |
| Pricing (2026) | Pay-per-use as of Feb 2026. No free tier. No monthly plans for new signups. Posting a tweet costs $0.015; a tweet with a URL costs $0.20. |
| Video format | MP4, up to 512MB, max 140 seconds, 1280×720 minimum |
| Rate limits | 50 posts/24hr per user on Basic; higher on Pro (enterprise contract) |
| Gotchas | Cost math for volume posting: 1,000 video posts/month = ~$15–$200/month depending on URL presence. Old Basic ($200/mo) and Pro ($5,000/mo) subscription tiers are closed to new signups as of Feb 2026 — everyone is on pay-per-use credits now. Enterprise contracts (full archive search etc.) start at $42,000/month but are not needed for posting. |
| Effort | Medium-low technically (~2 days adapter), but economic model is hostile for automation at volume. Recommend low priority unless the client specifically requests X distribution. |

### Pinterest

| Attribute | Detail |
|---|---|
| Official video API | Yes — Pinterest API v5, Pins endpoint supports video |
| Auth model | OAuth2 Authorization Code (required for user-delegated actions; cannot use client credentials alone) |
| Required scopes | `pins:write`, `pins:read`, `boards:read`, `boards:write`, `user_accounts:read` |
| App review required | No upfront partner review — standard app creation and OAuth2 flow |
| Token expiry | Continuous refresh token (60-day expiration, indefinitely refreshable) |
| Video format | MP4, max 2GB, 4 seconds–15 minutes, min 240p |
| Rate limits | Standard API limits; no published hard cap for video pins |
| Gotchas | Pinterest organic video reach is lower than IG/TikTok for most niches; roofing content may underperform here. Best for before/after project boards. |
| Effort | Low — ~2 days for adapter. No partner review gating. |

### Snapchat

| Attribute | Detail |
|---|---|
| Official video API | Yes — Snapchat Publisher API / Snap Kit |
| Auth model | OAuth2; requires a Snapchat Business or Creator account (personal accounts cannot post via API) |
| Required account | Business Account or verified Creator account |
| Video format | MP4, max 500MB, 5–60 seconds, 1080×1920 (9:16 vertical only) |
| Content types | Stories (24-hour ephemeral) and Spotlight (permanent, discovery feed) |
| Rate limits | Not published; practical limit is posting cadence appropriate for the platform |
| Gotchas | Every post requires a video — no text-only or image-only via API. Stories disappear in 24 hours. Snapchat Spotlight is their TikTok competitor and has better discovery potential. |
| Effort | Medium — need business account setup + Snap Kit app review. ~3 days once approved. |

### Threads (Meta)

| Attribute | Detail |
|---|---|
| Official video API | Yes — Threads API (Meta, official 2024+, expanded 2025) |
| Auth model | OAuth2, same Meta developer app infrastructure as Instagram |
| Video format | MP4 or MOV, up to 5 minutes, publicly accessible URL required (not direct upload — must pre-upload to GCS/CDN and pass URL) |
| Rate limits | 250 posts per 24-hour period per user |
| Publishing flow | Two-step: create media container → publish (same pattern as IG Reels) |
| App review required | Yes, but same Meta app as Instagram/Facebook — if we already have IG approved, Threads is additive |
| Gotchas | Media must be hosted at a publicly accessible URL. GCS public bucket or presigned URL needed. Carousel posts up to 10 items supported. |
| Effort | Low — reuses Meta app already in place. ~1.5 days to add Threads endpoint to meta_ig.py or a new adapter. |

### YouTube Shorts (Upload)

| Attribute | Detail |
|---|---|
| Official video API | Yes — YouTube Data API v3, `videos.insert` |
| Auth model | OAuth2, Authorization Code flow |
| Required scopes | `https://www.googleapis.com/auth/youtube.upload` |
| Shorts detection | YouTube auto-classifies as Short when video is ≤60 seconds and 9:16 aspect ratio (or uses `#Shorts` in title) |
| Format | MP4, H.264, AAC, up to 256GB or 12 hours; for Shorts: ≤60s, 9:16 |
| Rate limits | 10,000 quota units/day by default; `videos.insert` costs 1,600 units (≈6 uploads/day on free quota). Request quota increase via Google console. |
| App review | Needs OAuth consent screen verification for publishing to non-test accounts |
| Gotchas | Quota is the main constraint — need to request increased quota. We have `youtube_stats.py` and `youtube_comments.py` already; we likely already have an approved OAuth app. Check if upload scope is included. |
| Effort | Low-medium — 2 days to add upload endpoint; quota increase request may add 1–2 weeks of wall-clock. |

### Bluesky

| Attribute | Detail |
|---|---|
| Official video API | Partial — AT Protocol supports video via blob upload, but video support in the Bluesky app is newer (2024) and third-party API support is still maturing |
| Auth model | AT Protocol — App Passwords (not OAuth2). Users generate an app password in Bluesky settings. |
| Video format | MP4, H.264, max 50MB, ≤60 seconds |
| Rate limits | Not published |
| Gotchas | Very small audience for roofing content. Platform primarily text/image heavy. Video upload requires uploading as blob then attaching to post record — more complex than Meta APIs. No official SDK. |
| Effort | Medium-high (~3 days). Low ROI for roofing niche. Not recommended near-term. |

### Amazon (Video)

| Attribute | Detail |
|---|---|
| Relevant service | Amazon Live (live streaming) or Amazon Posts (image/video for sellers) |
| Relevance to roofing | Very low — Amazon Live/Posts is primarily for product sellers with Amazon listings |
| Recommendation | Skip entirely for this use case. |

---

## 4. Platform Support Recommendation Order (Roofing Content Client)

Ordered by: audience reach × content fit × engineering effort × API friction.

| Priority | Platform | Rationale |
|---|---|---|
| P1 | **Instagram Reels** | Already have. Highest ROI for roofing — visual transformations, project reveals, local brand building. |
| P2 | **TikTok** | Already have. Strong discovery for local service content; before/after videos perform well. |
| P3 | **YouTube Shorts** | High search intent; homeowners search "roof repair cost" etc. Our channel already archived. 2 days + quota increase. |
| P4 | **Facebook Reels / Pages** | Meta ecosystem — existing homeowner demographic. Reuses our Meta app. 1–2 days. |
| P5 | **Threads** | Reuses Meta app, minimal extra effort. Growing platform, Meta algorithm lift from IG cross-post. 1.5 days. |
| P6 | **LinkedIn** | Best for B2B positioning (insurance adjusters, property managers, commercial roofing). Partner approval adds lead time. Worth applying now. |
| P7 | **Pinterest** | Good for project galleries / before-after boards. No partner friction. 2 days. Lower urgency. |
| P8 | **Snapchat** | Lower homeowner reach than other platforms; useful for 25–34 age bracket. Business account needed. 3 days. |
| P9 | **X / Twitter** | Hostile API pricing model for automation; low organic reach for local service content. Deprioritize unless client specifically requests. |
| Skip | **Bluesky** | Minimal audience for roofing niche. |
| Skip | **Amazon** | Irrelevant to roofing service business. |

**Recommended near-term sequence:** YouTube Shorts → Facebook Reels → Threads → LinkedIn application (start process now, implement when approved) → Pinterest.

---

## 5. Auth Architecture Note

All the new platforms use OAuth2 Authorization Code with refresh tokens. The pattern should be:
- Store per-tenant, per-platform `(access_token, refresh_token, expiry)` in a `PlatformCredential` table (or equivalent)
- Implement a single `refresh_token_if_needed()` utility reusable across adapters
- Our existing `meta_ig.py` likely already models this — extend the pattern

Meta (Facebook + Threads) tokens: 60-day refresh cycle.
LinkedIn tokens: 60-day access, 365-day refresh.
Pinterest tokens: 60-day continuous refresh, indefinitely refreshable.
X tokens: No expiry on OAuth2 app tokens, but pay-per-use economics dominate.

---

*Sources: [repurpose.io](https://repurpose.io/), [tooljunction.io/ai-tools/repurpose-io](https://www.tooljunction.io/ai-tools/repurpose-io), [developers.facebook.com/docs/video-api/guides/reels-publishing](https://developers.facebook.com/docs/video-api/guides/reels-publishing/), [learn.microsoft.com LinkedIn Videos API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api?view=li-lms-2026-06), [xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/), [developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization](https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/), [businesshelp.snapchat.com](https://businesshelp.snapchat.com/s/topic/0TO0y000000cYW0GAM/snapchats-api), [zernio.com/blog/threads-api](https://zernio.com/blog/threads-api), [posteverywhere.ai/blog/post-to-threads-api](https://posteverywhere.ai/blog/post-to-threads-api)*
