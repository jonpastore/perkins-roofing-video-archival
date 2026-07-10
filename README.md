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
pytest tests/ --cov=core --cov-config=.coveragerc --cov-fail-under=100

# frontend
cd web && npm ci && npm run build
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
- **Most recent:** [CONTINUATION-2026-07-10-pm.md](CONTINUATION-2026-07-10-pm.md) (evening: Squares/estimator/proposals/clip-studio/email/YouTube-fix shipped; Ez-Bids plan approved)
- [CONTINUATION-2026-07-09.md](CONTINUATION-2026-07-09.md) ·
  [docs/continuations/CONTINUATION-2026-07-08-pm.md](docs/continuations/CONTINUATION-2026-07-08-pm.md)
- Archived: [docs/continuations/CONTINUATION-2026-07-08.md](docs/continuations/CONTINUATION-2026-07-08.md) ·
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
