# Perkins Roofing Video Platform — v2 Design Spec

**Date:** 2026-07-04 · **Author:** DeGenito (Jon) · **Status:** approved for phased build

Expands the dev-verified core POC (`app/`, 161 videos, SQLite/Ollama) into a multi-user,
multi-tenant-clean platform in the client's own GCP. Reconciles 11 requirements into 5
dependency-ordered waves. Externally-blocked pieces are built behind interfaces and flipped
live as creds/approvals land (creds expected Mon 2026-07-06).

## Settled decisions

| Topic | Decision |
|-------|----------|
| LLM + embeddings (prod) | **Vertex Gemini for everything** — email proofing, Content-Graph extraction, article gen. No Anthropic key; all AI spend on Tim's GCP. |
| Embeddings migration | **Re-embed all 832** with the single prod model. Existing 161 Ollama/`nomic` dev vectors are throwaway (no mixing models in one index). |
| Corpus | Transcribe **all 832** incl. 648 Shorts; **VAD-skip** near-silent Shorts to bound STT cost. |
| Auth | **Firebase Auth (Google sign-in) + custom claims** → roles `admin` / `sales`; verified server-side in FastAPI. GCP on perkinsroofing.net (Jon = Workspace admin). |
| Coverage gate | **97% on core-logic modules**; I/O adapters omitted via `.coveragerc`. GitHub Actions gating. |
| Scheduling | One `scheduled_content` table (`publish_at`, `status`, editable) + **Cloud Scheduler cron** promoter. Shared by articles + reels. No durable-workflow engine. |
| Articles | Adapt **DeGenitoAI/seo-aio** patterns (pillar+cluster, answer-first, FAQ-from-PAA, JSON-LD) → **WordPress REST**. |
| Email | Compose/paste in-app → **Gemini proofread** → send via **Resend**, `reply-to` = the user's own email. |
| Video | AI-proposed clip in/out (Content Graph) → **admin-approved** → **ffmpeg fuse** (Cloud Run Job) title+clip+closing → 9:16 1080×1920 → **public GCS URL**. |

## Architecture

```
                    Firebase Auth (Google sign-in, custom claims: admin|sales)
                                     │  verifies ID token
        Admin/Sales SPA  ───────────┤
        (Firebase Hosting)          ▼
                          FastAPI API service (Cloud Run) ── authz middleware
                            │ search/ask · email · articles · video · social · admin config
                            ▼
        Cloud SQL Postgres + pgvector ◄── Cloud Run JOBS (offline):
        (videos, segments, words,           • ingest+STT+embed
         graph, chunks, users/roles,         • ffmpeg render
         email_templates, articles,          • article generate/publish
         scheduled_content, social_posts)    • social publish
                            ▲
        Secret Manager (WP, Resend, Serper, Meta, TikTok, YouTube keys)
        GCS (media, rendered reels — public URLs) · Cloud Scheduler (cron: poll + promote)
        Vertex AI Gemini (LLM + embeddings) · Cloud STT v2 (transcription)
```

**Non-negotiables carried from the council review:** split serving from ingestion; canonical
versioned artifact model; transcript-source abstraction; hybrid retrieval; eval harness before
public release; cost guardrails; clean tenancy (all data/secrets in client GCP).

## Module boundaries (enables the 97% gate)

All external I/O moves behind thin adapter interfaces so pure logic is unit-testable and
adapters are `.coveragerc`-omitted:

- `adapters/` (omitted from coverage): `youtube.py`, `vertex.py`, `stt.py`, `wordpress.py`,
  `resend.py`, `meta_ig.py`, `tiktok.py`, `ffmpeg.py`, `firebase.py`, `secrets.py`.
- `core/` (97% gate): ingest orchestration, transcript normalize, graph extract, retrieval,
  answer/abstention, article planner (pillar/cluster), scheduler promoter, mini-series planner,
  authz rules, JSON-LD builders.

## Waves

### Foundation (buildable now — no creds)
- Repo restructure into `adapters/` + `core/` + `api/` + `jobs/`; keep existing logic, wrap I/O.
- **CI**: GitHub Actions — lint + `pytest --cov=core --cov-fail-under=97`; frontend build.
- **Firebase Auth** + role custom-claims; FastAPI dependency that verifies token + enforces role.
  Dev against the Firebase emulator; real project when P1 lands.
- **Vertex Gemini** backend (implement `llm.py` vertex stubs for chat + embeddings; mockable).
- **Admin/Sales SPA shell** (Vite/React on Firebase Hosting): role-gated nav, login, API client.
- Finish **Terraform** (Cloud SQL+pgvector, GCS, Cloud Run svc+jobs, Scheduler, Secret Manager,
  SAs, budget alert) + a `bootstrap.sh` that Jon runs post-billing.

### Wave 1 — Data completeness (Req 3)
- Enumerate full channel (yt-dlp); ingest remaining long-form + all 648 Shorts.
- **STT v2** adapter with **VAD pre-check** (skip near-silent). Transcript-source abstraction picks
  captions → STT fallback.
- **Re-embed all 832** with Vertex embeddings into Cloud SQL pgvector (HNSW). Runs as a Cloud Run Job.
- *Code now; live full run needs P1 (billing).*

### Wave 2 — Content engines (Req 5, 6, 7)
- **Email**: `email_templates` CRUD (admin) + compose UI (sales) → Gemini proofread endpoint
  (returns suggestions/diff) → **Resend** send with `reply-to` = current user's email.
- **Articles**: topics → **pillar+cluster plan** → generate (Vertex Gemini, seo-aio prompt patterns,
  answer-first, FAQ-from-PAA) with **YouTube `?t=` embeds + VideoObject/FAQPage/Article JSON-LD** →
  **WordPress REST** publish (Markdown→HTML; JSON-LD via a ~15-line WP **mu-plugin** echoing post-meta
  in `wp_head`). Admin sets WP URL+key (staging now, prod on confirm).
- **Scheduling**: `scheduled_content` rows default **unpublished** w/ editable `publish_at`; admin
  configures cadence; Cloud Scheduler cron promotes due rows (WP `status: future`→`publish`).
- *WP staging creds exist; email needs P4/Resend key.*

### Wave 3 — Video pipeline (Req 8, 9, 11)
- **Extraction**: yt-dlp pull source video; clip by in/out timecodes.
- **Mini-series planner**: rank **longest/most-robust** videos (Content Graph density) → propose
  **4-7 part** series w/ per-part in/out → **admin-approved** in UI.
- **Render**: admin uploads title + closing screens → **ffmpeg fuse** (Cloud Run Job), normalize to
  9:16 1080×1920 + loudness → output to **public GCS URL**. Idempotent, keyed by series+part.

### Wave 4 — Social publishing (Req 10 — blocked on P2/P3 + app review)
- `meta_ig.py` + `tiktok.py` adapters behind a `SocialPublisher` interface; reuse Wave-2 scheduler
  for daily cadence across IG + TikTok. Placeholder creds + sandbox now; live after app review.
- IG: `instagram_content_publish` (public GCS video URL, 25/24h). TikTok: Content Posting API
  `video.publish` (post-audit for public). Idempotent (store returned post IDs).

## Data model additions
`users(uid, email, role, created_at)` · `email_templates(id, name, subject, body, created_by)` ·
`articles(slug, title, meta, content_md, faq_json, jsonld_json, role, pillar_slug, wp_post_id, status, publish_at)` ·
`scheduled_content(id, kind[article|reel], ref_id, publish_at, status, target)` ·
`social_posts(id, series_id, part, platform, gcs_url, external_id, status)` ·
`mini_series(id, video_id, title, parts_json, approved)`.

## Testing
- `core/` unit tests to **97%** (adapters mocked); gate in CI.
- Retrieval eval harness reused (citation precision, abstention) before any public go-live.
- Integration smoke: ingest→embed→search on a fixture video; article-plan→JSON-LD build;
  scheduler promote; ffmpeg render on a 5s fixture; each adapter has a contract test w/ a fake.
- Idempotency tests for publish (WP/IG/TT) — no double-post on retry.

## Prerequisites (Jon)
P1 GCP project + **billing** · P2 register Meta + TikTok apps (start audit Mon) · P3 all creds →
Secret Manager · P4 Resend acct + DNS verify · P5 named article author (E-E-A-T) · P6 confirm WP
SEO plugin (Yoast/RankMath).

## Out of scope / deferred
Competitor intelligence, comment-bot (ToS-flagged, consent-gated), ad-boost optimization,
dashboards/monthly reports, YouTube Analytics OAuth deep metrics.
