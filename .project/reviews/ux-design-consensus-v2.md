# UX design consensus review — v2

Status: UNDER_INDEPENDENT_REVIEW
Iteration: 2
Evidence Readiness: 89/100 maximum for consequential planning until `EXT-GL-01` is directly verified; this is a readiness score, not a probability.
Residual Uncertainty: Perkins-specific GHL account contract and the final customer-facing sender policy.
Reviewer Verdicts: pending independent Architect, Critic and Evidence Verifier review.
Blocking Findings: no unresolved agent-resolvable design/documentation finding. `EXT-GL-01` prevents a 95/100 executable-plan gate; `DEC-GL-01` affects only customer-facing sender wording.
Open User Decisions: DEC-GL-01 only.

## Frozen v2 scope

This snapshot preserves v1 UX artifacts and adds the GHL spec, PRD, DDD, TRD, UIUX,
security-design and verification-design artifacts listed in `.project/artifact-registry.yaml`.
No production code, GHL configuration, credentials, workflows or account data were changed.

Snapshot manifest SHA-256: `ca33d8f08b42345ca144a4c3d2387fff8bfa85689d1ff24b05e58fcb7e0fa3ea`
(`.ux-review/02-product-interview.md`) through
`c4e8ef11ec6c88185c78f617544f32ae8fabbdb7ab54397feae7d601883a2ce9`
(`.project/decisions.md`), recorded in the iteration-2 session evidence. The changed parity,
requirements, security and verification artifacts are included in that manifest.

## Iteration-1 condition disposition

| Condition | Classification | v2 disposition |
| --- | --- | --- |
| CON-UX-01 role/capability/data scope | AGENT_RESOLVABLE | Resolved in the target capability × action × scope matrix in `ghl-lifecycle-integration-ddd.md`; current coarse roles are explicitly not misrepresented as the target policy. |
| CON-UX-02 GHL contract discovery | AGENT_RESOLVABLE + EXTERNAL_ACCESS_REQUIRED | Local/product-owner/public-vendor evidence defines the contract envelope. Perkins field IDs, stages, installed scopes, workflow dependencies and retry logs require rotated credentials and read-only account access. |
| CON-UX-03 sender identity | USER_DECISION_REQUIRED | Agent analysis recommends `Perkins Roofing — <Branch> Team`, safe fallback `Perkins Roofing team`, and defines acceptance. Only final branded wording/permission for personal identity remains. |
| CON-UX-04 calendar/timezone/SLA/metrics | AGENT_RESOLVABLE | DOM-GL-04, PRD-GL-04 and TST-GL-04 define IANA timezone, DST/holiday, policy-version and baseline/telemetry requirements. |
| CON-UX-05 objective verification | AGENT_RESOLVABLE | TST-GL-01…07 cover accessibility, browsers/devices, race/error, authorization, integration and quality gates. |
| CON-UX-06 integrity/security controls | AGENT_RESOLVABLE | DOM-GL-01…05, TRD-GL and SEC-GL-01…06 formally capture conditional transitions, ledger/outbox, scope/audit and correlated/versioned events. Runtime deployment remains future evidence, not a claim. |
| CON-UX-07 CompanyCam wording | AGENT_RESOLVABLE | Parity entry now cites the concrete API, sync/webhook and rendered integration-status surfaces; only the future contextual placement is unimplemented. |

## Evidence and dissent response

- Current code directly supports Firebase/GCIP tenant resolution, RLS-stamped sessions, a
  role→action matrix, audit routes, tenant-scoped CompanyCam readers and CompanyCam webhook
  signature/replay handling. Four pure auth/OAuth test modules passed (173 tests).
- API/model-backed CompanyCam/proposal validation could not collect because this environment is
  missing `jcs`; that is retained as an evidence-environment gap, not a product claim.
- The repository contains no GHL application client. Therefore no account-specific field/stage,
  webhook or migration claim is marked verified.
- HighLevel public documentation supports OAuth-scoped API access, contacts/opportunities/
  calendars/webhooks, event IDs/retries and current Ed25519 webhook signatures. Sources:
  `https://marketplace.gohighlevel.com/docs/intro/index.html`,
  `https://marketplace.gohighlevel.com/docs/webhook/WebhookIntegrationGuide/index.html`, and
  `https://marketplace.gohighlevel.com/docs/ghl/contacts/contacts/index.html`.

## Decision and reversal conditions

Direction A remains the recommended shell, retaining Direction B as Pipeline and Direction C as
the Customer/property workspace. No current capability is deprecated. Reconsider Direction A if
the GHL account cannot support branch-scoped ownership, server scope cannot be enforced, or
payment verification cannot precede Won/handoff. Initial integration rollout remains a reversible,
read-only mirror behind a feature flag.

## Pre-mortem

| Failure | Detection | Mitigation / recovery |
| --- | --- | --- |
| Stale/local activity clears risk work | ledger-version and SLA mismatch telemetry | server-confirmed append-only events; retain follow-up; rebuild projections |
| GHL changes break workflows or cross branches | account dependency inventory and contract tests | scoped connections, compatibility mapping, pilot and disable-outbound rollback |
| Unverified deposit produces Won/handoff | provider reconciliation and negative transition tests | conditional state machine, provider ledger and transactional outbox |
| Scope leak reaches corporate drill-down | negative authorization/audit tests | server-derived scopes, aggregate-first access and revocation/audit |
| Assistive-tech/phone task failure | a11y/device tests and task metrics | retain laptop-first density; correct task flow before rollout |
