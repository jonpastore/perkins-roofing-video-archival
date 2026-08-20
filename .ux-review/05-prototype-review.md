# Prototype review — Perkins revenue command center

Status: COMPLETE
Phase: Isolated prototype construction and rendered review
Last Updated: 2026-08-20
Inputs Used: `.ux-review/03-ux-strategy.md`; `.ux-review/04-design-directions.md`; `.ux-review/prototype/`; rendered browser review
Open Questions: Tim's automated sender-identity policy; production authorization and integrations
Blocking Findings: Resolved in prototype; server guarantees remain implementation acceptance criteria
Next Recommended Phase: Present the revised design decision package for explicit approval.

## Scope

The disposable mock-data prototype tests Direction A’s three representative contexts without production routes, APIs, authentication or external integrations. It retains the existing Perkins Roofing logo unchanged, rendered from `web/public/perkins-logo.png`; no production asset was modified.

## Rendered evidence

| Context                                         | Evidence                                            | Result                                                                                                                                                        |
| ----------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phone 390×844 — manager queue                   | `.playwright-cli/page-2026-08-20T02-44-06-329Z.png` | Queue precedes compact summary metrics; no horizontal metric strip.                                                                                           |
| Phone — navigation drawer and focused Evan task | `.playwright-cli/page-2026-08-20T02-44-27-643Z.png` | Drawer opens with named links and Escape closes it; selected task becomes a focused action sheet with Call, Message/open GHL, and structured outcome capture. |
| Phone — confirmed attempt                       | `.playwright-cli/page-2026-08-20T02-44-51-595Z.png` | Verified attempt stays in queue as `Attempted — follow-up due`, adds app/GHL-pending evidence and announces the result.                                       |
| Desktop — corporate Miami drill-down            | `.playwright-cli/page-2026-08-20T02-45-30-598Z.png` | All-branches scope changes consistently to Miami Branch and shows the two matching exceptions.                                                                |
| Existing logo inspection                        | `.playwright-cli/page-2026-08-20T02-44-13-527Z.yml` | Accessibility tree exposes the unchanged `Perkins Roofing Corp.` image in desktop and mobile navigation.                                                      |

## FACT

- Browser inspection covered desktop 1440×900 and phone 390×844. Final console check reported zero errors and warnings.
- The phone navigation control now opens a named drawer, reports `aria-expanded`, and returns focus to the trigger with Escape.
- Selecting a phone risk item moves focus to a task sheet rather than leaving its action area below the queue. The sheet exposes immediate communication choices and a separate structured outcome dialog.
- Human activity requires channel/outcome/context UI. Its mock result remains a visible follow-up with `GHL activity sync pending`; it does not remove work or claim payment/lifecycle transition.
- Queue accessible names include risk, owner, next action, deadline and priority.
- Corporate begins at `All branches`; selecting Miami changes sidebar, breadcrumb, queue, count and record to Miami Branch data. The drill-down is explicitly labeled mock/authorized-and-auditable.
- Independent re-check confirmed the Miami drill-down also updates all scope-bearing summary metrics and labels (`$27,100` at risk, `76%` SLA, five inspections, manager follow-up), so it no longer mixes portfolio and branch figures.
- The payment-pending record separates contract amount, branch-required deposit, payment-link delivery and provider-confirmation state.
- Loading, integration-error, identity-conflict and empty states are rendered. Retry performs a visible loading-to-last-confirmed result; conflict says no identity data was overwritten.

## INFERENCE

- Direction A now adequately demonstrates its intended phone and corporate behavior: phone is for decisive work, while corporate is an exception-first portfolio with bounded drill-down.
- The restrained operational visual system has enough hierarchy for urgent work without changing the established Perkins logo or turning the interface into a marketing surface.

## UNKNOWN / prototype limits

- Server authorization, grant checks, transition validation, payment verification, idempotency, outbox delivery and GHL behavior were not and cannot be verified by a static prototype. CallRail is not approved and out of scope.
- The prototype does not cover actual search, reassignment, large datasets, multi-property accounts, all keyboard/assistive-technology behavior, real mobile device input, timezone variation or long-text stress.

## Final prototype constraints carried into implementation

1. Phone task selection must reveal immediate contact, outcome capture and an accessible return to queue.
2. A recorded attempt must become an auditable event with a due follow-up; clients cannot clear SLA/revenue work locally.
3. Scope labels, counts, queue and record must derive from one authorized scope source.
4. Visible recovery controls must have real feedback paths; stale/failed integration data stays clearly labeled.
5. Payment-pending work must show required deposit and verified provider state, not just contract value.

## Capability-preservation prototype additions

Two additional mock-data surfaces were added after the initial review because the capability matrix identified consequential unanswered IA questions:

| Surface                                                   | Purpose                                                                                                                                           | Rendered evidence                                               | Result                                                                                                                            |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| [Estimate workspace](prototype/estimate-workspace.html)   | Preserve complex measurement, provenance, pricing, active-version, customer/property and proposal-preparation work in a dedicated sales workflow. | `.playwright-cli/page-2026-08-20T11-31-58-600Z.yml` at 1440×900 | It keeps dense estimator evidence out of Today while making its linkage to the customer/property and proposal lifecycle explicit. |
| [Platform Operations](prototype/platform-operations.html) | Preserve readiness, integration, processing/remediation, audit, diagnostics and usage/cost operations in a restricted workspace.                  | `.playwright-cli/page-2026-08-20T11-33-53-678Z.png` at 390×844  | It distinguishes granular system health from record-level GHL status and keeps privileged remediation out of branch work.         |

Both pages render the unchanged Perkins logo and completed a final browser console check with zero errors or warnings. They remain isolated, static mockups with no production API, authentication or external-service connection.

## Headless validation evidence

All prototype validation uses Playwright with headless Chromium and a local static HTTP server. No display server, X11, Wayland, interactive browser, or production dependency was used. Screenshots at the required representative viewports are retained under [`prototype/evidence`](prototype/evidence/):

| Surface                | 1440×900                                                        | 1280×800                                                        | 768×1024                                                        | 390×844                                                        |
| ---------------------- | --------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------- |
| Revenue command center | [evidence](prototype/evidence/command-center-1440x900.png)      | [evidence](prototype/evidence/command-center-1280x800.png)      | [evidence](prototype/evidence/command-center-768x1024.png)      | [evidence](prototype/evidence/command-center-390x844.png)      |
| Estimate workspace     | [evidence](prototype/evidence/estimate-workspace-1440x900.png)  | [evidence](prototype/evidence/estimate-workspace-1280x800.png)  | [evidence](prototype/evidence/estimate-workspace-768x1024.png)  | [evidence](prototype/evidence/estimate-workspace-390x844.png)  |
| Platform Operations    | [evidence](prototype/evidence/platform-operations-1440x900.png) | [evidence](prototype/evidence/platform-operations-1280x800.png) | [evidence](prototype/evidence/platform-operations-768x1024.png) | [evidence](prototype/evidence/platform-operations-390x844.png) |

The targeted preservation re-check confirms that the estimate surface is explicitly pre-proposal, retains decision-critical phone data, and keeps post-signature edits behind an explicit revision/change-order boundary. It also confirms that Platform Operations provides per-exception remediation and a named Legacy Data path, while keeping Corporate reporting distinct from Product Admin and Platform Admin roles.

## Direction A refinement — 2026-08-20

The product owner re-scoped the active engagement to UI/UX. The broad payment/GHL/system-design review is preserved as a deferred implementation/release constraint; it is not a gate on this disposable UX prototype.

The Direction A prototype was refined and freshly rendered from its local static server. No production application source, external account, credential, or integration configuration was changed.

| Refined area            | Design result                                                                                                                                                                                        | Fresh evidence                                                                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Queue filtering         | `All`, `Mine`, `Due now`, and `Payment` are now operable pressed-state filters with scope-correct counts instead of decorative chips.                                                                | `output/playwright/ux-command-center-laptop.png`; `output/playwright/ux-command-center-mobile.png`                                                       |
| Commercial ambiguity    | A long-name/long-address work item models `POLICY REVIEW REQUIRED` without inventing provider-state or contractual meaning; commercial action remains visibly blocked.                               | `output/playwright/ux-policy-review-desktop.png`; `output/playwright/ux-policy-review-tablet.png`; `output/playwright/ux-policy-review-mobile-final.png` |
| Role-appropriate action | A policy-review item exposes authorized payment review/evidence actions and explicitly omits customer outreach or handoff action. Normal lead work retains phone-first contact and outcome actions.  | `output/playwright/ux-policy-review-mobile-final.png`                                                                                                    |
| Integration abstraction | The shell now states the user-level condition `Queue current`; the mock no longer implies a known live provider integration there. The unapproved CallRail reference was removed from the mock data. | Browser accessibility snapshots and zero console messages for the final command-center renders.                                                          |

Fresh browser checks at 1440×900, 1280×800, 768×1024, and 390×844 reported zero console errors or warnings. At tablet and phone widths, long customer/property data wraps, the payment filter remains accessible, selecting a queue row moves focus into the focused record surface, and the back control returns to the queue.

## UX consensus remediation v2 — 2026-08-20

The UX-only consensus recheck found and corrected additional interaction and scope clarity gaps. These changes remain inside the disposable prototype; server authorization stays an implementation requirement.

| Review finding                                                                       | Remediation                                                                                                                                                                                                                             | Fresh evidence                                                                                  |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| A branch-scoped customer record implied that the branch owns canonical identity.     | The record now identifies a tenant-global canonical Person and the currently authorized branch operational relationship; cross-branch links are explicitly authorized/audited, never automatic.                                         | `output/playwright/ux-v2-desktop.png`; `output/playwright/ux-v2-mobile-record-dialog-final.png` |
| Automated communication could look employee-sent or be confused with a human action. | The record shows `Perkins Roofing — Jupiter Team` as automated sender provenance; human activity remains separate and `Open CRM conversation` does not imply an automated send.                                                         | `output/playwright/ux-v2-desktop.png`                                                           |
| Restricted workspaces were not demonstrably role-gated.                              | The reviewer-only role harness hides Reports/Content Operations/Platform Operations from branch roles, exposes corporate destinations only in corporate preview, and isolates the Platform Admin preview from customer queues.          | `output/playwright/ux-v2-platform-isolated.png`                                                 |
| A phone record sheet looked modal but did not model a safe modal interaction.        | The sheet now has dialog semantics, background inert/hidden treatment, Escape, a focus loop and row-focus return.                                                                                                                       | `output/playwright/ux-v2-mobile-record-dialog-final.png` plus keyboard recheck                  |
| Shared shell controls were visually actionable but out of prototype scope.           | They now announce their documented workspace-boundary status rather than silently failing.                                                                                                                                              | Browser interaction recheck; zero console messages                                              |
| 200% zoom evidence was overstated.                                                   | A 720 CSS-pixel layout-equivalent desktop-zoom check was rendered and inspected without horizontal clipping. This is a layout check; real assistive technology and operating-system text scaling remain production acceptance evidence. | `output/playwright/ux-v2-200pct-zoom-layout-final.png`                                          |
