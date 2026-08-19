# TRD: Growth-stack in-repo support

## T1 — Daily articles switch
- `CONTENT_GEN_MODE` On writes `dump`, Off writes `off`.
- `GET /config/job-switches` includes `content_gen: bool`.
- Default Off if unset. Live DB may already be dump.

## T2 — Tim inbox items
- Pure `core.engagement_inbox.inbox_items` merges YouTube comments needing reply, unanswered PAA, and film-next questions.
- Kinds: `youtube_comment` | `paa` | `film`. Actions: `reply` | `answer` | `film`.
- PAA from a competitor scan persist as `comment_drafts` with `platform=paa`, `video_id=inbox`, `comment_id` = slug of the question. Idempotent upsert.

## T3 — Competitor page value
- `score_foreign_page(title, meta, html, keyword)` uses `score_article` + `aio_signals`.
- `is_valuable` is true only if named-entity AIO or fact-density passes — word count alone is not value.

## T4 — UI
- JobSwitches: “Daily articles” row.
- Settings table hides `CONTENT_GEN_MODE` (switch owns it).
- Comments page: platform filter All / YouTube / Questions. Post-to-YouTube hidden unless `platform=youtube`.
- Score chip (Opportunity / Heat / Coverage + help) on Opportunities, Topic Graph, Clip Studio, Archive, Comments.
- `GET /topic-graph/social-brief` includes `this_week` (max 5). Opportunities default is that queue.
- Clip Studio top list is Heat-ranked edit-down (`cut_for_social`). Approve requires town, problem, hook, audience, phone CTA, and 15–40s.
