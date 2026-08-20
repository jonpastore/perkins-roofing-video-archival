# Continuation — 2026-08-20: GHL lifecycle / UX consensus v4

## Resume rule

This is a resumed brownfield UX/design engagement. **Do not restart discovery, UX strategy,
prototype construction, parity mapping, adversarial review, or the consensus loop.** Read the
current installed skills first, then load `.project/project-state.yaml` and the artifacts below.
Preserve all product-owner decisions, prototypes, screenshots and capability/data dispositions.

## Current lifecycle state

- Mode/phase: `BROWNFIELD`, solution design; resolve user/external conditions.
- Current consensus: iteration 4 completed under **stop condition C**.
- Bounded design outcome: Direction A (Revenue command center) is conditionally approved as a
  read-only design/mirroring strategy. Direction B remains Pipeline; Direction C remains the
  Customer/property workspace.
- Executable-plan Evidence Readiness: **89/100 maximum**. It cannot reach the 95/100 gate until
  the remaining external/user/legal conditions are closed.
- Production authorization: **not granted**. No production application code, GHL configuration,
  payment-provider configuration, credentials, secrets or account data were changed.

## Authoritative/durable artifacts

Read these in this order:

1. `.project/project-state.yaml`
2. `.project/reviews/ux-design-consensus-v4.md`
3. `.project/decisions.md` and `.project/traceability.md`
4. `docs/specs/ghl-lifecycle-integration.md`
5. `docs/requirements/ghl-lifecycle-integration-{prd,ddd,trd,uiux}.md`
6. `docs/plans/ghl-lifecycle-integration-verification.md`
7. `.devsecops-review/ghl-lifecycle-design-readiness.md`
8. `.ux-review/{02-product-interview,03-ux-strategy,04-design-directions,05-prototype-review,06-adversarial-design-review,feature-capability-parity}.md`
9. `docs/continuations/CONTINUATION-2026-08-19-ghl-discovery.md`

The consensus iterations are retained at `.project/reviews/ux-design-consensus-v{1,2,3,4}.md`.
V4 contains the complete final classification and reviewer result; do not repeat iterations 1–4
unless a change invalidates their snapshot.

## Work completed and preserved

- Product-owner interview decisions, including GHL/app authority, risk ordering, response SLA,
  branch/corporate roles, lifecycle/payment boundary, and mobile/laptop intent.
- UX strategy, design directions, capability/data parity matrix and three isolated mock-data
  prototype surfaces with rendered/adversarial evidence.
- CompanyCam parity language reconciled to concrete API, sync/webhook and rendered status surfaces.
- GHL requirements/domain/TRD/UIUX baseline drafted with role/capability/data scope, state rules,
  field/event authority, durable inbox/ledger/outbox, ordering/retry/conflict/rollback policy,
  sender policy analysis, accessibility and browser/device verification matrix.
- Security design requirements and threat/control evidence drafted under `.devsecops-review/`.
- Independent consensus reviews completed through iteration 4. No unresolved agent-resolvable or
  true-blocker finding remains.

## Remaining conditions — do not infer

| ID | Classification | Needed to continue |
| --- | --- | --- |
| EXT-GL-01 | EXTERNAL_ACCESS_REQUIRED | Credential rotation, then read-only Perkins GHL account mapping: location/sub-account IDs, installed scopes, custom fields, pipeline/stages, workflow dependencies, webhook payloads/logs/retries and compatibility. Do not change GHL configuration. |
| DEC-GL-01 | USER_DECISION_REQUIRED | Final automated sender wording and whether personal identity is permitted. Recommendation: `Perkins Roofing — <Branch> Team`; safe fallback: `Perkins Roofing team`. |
| DEC-GL-04 | USER_DECISION_REQUIRED + EXTERNAL_ACCESS_REQUIRED | Select required-deposit verification source/provider; then verify its authenticated event/account contract before any Won/handoff transition. Existing app manual/Knowify payment records do not select that provider. |
| DEC-GL-05 | USER_DECISION_REQUIRED / REQUIRES_LEGAL_REVIEW | Set PI/audit/raw-webhook retention, deletion exceptions and legal basis. Until decided, retain only the documented minimization/platform-restriction design; do not claim compliance. |

The affected workstreams may remain blocked while independent non-production documentation or
account mapping proceeds. Do not claim the 95/100 executable-plan gate or produce delivery plans
that include outbound GHL/payment/Won-handoff implementation before these conditions close.

## Validation evidence and known environment gap

- Pure authorization/OAuth validation passed: 173 tests across `tests/core/test_authz.py`,
  `tests/core/test_oauth_state.py`, `tests/test_f1_authz.py`, and `tests/test_oauth_store.py`.
- API/model-backed CompanyCam and proposal tests could not collect because the local environment
  lacks the `jcs` Python dependency. Treat this as an environment/evidence gap, not a product
  regression; do not hide it with exclusions.
- Headless prototype checks were performed using the repository-root static server. The prototype
  directory server caused a false logo 404 and is not valid evidence. The correctly rooted run had
  zero console errors and verified navigation focus return, task-sheet focus, outcome-dialog focus
  and Escape return.

## Next-session procedure

1. Load the current installed lifecycle, consensus, requirements, security and verification skills.
2. Read the artifacts above and inspect `git status --short`; preserve unrelated/untracked work.
3. If the owner supplied a remaining decision, update only the owning requirements/decision/state
   artifacts and assess changed-snapshot impact.
4. If GHL credentials are confirmed rotated, run only read-only account discovery; record sources,
   exact IDs/scopes/payload evidence and any contradiction. Do not create/edit workflows, fields,
   stages, locations, credentials or messages.
5. Re-enter consensus only for materially changed artifacts/conditions. Use the first unused
   iteration only if the existing v4 snapshot has changed; otherwise continue from the current
   state and do not recreate reviewer work.
6. After all conditions are resolved and the 95/100 gate passes, obtain explicit design/implementation
   authorization before delivery planning or production changes.

