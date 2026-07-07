# Maturity Roadmap — from "excellent engineering" to "industry-leading AI product"

The plan to take the Perkins v2 platform from strong engineering hygiene to a reference-grade,
cutting-edge AI product. Written as a companion to `ENGINEERING_RULES.md`: each item has a
**why**, **acceptance criteria** (definition of done), and rough effort, so it's trackable like
the rest of the charter.

**Audience:** engineering + leadership. **Status:** proposed 2026-07-07. Grounded in the
2026-07-07 deep reviews (`docs/reviews/`) and a maturity scan of the repo.

---

## Where we are today (honest scorecard)

Genuinely top-decile **engineering hygiene** — the part most teams never reach:

| Dimension | State |
|---|---|
| Tests / coverage | ✅ 100% `core/` with an enforced CI gate; 1142 tests |
| Lint | ✅ ruff clean (`core adapters api jobs`) |
| SAST / SCA | ✅ bandit (0 HIGH) + pip-audit (0 CVEs) in CI |
| Infra-as-code | ✅ 100% Terraform + Ansible, drift checks (R3/R4) |
| Engineering charter | ✅ binding R1–R5 + per-wave architect/critic review |
| Architecture | ✅ pure-`core` / `adapters` / `api` / `jobs` split; documented reviews |

The gap to "industry-leading, cutting-edge" is **not** more hygiene — it's the capabilities that
define an **AI product** and a **production service**. Those are concentrated in a few areas.

## Guiding principle: build the right things, not everything

"A perfect example of *everything*" is an anti-pattern — gold-plating adds surface area and
*reduces* quality. The cutting-edge move is to go deep where it defines the product (evaluation,
observability, quality-gated delivery) and to **explicitly decline** what doesn't fit a
single-tenant content platform (see [Out of scope](#explicitly-out-of-scope)).

---

## Tier 0 — The crown jewel: an AI evaluation & observability system

**This is the single highest-leverage gap.** v2 generates SEO articles, FAQ banks, clip
selections, comment replies, and grounded answers — all LLM-driven — and none of it is
systematically evaluated. The only eval in the repo (`app/eval.py`) is the legacy 12-question
Ask-Tim seed from the prototype. Today every prompt tweak and model swap ships blind.

For an AI product, **eval is what tests are for normal software**: the quality gate.

### 0.1 Offline eval harness (`evals/`)
- **Why:** you can't improve or safely change what you don't measure; a prompt edit that
  regresses answer quality should fail CI exactly like a failing test.
- **Acceptance criteria:**
  - Golden datasets per LLM feature (grounded answer, article, FAQ, clip selection) with
    versioned inputs + reference expectations under `evals/datasets/`.
  - Metrics: **groundedness/faithfulness** (answer supported by retrieved context),
    **citation accuracy** (cited timecodes/links actually support the claim),
    **retrieval precision/recall@k**, **hallucination rate**, and per-feature task metrics
    (e.g. SEO score delta, FAQ answerability).
  - **LLM-as-judge** scoring with a pinned judge model + rubric, plus a slot for human labels.
  - `python -m evals run <suite>` prints a scorecard; results are reproducible (seeded).
- **Effort:** L (the foundational investment).

### 0.2 Eval-gated CI
- **Why:** make quality a merge gate, not a hope.
- **Acceptance:** a CI job runs the eval suite against a small golden set on PRs touching
  prompts/retrieval/models; fails (or warns with sign-off) on a regression beyond a threshold.
  Baseline scores committed and diffed.
- **Effort:** M.

### 0.3 Prompt registry + versioning
- **Why:** prompts are inline strings today — no A/B, no rollback, no provenance.
- **Acceptance:** prompts live in one place (`core/prompts/` or a registry) with a version id;
  generated artifacts record which prompt+model version produced them; changing a prompt is a
  reviewable, eval-gated diff.
- **Effort:** M.

### 0.4 Online eval + AI observability
- **Why:** catch the regressions users actually see; monitor drift.
- **Acceptance:** sample a % of prod LLM outputs → async groundedness/quality scoring →
  a dashboard + alert on score drop or cost/latency spike; per-feature LLM cost + token
  tracking (extends `observability.Cost`).
- **Effort:** M–L.

### 0.5 Guardrails
- **Why:** public-facing generated content on a client's brand.
- **Acceptance:** structured input/output guardrails — prompt-injection screening (extends the
  existing `fence()`), PII detection/redaction on comments/emails, and an output policy check
  before anything is published to WordPress/social.
- **Effort:** M.

---

## Tier 1 — production-grade for an AI service

### 1.1 Observability (tracing, errors, metrics, SLOs)
- **Gap:** no OpenTelemetry tracing, no error tracking (Sentry), no custom metrics/SLOs; a cron
  returning `{"errored": 12}` looks HTTP-200 healthy.
- **Acceptance:** OTel traces across api→adapters→jobs with request/run/video ids; error
  tracking wired; log-based alerts on job failures + 5xx; documented SLOs (answer latency,
  ingestion success rate) with dashboards. (Fixes the round-1 backlog "no alerting" items.)
- **Effort:** M.

### 1.2 Streaming + semantic caching (AI UX + cost)
- **Gap:** the Ask widget + article gen block (no SSE); every query re-embeds/re-calls; `embed()`
  has no cost cap.
- **Acceptance:** SSE token streaming to the widget; an LRU/semantic cache for query embeddings
  and idempotent LLM calls; an embed-side cost cap. Measurable p95 latency + cost reduction.
- **Effort:** M.

### 1.3 Test quality beyond coverage
- **Gap:** 100% `core/` coverage is real, but `adapters/api/jobs` are coverage-omitted, and the
  QA audit found tautological tests; 12/20 jobs + 8/16 adapters have no behavioral test.
- **Acceptance:**
  - **Mutation testing** (mutmut/cosmic-ray) on `core/` with a surviving-mutant budget — proves
    the tests actually catch bugs, not just execute lines.
  - **Integration tests against real Postgres+pgvector** (testcontainers) — the prod ranking path
    (`halfvec` HNSW) is currently untested for correctness.
  - **One E2E flow** (Playwright) through the SPA (login → ask → article approve).
  - A behavioral `scripts/validate_*.py` for each remaining I/O job/adapter (closes the R1 gap).
- **Effort:** L.

---

## Tier 2 — cutting-edge engineering

### 2.1 Static type gate
- **Gap:** no mypy/pyright on a large Python backend.
- **Acceptance:** mypy (or pyright) in CI, `strict` on `core/`, incremental on the rest; typed
  public function signatures. **Effort:** M.

### 2.2 Supply-chain security
- **Gap:** no SBOM, no image signing, no secret scanning; deps are `>=` with no hashed lock.
- **Acceptance:** hashed `requirements.lock` (pip-compile) used in CI + Docker; **SBOM**
  (CycloneDX/syft) as a build artifact; **image signing + provenance** (cosign/SLSA); **secret
  scanning** (gitleaks) in CI; Dependabot/Renovate for automated updates. **Effort:** M.

### 2.3 Database maturity
- **Gap:** raw SQL migrations with no ledger — every deploy re-runs all files; no restore drills.
- **Acceptance:** a migration framework (Alembic) or a `schema_migrations` ledger so each file
  runs once, ordered, tracked; a documented + tested backup/restore drill; connection-pool +
  read-path config reviewed. **Effort:** M.

### 2.4 Developer experience
- **Gap:** no pre-commit, devcontainer, task runner, or conventional-commit automation.
- **Acceptance:** `.pre-commit-config.yaml` (ruff, mypy, gitleaks); a `justfile`/Makefile for the
  common gates; a devcontainer for one-command onboarding; conventional commits →
  auto-changelog. **Effort:** S–M.

---

## Tier 3 — polish & compliance

- **Frontend:** WCAG a11y fixes (focus traps, labels, dialog roles — see BACKLOG §B7), route
  code-splitting + TinyMCE/Firebase lazy-load (1.7MB→split), CSP headers, visual-regression tests.
- **Product/legal:** GDPR/CCPA data-retention + right-to-deletion for stored comments/emails;
  YouTube ToS compliance stance carried into v2; privacy policy; **model cards** for the
  generated-content features.
- **Progressive delivery:** preview env per PR; canary/blue-green; auto-rollback on SLO breach.
- **FinOps:** cost-per-feature dashboards; the billing budget alert wired (round-1 backlog).

---

## Explicitly out of scope (declining these IS the senior move)

For a single-client roofing content platform, these would be gold-plating that *reduces* quality
by adding surface area — do **not** build them without a real driver:

- Multi-region / active-active HA, service mesh, Kubernetes (Cloud Run is right-sized).
- GraphQL / gRPC public APIs (REST + the SPA is sufficient).
- A feature-flag platform, event-sourcing/CQRS, microservice decomposition.
- Self-hosted model serving (managed Vertex/cerberus-Whisper is the right call).

---

## Sequenced execution plan

1. **Tier 0.1–0.2 — the eval harness + CI gate.** Highest leverage, most differentiating, most
   on-brand for an AI product. Start here.
2. **Tier 1.1 — observability.** So we can see prod once eval tells us what "good" is.
3. **Tier 1.3 — test quality** (mutation + real-pgvector integration + one E2E).
4. **Tier 2.1–2.2 — type gate + supply-chain** (mypy, SBOM, signing, hashed lock, secret scan).
5. **Tier 0.3–0.5, 1.2** — prompt registry, online eval, guardrails, streaming/caching.
6. Tier 2.3–2.4 and Tier 3 as steady-state hardening.

Each item lands with tests + docs + a CHANGELOG entry per the Definition of Done, and (Tier 0/1)
its own eval or validation — quality-gated, not hope-gated.

> Tracking: fold Tier items into `docs/BACKLOG.md` waves as they're scheduled; record review
> verdicts in `docs/reviews/`.
