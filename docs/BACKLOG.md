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
