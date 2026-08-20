# Adversarial design review — Perkins revenue command center

Status: COMPLETE
Phase: Mandatory pre-implementation adversarial review
Last Updated: 2026-08-20
Inputs Used: `.ux-review/03-ux-strategy.md`; `.ux-review/04-design-directions.md`; `.ux-review/05-prototype-review.md`; independent rendered, security and adversarial reviews
Open Questions: Server behavior and integration configuration remain unverified
Blocking Findings: No unresolved prototype/design blockers; GHL technical discovery and server controls below are implementation gates. CallRail is not approved and out of scope.
Next Recommended Phase: Present decision package and obtain explicit design approval

## Challenge summary

| Challenge                                                 | Result                                                 | Evidence                                                                          |
| --------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Phone salesperson can contact a critical lead immediately | Mitigated                                              | Focused task sheet exposes Call, Message/open GHL and outcome capture.            |
| An attempt cannot falsely clear revenue work              | Mitigated in prototype; server implementation required | Follow-up remains visible with app event and GHL-pending state.                   |
| Corporate can reach the branch it is asked to manage      | Mitigated                                              | Miami drill-down changes scope, count, queue and record together.                 |
| Error recovery is truthful and functional                 | Mitigated                                              | Retry visibly returns to the last-confirmed queue; identity conflict is explicit. |
| Operational queue is accessible                           | Mitigated in prototype                                 | Row name includes owner, next action, due state and priority.                     |
| Deposit-pending work has decision context                 | Mitigated in prototype                                 | Required deposit, payment link and provider-confirmation data are separate.       |

## Finding dispositions

| ID                         | Severity      | Disposition | Decision                                                                                                                                                                        |
| -------------------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ADR-01 / PB-01             | High          | MITIGATE    | Phone drawer and focused task sheet implemented in prototype; production must preserve focus/back behavior.                                                                     |
| ADR-02 / SEC-UX-02 / PB-03 | High          | MITIGATE    | Structured outcome capture now retains follow-up and shows GHL pending. Production requires append-only, idempotent, server-confirmed events.                                   |
| ADR-03                     | High          | MITIGATE    | Prototype retry now transitions visibly through loading to last-confirmed data. Production must provide the corresponding record/event retry semantics.                         |
| ADR-04 / PB-04             | High          | MITIGATE    | Corporate All branches and Miami branch drill-down now use a single mock scope source. Server grant checks/audit are required.                                                  |
| ADR-05                     | High          | MITIGATE    | Queue row names now carry the operational dimensions; production needs equivalent list/table semantics and screen-reader validation.                                            |
| ADR-06 / SEC-UX-01         | High / Medium | MITIGATE    | Prototype now shows required deposit and provider status; production transition/verification rules are mandatory.                                                               |
| SEC-UX-03                  | High          | MITIGATE    | Strategy explicitly requires server-derived scope on every query/action, aggregate-first corporate view and audited drill-down. UNVERIFIED until backend review/implementation. |
| SEC-UX-04                  | Medium        | MITIGATE    | Per-record last-confirmed/pending/conflict presentation is defined; production requires correlation IDs and monotonic versions.                                                 |
| SEC-UX-05                  | Medium        | MITIGATE    | Identity-conflict state explicitly preserves contact data; production requires authorized resolution/history.                                                                   |
| SEC-UX-06                  | Low           | ACCEPT      | `innerHTML` is confined to static, controlled mock data. It must not be copied into production rendering.                                                                       |
| PB-02                      | Medium        | MITIGATE    | Phone places queue before two compact metrics and removes horizontal metric overflow.                                                                                           |
| PB-05                      | Medium        | MITIGATE    | Queue counts and hero copy derive from the same mock list; selected work remains selected after logging.                                                                        |
| PB-06                      | Medium        | DEFER       | Search/notifications are outside the focused prototype. Do not present inert controls in production unless implemented or intentionally unavailable.                            |

### Re-check result

Independent rendered and adversarial re-checks found no remaining prototype/design blocker. The last scope-consistency issue was corrected: a corporate Miami drill-down now updates all scope-bearing metrics and labels to Miami-specific mock data. Non-blocking prototype cleanup also supersedes the old `Awaiting human outreach` timeline entry after a recorded attempt.

## Mandatory production acceptance criteria

1. **Lifecycle/payment integrity:** server-owned conditional transition rules; branch deposit requirement and verified payment-provider event required before Won/handoff; provider-ID idempotency ledger and transactional-outbox handoff.
2. **Activity integrity:** append-only actor/timestamped human activity; idempotency key; server confirmation before SLA mutation; preserved follow-up and explicit pending/failed/retry state.
3. **Authorization:** server-derived branch/cross-branch scope on list, aggregate, detail, reassignment, activity, payment and export operations; auditable corporate PII drill-down.
4. **Integration integrity:** source/event/correlation ID, last-confirmed time and monotonic lifecycle version; duplicate/out-of-order webhooks cannot overwrite newer facts.
5. **Identity safety:** no silent contact overwrite; authorized conflict review with source history.
6. **Accessibility and responsive behavior:** keyboard and screen-reader validation of queue/task sheet/drawer; visible focus, focus return, 200% zoom and real-device checks.

## Security boundary status

- SERVER-SIDE AUTHORIZATION: UNVERIFIED
- SERVER-SIDE VALIDATION: UNVERIFIED
- TENANT / BRANCH ISOLATION: UNVERIFIED
- PAYMENT PROVIDER VERIFICATION: UNVERIFIED
- GHL EVENT IDEMPOTENCY / ORDERING: UNVERIFIED

These are not passed because the prototype has no server or external integration. They are explicit design-to-implementation gates, not reasons to claim the design is secure today.

## Feature and capability preservation challenge

The independent review challenged the two selective preservation prototypes and the matrix rather than repeating repository discovery. All prototype/design findings were mitigated; the future-integration boundary remains explicit and unverified.

| ID     | Severity | Disposition | Re-check result                                                                                                                                                                                                                                      |
| ------ | -------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CAP-01 | High     | MITIGATE    | Product owner clarified GHL as approved-but-not-yet-app-integrated, with a corporate Tim account/location and per-branch sub-accounts/locations. GHL technical discovery remains mandatory before planning; CallRail is unapproved and out of scope. |
| EST-01 | High     | MITIGATE    | Estimate prototype is now pre-proposal. Draft actions cannot be misread as post-signature repricing; signed work requires a revision/change-order path.                                                                                              |
| EST-02 | High     | MITIGATE    | The phone estimate view retains measurement source, confidence, dimensions, pricing and version data through visible summary/progressive disclosure.                                                                                                 |
| OPS-01 | High     | MITIGATE    | Platform exceptions now expose bounded contextual remediation, including raw-record access, reconnect, safe job inspection/retry and readiness detail.                                                                                               |
| OPS-02 | High     | MITIGATE    | Corporate reporting, Product Admin and Platform Admin are distinct target capability boundaries; the static mock correctly says server authorization is authoritative.                                                                               |

### Re-check conclusion

No remaining feature-preservation, rendered-prototype, or adversarial-design blocker prevents presenting the decision package. This does **not** validate server authorization, server transition logic, GHL integration, idempotency, payment verification or current GHL connection state; those remain required technical-discovery and implementation acceptance gates. CallRail is not approved and is not in scope.

## UX-only adversarial refinement — 2026-08-20

The product owner explicitly parked the broad system-design consensus and requested a UI/UX-only review of Direction A. The independent review stayed within that scope; it did not reopen provider, GHL, legal, handoff, or release architecture.

| Finding                                                                                     | Severity | Disposition and re-check evidence                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 641–1050px navigation became an unlabeled icon rail.                                        | High     | **MITIGATED.** Tablet retains a labeled branch workspace and nav at 768×1024; see `output/playwright/ux-remediated-tablet.png`.                                                                                                                |
| Mobile drawer had no direct touch-close path or keyboard containment.                       | High     | **MITIGATED.** Drawer has an internal close control, an interactive backdrop, Escape/focus return, and a keyboard loop confined to drawer controls; see `output/playwright/ux-remediated-mobile-drawer.png` and final accessibility snapshots. |
| Estimate and Platform Operations mobile mock pages were dead ends.                          | High     | **MITIGATED.** Each has a visible `← Back to workspaces` link at 390×844; see `output/playwright/ux-estimate-mobile-navigation.png` and `output/playwright/ux-platform-mobile-navigation.png`.                                                 |
| Payment state contradicted itself by saying it was both awaiting confirmation and verified. | Medium   | **MITIGATED.** It now says `Payment link delivered 9:13 AM · provider confirmation pending`; no payment eligibility is implied.                                                                                                                |
| Review-only role scenarios looked like end-user self-service role switching.                | Medium   | **MITIGATED.** The controls now live in a collapsed, explicitly reviewer-only scenario harness with pressed-state semantics. Product role/scope remains server-authorized.                                                                     |
| Full queue replacement was a polite live region.                                            | Medium   | **MITIGATED.** The queue is no longer live; concise outcome messages use the dedicated status region.                                                                                                                                          |
| Specialist prototype pages lacked a visible-focus pattern.                                  | Medium   | **MITIGATED.** Capability pages now share the prototype’s visible focus treatment. Token consolidation remains an implementation design-system task, not a reason to duplicate a prototype-only system.                                        |

Final browser re-checks reported zero console errors or warnings. The long-data, payment-review, loading/error, focus, navigation, laptop, tablet, and phone cases are covered by the refreshed evidence listed above.

## UX-only consensus recheck v2 — 2026-08-20

| Finding                                                                                           | Severity | Disposition and re-check evidence                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Customer context hid the distinction between canonical identity and branch operations.            | High     | **MITIGATED.** The record identifies a canonical Person plus a current branch operational relationship and warns that cross-branch links require authorized/audited review.                                                       |
| Automated sender policy was absent from record-level outreach context.                            | High     | **MITIGATED.** Automated provenance visibly uses `Perkins Roofing — Jupiter Team`; human outreach is separately captured and no individual employee sender is presented.                                                          |
| Corporate/Platform routes were not visibly tied to a role boundary.                               | Medium   | **MITIGATED.** Reviewer scenarios apply an explicit capability set. Branch views omit Reports/Content/Platform destinations; the Platform Admin preview hides customer work and links to the restricted Platform Operations mock. |
| The mobile record context could leave keyboard or assistive users in obscured background content. | High     | **MITIGATED.** The record panel is a modal dialog on phone: its background is inert/hidden, focus loops within the panel, Escape closes it, and focus returns to the initiating queue row.                                        |
| The prototype silently accepted clicks on shared shell controls outside the focused proof.        | Medium   | **MITIGATED.** Such controls now provide a concise prototype-boundary status message; they are not presented as completed product behavior.                                                                                       |
| Text-scaling claim lacked an honest evidence boundary.                                            | Medium   | **MITIGATED AT PROTOTYPE LEVEL.** The layout-equivalent 200% browser-zoom width was rendered without clipping; actual screen-reader and OS text-scale checks remain named production acceptance evidence.                         |

No provider, GHL, legal, payment-policy, handoff, credential, or release item was reopened in this UX-only recheck unless it affected the visible user state.

### Final v4 role-scope recheck

The final role review removed an implied Content Operations grant from Platform Admin. Fresh manager and corporate renders now prove the intended separation: branch navigation exposes no corporate/platform destination, corporate exposes Reports plus Content Operations but not Platform Operations, and Platform Admin exposes Platform Operations without branch customer/revenue context or a content-workspace grant.
