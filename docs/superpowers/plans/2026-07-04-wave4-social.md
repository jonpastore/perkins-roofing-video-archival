# Wave 4 — Social Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Call sequences below are from the current official docs (verified 2026-07-04) and are executable; live posting is gated on app review (P2/P3).

**Goal:** Publish rendered 9:16 reels (from Wave 3) to Instagram Reels and TikTok on the shared scheduler cadence, from a public GCS URL, idempotently.

**Architecture:** `meta_ig.py` + `tiktok.py` adapters behind a single `SocialPublisher` interface; the Wave-2 scheduler promotes due `kind=reel` rows to the publisher. Both platforms ingest by **public URL** (the GCS reel URL). Live posting is blocked on Meta App Review + TikTok app audit; until then, sandbox/self-view only.

**Tech Stack:** Instagram Graph API (`graph.instagram.com`), TikTok Content Posting API (`open.tiktokapis.com`), Secret Manager (tokens), the Wave-3 public GCS URL.

## Global Constraints
- Inherits Wave 0 constraints. Both APIs ingest via **public HTTPS URL, no redirects** — use the Wave-3 GCS reel URL directly.
- **Idempotency:** store returned external IDs in `social_posts(id, series_id, part, platform, gcs_url, external_id, status)`; never re-post a row with a non-null `external_id`.
- Reel artifact already meets both platforms' specs (Wave-3 render: 9:16, H.264, ≤300s, ≤300MB, faststart).
- **Music-clean** title/closing (licensed source audio gets flagged/muted on IG/TT).
- Blocked-on: **P2** (register Meta + TikTok apps, start review Mon 2026-07-06), **P3** (tokens → Secret Manager).

---

### Task 1: `SocialPublisher` interface + `social_posts` table
**Files:** Create `core/social.py`, migration for `social_posts`; Test `tests/core/test_social.py`
**Interfaces:**
- `core/social.py: class SocialPublisher(Protocol): def publish(self, *, video_url, caption, idempotency_key) -> str` (returns external post id). `def already_posted(rows, series_id, part, platform) -> bool` (pure idempotency guard).
- [ ] Test `already_posted` returns True when a matching row has a non-null `external_id`. Implement. Commit.

---

### Task 2: Instagram Reels adapter (3-call sequence)
**Files:** Create `adapters/meta_ig.py`; Test `tests/adapters/test_meta_ig.py` (mocked HTTP)
**Interfaces:** `adapters/meta_ig.py: class IgPublisher(SocialPublisher)` using `graph.instagram.com/v21.0`, a **permanent System User token** (Secret Manager), `ig_user_id`.

**Exact sequence (from docs):**
1. **Create container:** `POST /{ig_user_id}/media` — params `media_type=REELS`, `video_url=<GCS URL>`, `caption`, `access_token`. → returns `{id: container_id}`.
2. **Poll status:** `GET /{container_id}?fields=status_code&access_token=…` once/min, ≤5 min. Values: `IN_PROGRESS` → keep polling; `FINISHED` → proceed; `ERROR`/`EXPIRED` → abort, create a new container (do not retry same id).
3. **Publish:** `POST /{ig_user_id}/media_publish` — params `creation_id=container_id`, `access_token`. → returns `{id: ig_media_id}`.

**Limits/handling:** 50 publishes/24h moving window (check `GET /{ig_user_id}/content_publishing_limit`). Scopes (Facebook-Login path): `instagram_content_publish` + `instagram_basic` + `pages_read_engagement`, all **Advanced Access** (App Review + Business Verification + screencast).

- [ ] Test the 3-call sequence against mocked responses (container → FINISHED → publish returns id); test `ERROR` aborts; test rate-limit path. Implement. Commit.

---

### Task 3: TikTok adapter (init PULL_FROM_URL → poll)
**Files:** Create `adapters/tiktok.py`; Test `tests/adapters/test_tiktok.py` (mocked HTTP)
**Interfaces:** `adapters/tiktok.py: class TikTokPublisher(SocialPublisher)` using `open.tiktokapis.com`, OAuth access token (+ refresh) + `open_id` (Secret Manager).

**Exact sequence (from docs):**
1. **Init:** `POST /v2/post/publish/video/init/` with body `{post_info:{title, privacy_level, disable_*: false, video_cover_timestamp_ms}, source_info:{source:"PULL_FROM_URL", video_url:<GCS URL>}}`. → returns `{data:{publish_id}}` (`upload_url` null for PULL_FROM_URL — no upload step).
2. **Poll:** `POST /v2/post/publish/status/fetch/` body `{publish_id}` (≤30/min). Status: `PROCESSING_DOWNLOAD` → keep polling; `PUBLISH_COMPLETE` → done (`publicly_available_post_id` after moderation); `FAILED` → read `fail_reason`. **No finalize step.**

**Limits/handling:** init 6/min; scope `video.publish`; **unaudited app forces `SELF_ONLY` + max 5 users/24h** — audit lifts this. Requires **domain/URL-prefix verification** (DNS TXT) for the GCS URL host so PULL_FROM_URL is allowed. Refresh token via `POST /v2/oauth/token/` grant_type=refresh_token.

- [ ] Test init (PULL_FROM_URL → publish_id) + poll to `PUBLISH_COMPLETE` + `FAILED` path against mocks. Implement token refresh. Commit.

---

### Task 4: Wire publisher into the scheduler + idempotency
**Files:** Modify `jobs/promote_job.py` (Wave 2), `core/scheduler.py`
**Interfaces:** For each due `kind=reel` row, resolve target platform(s), call the matching `SocialPublisher.publish(video_url=<GCS URL>, caption, idempotency_key=series+part)` **only if** `already_posted` is False; persist the returned `external_id` + set status `posted`.
- [ ] Test the promoter skips already-posted rows and records external ids. Implement. Commit.

---

### Task 5: Go-live checklist (post-review, manual)
Not code — the runbook run when P2/P3 land:
- [ ] Meta App Review approved (Advanced Access on the 3 scopes) + Business Verification; System User token minted → Secret Manager.
- [ ] TikTok app audited (`video.publish`) + GCS reel-bucket domain URL-prefix verified via DNS TXT; OAuth tokens → Secret Manager.
- [ ] Smoke: render one reel (Wave 3) → publish to IG + TikTok → confirm `external_id` stored, no double-post on re-run.

---

## Self-Review
- Spec coverage: IG + TikTok adapters behind `SocialPublisher` (T1-3) ✓ · reuse Wave-2 scheduler for cadence (T4) ✓ · public-URL ingestion (both) ✓ · idempotent via stored external ids (T1,4) ✓ · app-review/audit reality captured (T2,3,5) ✓.
- Exact endpoints/params/limits are current (2026-07-04). Live posting gated on P2/P3 + review — code + mocked tests build now.
- **Corrections folded in vs earlier notes:** IG limit is **50/24h** (not 25); server token is a **permanent System User token** (not a Page token); host is **`graph.instagram.com`**; TikTok Share Video API is deprecated → Content Posting API only.
