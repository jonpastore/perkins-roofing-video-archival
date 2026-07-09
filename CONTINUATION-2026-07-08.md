# CONTINUATION — 2026-07-08 (full day, Opus 4.8 → Fable 5)

Previous handoff: `CONTINUATION-2026-07-06-pm.md` (top level). This was the pivot session: the
project graduated from "Perkins video platform" to an **approved multi-tenant full-funnel sales &
marketing platform** (content → leads → quote → proposal → handoff). Everything below is current
as of commit `b19b34b` + this doc's commit.

---

## 1. THE HEADLINE — what the next session does

**The full-funnel plan is APPROVED** (`docs/superpowers/plans/2026-07-08-full-funnel-plan.md`, v2
Fable-ultrathink). Jon's explicit instructions for the next session:

1. **Phase-0 documentation FIRST**: produce thorough **PRDs** (per sidebar section: Knowledge Base,
   Marketing, Estimating, Quoting, Admin), **TRDs** (per wave F0–F6), and a **DDD document**
   (bounded contexts, aggregates, entities/value objects, ubiquitous-language glossary, context
   map — Tenancy/Identity, Corpus/KB, Content/Marketing, Pricing/Estimating, Quoting/Proposal,
   Measurement). Suggested home: `docs/superpowers/specs/full-funnel/` (PRD-*.md, TRD-*.md, DDD.md).
   Ground them in: the plan doc, `perkins-ezbids-proposal` + `perkins-knowify-teardown` +
   `perkins-squarequote-review` memories, Exhibit B/C facts, and the phase-2 spec.
2. **Then execute F0 (thin tenancy) + F1 (IA reorg)** — with **strict TDD, fail-first, ALWAYS**:
   write the test → run it → confirm it fails **for the right reason** → minimal implementation →
   green → refactor. This is now standing policy for every wave, every feature. No implementation
   before a red test. (R1's 100% core gate stays; TDD is *how* we get there, not a substitute.)

## 2. Approved plan — wave summary (full detail in the plan doc)

| # | Wave | Ships | Gate | Est |
|---|---|---|---|---|
| F0 | Thin tenancy | `tenants` + `tenant_id` (default 1 = Perkins) on all tables, ORM discipline. No RLS/GCIP yet | Perkins unchanged | 0.5s |
| F1 | IA reorg | Sidebar → KB · Marketing · Estimating · Quoting + Admin config-tab shell | all pages reachable | 1–2s |
| F2 | Estimating complete | Config-driven pricing (versioned+RFC8785-hashed, admin-editable), cost-category tags (fixes 13%/33% + commission), low-slope tables, branches, HVHZ=Dade+Broward / FBC=PB+Lee+StLucie **+ per-county overrides**, boundary rules | **5 golden files ±$0.01 in CI** | 2s |
| F2b | Measurement service | **Google Solar API primary** (pitch/azimuth/area per segment) + manual entry fallback; eaglepoint ml-service → GCP; DROP LiDAR/U-Net/Mapbox | real Perkins addresses validate | 2–3s |
| F3 | **Quoting/Proposals** | Proposal builder: self-serve multi-**templates**, **revisions**, **good-better-best tiers** (Knowify's 3 gaps) · no-login e-sign+audit+consent+PDF-copy · tracking+reminders · deposit+handoff · Gotenberg PDF · Knowify migration (XLS import + PDF archive) | quote→accept on a phone; Tim 3-day preprod + 14-day acceptance | 3–4s |
| F4 | Tenancy hardening | RLS (SET LOCAL pattern) + GCIP (Perkins stays project-pool) + ≥30 denial tests + cross-tenant probe + PITR | **before tenant #2** | 2s |
| F5 | Marketing/KB tenant-ization | `for_each_tenant` job wrapper, per-tenant configs/creds/metering, brand kit, **wire Track A engines into Clip Studio UI** | test tenant publishes safely | 2–3s |
| F6 | Edge + onboarding | Cloudflare ingress + **app.perkinsroofing.net** + tenant provisioning + per-tenant SSO + security re-review | onboard tenant <1hr | 2s |

**Commercial clock:** Jon's payment email → quoting build starts next week, deposit week after,
completion ~2wk later. Critical path F0 → (F1∥F2) → F3. Slip protection: cut reminders/leads first,
never templates/e-sign/revisions/tiers.

## 3. Locked decisions (do not relitigate)

GCP everything · PostgreSQL (RLS + tenant_id, NOT schema-per-tenant) · Cloudflare ingress (token
coming from Jon) · **app.perkinsroofing.net** · GCIP auth (Perkins stays on project-level pool as
tenant 1; invite-link tenant resolution, NO per-tenant subdomains v1) · whole platform multi-tenant
incl. content mgmt (2nd revenue stream) · Ez-Bids rebuilt on our stack (`core/estimator.py` is the
foundation) · Knowify: displace proposal feature only, no QuickBooks/accounting (Tim's backend is
elsewhere) · measurement = **Google Solar API + manual fallback** (NO LiDAR/drones; raw Google-Earth
scraping is ToS-prohibited; paid upgrade path = Nearmap/Vexcel oblique) · e-sign built-lite
(tokenized no-login accept + consent + audit + emailed PDF copy) · Gotenberg for PDFs · royalty-FREE
music only (Pixabay/YT Audio Library/FMA — never "licensed" catalogs) · non-goals: payments
processing, accounting/QBO, CRM/ERP, engagement-sim bots, native iOS v1.

## 4. What shipped this session (all committed + pushed, `main`)

1. **Vlad's deep-review branch** validated end-to-end and ff-merged (`4076bd8…`); CI gate now 100%
   core coverage; dep floors = current PyPI; security fixes verified.
2. **Phase-2 spec** (`docs/superpowers/specs/2026-07-08-phase2-requirements.md`) from the Zoom
   recap + Opus Clip/repurpose.io teardowns + FL competitor research (insurance-law content moat,
   pillar/cluster map §9).
3. **Estimator**: `core/estimator.py` (Exhibit-B sloped tables, sliding scale, self-check =
   workbook's $20,280) + `api/routes/estimator.py` (+`manage_estimates` authz) + `Estimator.tsx` UI.
   Known deltas vs Exhibit B are listed in plan §5 (low-slope, commission split, PM matrix,
   dumpster threshold, cost-category tags).
4. **Autopilot phase-2 build** (all 100% covered): Track E content-safety gate
   (`core/content_safety.py` + `adapters/safety.py`, fail-closed incl. no-judge) · Track D publish
   pipeline (`core/publish_planner.py`, `jobs/publish_job.py` SKIP LOCKED, migration 0012, Cluster
   model) · **Track A complete engine**: A1 `clip_select`, A3 `captions`, A8 `music_mix`,
   A9–A11 `clip_fx`, A2 `reframe`, A6 `speech_cleanup`, A7 `broll` · scaffolds: Track C
   distribution (`core/publish_dispatch` + `adapters/distribution/*` + `jobs/distribute_job`),
   Track F avatar (ElevenLabs/HeyGen mocks), Track B cleanup (`core/audio_filter`). Opus security
   review fixes: distribution caption gate bypass (H1), dead drip throttle (H2), estimator 422s,
   fail-closed gate, migration hardening.
5. **Caption v5**: council review (ChatGPT/Grok) → `docs/prompts/social-caption-v3.md` → Jon's v5
   (`docs/prompts/social-caption-v5.md`, strict JSON contract) → `core/caption_output.py` parses
   v5 JSON (+v3 fallback), gates BLOCK/REVIEW/OK, wired into `distribute_job`. Tested live against
   a sample transcript.
6. **Users UI/admin**: Internal/External invite toggle (Internal default), TinyMCE signature modal
   + copy-from-user, icon buttons, `is_default_admin` delete protection · **keyless domain-wide
   delegation** for the Workspace directory (IAM signJwt; Admin SDK API enabled + Terraform) ·
   `WORKSPACE_ADMIN_SUBJECT=jon@perkinsroofing.net` in deploy.sh · **migrations 0010–0012 applied
   to prod** via `scripts/apply_migrations_connector.py` (fixed comment-split bug).
7. **Deploys**: API revision `api-00039-ml7` (image `335da37`) — NOTE code `b19b34b` (Track A +
   estimator UI) is committed but API **not redeployed since**; web (Firebase Hosting) IS at
   `b19b34b` incl. Estimator tab. Deploys on hold pending custom domain? No — web deploys were
   held after the domain decision; API deploy fine when needed via `bash scripts/deploy.sh`
   (clean tree required).
8. **Ez-Bids proposal + 63pp legal package digested** (memory `perkins-ezbids-proposal`): $9,400,
   Ez-Bids LLC 90/10, Exhibit B = authoritative pricing (incl. low-slope), Exhibit C = 5 golden
   files ±$0.01 + adversarial scenarios, SquareQuote license (perpetual royalty-free, stays
   DeGenito IP — **don't merge its source into this repo**).
9. **Knowify teardown** (memory `perkins-knowify-teardown`): replace proposal feature only; NO
   proposal API exists (PDF-only export); beat their template-lock/no-revisions/no-tiers gaps.
10. **SquareQuote review** (repo `DeGenitoAI/eaglepoint`, cloned at `~/projects/eaglepoint`;
    memory `perkins-squarequote-review`): prod = OSM+NAIP only (LiDAR silently off, U-Net dead code
    w/ random weights, edge math wrong, Mapbox ToS violation) → pivoted to **Solar API** per Jon.
11. **Tim deliverables**: `docs/2026-07-08-tim-requirements.md` + **send-ready email**
    `docs/2026-07-08-tim-email.md` (golden files, 3 confirmations, branches/users, Knowify,
    DNS/Tucows, voice samples, testing commitments).

## 5. Open items — humans (jarvis #315–331; live list = `mcp__jarvis-memory__my_tasks`)

- **Tim**: send `docs/2026-07-08-tim-email.md` → golden files + 3 pricing confirmations + branch/user
  list + T&Cs/deposit/license# (#318/#324) · intro/outro clips + voice samples (#317)
- **Josh**: Knowify admin access · IG/TikTok creds · caption prompts · Roofr quotes (#315/#316)
- **Amber/Tucows**: DNS for app.perkinsroofing.net (#330) — **Jon is creating a Cloudflare token
  for me** to do the zone work (import ALL records incl. Workspace MX/SPF/DKIM before NS change)
- **Jon**: ⚠️ Ez-Bids LLC entity/IP/branding vs unified platform → counsel (plan §10.6) · Solar API
  enablement + billing (Terraform when built)
- Standing: social app reviews (2–4wk), Pexels/HeyGen/ElevenLabs keys, royalty-free music catalog
  (#325–329), gmail-enhanced MCP has NO accounts registered (jon@degenito.ai unreachable — use
  claude.ai Gmail = jpastore79 or files)
- **Carried over from 2026-07-06pm (still open, lower priority than the funnel):** task 27 —
  Rank Math keyword-density refine loop + batch article regen (`jobs/regen_articles_seo`) · YouTube
  reply OAuth token mint (owner action, `scripts/youtube_oauth_setup.py`) · retire cerberus Whisper
  node in `ansible/whisper.yml` so drift_check is fully green (cerberus is dev-only now).
  DONE from that list: GSuite invite dropdown (keyless DWD, this session).

## 6. Gotchas for the next session

- **TDD fail-first is mandatory** (Jon's instruction): red test → verify failure reason → minimal
  code → green. Applies to F0 onward. Money paths (pricing/proposals) get behavioral tests per R1.
- `scripts/deploy.sh` **refuses a dirty tree** (R3-ENFORCE) — commit first. `web/.firebase/` is
  gitignored now (was tripping the guard). Run via `bash scripts/deploy.sh` (not executable).
- **Prod DB DDL**: the permission classifier blocks direct DDL; use
  `scripts/apply_migrations_connector.py` (idempotent, ≥0010 by default) **only with Jon's explicit
  permission**; needs fresh ADC (`gcloud auth application-default login` — interactive, Jon runs).
- Firebase CLI + gcloud authed as jon@perkinsroofing.net; project `video-archival-and-content-gen`.
- Full suite takes minutes; run backgrounded with output to /tmp log + `EXIT=$?` marker; the
  100% gate covers `core/` only (adapters/api/jobs omitted but need behavioral tests).
- Parallel subagents writing to the repo: give explicit file-ownership boundaries (a mid-session
  collision produced conflicting gate claims); implementation subagents = **sonnet** per token policy.
- `~/projects/eaglepoint` = SquareQuote clone (read-only reference; do NOT import source here).
- Memory files (`~/.claude/.../memory/`): `perkins-full-funnel-reorg`, `perkins-ezbids-proposal`,
  `perkins-knowify-teardown`, `perkins-squarequote-review`, `perkins-phase2-2026-07-08` — read via
  MEMORY.md index at session start.

## 7. Command cheat sheet

```bash
# gates
source .venv/bin/activate && ruff check core adapters api jobs
pytest tests/ --cov=core --cov-config=.coveragerc --cov-fail-under=100 -q   # background it
# deploys (clean tree!)
bash scripts/deploy.sh                                  # API + jobs (Cloud Build, ~5 min)
cd web && npm run build && firebase deploy --only hosting --project video-archival-and-content-gen
# prod migrations (ONLY with Jon's explicit OK)
.venv/bin/python scripts/apply_migrations_connector.py
# jarvis
mcp__jarvis-memory__my_tasks  # live blocker list
```

---
*Standing archive directive (performed this session): moved oldest top-level continuation
(`CONTINUATION-2026-07-05.md`) into `docs/continuations/`, top level now holds 2026-07-06,
2026-07-06-pm, and this file (≤3); fixed inbound links (README §Session history,
CONTINUATION-2026-07-06.md); README index "most recent" now points here. Apply the same directive
on every future continuation.*
