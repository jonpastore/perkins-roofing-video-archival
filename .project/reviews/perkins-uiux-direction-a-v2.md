# Perkins Roofing UX Design Package — Direction A Hybrid (v2)

Status: FROZEN FOR UX-ONLY CONSENSUS RECHECK  
Date: 2026-08-20  
Supersedes: `.project/reviews/perkins-uiux-direction-a-v1.md`  
Scope: Brownfield UX and disposable prototype only. Payment/GHL/provider/handoff/legal/release work remains preserved and deferred.

## Candidate and IA

Direction A hybrid remains the candidate: role- and branch-scoped **Today** for urgent revenue work; dedicated **Customers**, **Sales Work**, **Schedule**, **Knowledge/Content Operations**, **Reports**, and restricted **Product Admin/Platform Operations** for the preserved specialist work. The full capability/data disposition remains canonical in `.ux-review/feature-capability-parity.md`; no current meaningful capability is deprecated or silently removed.

## UX design decisions verified in the prototype

- Today is an exception-first work queue, not a replacement for pipeline, customer records, finance, reporting, content, or platform operations.
- A visible customer/property context distinguishes a tenant-global **canonical Person** from the current authorized **branch operational relationship**. Cross-branch linkage requires an authorized/audited relationship; it is never an automatic merge.
- Stable commercial labels are `Payment pending`, `Payment verified`, `Payment exception`, and `Policy review required`; provider/contract internals are not exposed to users.
- Automated communication provenance uses `Perkins Roofing — <Branch> Team`, with `Perkins Roofing Team` as the documented fallback. Human outreach is separate, and a CRM conversation action does not imply an automated send.
- Branch/sales navigation omits restricted destinations. The reviewer-only scenario harness demonstrates corporate Reports/Content Operations and a Platform Admin route that deliberately withholds customer queues absent audited support scope.
- Phone opens a focused record as a modal dialog: role/name semantics, background inert/hidden treatment, focus loop, Escape and row-focus return are modeled. Mobile navigation retains close/focus-return behavior.
- Shared shell controls outside the focused proof announce their prototype-boundary status rather than silently failing.

## Fresh evidence

| Evidence                                                                                                     | What it verifies                                                                                              |
| ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `output/playwright/ux-v2-desktop.png`                                                                        | 1440×900 Direction A hierarchy, long-data-safe record context, sender provenance.                             |
| `output/playwright/ux-v2-tablet.png`                                                                         | 768×1024 labelled tablet navigation and dense work surface.                                                   |
| `output/playwright/ux-v2-mobile-record-dialog-final.png`                                                     | 390×844 policy-review record, person/branch cue, safe automated-sender provenance and modal record treatment. |
| `output/playwright/ux-v2-platform-isolated.png`                                                              | Platform Admin preview with no customer queue or operational customer data.                                   |
| `output/playwright/ux-v2-200pct-zoom-layout-final.png`                                                       | 720 CSS-pixel layout-equivalent desktop 200%-zoom check, inspected for clipping.                              |
| `output/playwright/ux-estimate-mobile-navigation.png`, `output/playwright/ux-platform-mobile-navigation.png` | Explicit mobile return navigation from specialist workspaces.                                                 |

Browser console checks for these re-renders reported zero errors or warnings. The 200%-zoom item is a prototype layout check; real assistive-technology and OS text-scaling validation remain implementation acceptance evidence.

## Accessibility and responsive contract

- Desktop/laptop retains labelled workspace navigation, dense queue + record context and no capability deletion.
- Tablet retains labels rather than an icon rail.
- Mobile is queue-first, supports modal record focus behavior, and has explicit specialist-page return routes.
- Visible focus is present on prototype controls; concise changes use a dedicated status surface rather than a live queue.
- Representative loading, empty, integration-error, identity-conflict, stale/policy-review, long-data, role and scope states are rendered.

## Deferred dependencies (not UX design blockers)

Exact GHL/provider IDs, credentials, workflows, webhooks, terminal state names, remote handoff details, legal/contract policy values and production retention settings remain implementation/pre-production dependencies. The prototype uses stable user-facing abstractions and does not claim those systems are configured. Current iOS build-91 runtime-call evidence remains a parallel release lane; no evidence makes it a UX blocker.

## Review question

Is this a coherent, responsive, accessible, capability-preserving UX design package for Direction A at the product/design-contract level? Target: **UX Design Readiness ≥95/100**. Approval of this artifact does not authorize implementation or release.
