# CONTINUATION — 2026-07-08 PM (overnight autopilot, Fable 5 orchestration + sonnet implementation)

Previous handoff: `CONTINUATION-2026-07-08.md`. This session executed that handoff's mission
end-to-end: **Phase 0 documentation set + F0 (thin tenancy) + F1 (sidebar IA)** — all committed
and pushed to `main` (`7ccd40d` → `0f596a9` → `a1c7f88` → `758cbbd`).

---

## 1. What shipped (all on main, all gates green)

1. **Phase 0 doc set** (`7ccd40d`) — `docs/superpowers/specs/full-funnel/`: 5 PRDs
   (knowledge-base, marketing, estimating, quoting, admin), 8 TRDs (F0, F1, F2, F2b, F3, F4,
   F5, F6), DDD.md. Drafted by 9 parallel sonnet agents; R2-reviewed by opus architect + critic
   (both APPROVE-WITH-FIXES); all 19 HIGH findings fixed pre-commit by 3 sonnet fix agents.
2. **F0 thin tenancy** (`0f596a9`) — `tenants` table (Perkins = id 1) + `tenant_id INTEGER NOT
   NULL DEFAULT 1 REFERENCES tenants(id)` on all 16 tenant-scoped tables + composite indexes;
   `core/tenant.py` (TenantMixin for F2+ tables, TenantQueryMixin belt, `set_tenant_context`
   no-op F4 seam); migration `infra/migrations/0013_thin_tenancy.sql` (idempotent,
   GREATEST-guarded setval). Fail-first TDD: 20 tests red-for-right-reason → green.
3. **F1 sidebar IA** (`a1c7f88`) — two-level sidebar (Knowledge Base · Marketing · Estimating ·
   Quoting + Admin), AdminConfig shell with 7 sub-tabs (Users & Roles embeds Users; Platform
   Settings embeds Settings; Tenants hidden until F4), mobile drawer, role gating. 23
   section-scoped authz actions in `core/authz.py` per TRD-F1 §11 (the single registry).
   112 authz tests red→green. New tab keys: `quoting`, `admin-config`, `contract-faq`,
   `status-view`; legacy `users`/`config` render AdminConfig (no broken bookmarks).
4. **F2 prep** (`758cbbd`) — `infra/fixtures/pricing_config_exhibit_b.json`: Exhibit-B seed
   config per TRD-F2 §3 schema; 22 Tim-pending fields are `null` + `_pending` markers
   (engine ConfigErrors on access — never guesses).

**Gates:** full suite 100% core coverage (EXIT=0, twice), ruff clean (`core adapters api jobs`),
`npm run build` green, `scripts/validate_f1_routes.py` 19/19 keys.

## 2. ⚠️ DEPLOY ORDER CONSTRAINT (critical)

**Do NOT deploy the API before applying migration 0013 to prod.** The committed models now
declare `tenant_id` on 16 tables; deploying that code against the un-migrated prod schema breaks
queries. Correct order: (1) Jon mints fresh ADC, (2)
`.venv/bin/python scripts/apply_migrations_connector.py` (picks up 0013 automatically),
(3) `bash scripts/deploy.sh`. Web (Firebase Hosting) deploy of F1 is schema-independent and can
go anytime — but F1's manual QA checklist (below) should be walked first.

## 3. R2 wave-review outcomes (F0+F1 implementation)

Architect + critic both returned **zero HIGH**. MED/LOW fixes applied before commit:
- Migration setval now `GREATEST((SELECT MAX(id) FROM tenants), 1)` — re-running 0013 after
  tenant 2 exists can no longer rewind the sequence into a PK collision (critic MED-1).
- `platform_admin` ShellConfig removed from App.tsx (was over-scoped; rendered controls its
  authz denies). Backend authz entry stays ({admin_tenants, admin_users}). F4 re-adds the shell
  + per-sub-tab gating (architect M2 / critic MED-2; F4 TODO comment in AdminConfig.tsx).
- Sales keeps **Archive** in its flat list (TRD-F1 §3b had silently dropped it — violated the
  Perkins-unchanged gate; TRD is the doc in error, restore was per P1). (architect M1)
- Latent crash fixed in `app/models.py` seed listener: generic `Table.insert()` has no
  `on_conflict_do_nothing`; now uses `sqlalchemy.dialects.postgresql.insert`. (orchestrator find)
- Seam contract amended: F0 does NOT plant `set_tenant_context` call sites; F4 plumbs the single
  call in the shared session dependency as its first step (TRD-F0 §10.2 updated). (architect L4)
- `test_existing_rows_have_tenant_id_1` marked SMOKE-ONLY on SQLite (real backfill guarantee is
  the PG migration; behavioral default coverage is TestNewRowDefaults). (critic LOW-1)

## 4. Outstanding for Jon (human actions)

1. **Apply migration 0013 to prod** (then API deploy is unblocked) — §2 order.
2. **F1 manual QA checklist sign-off** (R1 item; full checklist in the f1-exec report — sign-in
   per role, every tab reachable, mobile drawer at 390px, legacy `users`/`config` keys render
   AdminConfig, `npm run build` green). Web deploy after.
3. **Send Tim's email** (`docs/2026-07-08-tim-email.md`) — golden files + 3 pricing
   confirmations gate F2's contract-grade signoff (22 `_pending` fixture fields map to it).
4. Standing blockers unchanged: jarvis #315–331 (Cloudflare token #330, Solar API enablement
   #331, creds, app reviews).

## 5. Next session

**F2 (estimating engine) per TRD-F2** — the critical-path wave for the ~3-week F3 commercial
deliverable (F0 → F1∥F2 → F3). Start: `pricing_configs` model/migration 0014 (TDD fail-first),
pure `estimate(config, input)` refactor, RFC 8785 hash (`jcs` pin), cost-category tags +
eligible_base floors, seed from `infra/fixtures/pricing_config_exhibit_b.json`. Exhibit-B-derived
unit fixtures are the internal gate; golden files land via Tim. F2b (Solar API) can interleave
after 0015 (code parallel, migration sequential). Known env facts: jinja2/openpyxl NOT in
`app/requirements.txt` yet (F3 adds), `firebase-admin>=7.5` already pinned, test suite runs
SQLite (`tests/conftest.py`), RLS tests need the F4 Postgres fixture (TENANCY_PG_URL).

## 6. Session gotchas learned

- **Headroom's per-command output compressor can garble pytest output** (rendered "Pytest: No
  tests collected" for a 132-passed run, even through file redirects). Ground truth = the
  backgrounded `(pytest ... > /tmp/x.log; echo EXIT=$?)` pattern, then grep the log's summary
  line + EXIT marker. Trust those two, not the compressed inline echo.
- OMC teammate agents (opus reviewers especially) may go idle before their report lands —
  nudge via SendMessage; reports arrive ~1–2 min after.
- Parallel doc/fix agents with disjoint file ownership worked cleanly (9 + 3 + 2 concurrent);
  one stray `.omc/` state dir appeared inside the docs folder (agent cwd artifact) — delete
  before committing.
- Migration files MUST be `.sql` — `scripts/apply_migrations_connector.py` globs `*.sql` only;
  a `.py` migration is silently skipped (caught in R2; TRDs F3–F6 renumbered 0017–0020).

---
*Standing archive directive (performed this session): moved oldest top-level continuation
(`CONTINUATION-2026-07-06.md`) into `docs/continuations/`; top level now holds 2026-07-06-pm,
2026-07-08, and this file (≤3); fixed the inbound link in README §Session history; README index
"most recent" now points here. Apply the same directive on every future continuation.*
