# Plan v2.1: Multi-platform comments + OAuth health alarm + self-service capture

Status: **CONSENSUS APPROVED** (ralplan: v1 → Architect [3 HIGH] → Critic ITERATE [10 items] →
v2 → Architect delta [resolved + N1/N2] → v2.1 → Critic APPROVE, no residuals) —
**awaiting user execution approval**. Implementer note (non-blocking, from final Critic pass):
confirm the exact core/offboard.py registry/exclusion mechanism name when coding Phase 1.2.
Revision log at bottom maps every Critic checklist item to its change.

## RALPLAN-DR summary

**Principles**
1. Human-in-the-loop is structural: no auto-post path exists; #88 gates any future flag; **E1 (`run_gate(text,"social")`) is enforced in the provider `post_reply` wrapper so every platform is gated BY CONSTRUCTION — and the currently-unwired live YouTube reply path (api/routes/comments.py) gets the gate as this plan's first shipped change.** (v1 wrongly described this as already true.)
2. One credential system: `SecretManagerOAuthStore` per-tenant for everything new; legacy env creds migrate — **including YouTube reply OAuth (YOUTUBE_OAUTH_REFRESH_TOKEN / OAUTH_CLIENT_* → store), scheduled explicitly in Phase 1.**
3. Real code, mockable I/O: adapters are real API paths that activate when #319 creds land; fake-tested today.
4. Cost-bounded reads: X reads default OFF behind a per-tenant daily budget.
5. Fail loud, **by severity**: a hard auth failure (401 / `invalid_grant` / revoked consent) alarms on the FIRST probe cycle; only transient errors (5xx/timeouts) wait N=3 consecutive cycles. (Resolves v1's P5-vs-pre-mortem contradiction.)

**Decision drivers** (unchanged)
1. #319 review gating (2–4 wks) → OAuth health + capture UI deliver value NOW and are prerequisites for everything else.
2. Meta's shared app = one review for IG+FB → first external phase.
3. The pipeline generalizes iff comment identity = (tenant_id, platform, comment_id).

**Options**
- **A (chosen, reshaped): extract-don't-freeze provider layer + layered alarm.** Phase 2 lands only the schema + a thin function boundary around YouTube; the formal `CommentProvider` Protocol is EXTRACTED in Phase 3 from two real implementations (YouTube + Meta), not frozen against one. Alarm is layered (below).
- **B (rejected): extend legacy posting adapters** — cements env-cred debt (Principle 2).
- **C (adopted in part — layer split, per Architect synthesis + Critic item 9):** Cloud Monitoring owns **job liveness** (scheduler/job failure → email; ~20 lines of Terraform, native dedup/flap-suppression, R3-aligned). The app owns only the **business status the UI must render** (per-integration current status row) and sends the reconnect email **on status transition to broken** — a previous-vs-new comparison on the row we already store for the UI, not a hand-rolled state machine. No `alerted_at` re-alert logic in v1 of the feature (YAGNI; add re-alerting only if silence-after-first-email proves to be a problem). Option C is no longer strawmanned: native Monitoring does what it's best at; the app does only what Monitoring cannot (render status to Tim/Josh, know a token is dead while the job itself is healthy).

**Pre-mortem (rewritten where required)**
1. *Alarm cries wolf*: transient 5xx → severity split (Principle 5): hard auth failure alarms immediately; transient needs N=3. Email only on transition (prev != broken → broken). Cloud Monitoring's native dedup covers job-level flapping.
2. *Cross-tenant credential write via OAuth callback* (**rewritten — v1's mitigation was impossible**): the callback is an unauthenticated browser GET; **there are no caller claims to re-verify**. The signed `state` is the SOLE tenant binding, so it must be bulletproof: HMAC-SHA256 over {tenant_id, platform, nonce, exp} with the key in Secret Manager (rotatable, two-key overlap window); the nonce is **persisted server-side at /start and burned (single-use, deleted-on-read) at callback** — a replayed or forged state fails signature or nonce; `{platform}` must match a fixed registry; `redirect_uri` is exact-match allowlisted. The store write is keyed by the state's tenant_id **after** signature + nonce validation. `/oauth/{platform}/start` is gated `require_role_db` (tenant-scoped claims) — never legacy `require_role`, which defaults tenant_id=1.
3. *X read costs run away*: unchanged — default OFF, per-tenant daily budget, spend ledger, stop-at-cap.
4. *(new, from Critic-elevated M2)* *The monitor kills the credential*: some providers' refresh tokens are **single-use** (Knowify documented at core/knowify/tokens.py:11; treat any store platform as single-use until verified otherwise; Google refresh tokens are multi-use). A probe that force-refreshes rotates 48×/day and can invalidate a live cred. **Probes are LIVENESS READS ONLY** (cheap authenticated GET per provider); refresh happens only on observed-dead, under the existing advisory-lock pattern (lock 8274125 precedent).

## Phase 1 — OAuth health + self-service capture
- 1.0 **E1 gate fix (ships first, independent value)**: `run_gate(text,"social")` wired into the YouTube reply path (api/routes/comments.py before `post_reply`) — fail-closed, mirrors distribute_job.py:174. This is a live-today gap.
- 1.1 `core/integration_health.py` (pure, 100%): status enum (unconfigured/healthy/expiring/broken), **severity-split transition rule** (hard-auth-fail → broken immediately; transient → after N=3), transition-email decision (prev vs new). No dedup machine beyond that comparison.
- 1.2 Migration **0039**: `integration_status` — tenant_id **NULLABLE** (NULL = platform-level shared integrations: Knowify, Resend, WP — one row, not N duplicates; per-tenant OAuth rows carry tenant_id), integration, status, last_checked, last_ok, last_error, consecutive_failures. Unique(coalesce-tenant, integration) via partial indexes. **RLS decision (N1): RLS is NOT enabled on this table** — it is a platform-level table like `TenantOffboardLog` (app/models.py:403, explicitly no-RLS precedent); queries filter by tenant_id in-SQL; it holds status strings, not tenant content; it is EXCLUDED from the core/offboard.py tenant-table registry (platform-level rows must survive offboarding). This resolves both N1 breakages: tenant-scoped `GET /connections` reads shared NULL-tenant rows via a plain filter, and platform-level probes need no GUC.
- 1.3 Probe functions (adapters, fake-validated): **liveness reads only** — YouTube: tokeninfo/lightweight API GET (no refresh); WP: GET /users/me; Resend: domains list; Knowify: existing `/valid`; store platforms: provider "me"-style read where creds exist. Refresh only on observed-dead under advisory lock.
- 1.4 `jobs/integration_health_job.py`: iterates `core.tenant_loop.for_each_tenant` (tenant GUC per iteration; platform-level rows probed once under platform scope) → persist → **email via resend on transition to broken** (EMAIL_SEND_MODE allowlist respected). `/internal/integration-health` endpoint uses `_require_internal` (api/app.py:315) + Cloud Scheduler OIDC + X-Internal-Secret (infra/main.tf:622 pattern). Terraform: scheduler (30-min) + **Cloud Monitoring alert policy on job execution failure** (job-liveness layer).
- 1.5 `api/routes/connections.py`: `GET /connections` (admin, includes shared + tenant rows); `POST /connections/{integration}/secret` (re-enter form → new secret version); `GET /oauth/{platform}/start` (**require_role_db**, platform-registry check, mints signed state + persists nonce) → provider consent → `GET /oauth/{platform}/callback` (validation order: signature → **exp** → nonce burn → registry → exact redirect → server-side code exchange → SecretManagerOAuthStore write keyed by state tenant_id). **Nonce burn is atomic (N2): `DELETE ... RETURNING`** so two concurrent callbacks cannot both consume one nonce; expired `exp` fails closed. HMAC key: new secret `oauth-state-hmac` (0039-adjacent terraform), two-version rotation supported.
- 1.6 `web/src/pages/Connections.tsx`: status chips, Connect/Reconnect, re-enter-secret modal.
- 1.7 **YouTube cred migration onto the store** (Principle 2): capture-UI "Connect YouTube" writes to the store; `youtube_comments.py` reads store-first with env fallback until cutover, then env path removed.
- **Acceptance** (severity-split aware): staging: (a) revoke a token (hard 401) → broken + exactly one email after the NEXT probe cycle (≤30 min); (b) inject transient 5xx → no alarm until 3 consecutive cycles; (c) reconnect via UI → healthy, nonce single-use verified (replaying the callback URL fails); (d) kill the probe job → Cloud Monitoring email fires. E1: unsafe draft text → reply POST blocked.

## Phase 2 — Comment data model + YouTube seam
- Migration **0040**: add `platform` (backfill 'youtube'); **DROP CONSTRAINT IF EXISTS `comment_drafts_comment_id_key`** (the real prod name from 0007's inline UNIQUE — verify via information_schema in the migration; the ORM-only name `uq_comment_drafts_comment_id` does not exist in prod) and reconcile app/models.py:432 in the same change; add **unique(tenant_id, platform, comment_id)** per the `uq_*_tenant_*` convention (fixes the RLS silent-drop path at crawl_comments.py:144).
- Thin function boundary around YouTube fetch/reply (no Protocol yet — extracted in Phase 3 from two real implementations). Routes gain platform filter; UI badge.
- **Acceptance**: migration applies against a 0007-shaped database (tested on a scratch PG with 0001..0039 applied); existing YouTube tests green; queue filterable.

## Phase 3 — Meta comments (IG+FB) + Protocol extraction
- As v1 (endpoints/scopes/pagination/owner-detection), plus: `core/comment_provider.py` Protocol + CommentDTO **extracted here** from YouTube + Meta; registry-driven crawl lands here. `post_reply` wrapper carries the E1 gate for all providers by construction (the Phase-1.0 route-level gate moves into the wrapper). **Architect residual: the upsert existence SELECT (crawl_comments.py:119) gains `platform` in its filter here** — required once a second platform exists, else same-tenant cross-platform comment_id collisions false-dedupe.
- **Acceptance**: fake Graph server — crawl → drafts platform='instagram'/'facebook' → approve → gated reply with correct endpoint/payload; YouTube regression green under the extracted Protocol.

## Phase 4 — LinkedIn + TikTok (unchanged from v1, incl. honest "unsupported at tier" status)
## Phase 5 — X, cost-guarded default-OFF (unchanged from v1)

## #319 registration additions (unchanged from v1, plus)
- Register `https://<api-host>/oauth/{platform}/callback` redirect URIs everywhere (Phase-1 capture flow).

## Expanded test plan
- Unit (100%): integration_health severity-split transitions + email decision; state sign/verify + nonce burn semantics; CommentDTO (Phase 3); X budget ledger.
- Integration: fake provider HTTP servers (pagination, error paths, owner detection); oauth start/callback — tampered state 403, replayed nonce 403, unknown platform 404, non-allowlisted redirect 400; connections routes with fake auth.
- E2E (staging): the four-part Phase-1 acceptance above.
- Observability: dashboard tile; TenantLogFilter logs; alert emails in email_logs; Cloud Monitoring policy in terraform (drift-checked, R4).

## ADR
- **Decision**: layered alarm (Cloud Monitoring = job liveness; in-app row + transition email = business status) + self-service capture on SecretManagerOAuthStore; schema-first comment generalization with Protocol extracted at Meta; phased Meta → LinkedIn/TikTok → budget-guarded X.
- **Drivers**: #319 gating; credential unification (incl. YouTube env-cred retirement); single-use refresh-token safety; three same-day credential outages.
- **Alternatives**: legacy-adapter extension (rejected: env-cred debt); all-in-app alerting with dedup machine (rejected: reinvents Monitoring; kept only the transition comparison the UI row gives us for free); all-Cloud-Monitoring (rejected: cannot render status to Tim/Josh nor detect dead-token-while-job-healthy); Protocol-first (rejected: freezing an interface against one real implementation).
- **Consequences**: migrations 0039/0040; new secret `oauth-state-hmac`; scheduler + Monitoring policy in terraform; Connections SPA page; YouTube creds move to the store; X spend ledger later.
- **Follow-ups**: re-alert cadence if one-email-per-outage proves insufficient; Meta comment webhooks; auto-post behind #88; per-platform analytics on same creds.

## Revision log (Critic checklist → change)
1. H1 → Phase 2: drop by real name `comment_drafts_comment_id_key`, IF EXISTS + information_schema check, ORM reconciled same migration.
2. H2 → Phase 1.0 ships the YouTube gate fix now; Phase 3 wrapper gates all providers by construction; Principle 1 reworded honestly.
3. H3 → Pre-mortem 2 + Phase 1.5: HMAC key in Secret Manager w/ rotation, nonce persisted+burned single-use, exact redirect allowlist, platform registry, require_role_db on /start.
4. M2 (HIGH) → Pre-mortem 4 + Phase 1.3: liveness reads only; refresh only on observed-dead under advisory lock; single-use-refresh providers enumerated.
5. M1 → Phase 2: unique(tenant_id, platform, comment_id).
6. P5 contradiction → Principle 5 severity split + matching acceptance (a)/(b).
7. Pre-mortem 2 rewritten: state is the sole binding; "re-verify caller claims" removed.
8. P2 → Phase 1.7: explicit YouTube cred migration to the store.
9. Alarm layering → Option C adopted as layer split; ADR justifies; dedup machine dropped.
10. M3/L1/L2 → Phase 1.4 for_each_tenant + _require_internal spelled out; migrations numbered 0039/0040; shared-cred integrations get nullable-tenant platform-level rows.
