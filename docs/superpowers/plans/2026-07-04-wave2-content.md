# Wave 2 — Content Engines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Tasks are at interface altitude — expand code-level steps at execution time once the relevant cred (Resend/WP/Serper) is loaded.

**Goal:** Ship three content engines — (1) in-app email compose with Gemini proofread + Resend send, (2) an SEO/AIO article generator ported from DeGenitoAI/seo-aio (Vertex Gemini + Serper + WordPress REST), and (3) a shared scheduler that promotes articles + reels on a cron.

**Architecture:** The seo-aio IP (~700-line `templatePrompt`, 309-line `systemPrompt`, SERP/PAA→FAQ injection, pillar+cluster strategy, 3-check QA gate) is **ported TS→Python and Claude→Vertex Gemini** — the prompts are ~60-70% of the value and port verbatim; the model wrapper, JSON-repair, and publishing are rebuilt. WordPress publishing is new (seo-aio publishes to Cloudflare KV). All external calls behind adapters.

**Tech Stack:** Vertex `gemini-2.5-flash` (+ `gemini-2.5-pro` for long articles), Serper.dev (SERP/PAA), Resend, WordPress REST, a WP mu-plugin for JSON-LD, `scheduled_content` table + Cloud Scheduler.

## Global Constraints
- Inherits all Wave 0 constraints. Email `reply-to` = the sending user's own email (replies flow to their normal client).
- Article JSON-LD (VideoObject + FAQPage + Article) is echoed by a ~15-line WP **mu-plugin** in `wp_head` (WP strips `<script>` from post content).
- Cross-client dedup + fact-check + intent QA gate runs before any publish (ported from seo-aio, fail-open with an audit flag).
- New creds: Resend (P4), WordPress Application Password (P6 confirm plugin), Serper (P3).

---

### Task 1: Vertex Gemini wrapper hardening + Gemini JSON repair
**Files:** Modify `adapters/llm.py`; Create `core/json_repair.py`; Test `tests/core/test_json_repair.py`
**Interfaces:** `core/json_repair.py: def parse_model_json(text: str) -> dict` (multi-pass: strip code fences, fix trailing commas, escape stray control chars — tuned for Gemini output, ported from seo-aio's `parseClaudeJson`). Article gen uses `want_json=True`.
- [ ] Test on canned Gemini outputs (fenced JSON, trailing comma, unescaped newline) → parses. Fails → implement → passes → commit.

---

### Task 2: Email — templates CRUD + Gemini proofread + Resend send
**Files:** Create `core/email_proof.py`, `adapters/resend.py`, `api/routes/email.py`, `web/src/pages/Email.tsx`; Test `tests/core/test_email_proof.py`
**Interfaces:**
- `core/email_proof.py: def build_proof_prompt(draft: str) -> str` + `def diff_suggestions(original, proofed) -> list[Change]` (pure).
- `adapters/resend.py: def send(*, from_name, reply_to, to, subject, html) -> str` (returns message id).
- Routes (role `sales` compose/send; `admin` template CRUD): `GET/POST/PUT/DELETE /email/templates`, `POST /email/proof`, `POST /email/send`.
- [ ] Test the pure proof-prompt + diff. Implement routes + Resend adapter (reply-to = `request.user.email`). SPA compose page consumes them. Commit.

**Prereq:** Resend key + verified `perkinsroofing.net` DNS (P4).

---

### Task 3: Serper SERP/PAA adapter + SERP analysis (ported)
**Files:** Create `adapters/serper.py`, `core/serp_analysis.py`; Test `tests/core/test_serp_analysis.py`
**Interfaces:**
- `adapters/serper.py: def fetch_serp(query) -> Serp` (organic, peopleAlsoAsk, answerBox, knowledgeGraph, relatedSearches).
- `core/serp_analysis.py` (100% portable from seo-aio, no LLM): `classify_keyword(serp) -> Intent+Template`, `analyze_title_patterns(serp)`, `aggregate_authority_citations(top3)`, `analyze_top3_authors(top3)`.
- [ ] Test the pure analyzers against a canned Serp fixture. Implement. Commit.

**Prereq:** Serper API key (P3).

---

### Task 4: Article generation — port seo-aio prompt IP to Vertex
**Files:** Create `core/article_prompt.py` (port of `systemPrompt` + `templatePrompt`), `core/article_plan.py` (pillar+cluster), `jobs/article_job.py`; Test `tests/core/test_article_plan.py`, `test_article_prompt.py`
**Interfaces:**
- `core/article_plan.py: def build_plan(keywords, serps) -> Plan` (pillar = highest PAA density; clusters = answer-box targets + unranked keywords; internal-link map). Pure.
- `core/article_prompt.py: def system_prompt() -> str`, `def template_prompt(ctx: ArticleCtx) -> str` — E-E-A-T, answer-first, PAA→FAQ ("MUST answer these real Google queries"), featured-snippet format matching, callout boxes, internal-link anchor variation. **Ported near-verbatim; Anthropic phrasing removed.**
- `jobs/article_job.py`: plan → per-article generate (Vertex) → `parse_model_json` → QA gate → build JSON-LD → publish.
- [ ] Test plan selection (pillar/cluster) + that `template_prompt` injects PAA and answer-box format. Implement. Commit.

---

### Task 5: QA gate (fact-check + cross-client dedup + intent) — ported
**Files:** Create `core/qa_gate.py`; Test `tests/core/test_qa_gate.py`
**Interfaces:** `def verdict(checks: list[Check]) -> "pass|warn|block"` (block > warn > pass precedence). Fact-check + intent use Vertex; dedup = pure Jaccard 5-gram shingles vs prior articles. Fail-open sets `failed_open=True`.
- [ ] Test verdict precedence + Jaccard dedup (>85% → block) pure. Implement (LLM checks behind adapter). Commit.

---

### Task 6: JSON-LD builders + WordPress REST publish + mu-plugin
**Files:** Create `core/jsonld.py`, `adapters/wordpress.py`, `wp-mu-plugin/perkins-jsonld.php`; Test `tests/core/test_jsonld.py`
**Interfaces:**
- `core/jsonld.py: build_video_object(...)`, `build_faq_page(faq)`, `build_article(...)` → dicts (pure). YouTube `?t=` deep-links are the highest-leverage AIO field.
- `adapters/wordpress.py: def publish(*, title, html, meta, jsonld, status) -> int` (POST `/wp-json/wp/v2/posts`; stores JSON-LD as post-meta `_perkins_jsonld`).
- `wp-mu-plugin/perkins-jsonld.php` (~15 lines): `wp_head` hook echoes `_perkins_jsonld` as `<script type="application/ld+json">` (WP strips script from content).
- [ ] Test the JSON-LD builders (valid schema.org shapes). Implement adapter + mu-plugin. Publish a test post to `staging.perkinsroofing.net`, curl the page, confirm JSON-LD in `<head>`. Commit.

**Prereq:** WP Application Password + confirm Yoast/RankMath (P6).

---

### Task 7: `scheduled_content` table + Cloud Scheduler promoter
**Files:** Create `core/scheduler.py`, `jobs/promote_job.py`, migration for `scheduled_content`; Test `tests/core/test_scheduler.py`
**Interfaces:**
- `scheduled_content(id, kind[article|reel], ref_id, publish_at, status, target)`.
- `core/scheduler.py: def due(rows, now) -> list[row]` (pure). `jobs/promote_job.py` (Cloud Scheduler cron) promotes due articles (WP `future`→`publish`) and reels (hands to Wave-4 social).
- [ ] Test `due()` selects only `publish_at <= now && status == scheduled`. Implement promoter. Commit.

---

## Self-Review
- Spec coverage: email compose+proof+Resend (T2) ✓ · articles pillar/cluster + PAA/JSON-LD + WP (T3,4,6) ✓ · QA gate (T5) ✓ · scheduler (T7) ✓ · mu-plugin JSON-LD (T6) ✓ · seo-aio reuse as prompt-IP port (T4,5) ✓.
- Creds gating live use: Resend (T2), Serper (T3), WP (T6). Code builds without them (adapters mocked).
