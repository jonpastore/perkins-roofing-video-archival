# Perkins v2 Platform — Continuation (2026-07-05, session 2 / afternoon)

Resume handoff after a very large build session. Branch **`feat/platform-v2`** (not pushed).
Everything below is current as of the latest commit on that branch. The earlier morning handoff
is archived at `docs/continuations/CONTINUATION-2026-07-05-am.md`.

---

## ⚡ RESUME QUICK-START (read this first)

**1. Auth is degraded — use ADC, not the gcloud user login.**
The interactive `gcloud auth login` (user creds) is **expired**; ADC (`gcloud auth application-default`)
is valid. So:
- **gcloud / deploys:** prefix with the ADC token —
  `export CLOUDSDK_AUTH_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)`
- **DB password:** fetch via the Secret Manager REST API with the ADC token (gcloud CLI secret access
  fails on the expired user login). Snippet:
  ```python
  # PW = base64-decode of secretmanager .../secrets/db-password/versions/latest:access with Bearer ADC token
  ```
- **Cloud SQL proxy** runs on `127.0.0.1:5432` via ADC (`/tmp/cloud-sql-proxy <conn> --port 5432`).
- If ADC also expires, ask Jon to run `!gcloud auth application-default login` (and optionally `gcloud auth login`).

**2. Deploying (IaC / R3):**
- **API:** `export CLOUDSDK_AUTH_ACCESS_TOKEN=$(gcloud auth application-default print-access-token); bash scripts/deploy.sh`
- **SPA:** `cd web && firebase deploy --only hosting --project video-archival-and-content-gen`
- ⚠️ **NEVER** chain deploys with `while pgrep -f deploy.sh; do sleep; done` — the loop's own command
  line contains "deploy.sh" so it self-matches and **never runs the deploy** (this silently no-op'd ~8
  API deploys this session; the API sat 8 commits behind). Just run `deploy.sh` directly.
- **DB schema:** `scripts/apply_migrations.sh` applies `infra/migrations/*.sql` (0001–0006) idempotently
  (git → apply). Stop creating tables ad-hoc via `create_all`.

**3. LLM backend — SWITCH TO VERTEX (Jon's call):**
The local-model priming had integration issues (below). For all generation use the cloud:
`LLM_BACKEND=vertex LLM_MODEL=gemini-2.5-flash EMBED_BACKEND=vertex EMBED_MODEL=gemini-embedding-001`.
Local Ollama (cerberus Qwen3-30B-A3B) stays provisioned but is **not** the default anymore.

---

## ✅ WHAT'S BUILT THIS SESSION (deployed + tested, ~750 tests, drift clean)

**Platform is a full multi-role admin console.** Roles: **admin / web_admin / sales** (`core.authz`,
role-aware nav, admin-only Users+Config section). Deployed: API (Cloud Run), SPA (Firebase Hosting on
`perkins.degenito.ai`, HTTPS live), Cloud SQL + pgvector (HNSW via halfvec(3072)), Google sign-in
(secret in Secret Manager), default-admins jon/tim/amber.

Console tabs & features (all wired to live APIs):
- **Dashboard** (default) — KPIs + failed-stages table w/ **Title link + Retry** (`/status`, `/status/retry`).
- **Search / Ask** — grounded Q&A w/ confidence + descriptive **sources** (video title + snippet, hh:mm:ss,
  checkboxes + "Include in email"); **Search-topics** = 2,079 distilled topics (sort alpha/videos/length,
  paginated, per-topic video+articles modal); **Generate cluster articles** (5–7, Rendering→View nav).
- **Content Opportunities** — hub w/ sidebar count badge; suggested topics ranked by content length; FAQs;
  reels; unused videos; numbered pagination.
- **Articles** — cluster-grouped, fixed table, **TinyMCE WYSIWYG (HTML, no markdown)**, content modal
  (Article + **SEO/AIO score** tabs, YouTube embeds, viewport-locked), Publish/Schedule (tz-aware),
  WP-post link, `POST /articles/{slug}/reprocess` (sanitize + WP sync).
- **FAQ** — persistent (`faq_entries`): mine (capped, cost estimate shown), answer, coverage, publish to
  a WordPress FAQ page (find-or-create + FAQPage JSON-LD).
- **Email** — single tab (Compose | Templates), proof + Resend send.
- **Content Scheduling** — cleaned/de-duped series labels (no emoji/hashtag), status read-only.
- **Clip Studio** — AI clip suggestion (`/clips/suggest`) → curate → save series; **Render now**
  (`/clips/{id}/render` triggers the render Cloud Run job, render-from-archived-GCS media).
- **Video Approval** — content-driven parts (real second offsets — fixed the 0/.25/.5/.75 bug), meaningful
  titles, length + hh:mm:ss, `POST /video/{id}/repropose`.
- **Users** — list w/ display names, grant/revoke roles, **Invite** (pre-authorize external/web_admin).
- **Config** — editable env KVs, model dropdowns, **write-only secrets** (last-set + by-who via Secret
  Manager versionAdder), admin note → Users.
- **Archive** — 841/841 archived; left [+]/[-] accordion, expandable detail (topics/articles/social),
  download icon, no status column; **metadata backfilled** (all upload_date/duration/views from YouTube).

Data: ingest 836/841, **841/841 archived**, HNSW index, retrieval eval 100% separation. 20 mini-series
proposals exist (**but with the OLD equal-quarters bug — regenerate, see below**).

---

## ▶️ REMAINING TASKS (in order)

1. **Finish FAQ answers on VERTEX** — 5,189 questions mined; a Vertex answer run is in progress
   (`jobs/prime_backlog --answers 6000`, `LLM_BACKEND=vertex`). Verify all `faq_entries.status='answered'`;
   re-run to finish (resumable, ~$2 total on gemini-2.5-flash). *Do NOT use LLM_BACKEND=ollama for answers.*
2. **Regenerate the 20 bad video proposals** — they used the fraction bug. Either call
   `POST /video/{id}/repropose` for each, or delete the unapproved MiniSeries and re-run
   `jobs.propose_series_job` (now content-driven via `core.miniseries.propose_clips`). LLM_BACKEND=vertex.
3. **Prime article-cluster drafts on VERTEX** for the top aggregated topics
   (`jobs/prime_backlog --articles N`, LLM_BACKEND=vertex). The *local* article path returns empty JSON
   (see gotchas) — use cloud.
4. **Publish the FAQ page to WordPress** — `POST /faq/publish-wordpress` once answers exist (find-or-creates
   the site FAQ page + FAQPage JSON-LD). Needs WP creds in env.
5. **Visual walk** — mint a jon ID token (firebase-admin + `infra/vertex-dev-sa.json` custom token →
   Identity Toolkit exchange), seed it into Playwright IndexedDB, walk every tab to confirm the ultrawork
   batch renders. (Pattern used earlier this session.)
6. **(Optional) Local article gen** — Qwen3 via Ollama returns an empty response on the large
   schema-enforced article prompt (works for normal prompts + FAQ). Needs a non-schema Ollama prompt
   variant / streamed gen. Low priority — articles are few and quality-sensitive, so cloud is fine.
7. **External blockers:** org-directory user autocomplete (needs Google Workspace admin consent + domain-wide
   delegation); Meta/TikTok social creds (Mon 2026-07-06) to flip social live; Resend domain verify.
8. **GPU:** to return cerberus to Whisper — `ansible-playbook local_llm.yml -e reclaim_gpu_from_whisper=false`
   then `ansible-playbook whisper.yml`.

---

## 🔑 KEY FACTS / GOTCHAS

- **LLM backend routing (don't reintroduce the recursion):** `adapters.llm.get_default()` = the CHAT client,
  routed by `LLM_BACKEND` (`ollama`→`OllamaLLM`, else `VertexLLM`). `adapters.llm.get_embedder()` = a
  **dedicated Vertex embedder**, always Vertex (embeddings must match the stored 3072-dim chunks). `app.llm.embed`
  uses `get_embedder()`, NOT `get_default()` — otherwise `ollama` chat → embed → get_default → OllamaLLM.embed →
  recurse ("maximum recursion depth exceeded"). Fixed; keep it that way.
- **Local LLM node:** cerberus (RTX 5090 mobile, **24GB**) runs Ollama + **qwen3:30b-a3b** (+ nomic-embed),
  IaC in `ansible/local_llm.yml` (GPU reclaimed from Whisper; transcription is complete). FAQ *mining*
  worked locally (5,184 mined); *answers* + *article gen* have issues → run on Vertex.
- **Topic aggregation:** `jobs/aggregate_topics.py` embeds distinct content_graph topic labels and greedily
  clusters (cos 0.82) into `aggregated_topics` (4,201→2,079). `GET /topics` reads it as `{total, items}`
  paginated; re-run the job to refresh (lower the threshold for a tighter list).
- **New prod tables this session** (in `infra/migrations/0006_platform_faq_secrets.sql` +
  `0005_aggregated_topics.sql`): `platform_config`, `faq_entries`, `secret_audit`, `aggregated_topics`.
- **API SA IAM (Terraform):** firebaseauth.admin (token revocation + role claims), run.developer on the
  render job + actAs jobs-sa (Render now), secretmanager.secretVersionAdder+viewer (Config secret updates).
- **deploy.sh** sets the service to cpu 2 / mem 1Gi / timeout 900s (aligned in Terraform; drift clean) and
  wires `PGPASSWORD` from the db-password secret (the API had no DB password before — every DB endpoint 500'd).
- **Firebase custom-domain + CORS + token auto-refresh** all fixed earlier; `perkins.degenito.ai` is HTTPS-live.

## 📚 Where things live
- Waves/specs: `docs/superpowers/{specs,plans}/`. Rules: `docs/ENGINEERING_RULES.md`. Prod steps:
  `docs/PRODUCTION_CHANGES.md`. Backlog: `docs/BACKLOG.md` (B1–B5). Archived handoffs: `docs/continuations/`.
- Priming: `jobs/prime_backlog.py`, `jobs/aggregate_topics.py`, `jobs/backfill_metadata.py`.

---
*Continuation-doc archive directive (applied): moved the previous top-level handoff to
`docs/continuations/CONTINUATION-2026-07-05-am.md` (≤3 kept at top level). Apply again next session.*
