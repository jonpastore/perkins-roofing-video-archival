# Perkins Roofing — Video Intelligence & Content Platform (v2)

An AI content platform built on Perkins Roofing's YouTube catalog. It ingests videos
(transcript → Content Graph → 3072-dim embeddings), then powers a suite of LLM-driven
features on top of that knowledge base:

- **Ask** — grounded, timecoded, cited answers over the video library (RAG, with abstention).
- **Articles** — SEO articles (pillar/cluster) generated + published to WordPress with Rank Math
  metadata and JSON-LD.
- **FAQ** — mined, grounded Q&A banks feeding articles and standalone FAQ pages.
- **Clips / Reels** — content-graph-driven clip selection → rendered 9:16 reels → Instagram/TikTok.
- **Comments** — question detection + human-approved draft replies.
- **Email** — WYSIWYG/template composer with AI drafting.

Ingestion and generation run as **Cloud Run Jobs**; a **FastAPI** service backs an authenticated
**React/Vite** admin console. Everything runs in GCP (Cloud SQL + pgvector, Vertex AI, GCP STT,
GCS, Secret Manager, Cloud Scheduler) and is 100% Infrastructure-as-Code.

Built by **DeGenito**. Channel: [@perkinsroofingcorp](https://www.youtube.com/@perkinsroofingcorp).

---

## Status

| Gate | State |
|---|---|
| Tests | **1142 passing** |
| `core/` coverage | **100%** (enforced) |
| Lint (ruff) · SAST (bandit) · SCA (pip-audit) | clean (in CI) |
| Web build (tsc + vite) | green |
| Infra | 100% Terraform + Ansible, drift-checked |

## Quick start (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt pytest pytest-cov ruff bandit pip-audit

# the CI gates
ruff check core adapters api jobs
bandit -r core adapters api jobs app -lll -q
pip-audit -r app/requirements.txt
pytest tests/ --cov=core --cov-config=.coveragerc --cov-fail-under=97

# frontend
# Requires Node.js 24 (matches GitHub Actions / Firebase deploy host).
cd web && npm ci && npm run build
```

**Faster PG-backed test runs.** The RLS / billing tests need a real Postgres. By default
the fixtures spin up (and tear down) a Testcontainers instance every run. To reuse one
long-lived `pgvector` container instead — provisioning is paid once, then reused — run the
suite through the helper (it starts the container if needed, uses a fresh DB per run, and
sets `TENANCY_PG_URL` so the fixtures skip Testcontainers):

```bash
scripts/test_pg.sh                                   # full suite
scripts/test_pg.sh --cov=core --cov-fail-under=97    # the R1 gate
scripts/test_pg.sh tests/tenancy -q                  # a subset
scripts/test_pg.sh --stop-pg                          # stop + remove the container
```

Rules for every change are binding — read **[docs/ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md)**
(and **[CLAUDE.md](CLAUDE.md)**) first.

## Repository layout

| Path | What |
|---|---|
| [`core/`](core/) | Pure logic (coverage-gated at 100%) — retrieval, seo, article/faq/miniseries planners, authz, ratelimit |
| [`adapters/`](adapters/) | External I/O — GCP STT/storage/logging, Vertex LLM, WordPress, Meta/IG, TikTok, Resend, Serper, yt-dlp, Firebase |
| [`api/`](api/) | FastAPI service + `routes/` (archive, articles, clips, comments, config, email, faq, scheduling, suggestions, topics, users, video, logs) |
| [`jobs/`](jobs/) | Cloud Run Jobs — ingest, embed, enumerate, archive, render, article, social, crawl-comments, aggregate-topics, … |
| [`web/`](web/README.md) | React + TypeScript + Vite admin console (Firebase auth) |
| [`app/`](app/README.md) | Shared data layer / config / LLM routing (+ the v1 prototype core) |
| [`infra/`](infra/README.md) | Terraform + `migrations/*.sql` + Ansible |
| [`poc/`](poc/README.md) | Original proof-of-concept CLI |
| [`tests/`](tests/) | Test suite (`core`, `api`, `adapters`, `jobs`) |
| [`docs/`](docs/) | All project documentation (indexed below) |

---

## 📚 Documentation index

### Start here — charter & direction
- [CLAUDE.md](CLAUDE.md) — project rules for agents/contributors (summary of the engineering rules).
- [docs/ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md) — **binding** R1–R5 (coverage, per-wave review, 100% IaC, drift, Ansible).
- [docs/superpowers/specs/2026-07-04-perkins-platform-v2-design.md](docs/superpowers/specs/2026-07-04-perkins-platform-v2-design.md) — the v2 design spec (architecture).
- [docs/MATURITY-ROADMAP.md](docs/MATURITY-ROADMAP.md) — north-star plan to a cutting-edge AI product (Tier 0 = AI eval harness).
- [docs/BACKLOG.md](docs/BACKLOG.md) — ideas + deferred hardening items (§B6/§B7 from the reviews).

### Implementation plans (waves)
- [Wave 0 — Foundation](docs/superpowers/plans/2026-07-04-wave0-foundation.md)
- [Wave 1 — Data completeness](docs/superpowers/plans/2026-07-04-wave1-data.md)
- [Wave 2 — Content engines](docs/superpowers/plans/2026-07-04-wave2-content.md)
- [Wave 3 — Video pipeline](docs/superpowers/plans/2026-07-04-wave3-video.md)
- [Wave 4 — Social publishing](docs/superpowers/plans/2026-07-04-wave4-social.md)

### Component guides
- [app/README.md](app/README.md) — the production core / shared data layer.
- [web/README.md](web/README.md) — the React admin console.
- [infra/README.md](infra/README.md) — Terraform layout, apply/bootstrap, drift.
- [poc/README.md](poc/README.md) — the original proof-of-concept CLI.

### Operations & setup
- [docs/PRODUCTION_CHANGES.md](docs/PRODUCTION_CHANGES.md) — required config/plugins outside the codebase.
- [infra/SECRETS.md](infra/SECRETS.md) — the Secret Manager inventory and how secrets are wired.
- [docs/GSUITE_DIRECTORY_SETUP.md](docs/GSUITE_DIRECTORY_SETUP.md) — GSuite directory dropdown (one-time setup).
- [docs/YOUTUBE_REPLY_OAUTH.md](docs/YOUTUBE_REPLY_OAUTH.md) — enabling direct YouTube reply posting.

### Reviews (per-R2 verdicts)
- [2026-07-07 — deep review (backend)](docs/reviews/2026-07-07-deep-review.md)
- [2026-07-07 — comprehensive review (frontend / tests / adversarial / perf / SAST)](docs/reviews/2026-07-07-comprehensive-review.md)

### Session history / continuations
- **Most recent:** [CONTINUATION-2026-07-22.md](CONTINUATION-2026-07-22.md) (deployed prod d1e25b5; 61 articles live+validated on new staging 1228404 (30 new + 31 refreshed); estimator repair-quote + gutter-downspout, SEO submission (OFF), internal-links 404 fix, article-schema fix; Cloudflare LLM adapter (dormant) + BINDING model routing = CF llama generates / Vertex validates, app code sonnet-qwen/opus-review; WP_URL admin-config resolver with NO .env fallback; o365 mail MCP; docs/PRODUCTION_CUTOVER_PLAN.md)
- [CONTINUATION-2026-07-21.md](CONTINUATION-2026-07-21.md) (huge session: estimator+Quoting finished & deployed (Quoting panel, pre-send review gate, margin/commission sliders, measurement prefill, low-slope from Exhibit B §4 + tile roof-cuts decoded from Tim's formulas, prod pricing config v5/v6); clips fixed (speaker-tracking crop-comma bug, speech_cleanup, broll); ARTICLE PIPELINE REBUILT for local grounded gen — FAQ+Video-only schema (fixes Rank Math dup), internal links no-/blog, YouTube footer, dense answer-first (1000/1500), numeric-grounding gate that BLOCKS invented figures, gpt-oss-120b non-think + Vertex validate; 07-20 Zoom transcribed locally. HEAD 4227442, API image 41472dc; article-gen commits OPT-IN/not-deployed until LLM_BACKEND=litellm)
- [CONTINUATION-2026-07-20-pm2.md](CONTINUATION-2026-07-20-pm2.md) (all 3 resume tasks done, commit e8564d8, deployed: (1) Quoting config panel built — deposit/reminder/license + proposal-template CRUD + embedded T&C library; (2) core/proposal_review wired into send_proposal — HIGH issues block send (422) unless override_review, review_error warns-not-blocks; T&C/FAQ/AI-prompt render was ALREADY wired; (3) AV end-to-end validated on a real MP4 through real ffmpeg — 10/10 checks, censor muted span to −91 dB, reframe 9:16, caption mask burned, valid h264/aac; defaults measured correct. Deploy pending a human go — send-gate adds a live LLM call to the send path)
- [CONTINUATION-2026-07-20-pm.md](docs/continuations/CONTINUATION-2026-07-20-pm.md) (pm batch: TikTok refresh-token persist, article-job no-op, non-root Docker, Cloud Run 5xx/job-failure alert policies + activation (alert_email=dmarc@perkinsroofing.net), suggest-clips 500 fix (null timestamps), 4 admin/estimating UI fixes, Clip Studio help modal, core/proposal_review.py (fairness+prompt-injection reviewer, unwired). API ddc6dab, HEAD 749a38d)
- Archived: [docs/continuations/CONTINUATION-2026-07-20.md](docs/continuations/CONTINUATION-2026-07-20.md) · [docs/continuations/CONTINUATION-2026-07-19.md](docs/continuations/CONTINUATION-2026-07-19.md) · [docs/continuations/CONTINUATION-2026-07-17-night.md](docs/continuations/CONTINUATION-2026-07-17-night.md) · [docs/continuations/CONTINUATION-2026-07-17-eve.md](docs/continuations/CONTINUATION-2026-07-17-eve.md) · [docs/continuations/CONTINUATION-2026-07-17.md](docs/continuations/CONTINUATION-2026-07-17.md) · [docs/continuations/CONTINUATION-2026-07-16.md](docs/continuations/CONTINUATION-2026-07-16.md) · [docs/continuations/CONTINUATION-2026-07-11-eve.md](docs/continuations/CONTINUATION-2026-07-11-eve.md) · [docs/continuations/CONTINUATION-2026-07-11.md](docs/continuations/CONTINUATION-2026-07-11.md) · [docs/continuations/CONTINUATION-2026-07-11-pm.md](docs/continuations/CONTINUATION-2026-07-11-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-10-pm.md](docs/continuations/CONTINUATION-2026-07-10-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-10.md](docs/continuations/CONTINUATION-2026-07-10.md) ·
  [docs/continuations/CONTINUATION-2026-07-09.md](docs/continuations/CONTINUATION-2026-07-09.md) ·
  [docs/continuations/CONTINUATION-2026-07-08-pm.md](docs/continuations/CONTINUATION-2026-07-08-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-08.md](docs/continuations/CONTINUATION-2026-07-08.md) ·
  [docs/continuations/CONTINUATION-2026-07-06-pm.md](docs/continuations/CONTINUATION-2026-07-06-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-06.md](docs/continuations/CONTINUATION-2026-07-06.md) ·
  [docs/continuations/CONTINUATION-2026-07-05.md](docs/continuations/CONTINUATION-2026-07-05.md) ·
  [docs/continuations/CONTINUATION-2026-07-05-am.md](docs/continuations/CONTINUATION-2026-07-05-am.md)

### Origins (v1 prototype & proposal)
- [PRODUCTION-BUILD-PLAN.md](PRODUCTION-BUILD-PLAN.md) — the v1 production build plan.
- [OVERNIGHT-RESULTS.md](OVERNIGHT-RESULTS.md) — the overnight POC results.
- [Perkins-Roofing-Proposal.md](Perkins-Roofing-Proposal.md) ([PDF](Perkins-Roofing-Proposal.pdf)) — the client proposal.

### 🔒 Internal (DeGenito only — not for client distribution)
- [INTERNAL-NOTES.md](INTERNAL-NOTES.md) — commercial/engagement notes (pricing). Keep internal.

---

*This README is the front door. When the code and a doc disagree, the code wins — please fix the doc.*
