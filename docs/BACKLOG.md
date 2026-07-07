# Backlog — to scope later

Ideas captured for future scoping. Not yet planned into a wave.

## B1 — Continuous new-video monitoring → auto-ingest + content pipeline
**Idea (2026-07-04):** Monitor the channel for newly published videos and automatically run
them through the full pipeline: ingest (transcript → graph → embed) and then the
article/content/social generation process.

**Notes / feasibility:**
- Largely buildable on what already exists. `jobs/enumerate_channel.py` is idempotent and
  already upserts new videos (detects deltas). `jobs/ingest_worker.py` is resumable, so a
  scheduled run only processes the new ones.
- Wire it as a **Cloud Scheduler cron** (Wave 2 already introduces the scheduler + promoter):
  enumerate → ingest new → enqueue `scheduled_content` (article + reel) for the new videos →
  the existing promoter publishes on cadence.
- Open scoping questions: cadence (hourly/daily?), whether every new video auto-generates
  content or only admin-approved ones, and cost guardrails on the auto-generation step.
- Depends on: Wave 1 (ingest — DONE) + Wave 2 (content engines + scheduler) + Wave 3/4 (reels/social).

## B2 — Comment monitoring → AI-drafted answers → human-approved posting (ToS-safe)
**Idea (2026-07-04):** Monitor all YouTube videos in the channel for **unanswered comments**.
Have AI **evaluate whether a comment is a question that needs an answer**, and for those,
**draft an answer** and **queue it in a UI for a human to review, edit, and post**. The human
posts the response — the system never auto-posts.

**Why this is ToS-safe (important):** This is the human-in-the-loop, consent-gated version of
the "comment-bot" that the v2 spec lists under *out of scope* (ToS-flagged). Because a person
reviews and posts every reply, there is no automated posting / no bot behavior — which is what
keeps it within YouTube's Terms of Service. Keep that constraint as a hard requirement if scoped.

**Notes / feasibility:**
- Read side: YouTube Data API `commentThreads.list` per video (we already have a YouTube API
  key + `adapters/youtube.py`). Track which comments are already answered (by the channel) vs
  unanswered.
- Classify: reuse Vertex Gemini — a cheap classifier deciding "is this a question needing an
  answer?" (filter spam/praise/statements). Then draft a grounded answer using the **existing
  retrieval + abstention** stack (answer from Tim's videos, cite timecodes; abstain if unknown).
- Review UI: a new admin/sales queue in the SPA — comment, video context, AI draft, edit box,
  "mark reviewed" (human copies/posts, or a future *human-initiated* post action).
- Open scoping questions: how to reliably detect "unanswered", polling cadence + Data API quota
  cost (comment reads are quota-heavy across 841 videos), whether posting is manual-copy or a
  human-click action, and abstention policy for low-confidence drafts.
- Depends on: Wave 1 retrieval/answer (DONE) + a new comments adapter/table + SPA queue.

## B3 — Archive video detail: expandable topics, play buttons, and usage panels (Jon, 2026-07-05)
**Idea:** Turn each Archive row into a rich per-video detail view:
- **Play button next to the title** (opens the YouTube video).
- **Click the title → expand** the mined **topics + time references** for that video
  (`content_graph` kind=topics, 4,728 rows exist), each with a **play button that deep-links to
  that topic's timestamp** (`youtu.be/{id}?t={start}`).
- **"Used in Articles" panel** — every article whose content used this video. *Needs a
  video↔article linkage* (parse the `?t=` embeds in `articles.content_md`, or record the link at
  generation time in a join table). 
- **"Used in Social posts" panel** — social posts featuring this video, with links.
  Already queryable: `videos → mini_series.video_id → social_posts (series_id)` → `gcs_url`/
  `external_id`. Just needs an endpoint + UI.
- **Unanswered-comments column** — a count per video that, when clicked, opens the **B2** comment
  queue for that video (AI-draft → human approve → post back). Ties B3 ⇆ B2.

**Feasibility:** topics + social-usage + play buttons are buildable now (data + relations exist).
Article-usage needs a linkage mechanism. Comments column depends on B2.
**New API needed:** `GET /archive/{video_id}/detail` (topics, article-usage, social-usage,
unanswered-comment count).

## B4 — Pre-mined topic explorer → cluster-article generation (Jon, 2026-07-05)
**Idea:** The **"Search topics"** tab should not require a query — it should **pre-load the list of
extracted topics** we already mined (`content_graph` kind=topics), grouped/deduped with a count
of how many videos cover each. Each topic gets a **"Generate cluster article"** action that feeds
the topic into the existing article pipeline (`jobs/article_job.py`, seo-aio prompts) as a cluster
piece under a pillar. This operationalizes Req 7's pillar/cluster content strategy from real data.
**New API needed:** `GET /topics` (distinct mined topics + video counts + sample timecodes) and a
`POST /articles/generate` (topic → run the article pipeline → draft Article).

## B5 — FAQ extraction surface (Jon, 2026-07-05)
**Idea:** Requirement to **extract questions from the content for FAQ**. The objections/claims in
`content_graph` (3,655 claims, 1,574 objections) + `app/gen_faq.py` (FAQ JSON-LD builder) already
support this. Surface a **FAQ builder**: mined question/answer pairs (grounded, timecoded) that
feed each Article's `faq_json` + JSON-LD, and/or a standalone FAQ page. Ties into B4 (per-topic FAQ).

## B6 — Hardening backlog from the 2026-07-07 deep review
See [reviews/2026-07-07-deep-review.md](reviews/2026-07-07-deep-review.md) for the full pass.
These need a `terraform plan` / owner sign-off (infra was actively being edited), so they were
logged rather than hand-patched. Prioritized:

**Infra / IaC (fresh-apply + R3/R4):**
- `google-idp-client-secret`: seed a version + `depends_on` so a fresh `terraform apply`
  doesn't fail NOT_FOUND (or default `google_idp_client_id=""` until the secret is loaded).
- Move public access into Terraform: `google_cloud_run_v2_service_iam_member` `allUsers` →
  `roles/run.invoker`; drop `--allow-unauthenticated` from `scripts/deploy.sh` (R3-ENFORCE).
- `scripts/drift_check.sh`: pass the same `-var billing_account=…` as apply, and make the host
  playbook (`whisper.yml` vs `local_llm.yml`) a parameter so R4 can actually show changed=0.
- Scope `jobs-sa` `roles/storage.objectAdmin` to the `media` + `reels` buckets (least privilege).
- Add a `google_monitoring_notification_channel` (from `alert_email`), wire it into the billing
  budget `all_updates_rule`, and add a Cloud Run 5xx / job-failure log-based alert.
- Cloud SQL: enable `point_in_time_recovery_enabled` (+ retention); consider `REGIONAL` HA; then
  reconcile the "private IP only" docs with the actual public-IP+SSL config.
- Dockerfile: add a non-root `USER` and pin the base image by digest.

**Wiring / cost (jobs):**
- Wire `aggregate_topics` to a Cloud Scheduler → `/internal/aggregate-topics` (its table is
  consumed by topics/prime_backlog but nothing refreshes it).
- Fix or remove the `article` Cloud Run Job — its `__main__` needs topic+keyword args it isn't
  given, so any execution exits non-zero.
- Add a per-run cap to `poll_archive_kpis` (per-video comment API calls).

**R1 validations (behavioral checks for I/O jobs):**
- Add `scripts/validate_crawl_comments.py` and `scripts/validate_aggregate_topics.py` (and for
  `embed_job`, `backfill_metadata`, `enumerate_channel`, `consolidate_faqs`).

**Correctness / config:**
- `EMBED_MODEL` split-brain: config default `nomic-embed-text` vs adapter default
  `gemini-embedding-001` — make config fail-fast when `EMBED_BACKEND=vertex` with a non-Vertex
  model, and stamp `chunks.embed_model` from the embedder actually used.
- Recalibrate `ABSTAIN_THRESHOLD` against Vertex embeddings before go-live (0.71 is Ollama-tuned).
- `scheduling.py`: validate `kind ∈ {article, reel}` (currently a free string).
- `email.py`: strip single-quoted `href` in `_html_compliant` (only double-quoted handled).

## B7 — Comprehensive review round-2 (2026-07-07) deferred items
See [reviews/2026-07-07-comprehensive-review.md](reviews/2026-07-07-comprehensive-review.md).

**Frontend (web/):**
- Route-level `React.lazy()` + `Suspense` + Vite `manualChunks`; defer TinyMCE/Firebase — the
  SPA ships as one 1.7MB (563KB gzip) bundle to every role.
- Global 401/403 handling in `apiFetch` (re-login on refresh failure) + a top-level ErrorBoundary.
- `Scheduling.tsx` sends a timezone-naive `publish_at` → reels fire at UTC wall-time (use
  `localInputToIso` like the Articles modal).
- `Faq.tsx` "load more" has no `!r.ok`/`.catch` guard → unhandled rejection + skipped page on 500.
- Broken nav links: `Opportunities.tsx` `<a href="/video/proposals?...">` (hits the API route),
  `Settings.tsx` `<a href="/users">`, dead `href="#"` "Open in Clip Studio".
- Modal a11y: `role="dialog"`/`aria-modal`, focus trap, Escape-to-close, focus restore (Compose,
  Article, Topic modals); associate form `<label>`s with `htmlFor`/`id`.
- Paginate/virtualize the Archive + Articles lists (currently load the whole table).
- DOMPurify allow-list permits arbitrary `iframe`/`style` — restrict iframes to youtube.com/embed.

**Backend / infra:**
- `embed()` has no cost cap (only `chat()` does) — add an embed-item budget + query-embedding LRU.
- Inconsistent retry/backoff across HTTP adapters (only Vertex retries) — add a shared helper for
  idempotent GETs + guarded WordPress writes.
- Overlapping-cron double-publish risk in `promote_job`/`social_job` — `with_for_update(skip_locked)`
  or an advisory lock.
- `suggestions.py` O(videos × articles × content) substring scan — extract referenced ids via one
  regex pass per article.
- R1 gap: 12/20 jobs + 8/16 adapters have no behavioral test (highest-risk: archive_job,
  ingest_worker, consolidate_faqs).
- Reproducible builds: generate a hashed `requirements.lock` (deps are now bumped to latest floors
  but still `>=` ranges).
