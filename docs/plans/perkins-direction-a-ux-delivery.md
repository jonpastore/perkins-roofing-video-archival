# Delivery plan: Perkins Direction A v5 UX

Status: **IMPLEMENTATION AUTHORIZATION PACKAGE — no production work authorized**  
Risk tier: **CONSEQUENTIAL** (role-scoped operational UX with customer, proposal and payment-adjacent data)  
UX baseline: [Direction A v5](../../.project/reviews/perkins-uiux-direction-a-v5.md), approved at 97/100  
Verification baseline: [TST-UX Direction A](perkins-direction-a-ux-verification.md)

## Product/repository responsibility map

The workspace contains one Git repository, `video-archival` (`main` at `3a150ed` when planned). It is a monorepo with independent deployable surfaces, not separate product lifecycles.

| Boundary | Owns | Consumes / produces | UX impact | Release/version-skew risk | Planned disposition |
| --- | --- | --- | --- | --- | --- |
| `web/` | React/Vite shell, navigation, customer/sales/admin/platform views, client API layer and visual tokens | authenticated API responses; produces browser interactions | Primary Direction A implementation | browser cache/client-server response compatibility | UX IMPLEMENTATION REQUIRED |
| `api/`, `core/`, `app/` | FastAPI routes, role/tenant/branch enforcement, customer/quote/proposal/billing projections | database/domain models; produces scoped API contracts | data availability, errors, async status, authz | endpoint response and permission compatibility | UX IMPLEMENTATION REQUIRED only where existing contract lacks approved presentation data/scope |
| `infra/` | migrations, delivery configuration, browser-facing deployment/rollback environment | app/web artifacts; produces runtime infrastructure | only rollout, CI visual-test support and needed backwards-compatible migration | migration/deploy rollback | NO CHANGE REQUIRED initially; evaluate per accepted API/schema change |
| external GHL/payment/handoff systems | account mappings and authoritative external contracts | not accessed by this plan | stable user labels and deferred state surfaces only | high, gated integration enablement | IMPLEMENTATION CONTRACT DEPENDENCY / PRE-PRODUCTION CONFIGURATION |

Existing worktree is occupied by user-owned, untracked design/control-plane artifacts. It is **read-only for discovery and planning**. After authorization each package receives one owned isolated worktree; no reset, clean, stash or overwrite is permitted.

## Delivery sequencing

```text
PLAN-UX-01 shell/tokens/role routes
       ├── PLAN-UX-02 Today master/detail queue
       ├── PLAN-UX-03 customer/property/sales record workspace
       └── PLAN-UX-04 corporate/content/platform workspaces
                         └── integration and accessibility/visual conformance

PLAN-UX-05 deferred external-state projection (not executable until gates)
```

`PLAN-UX-01` is the foundation because it establishes role-gated routes, responsive shell and shared interaction tokens. Packages 02–04 can then run in separate worktrees if they do not change the same shared route/token/API-contract files. The integration coordinator owns contract overlap and final conformance.

## Work packages

### PLAN-UX-01 — Direction A shell, role routes and interaction tokens

- **Goal / refs:** Establish the approved role-scoped IA, saved navigation behavior, responsive shell and visual language. `DEC-UX-01`, UX-DIRECTION-A-V5, parity navigation rows, `TST-UX-01/02/06/07/10`.
- **Repository / likely paths:** `web/src/App.tsx`, `web/src/ui.tsx`, shell/navigation CSS and role/auth helpers; `web/src/api.ts` only if `/me` data is insufficient; corresponding API auth/me routes and `tests/api/test_me_endpoint.py`, `tests/api/test_me_nav.py`, `tests/api/test_f1_authz.py` only for verified gaps.
- **Contract:** Navigation is a presentation of server-authorized capabilities, never its substitute. Branch/sales receive operational work; corporate adds Reports/Content Operations; Platform Admin receives Platform Operations only unless an audited support context is granted. Keep saved pins/folds. Do not ship the prototype review-scenario control.
- **Acceptance:** No inaccessible role route; no branch/customer/revenue copy for unscoped Platform; primary call CTA uses non-destructive product treatment unless recorded brand/contrast evidence supports otherwise; selected row is non-error semantics; narrow widths retain context and usable detail transition.
- **Verification / observability:** `TST-UX-01/02/06/07/10`; server direct-route denial; visual snapshots at 1440×900, 1280×800, 768×1024, 390×844 and 200%; axe/keyboard/contrast checks. Record client route/auth-denial telemetry without sensitive data.
- **Rollout / rollback:** feature-flag or role-scoped rollout if shell replaces existing navigation; retain legacy route aliases until all approved destinations are reachable. Rollback switches flag/route mapping, no data migration.
- **Execution topology:** `agent/PLAN-UX-01`, `.worktrees/PLAN-UX-01`, base `3a150ed`; exclusive `web-shell-role-nav`, `api-me-capability-contract`; integration owner: designated release/integration owner.

### PLAN-UX-02 — Today risk queue and accessible master/detail workflow

- **Goal / refs:** Implement the branch-scoped Today queue with risk/owner/next action/freshness, stable payment labels and asynchronous no-reload detail/action flows. UX-DIRECTION-A-V5; `PRD-GL-01/04/05`, `NFR-GL-03/04`, `TST-UX-03/06/07/08/10`.
- **Repository / likely paths:** new/updated `web/src/pages` queue/detail modules, shared UI primitives, `web/src/api.ts`; `api/routes/dashboard.py`, customer/proposal/invoice projection routes and `core/dashboard.py` only where an existing scoped projection needs a backward-compatible field/endpoint; matching API/domain tests.
- **Contract:** UI consumes app-scoped projection data. Canonical user labels are Payment pending, Payment verified, Payment exception and Policy review required. It never treats CRM stage, browser action or provider state names as proof. No live GHL/provider/handoff enablement.
- **Acceptance:** loading/empty/error/stale/duplicate states explain next safe action; row focus/selection is announced; Enter/Space moves into detail as designed; Escape/Back returns focus to originating row; async success/failure preserves focus and queue context; mobile/tablet never becomes an unusably long contextless detail page.
- **Verification / observability:** `TST-UX-03/06/07/08/10`; API authorization, cursor/order and stale data tests; Playwright/axe/keyboard flow; visual regression with ugly data. Telemetry: queue load/action error/retry and permission denials (redacted).
- **Rollout / rollback:** role/branch pilot, compare task completion/error rates, retain old dashboard link until parity check passes; flag rollback to legacy dashboard/queue.
- **Execution topology:** `agent/PLAN-UX-02`, `.worktrees/PLAN-UX-02`, base after PLAN-UX-01 merge; claimed `web-today-master-detail`, `api-work-queue-contract`; integration owner owns any response contract change.

### PLAN-UX-03 — Customer, property and sales record workspace

- **Goal / refs:** Reframe existing customer/property, estimate, proposal, invoice and payment surfaces around the approved record-first experience without capability/data loss. UX-DIRECTION-A-V5, parity customer/sales rows, `PRD-GL-07/08/10`, `TST-UX-01/04/05/06/07/09`.
- **Repository / likely paths:** `web/src/pages/Customers.tsx`, `Quoting.tsx`, `Proposals.tsx`, `ProposalBuilder.tsx`, `Invoices.tsx`, `Payments.tsx`, `Scheduling.tsx`, `web/src/api.ts`; `api/routes/customers.py`, proposal/invoice/payment routes and serializers only where needed; existing `tests/api/test_f3_customers.py`, `test_f3_proposals.py`, billing/quote tests plus new UI tests.
- **Contract:** A tenant-global Person is visually distinct from an authorized branch operational relationship; never auto-merge or expose cross-branch data. Preserve multiple contacts/properties, measurements/provenance, revision lineage and public proposal flow. Automated messages disclose approved team sender/template provenance; human activity remains clearly human.
- **Acceptance:** CRUD, deactivate, search/filter/sort/pagination, contact/property editing, measurement-to-estimate/proposal path, payment/aging context and public signing stay reachable. Destructive action waits for server success and communicates error/recovery. No personal sender is implied for automatic outreach.
- **Verification / observability:** `TST-UX-01/04/05/06/07/09`; fixture-rich component/API/visual tests; direct API BOLA/branch denial; focus return after saves/deactivate; audit of destructive/identity-sensitive operations.
- **Rollout / rollback:** use route-level feature flag and preserve old URLs/redirects; no destructive data migration. Rollback returns old record screens while server contracts stay backward compatible.
- **Execution topology:** `agent/PLAN-UX-03`, `.worktrees/PLAN-UX-03`, base after PLAN-UX-01 merge; claimed `web-customer-sales-workspace`, `api-customer-sales-projection`; coordinate with PLAN-UX-02 for shared detail primitives.

### PLAN-UX-04 — Corporate/content and Platform Operations separation

- **Goal / refs:** Make preserved content, reporting, integration-health, logs/audit, tenant/SSO and administration destinations discoverable only to their authorized roles. UX-DIRECTION-A-V5, parity admin/platform rows, `PRD-GL-03`, `NFR-GL-03/04`, `TST-UX-01/02/06/07/09`.
- **Repository / likely paths:** `web/src/App.tsx`, `Status.tsx`, `Articles.tsx`, `Archive.tsx`, `Logs.tsx`, `AdminConfig.tsx`, `Knowify.tsx`, related configuration pages; `api/routes/connections.py`, `logs.py`, admin/platform routes and auth policies only for proven scope gaps; existing auth/negative-platform/log tests.
- **Contract:** Corporate is not Platform Admin. Platform shell must not surface branch/customer/revenue data or counts absent a separately authorized/audited support context. Raw credentials/payloads remain server-only.
- **Acceptance:** Corporate sees Reports + Content Operations and not Platform Operations. Platform sees only Platform Operations by default. Preserved operations remain reachable for entitled users and return clear empty/loading/degraded states; no source data leaks through labels/counts.
- **Verification / observability:** `TST-UX-01/02/06/07/09`; direct route/API denial including tenant and branch cases; visual role snapshots; axe/keyboard. Log scope denials and redacted integration-health failures.
- **Rollout / rollback:** role-by-role internal rollout, preserve legacy deep links where authorized; rollback route mapping/flag with no database migration.
- **Execution topology:** `agent/PLAN-UX-04`, `.worktrees/PLAN-UX-04`, base after PLAN-UX-01 merge; claimed `web-specialist-role-workspaces`, `api-platform-scope-contract`; integration owner resolves nav overlap.

### PLAN-UX-05 — Deferred external lifecycle-state projection

- **Goal / refs:** Only after the named external contracts exist, project GHL/payment/handoff lifecycle states into the already-approved stable UX language. `PRD-GL-02/05/06/09/11`, TRD-GL, `TST-GL-02/03/07…15`, `TST-UX-08`.
- **Status:** **NOT EXECUTABLE.** This is a reserved package, not authority to create adapters, credentials, webhook configuration or remote dispatch.
- **Dependencies:** EXT-GL-01, EXT-GL-02, EXT-GL-04 and EXT-GL-07 implementation-contract evidence; EXT-GL-05/06 before production configuration as applicable.
- **Acceptance when authorized:** authenticated server-side adapters only; redacted/signed contract fixtures; canonical stable user labels; no provider/GHL stage becomes payment proof; safe manual review for missing policy/contract; all TST-GL and security gates pass.
- **Execution topology:** allocate only after a new DeGenito-approved delivery revision; expected exclusive resources `external-payment-contract`, `ghl-connection-contract`, `remote-handoff-contract`.

## Integration, rollout and ownership

- **Integration owner:** assigned only on implementation authorization; reviews all package diffs, response-contract compatibility, coverage, UX/security conformance and merge order. Consequential implementers do not self-merge.
- **Merge order:** PLAN-UX-01 → (PLAN-UX-02, 03, 04 in controlled parallel worktrees) → integration conformance. PLAN-UX-05 is excluded.
- **Rollout:** internal/admin smoke → one branch pilot → controlled role/branch expansion → full. Advancement requires the applicable TST-UX gates and no unresolved high UX/security defect.
- **Rollback:** route/feature-flag restoration first; all client/API changes must remain backward compatible during pilot. Any approved migration needs an explicit separate migration/forward-recovery addendum.

## Residuals and gates

| Item | Classification | Why / disposition |
| --- | --- | --- |
| Existing shell/page composition and precise component extraction | IMPLEMENTATION_DETAIL | Resolve with Superpowers task plans inside the approved UX contract. |
| Browser/assistive-tech, visual, async and scope tests | TEST_VERIFICATION_REQUIREMENT | Required before package completion; prototype evidence is not release evidence. |
| GHL/payment/handoff account contracts | IMPLEMENTATION_CONTRACT_EVIDENCE | Needed only for PLAN-UX-05, not for Direction A shell/record work. |
| Credentials, approved policy values/notices, retention/legal validation | PRE_PRODUCTION_EXTERNAL_CONFIGURATION | Fail closed; no placeholder production values. |
| Current-release iOS build-91 call evidence | RELEASE_EVIDENCE | Parallel runtime lane; unrelated to this web UX plan unless a verified behavior changes UX. |
| No current write-safe implementation worktree | LOW_RISK_RESIDUAL | Create isolated worktrees only after authorization; current tree remains untouched. |

There is no load-bearing UX design blocker. **Implementation authorization remains a product-owner decision.** On authorization, use Superpowers `writing-plans`, then isolated worktrees, TDD, code review and fresh verification. Do not silently redesign.
