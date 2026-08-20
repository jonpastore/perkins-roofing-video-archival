# Continuation handoff — Perkins Roofing UX delivery authorization package

Date: 2026-08-20  
Workspace: `/home/jon/projects/perkins-roofing/video-archival`  
Repository: `video-archival` (single Git monorepo; planning baseline commit `3a150ed`)  
Mode / phase: `BROWNFIELD` / `ux-verification-and-delivery-planning-complete-awaiting-implementation-authorization`

## Resume rule

Read this handoff first, then reconcile only the current durable control-plane files and Git status. Do **not** restart UX discovery, repeat the product-owner interview, reopen Direction A selection, resume the parked broad system-design consensus, or begin implementation without a new explicit user authorization.

## Explicit approvals to preserve

- **UX design baseline:** APPROVED by the product owner.
- **Authoritative UX artifact:** `.project/reviews/perkins-uiux-direction-a-v5.md`
- **Direction:** Direction A v5 / Direction A hybrid.
- **UX Design Readiness:** 97/100.
- **UX baseline scope:** approved navigation/IA, product language, capability/data parity, role/data scope, responsive behavior, accessibility, master/detail queue, customer/property pattern, team sender identity, staff/manager differences and platform-specific dispositions.
- **Production implementation:** NOT YET AUTHORIZED.
- **System implementation readiness / release readiness:** separately tracked and still blocked; UX approval does not clear them.

## Current lifecycle state

Canonical state is `.project/project-state.yaml`; execution ownership is `.project/execution.yaml`.

```text
UX_DESIGN_STATUS: APPROVED
UX_DIRECTION: Direction A v5
UX_DESIGN_READINESS: 97
IMPLEMENTATION_AUTHORIZATION: PENDING_PRODUCT_OWNER
SYSTEM_DESIGN_REVIEW: DEFERRED_BY_USER_SCOPE
```

The next authorized lifecycle action is to obtain explicit implementation authorization for `PLAN-UX-01` through `PLAN-UX-04`. Only after authorization use the Superpowers sequence: `writing-plans → isolated worktrees → implementation/TDD → review → verification-before-completion → DeGenito conformance`.

## Frozen UX package and evidence

- Approved UX baseline: `.project/reviews/perkins-uiux-direction-a-v5.md`
- UX strategy: `.ux-review/03-ux-strategy.md`
- Capability/data parity: `.ux-review/feature-capability-parity.md`
- Prototype review and adversarial findings: `.ux-review/05-prototype-review.md`, `.ux-review/06-adversarial-design-review.md`
- Disposable prototype: `.ux-review/prototype/` — never production code.
- Fresh representative render evidence is enumerated in the v5 package, including manager/corporate/platform role navigation, sender provenance, tablet, mobile dialog and bounded zoom-layout checks.

Do not silently change these baseline decisions during implementation. Material changes require a UX change proposal.

## Approved implementation-quality refinements

Carry these into tests/work packages; they are **not** a reason to reopen UX approval:

1. Use a non-destructive primary/brand treatment for “Call Marisol” unless documented brand/contrast evidence supports red.
2. Check small/supporting text at normal and 200% browser/text scaling and representative laptop widths.
3. Never ship the prototype-only “Review scenario: Branch manager” control without separately approved role-switching design.
4. Ensure selected-row styling does not communicate error/destructive meaning.
5. Define and test master/detail focus, selection, screen-reader announcement, entry into detail/actions, return to queue, and post-async focus behavior.
6. Preserve the approved hierarchy at narrow widths; no context-losing long detail flow.

## Verification and delivery plans ready for authorization

- Verification matrix: `docs/plans/perkins-direction-a-ux-verification.md`
- Delivery plan: `docs/plans/perkins-direction-a-ux-delivery.md`
- Traceability: `.project/traceability.md`
- Decision record: `.project/decisions.md` (`DEC-UX-01`)

### Executable only after user authorization

| Package | Purpose | Scope |
| --- | --- | --- |
| PLAN-UX-01 | Direction A shell, role routes, interaction tokens | `web/`; API auth/me only for proven capability-contract gaps |
| PLAN-UX-02 | Today risk queue and accessible master/detail workflow | `web/`, scoped API/domain projections only if necessary |
| PLAN-UX-03 | Customer/property/sales record workspace | `web/`, existing customer/quote/proposal/invoice/payment contracts only as needed |
| PLAN-UX-04 | Corporate/content and Platform Operations separation | `web/`, scope/authorization endpoints only for verified gaps |

### Explicitly deferred / not executable

`PLAN-UX-05` (GHL/payment/handoff lifecycle state projection) requires named external contract evidence. It does not authorize adapter code, credentials, webhooks, remote dispatch or production configuration.

## Deferred non-UX work (preserve, do not resume)

The broad architecture/integration consensus is parked by explicit user scope. Preserve its findings, but do not continue iterations or spend effort raising its readiness unless the user reprioritizes it.

- `EXT-GL-01`: exposed GHL credential must never be reused; rotate/revoke and obtain safe access before account discovery.
- `EXT-GL-02`: least-privilege GHL discovery/scopes/location/log/non-production evidence.
- `EXT-GL-04`: authenticated authoritative payment-provider contract.
- `EXT-GL-05`: legal/privacy validation before production.
- `EXT-GL-06`: approved external contractual/business policy values and notices before production configuration.
- `EXT-GL-07`: remote-handoff destination/authentication/acknowledgement/idempotency/retry/compensation contract.
- Current iOS build-91 runtime verification remains a parallel release-evidence lane; it is not a UX blocker absent a verified UX-impacting runtime fact.

## Repository / worktree safety

- This workspace is a **single Git monorepo** with `web/`, `api/`, `core/`, `app/` and `infra/` boundaries. Do not invent sibling repositories.
- At handoff, `git status --short` has user-owned/untracked design/control-plane/prototype artifacts (notably `.project/`, `.ux-review/`, `.devsecops-review/`, `docs/requirements/`, `docs/plans/`, `output/`). Preserve them.
- No production implementation code was modified in this planning phase.
- No implementation worktree exists. Do not reset, clean, stash, checkout over, or write into the current dirty worktree.
- After authorization, create one isolated worktree per write-owning `PLAN-UX-*` package as specified in the delivery plan; record ownership/heartbeats in `.project/execution.yaml`.

## Validation already completed

- YAML syntax checks passed for `.project/project-state.yaml`, `.project/artifact-registry.yaml`, and `.project/execution.yaml`.
- Project context review completed with `morpheus-ek graph review-context` for the planning artifacts.
- `morpheus-ek policy check --target .` passed (reported `cards: 0`, readiness score 80 because no policy-pack coverage was available).
- No production test suite was run because only documents/control-plane/prototype-baseline state changed; implementation verification remains planned, not evidenced.

## Evidence-driven requirements and planning continuation

The product owner asked for a no-questions continuation while unavailable.
Make reversible, documented assumptions and put every genuine unresolved decision
in a prioritised question register with a recommended default and impact. Do not
stop to request routine clarification.

### UX decision contract (reconfirm; do not reopen)

Report these values at the beginning of the next session:

```text
UX baseline: APPROVED
Frozen artifact: .project/reviews/perkins-uiux-direction-a-v5.md
UX readiness: 97/100
Production implementation: NOT YET AUTHORIZED
System implementation readiness: separately tracked
Release readiness: separately tracked
```

Do not repeat broad UX design, requirements discovery, system architecture, or
consensus work. The parked broad architecture/integration review remains parked.
The six approved implementation-quality refinements above remain test and work
package requirements, not design-approval gates. Preserve all frozen Direction A
v5 capability/data parity, role/data-scope, product language, IA, responsive,
accessibility, state/interaction, sender identity, master/detail, customer/property,
staff/manager, and platform-specific capability decisions. Any material departure
is a UX change proposal; never silently redesign.

### Proposal to canonical development requirements

Locate and process `DeGenito-Perkins-Partnership-Proposal-2026-08.pdf`. Extract
text with page-level provenance (OCR if needed) and reconcile it with existing
canonical specifications and requirements rather than creating a duplicate
requirements system. Map each source requirement to the canonical spec, PRD, TRD,
DDD, or UIUX artifact; create a new feature artifact only for genuinely separate
scope.

Record business goals, scope/non-goals, roles, workflows, data, integrations,
business rules/states, acceptance criteria, technical contracts, security/privacy,
operational constraints, error cases, observability, rollback, and UX implications.
The frozen UX baseline controls UX; the proposal is the primary business source.
Build a source/conflict/assumption matrix with proposal page references.

### Meeting evidence: read-only Gmail and remote Zoom recording

First configure the new Codex session to use the existing local LiteLLM endpoint
at `http://127.0.0.1:4000`, using the currently supported Codex configuration
method without overwriting unrelated global settings or exposing credentials.
Independently confirm LiteLLM connectivity and that `gmail_enhanced_mcp` is
available. Use that MCP read-only to retrieve today's Zoom meeting notes and
related proposal/partnership messages. Do not send, delete, label, or otherwise
change email. Treat notes as clarifying evidence, not an unrecorded override of
the proposal or approved UX package.

The complete local Zoom recording package was copied intact and checksum-verified
to Cerberus. Process this remote directory, preserving the source files:

```text
jon@cerberus-ai:~/projects/perkins-roofing-video-archival/2026-08-20 13.48.04 Review Proposal/
```

It contains the Zoom conversion segments
`double_click_to_convert_01.zoom` and `double_click_to_convert_02.zoom`, plus
`recording.conf`, `zoomver.tag`, `chat.txt`, and temporary audio/video conversion
files. The source recording must not be overwritten or deleted. Convert/transcribe
on Cerberus, use speaker labels only where reliable, retain provenance, and do not
commit raw media, credentials, or unnecessary sensitive transcript content.

Verified SHA-256 values:

```text
088d8ab2e560160625012e6ed7e68dcf358b153cbaeb7bd653a5e69983a8c5ed  double_click_to_convert_01.zoom
89a5d3eee234a5cef1bd26b1982f8bb2981bf96f7bfe2d4842f615c67a8d6f43  double_click_to_convert_02.zoom
```

If LiteLLM, the MCP, PDF, or a required conversion utility is unavailable, record
the exact blocker and continue every other planning task.

### Reconcile—do not restart—verification and delivery planning

The existing verification matrix and delivery plan are already ready for
authorization. Validate, reconcile, and extend them for the proposal and meeting
evidence; do not restart either lifecycle phase. Verification must cover capability
and data parity, role/data scope, async/no-reload behavior, loading/empty/error/
stale/duplicate states, master/detail selection, keyboard/focus, WCAG 2.2 AA,
contrast, 200% scaling, responsive breakpoints, realistic/ugly data, visual
regression, destructive actions, server-side authorization assumptions, and
first-party coverage.

Create repository-specific work packages only where justified. For each repository
state its UX responsibility, required implementation, dependencies/contracts,
likely files/components, verification duties, worktree/branch ownership, and
rollout/rollback implications. Classify each as exactly one of:

- `UX IMPLEMENTATION REQUIRED`
- `IMPLEMENTATION CONTRACT DEPENDENCY`
- `DEFERRED PRE-PRODUCTION CONFIGURATION`
- `NO CHANGE REQUIRED`

Do not create work merely because a repository exists, and do not pull deferred
GHL, payment, legal, or production configuration into scope unless a specific
approved UX behavior requires it.

### Required stopping condition

Do not modify production code. Commit only validated documentation, traceability,
plan, and handoff updates; never commit secrets, raw recordings, or credentials.
Prepare the implementation authorization package, including canonical artifact
links, proposal/Zoom/Gmail provenance and conflict matrix, complete assumptions,
prioritised questions with recommended defaults, repository work packages,
verification obligations, authorization boundaries, and an explicit confirmation
that no production code was modified. Stop when that package is ready for product
owner approval.
