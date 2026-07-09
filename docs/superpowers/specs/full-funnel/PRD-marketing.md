# PRD — Marketing
**Section:** Marketing (sidebar group 2 of 4)
**Platform:** Perkins v2 multi-tenant full-funnel (GCP / Cloud SQL / GCS)
**Wave scope:** F1 (IA reorg), F5 (Track A UI wiring, tenant-ization of jobs/creds/brand kit)
**Status:** DRAFT (R2 fixes applied — pending Jon approval) — ground truth is `docs/superpowers/plans/2026-07-08-full-funnel-plan.md` v2

---

## 1. Purpose & product thesis fit

The Marketing section converts KB corpus into a full content funnel: short-form video clips, long-form SEO articles, social posts, email campaigns, and a publish pipeline that drips content systematically across platforms. The platform's differentiation over Opus Clip and repurpose.io is not feature parity — it is that we generate a complete funnel (clip → article → social → email → lead) grounded in the contractor's own video corpus, with Florida insurance-law content that competitors cannot replicate. We repurpose nothing; we generate from primary source material.

---

## 2. Personas & user stories

**P1 — Owner (Tim)**
- As the owner, I want clips extracted from my best videos and published to social media automatically, so I generate leads without adding to my workload.
- As the owner, I want avatar-driven educational videos on topics my archive covers, so I can own the Florida insurance-law content lane without re-recording.
- As the owner, I want to approve generated content before it goes live, so nothing crude or off-brand publishes without my consent.

**P2 — Staff admin (Josh)**
- As the staff admin, I want to edit clip titles, captions, and hashtags before publishing, so I can tune copy for each platform without re-rendering the video.
- As the staff admin, I want to view and manage the publish calendar, so I can control cadence and avoid content gaps.
- As the staff admin, I want to crawl YouTube comments, generate AI draft replies, and post approved replies, so community management is fast.

**P3 — Platform admin (DeGenito)**
- As the platform admin, I want each tenant's social credentials, brand kit, and caption prompts isolated and configurable, so licensee A's content never touches licensee B's accounts.
- As the platform admin, I want per-tenant usage metering on render minutes and LLM tokens, so the future licensee billing story is pre-wired.

---

## 3. Functional requirements

### 3.1 Clip Studio — Track A engine (existing engines; UI wiring in F5)

All Track A engines are built and 100%-covered (committed `b19b34b`). F5 wires them into the Clip Studio UI. Existing UI: `web/src/pages/ClipStudio.tsx`.

| # | Requirement | Engine | Priority |
|---|---|---|---|
| MKT-1 | **Viral-moment detection (A1):** from a selected video's transcript + content-graph, LLM scores candidate segments 0–99 on Hook/Flow/Value/Trend using a roofing-tuned rubric; returns top-N ranked clips with start/end/score/reason. | `core/clip_select.py` | Must |
| MKT-2 | **9:16 reframe + active-speaker tracking (A2):** ffmpeg crop to 9:16; auto-center on active speaker (MediaPipe class) with motion smoothing; static center-crop fallback to avoid multi-speaker head-cut bug. | `core/reframe.py` | Must |
| MKT-3 | **Word-highlight karaoke captions (A3):** word-level Whisper timestamps burned into animated captions with ≥2 brand styles; SRT/VTT export alongside rendered video. | `core/captions.py` | Must |
| MKT-4 | **Per-clip copy generation (A4):** platform-tuned title/hashtag/description for YT Shorts, TikTok, IG Reels from Josh's explicit prompts. Gated on Josh providing prompts (jarvis #315). | `core/caption_output.py` | Must |
| MKT-5 | **Brand intro/outro stitching (A5):** 1–2s intro + 5–10s social promo/outro concatenated per rendered clip. Intro/outro clips stored per tenant in GCS; uploaded via Admin → Marketing brand kit. | existing ffmpeg concat in render pipeline | Must |
| MKT-6 | **Speech cleanup (A6):** detect and cut "um/uh"/stutters via transcript alignment before render. | `core/speech_cleanup.py` | Should |
| MKT-7 | **B-roll overlay (A7):** Pexels stock video keyed to transcript context inserted as overlay cuts. AI-image generation is explicitly deferred (too hit-or-miss even at Opus Clip). | `core/broll.py` | Could |
| MKT-8 | **Music mix (A8):** background music mixed at configurable level using **royalty-free catalog only** (Pixabay / YouTube Audio Library / Free Music Archive). No licensed or "royalty-reduced" catalogs. Music catalog configured per tenant in Admin → Marketing. | `core/music_mix.py` | Should |
| MKT-9 | **FX / transitions (A9–A11):** clip-level transitions and visual effects. | `core/clip_fx.py` | Should |
| MKT-10 | Clip Studio UI: video picker → suggested clips list (editable title/caption/hook/reason) → include/exclude toggle per clip → render trigger → render status polling → rendered series listed for distribution. Existing UI extended with Track A controls (reframe toggle, captions style, music on/off, intro/outro toggle). | `ClipStudio.tsx` | Must |
| MKT-11 | Content-safety gate (E1): every rendered clip's generated copy (caption, hashtag, description) passes `core/content_safety.py` (denylist regex + LLM-judge) before the clip is eligible for distribution. Gate is fail-closed: a judge timeout or error blocks the clip for human review, never silently passes. | `core/content_safety.py`, `adapters/safety.py` | Must |
| MKT-12 | Video approval queue (`VideoApproval.tsx`): clips blocked by safety gate or flagged for human review appear here with reason; reviewer approves or dismisses. | existing `VideoApproval.tsx` | Must |

### 3.2 Articles & SEO (existing: `Articles.tsx`, `core/article_plan.py`, `core/article_prompt.py`, `core/seo.py`, `core/serp_analysis.py`)

| # | Requirement |
|---|---|
| MKT-13 | Article generation: select a topic → LLM generates a long-form article grounded in that topic's corpus chunks; article stored with `tenant_id`, `slug`, `status` (draft/approved/published/scheduled). |
| MKT-14 | Articles page: list with status badges, filter by status, inline Rank Math SEO check display, edit via TinyMCE WYSIWYG editor, approve, publish, or schedule. |
| MKT-15 | **Rank Math checks:** each article carries `focus_keyword`, `rank_math_score`, and structured Rank Math check results (keyword in title/slug/meta/first-paragraph/headings/image-alt, keyword density, internal links, content length, readability). Score and checks displayed inline. |
| MKT-16 | **SEO — AIO answer block:** every generated article leads with a 40–60 word plain-declarative answer block (spec §5, D6). Long-tail 8+ word queries are ~7× likelier to trigger an AI Overview; "near me" rarely does — the answer block is mandatory for all pillar and cluster articles. |
| MKT-17 | **SEO — FAQPage JSON-LD on articles:** each article carries FAQPage schema (reuses `core/jsonld.py`) derived from the FAQ entries linked to the same topic. |
| MKT-18 | **Pillar/cluster data model:** `clusters` table (pillar + status: pending/active/completed) + `articles.cluster_id` + `role` (pillar/support) + `priority` + `scheduled_at`. The 10-pillar / ~54-cluster map from spec §9 is the seed data. |
| MKT-19 | **Seed publish:** on pipeline activation, publish top X% (configurable, default 55%) of publish-first ranked keywords immediately (D2). The ~13 publish-first articles listed in spec §9 are the default seed set. |
| MKT-20 | Articles carry `tenant_id`; article pipeline scoped to tenant; per-tenant Rank Math API key config in Admin → Marketing. |

### 3.3 Publish pipeline — pillar/cluster drip (existing: `core/publish_planner.py`, `jobs/publish_job.py`)

| # | Requirement |
|---|---|
| MKT-21 | **Drip engine:** Cloud Scheduler → Cloud Run Job drains `publish_queue` via `SELECT … FOR UPDATE SKIP LOCKED` (`core/publish_planner.py`); keeps N articles in-flight at all times ("always full"). Pillar article publishes before any of its cluster supports. Next cluster's pillar activates on cluster completion. |
| MKT-22 | No Redis. Postgres-as-queue (SKIP LOCKED) only. Cloud SQL is already running; Redis added only if sub-second fan-out is required (it is not for article drip). |
| MKT-23 | `SKIP LOCKED` is the double-publish safety mechanism; `jobs/publish_job.py` is idempotent on retry (status check before write). |
| MKT-24 | Publish pipeline records are tenant-scoped (`tenant_id`); `for_each_tenant()` job wrapper (F5) ensures cron iterates all tenants safely. |
| MKT-25 | Pipeline status visible in Admin → Marketing config tab: active pillar, articles in-flight count, next-to-publish. |

### 3.4 Social / Distribution (existing: `adapters/distribution/`, `core/publish_dispatch.py`, `jobs/distribute_job.py`)

| # | Requirement |
|---|---|
| MKT-26 | **Platform coverage:** YouTube Shorts (Must), Facebook Reels/Video (Must — where OAuth creds exist); TikTok (Should — blocked on app review, jarvis #315), Instagram Reels (Should — blocked on app review, jarvis #315), LinkedIn (Should — blocked on app review, jarvis #316), X/Twitter (Should — $200/mo API cost must be confirmed by Jon/Tim before enabling), Pinterest (Could), Snapchat Spotlight (Could), Threads (Could). IG/TikTok/X must not be shipped as Must-tier until their respective credential and app-review blockers resolve. |
| MKT-27 | **Caption v5 JSON contract:** distribution job consumes `core/caption_output.py` v5 JSON output (fields: `platform`, `text`, `hashtags`, `cta`). The caption struct has **no** `safety_verdict` field — safety is evaluated separately by `gate_caption()` in `core/content_safety.py`, which returns a `(verdict, reason)` tuple independently of the parsed caption. v3 fallback supported during transition. |
| MKT-28 | **Content-safety gate on distribution:** `distribute_job` calls `gate_caption()` and checks the returned verdict; BLOCK halts distribution to all platforms and routes clip to video approval queue; REVIEW requires human approval before dispatch; OK proceeds. Gate is fail-closed: a judge timeout or error returns BLOCK, never OK. The verdict is not embedded in the caption struct — it is a separate gate result. |
| MKT-29 | **OAuth token store (C1):** per-tenant, per-platform OAuth token storage in Secret Manager under `tenants/{tenant_id}/…`; auto-refresh logic per platform spec. |
| MKT-30 | **Publish job queue (C2):** per-platform rate-limit aware, retry with exponential backoff, status: PENDING / IN_FLIGHT / PUBLISHED / FAILED. |
| MKT-31 | **CDN hosting for Meta container-creation flow (C3):** GCS signed URLs for Meta video container-creation API (IG/FB require URL-based upload). |
| MKT-32 | **Auto-transcode (C4):** auto-resize/transcode rendered clip to each platform's spec (9:16, H.264/AAC, platform-specific length caps) before dispatch. |
| MKT-33 | **Fan-out workflow (C5):** one approved clip → fan out to all selected destination platforms, hands-off. Staff selects target platforms per series; default = all enabled platforms for the tenant. |
| MKT-34 | **Per-platform copy customization (C6):** per-platform caption/hashtag with variable interpolation (location, product, crew name). Platform defaults from Josh's prompts; overridable per clip. |
| MKT-35 | **Content calendar (C7):** scheduled distribution view by date/platform; manual reschedule. Scheduling page (`Scheduling.tsx`) extended with distribution calendar. |
| MKT-36 | **Per-platform analytics pull (C9):** views/engagement/reach pulled per post on cron; displayed on Opportunities page and per-video in Archive. |
| MKT-37 | Social credentials are per-tenant; platform_admin can configure on behalf of a tenant. **No cross-tenant credential access.** |

### 3.5 Comments (existing: `Comments.tsx`, `core/comments.py`, `adapters/youtube_comments.py`)

| # | Requirement |
|---|---|
| MKT-38 | **Comment crawl:** YouTube comment crawl triggered on demand or on cron; comments stored with `video_id`, `author`, `text`, `published_at`, `needs_reply`, `status` (pending/drafted/ready/posted/dismissed). |
| MKT-39 | **Draft reply generation:** LLM generates a draft reply per comment requiring a response; staff reviews, edits, and approves. |
| MKT-40 | **Post reply:** approved replies posted via `adapters/youtube_comments.py::post_reply` (YouTube Data API `youtube.force-ssl` scope). Blocked on channel owner authorizing the OAuth token (jarvis #316). |
| MKT-41 | Comment reply copy passes through content-safety gate before posting. |
| MKT-42 | Comments page: filter by status and `needs_reply` flag; paginated; inline edit + approve + post; regenerate draft action. |
| MKT-43 | Comment records carry `tenant_id`. |

### 3.6 Email (existing: `Email.tsx`, `ComposeEmail.tsx`, TinyMCE)

| # | Requirement |
|---|---|
| MKT-44 | Compose email with TinyMCE WYSIWYG editor; recipient selection; signature modal (copy-from-user); send or schedule. |
| MKT-45 | Email scheduling: `Scheduling.tsx` handles scheduled sends with `kind='email'`; status PENDING / SENT / FAILED. |
| MKT-46 | "Include in email" action from Search/Ask page pre-fills email body with sourced KB answer for staff follow-up. |
| MKT-47 | Email records and drafts carry `tenant_id`; Google Workspace delegation scoped per tenant (keyless DWD, IAM signJwt). |

### 3.7 AI Presenter — Tim avatar (Track F; `core/avatar_script.py`)

| # | Requirement | Priority |
|---|---|---|
| MKT-48 | **Voice clone (F1):** ElevenLabs Professional Voice Clone from Tim's archived audio. Tim consent on record per ElevenLabs ToS. Cloud API only; no cerberus. | Should |
| MKT-49 | **Avatar video (F2):** script → HeyGen talking-head video via cloud API. | Should |
| MKT-50 | **Topic-driven generation (F3):** Tim selects a topic → `core/avatar_script.py` generates grounded script from corpus chunks → content-safety gate → avatar render → enters approval queue. | Should |
| MKT-51 | **First avatar demo topic (F4):** roof-age/insurance-nonrenewal survival guide (spec §8.F4 — highest-ranked blue-ocean gap). | Could |
| MKT-52 | HeyGen API key and ElevenLabs API key stored per tenant in Secret Manager. | Should |

### 3.8 Admin — Marketing config tab (plan §7)

| # | Requirement |
|---|---|
| MKT-53 | Config tab fields: brand kit (logo, colors, fonts, intro-outro clip upload), voice samples (ElevenLabs), caption prompts (v5 format, per platform), publish cadence (drip N in-flight), seed % (default 55%), social account OAuth connections, safety-gate denylist (additions to global list), Rank Math API key, music catalog (royalty-free only — Pixabay / YT Audio Library / FMA). |
| MKT-54 | Brand kit assets stored in GCS `tenants/{tenant_id}/brand/`; config stored in `tenants.settings` JSONB. |
| MKT-55 | Music catalog management: upload or link royalty-free tracks; system rejects upload if a track lacks a confirmed royalty-free license declaration. Licensed or "royalty-reduced" tracks must not be added. |
| MKT-56 | Platform_admin can view and edit any tenant's Marketing config. Per-tenant social creds are isolated in Secret Manager; platform_admin never sees raw tokens. |

### 3.9 Opportunities (existing: `Opportunities.tsx`)

| # | Requirement |
|---|---|
| MKT-57 | Opportunities page surfaces: un-clipped high-scoring videos, un-written topic articles, unanswered FAQs, un-deployed social posts — ranked by potential impact. |
| MKT-58 | Topic-to-cluster action on Opportunities triggers article generation for a selected cluster keyword and enqueues it in the publish pipeline. |
| MKT-59 | Opportunities data is tenant-scoped. |

---

## 4. Acceptance criteria

| Criterion | Testable condition |
|---|---|
| AC-MKT-1 | Select a video in Clip Studio, trigger clip detection, receive ≥1 ranked clip with start/end/score; render one clip with captions + intro/outro; rendered video plays correctly. |
| AC-MKT-2 | Clip caption containing a term on the content-safety denylist is blocked (verdict=BLOCK); the clip routes to the video approval queue and does not appear in the distribution queue. |
| AC-MKT-3 | LLM-judge timeout during safety check produces verdict=BLOCK (fail-closed), never OK. |
| AC-MKT-4 | Approved clip fans out to ≥2 configured platforms; distribute_job records PUBLISHED status per platform; Analytics pull returns engagement data for posted content. |
| AC-MKT-5 | Generating a pillar article produces: AIO answer block (40–60 words, declarative), FAQPage JSON-LD, Rank Math score display, focus keyword present in title/slug/meta. |
| AC-MKT-6 | Drip engine: with N=2 in-flight, after one article publishes, the engine immediately enqueues the next without manual trigger; pillar publishes before its cluster supports. |
| AC-MKT-7 | Avatar workflow: topic selected → script generated grounded in corpus chunks → safety gate PASS → HeyGen render triggered (mocked in test) → result enters approval queue. |
| AC-MKT-8 | Music track uploaded without royalty-free license declaration is rejected by the system. A confirmed royalty-free track is accepted and appears in the clip music picker. |
| AC-MKT-9 | Tenant A's social credentials, brand kit, and publish queue are inaccessible from tenant B's session (ORM filter + RLS post-F4). |
| AC-MKT-10 | Core coverage ≥ 97% (enforced at 100%) for all Track A core modules (`clip_select`, `reframe`, `captions`, `speech_cleanup`, `broll`, `music_mix`, `clip_fx`, `caption_output`, `content_safety`, `publish_planner`, `publish_dispatch`, `avatar_script`, `seo`, `article_plan`, `article_prompt`); behavioral tests confirm safety gate fail-closed on timeout. |
| AC-MKT-11 | Mobile: staff can navigate to Clip Studio, select a video, approve a clip, and trigger distribution from a phone-size viewport (responsive requirement, plan §2). |

---

## 5. Non-goals (explicit)

- No engagement-simulation bots (fake scroll/dwell to inflate signals — rejected in spec §5.D5; Google spam policy risk).
- No licensed, "royalty-reduced," or uncleared music. Royalty-free only (Pixabay, YouTube Audio Library, Free Music Archive).
- No AI-image b-roll generation in v1 (A7 is Pexels stock only; AI-image is Could/deferred — too hit-or-miss per Opus Clip's own warnings).
- No native iOS app in v1.
- No payment processing through the Marketing section.
- No engagement metrics manipulation or artificial boosting.
- No Snapchat/Threads distribution until app review is granted (Could tier).
- No accounting or QuickBooks integration.
- Cerberus (RTX 5090) is dev-only; all video/audio render and avatar generation in prod runs on cloud (Cloud Run / hosted APIs). No host-GPU dependency in prod.

---

## 6. Differentiators vs. Opus Clip and repurpose.io

| Capability | Opus Clip | repurpose.io | This platform |
|---|---|---|---|
| Clip source | Any video upload | Any source | Contractor's own 841-video corpus — grounded, not generic |
| Content grounding | Generic multimodal | None (repurpose only) | RAG from corpus → every article/caption is grounded in the contractor's documented expertise |
| Florida insurance-law content | None | None | Full pillar/cluster map on Citizens, HVHZ, HB 1611, 25% rule, wind-mit discounts — blue-ocean moat |
| Full funnel | Clips only | Distribution only | Clip → article → social → email → lead → quote — one platform, one funnel |
| AI Presenter | No | No | Tim avatar (HeyGen + ElevenLabs voice clone, consent on record) — personalised educational content at scale |
| Contract-FAQ | No | No | T&C → accessible consumer FAQ with JSON-LD |
| Music policy | Licensed (extra cost) | N/A | Royalty-free only — no licensing exposure for the contractor |
| Multi-tenant | No | No | Per-tenant corpus, creds, brand kit, metering — licensable product |

---

## 7. Multi-tenant considerations

- Social OAuth tokens stored per tenant in Secret Manager (`tenants/{tenant_id}/social/{platform}`); the distribution `oauth_store` interface already anticipates this (existing `adapters/distribution/`).
- Brand kit (logo, colors, fonts, intro/outro clips) stored per tenant in GCS `tenants/{tenant_id}/brand/`; loaded into render pipeline via tenant config at job time.
- Caption prompts (v5 JSON format), safety-gate denylist extensions, Rank Math key, music catalog, HeyGen/ElevenLabs keys — all in `tenants.settings` JSONB, editable in Admin → Marketing config tab.
- `for_each_tenant()` job wrapper (F5): publish pipeline, distribute job, comment crawl, analytics pull all iterate tenant list with `SET LOCAL app.tenant_id` and per-tenant cost counters. No job touches data outside a tenant context.
- Usage metering: LLM tokens (article gen, caption gen, safety judge, avatar script), render minutes (clip render, avatar render), STT minutes (for future re-transcription) — all emitted on structured-log path per tenant (plan §3.10).
- Per-tenant social app registrations: each licensee will need their own developer app credentials per platform; platform_admin provisions in Admin → Tenants.

---

## 8. Dependencies & open items

| Item | Owner | Blocks | Jarvis # |
|---|---|---|---|
| Josh's caption prompts (per platform, v5 format) | Josh | MKT-4, MKT-34 | #315 |
| IG / TikTok dev app registration + app review (2–4 wk) | Josh / DeGenito | MKT-26 (IG, TikTok) | #315 |
| Facebook / LinkedIn / X app review | DeGenito | MKT-26 (FB, LinkedIn, X) | #316 |
| YouTube reply OAuth token mint | Tim (channel owner action) | MKT-40 | #316 |
| Tim intro/outro clips + voice samples | Tim | MKT-5 (intro/outro), MKT-48 (voice clone) | #317 |
| Royalty-free music catalog population | DeGenito / Jon | MKT-8, MKT-53, MKT-55 | #325–326 |
| Pexels API key | DeGenito | MKT-7 (b-roll) | #327 |
| HeyGen API key | DeGenito | MKT-49 | #328 |
| ElevenLabs API key | DeGenito | MKT-48 | #329 |
| Seed % confirmation (default 55%) | Jon | MKT-19 | spec D3 (open) |
| Rank Math keyword-density refine loop + batch article regen | Engineering | MKT-15, carried over | task 27 |
| F5 wave: `for_each_tenant()` job wrapper + per-tenant brand kit | Engineering | All multi-tenant Marketing jobs | — |
| Cloud Run GPU / hosted upscaler for video cleanup (B2) | Engineering (F5) | MKT-2 quality (not blocking) | — |

**Open questions not resolvable from available sources:**
1. Seed % for drip pipeline: plan says "configurable, default ~50–60%" (spec D3 unresolved). Recommend 55% as default; confirm with Jon.
2. X/Twitter distribution: API v2 costs $200/mo Basic or pay-per-use. Confirm Jon/Tim are willing to absorb this before enabling X as a Must-tier platform for Perkins (vs. Should).
3. Per-tenant social app registrations for licensees: does each licensee bring their own developer app credentials, or does DeGenito run a shared app (Meta app review implications)? Affects tenant onboarding complexity.
4. Bulk upload → staggered distribution (C10): is this required before launch for Perkins, or a Should for licensees only?
