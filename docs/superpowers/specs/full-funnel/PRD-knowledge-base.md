# PRD — Knowledge Base
**Section:** Knowledge Base (sidebar group 1 of 4)
**Platform:** Perkins v2 multi-tenant full-funnel (GCP / Cloud SQL / pgvector)
**Wave scope:** F0 (tenant columns), F1 (IA reorg), F5 (tenant-ization of corpus/jobs)
**Status:** DRAFT (R2 fixes applied — pending Jon approval) — ground truth is `docs/superpowers/plans/2026-07-08-full-funnel-plan.md` v2

---

## 1. Purpose & product thesis fit

The Knowledge Base is the corpus layer of the funnel. It ingests the contractor's entire video archive, extracts structured knowledge (STT → chunks → embeddings → topics → FAQs), and surfaces that knowledge to the owner, staff, and — through published FAQs and articles — the public web. Every downstream section (Marketing, Estimating, Quoting) draws from this corpus.

The KB is also the insurance-law content moat: no Florida roofing competitor runs a structured video corpus at this scale. The 841-video archive gives Perkins — and every future licensee — a grounding layer that generic AI tools (Opus Clip, repurpose.io) cannot replicate because they have no access to the contractor's own institutional knowledge.

---

## 2. Personas & user stories

**P1 — Owner (Tim)**
- As the owner, I want to ask a question in plain English and get an answer grounded in my own videos, so I can quickly recall job procedures, material specs, and code requirements without rewatching footage.
- As the owner, I want to see which topics my archive covers best and worst, so I can direct new content to fill gaps.

**P2 — Staff / sales (Josh)**
- As a sales rep, I want to search the archive for answers to a prospect's specific question (e.g., "does your HVHZ shingle qualify for a Citizens discount?"), so I can respond accurately in the field.
- As a staff admin, I want to trigger re-ingest or FAQ mining on demand, so fresh videos enrich the corpus without engineering involvement.

**P3 — Platform admin (DeGenito)**
- As the platform admin, I want to provision a new tenant with an isolated corpus, configure their channel sources, and set abstain thresholds, so each licensee's KB is scoped to their own content.

**P4 — Public web visitor (future)**
- As a homeowner, I want to find answers to common roofing questions on the contractor's website, so I can make informed decisions and contact the right company.

---

## 3. Functional requirements

### 3.1 Video corpus / archive ingest (existing: `Archive.tsx`, `web/src/pages/Archive.tsx`)

| # | Requirement |
|---|---|
| KB-1 | Ingest all videos from a configured YouTube channel (currently 832+); store video metadata, transcript (Whisper STT via cerberus dev / cloud STT in prod), duration, upload date, YouTube URL, KPI counters (views, likes, comment count). |
| KB-2 | Archive page displays per-video status: archived, transcript available, topics extracted, clips generated, articles generated, social posts generated, last pulled. Filterable by archived/topic/article/social tri-state flags and full-text search on title. |
| KB-3 | Per-video detail panel shows linked topics, articles, social posts with generation timestamps. |
| KB-4 | Manual trigger: re-ingest individual video (re-fetch metadata + KPIs); bulk ingest new channel videos on cron (auto-drain). |
| KB-5 | All archive records carry `tenant_id`; archive page shows only the current tenant's videos. |
| KB-6 | GCS audio/video assets stored under `tenants/{tenant_id}/…` prefix. |

### 3.2 STT, chunking, and embeddings

| # | Requirement |
|---|---|
| KB-7 | Transcripts produced by Whisper (cloud STT in prod, cerberus dev-only); stored per video; re-run on demand. |
| KB-8 | `core/chunking.py` splits transcripts into fixed-length overlapping chunks; each chunk embedded (Vertex text-embedding); stored in `chunks` table with `tenant_id` + pgvector column. |
| KB-9 | `chunks` table partitioned or indexed per-tenant; `tenant_id` FK + RLS policy enforced (post-F4). |
| KB-10 | Chunk pipeline idempotent: re-run on updated transcript overwrites existing chunks for that video. |

### 3.3 Topic graph (existing: `core/graph.py`)

| # | Requirement |
|---|---|
| KB-11 | `core/graph.py` clusters chunks into named topics; results stored in `content_graph` (GraphNode rows) and materialized into `aggregated_topics`; both carry `tenant_id`. |
| KB-12 | Topic list exposed on Search/Ask page with video count, content-length indicator, and link to topic-video modal. |
| KB-13 | Topic pagination (existing `topicOffset` / `TOPIC_PAGE_SIZE`); archive-specific cap confirmed. |

### 3.4 Search / Ask (existing: `SearchAsk.tsx`, `core/retrieval.py`, `core/answer.py`)

| # | Requirement |
|---|---|
| KB-14 | Semantic search: user query → embedding → ANN retrieval from `chunks` (HNSW pgvector) filtered to current tenant; returns ranked source snippets with video title, timestamp, and YouTube deep-link. |
| KB-15 | RAG answer: top-N chunks → LLM synthesizes a grounded answer with inline citations (video title + timestamp URL). |
| KB-16 | Abstain path: when confidence is below tenant-configurable threshold (Admin → Knowledge Base), response is `abstained=true` and the answer is suppressed; the UI shows a graceful no-answer state rather than a hallucinated one. Abstain threshold is a per-tenant Admin config (not a code constant). |
| KB-17 | Citations rendered as clickable timestamped links (existing `TimestampLink` component). |
| KB-18 | "Include in email" action on search results composes a pre-filled email body with sources for staff follow-up. |
| KB-19 | All retrieval is tenant-scoped: pgvector ANN filtered by `tenant_id`; after F4, RLS is the enforcement layer, ORM filter is the belt. |

### 3.5 FAQ generation & consolidation (existing: `Faq.tsx`, `core/faq_consolidate.py`, `core/jsonld.py`)

| # | Requirement |
|---|---|
| KB-20 | FAQ mining: LLM extracts question/answer pairs from video transcripts; stored in `faq_entries` table with `video_id`, `tenant_id`, `status` (pending / approved / published / dismissed). |
| KB-21 | Admin-trigger: "Mine FAQs" button (existing) runs `faq_consolidate` against un-mined videos in tenant scope. |
| KB-22 | FAQ list page: filter by status (all / answered / unanswered) + full-text search; inline answer editing; approve → publish action. |
| KB-23 | Published FAQs rendered with FAQPage JSON-LD schema (`core/jsonld.py`) for structured-data eligibility (AI Overview / rich result). |
| KB-24 | FAQ answers carry citation links in `[link n](url)` markdown form, rendered as clickable anchors (existing `renderAnswer`). |
| KB-25 | FAQ consolidation (`core/faq_consolidate.py`) deduplicates near-identical questions across videos before display. |
| KB-26 | All FAQ records carry `tenant_id`; FAQ page shows only the current tenant's items. |

### 3.6 Contract-FAQ (Track I — jarvis #321)

| # | Requirement |
|---|---|
| KB-27 | Parse Perkins T&Cs (PDF/DOCX upload) into clause segments; store as a separate corpus partition within the KB (`source_type='contract'`). |
| KB-28 | LLM converts each clause into a plain-English FAQ entry (question + accessible answer); stored in `faqs` with `source_type='contract'` and `tenant_id`. |
| KB-29 | Contract-FAQ entries pass through the same content-safety gate (`core/content_safety.py`) as video-derived FAQs before publishing. |
| KB-30 | Contract-FAQ reuses existing FAQPage JSON-LD and FAQ UI — no separate page. Contract-sourced entries are visually distinguished (badge) but share the same review/approve/publish workflow. |
| KB-31 | Re-parse on T&C update: uploading a new contract version re-runs clause extraction; prior contract-FAQ entries are marked `superseded` and excluded from public render. |

### 3.7 Admin — Knowledge Base config tab (plan §7)

| # | Requirement |
|---|---|
| KB-32 | Config tab fields: channel source URL(s), ingest schedule (cron expression), abstain threshold (0.0–1.0 float), FAQ policy (auto-mine on ingest: yes/no), content-safety denylist additions for KB context. |
| KB-33 | Changes to config are tenant-scoped; platform_admin can view/edit any tenant's KB config. |

---

## 4. Acceptance criteria

| Criterion | Testable condition |
|---|---|
| AC-KB-1 | A question answered by the video archive returns an answer with ≥1 citation; the citation link resolves to the correct video at the correct timestamp. |
| AC-KB-2 | A question outside the corpus (confidence below threshold) returns `abstained=true`; the UI shows a no-answer state; no hallucinated answer is displayed. |
| AC-KB-3 | A cross-tenant probe (tenant B's session token) returns 404-indistinguishable for tenant A's KB content (post-F4 gate). |
| AC-KB-4 | FAQ mining produces ≥1 FAQ per video that has a usable transcript; deduplication removes near-exact duplicates before display. |
| AC-KB-5 | Published FAQ page renders valid FAQPage JSON-LD (Google Rich Results Test passes). |
| AC-KB-6 | Contract-FAQ: upload a T&C PDF → clause extraction produces ≥1 FAQ per significant clause → entries appear in FAQ list with `contract` badge → approve → publish renders with JSON-LD. |
| AC-KB-7 | All `chunks`, `content_graph`, `aggregated_topics`, `faq_entries` records for tenant A are inaccessible from tenant B's session (ORM filter + RLS). |
| AC-KB-8 | Core coverage ≥ 97% (enforced at 100%) for `core/chunking.py`, `core/retrieval.py`, `core/answer.py`, `core/faq_consolidate.py`, `core/jsonld.py`, `core/graph.py`; behavioral test confirms abstain path triggers at threshold. |

---

## 5. Non-goals (explicit)

- No engagement-simulation bots (fake dwell, scroll simulation — plan §0).
- No public self-service signup for end-homeowners to create KB accounts (public FAQ is read-only web content).
- No real-time chat / streaming answer widget in v1.
- No multi-language transcript support in v1 (English only; Whisper lang detection disabled for cost).
- No LiDAR or drone-imagery corpus ingestion.
- Contract-FAQ does not replace legal counsel; the content-safety gate and human approval step are mandatory before any contract clause is published.

---

## 6. Differentiators

- **Corpus-grounded answers**: unlike ChatGPT or generic RAG tools, every answer cites the contractor's own recorded knowledge — zero hallucination risk on out-of-scope topics (abstain path).
- **Insurance-law content moat**: 841-video archive covering Florida wind-mitigation, HVHZ, Citizens requirements, HB 1611 RUL — no regional competitor has this grounded corpus.
- **Contract-FAQ**: surfacing T&C language as accessible consumer FAQs reduces support load and demonstrates transparency — no roofing CRM or competitor tool offers this.
- **Multi-tenant isolation**: each licensee gets a fully isolated corpus with per-tenant abstain thresholds and channel sources — the KB becomes a white-label product.

---

## 7. Multi-tenant considerations

- `tenant_id` FK on `chunks`, `content_graph`, `aggregated_topics`, `faq_entries`, `videos` (and contract-parsed clause segments). All enforced by ORM base filter (F0+) and RLS (F4+).
- GCS prefix isolation: `tenants/{tenant_id}/audio/`, `tenants/{tenant_id}/transcripts/`.
- Per-tenant `pricing_configs`-equivalent for KB: abstain threshold, channel sources, FAQ policy, safety-gate denylist — all in the `tenants.settings` JSONB (Admin → Knowledge Base config tab, KB-32).
- `for_each_tenant()` job wrapper (F5): ingest cron, FAQ-mine cron, embedding refresh all iterate tenant list, `SET LOCAL app.tenant_id`, reset per-tenant cost counters, drain.
- Per-tenant HNSW pgvector index; if tenant count grows, `chunks` partitioned by `tenant_id` (plan §3.9 scaling lever, not v1).
- Usage metering (plan §3.10): LLM tokens (answer generation, FAQ mining), STT minutes — logged per tenant on every structured-log event for future licensee billing.

---

## 8. Dependencies & open items

| Item | Owner | Blocks | Jarvis # |
|---|---|---|---|
| Social app reviews (IG, TikTok, etc.) | Josh / platform reviews | Marketing only, not KB | #315–316 |
| Voice samples / intro-outro clips | Tim | Marketing/Avatar, not KB | #317 |
| YouTube channel ingest creds | Josh (already connected) | KB-1 (already working) | — |
| FAQ prompt tuning (Josh's explicit prompts) | Josh | KB-20 quality, not blocking mine | #315 |
| T&C document upload (Contract-FAQ) | Tim / Josh | KB-27 (Track I) | #321 |
| Music catalog (royalty-free) | DeGenito | Marketing, not KB | #325–326 |
| Rank Math keyword-density refine loop | Carried over | Articles (Marketing PRD) | task 27 |
| Cloud SQL PITR enabled | Terraform (F4) | Multi-tenant contractual req | — |
| F4 RLS / GCIP hardening | Engineering | Full KB cross-tenant gate | — |
| pgvector ANN filter validation at scale | Engineering | AC-KB-7 + AC-KB-3 | — |

**Open questions not resolvable from available sources:**
1. Contract-FAQ scope: should clause parsing cover only Perkins standard T&Cs, or also per-job addenda? (Affects KB-27 upload UX; assume standard T&Cs only until Tim confirms.)
2. Abstain threshold default value: plan says "admin-configurable" but no default is specified. Recommend 0.5 as default; confirm with Jon.
