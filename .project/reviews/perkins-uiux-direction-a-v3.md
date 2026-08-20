# Perkins Roofing UX Design Package — Direction A Hybrid (v3)

Status: FROZEN FOR UX-ONLY CONSENSUS RECHECK  
Date: 2026-08-20  
Supersedes: `.project/reviews/perkins-uiux-direction-a-v2.md`

## UX decision

Approve Direction A hybrid as the capability-preserving target UX: a role- and branch-scoped revenue command center for immediate work, with dedicated customer/property, sales, schedule, knowledge/content, reporting, and restricted product/platform workspaces. This is design-only; implementation and production remain separate gates.

## Refined design contract

- Tenant-global **Person** is distinct from an authorized **branch operational relationship**. Record UI names both; cross-branch association is an audited link, never an automatic merge.
- Automated customer messages disclose `Perkins Roofing — <Branch> Team` and retain template/sender provenance; `Perkins Roofing Team` is the fallback. Human activity is a distinct, auditable action.
- Branch/sales users see Today, Pipeline, Customers, Sales Work, Schedule and Knowledge—not Reports, Content Operations or Platform Operations. Corporate sees its permitted portfolio/content destinations. Platform Admin sees only its restricted destinations and a platform shell with no branch revenue, queue or customer context absent audited support scope.
- A phone record is a full-viewport modal interaction with dialog semantics, inert/hidden background, focus loop, Escape, and initiating-row focus return.
- Out-of-scope shared-shell actions announce the focused-prototype boundary rather than silently behaving as completed functionality.
- `Payment pending`, `Payment verified`, `Payment exception`, and `Policy review required` are stable visible abstractions; no provider/legal configuration is exposed or inferred.

## Evidence frozen with this artifact

| View / condition                                        | Evidence                                                                                                     |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Desktop Direction A at 1440×900                         | `output/playwright/ux-v3-desktop.png`                                                                        |
| Desktop record with sender provenance at 1440×1100      | `output/playwright/ux-v3-desktop-sender-provenance.png`                                                      |
| Tablet labels/density at 768×1024                       | `output/playwright/ux-v3-tablet.png`                                                                         |
| Phone policy-review dialog at 390×844                   | `output/playwright/ux-v3-mobile-record-dialog.png`                                                           |
| Platform isolation / restricted route                   | `output/playwright/ux-v3-platform-isolated.png`                                                              |
| 720 CSS-pixel layout-equivalent 200% desktop-zoom check | `output/playwright/ux-v3-200pct-zoom-layout.png`                                                             |
| Specialist mobile return navigation                     | `output/playwright/ux-estimate-mobile-navigation.png`; `output/playwright/ux-platform-mobile-navigation.png` |

Fresh browser-console checks were clean. The zoom evidence is expressly a prototype layout check; real assistive technology and operating-system text scaling remain implementation acceptance evidence.

## Capability and scope evidence

`.ux-review/feature-capability-parity.md` remains canonical: all discovered capability/data groups have a PRESERVE/RELOCATE/REDESIGN/CONSOLIDATE/PLATFORM_SPECIFIC/UNKNOWN disposition, with no proposed deprecation. Strategy and prior rendered/adversarial evidence remain in `.ux-review/03-ux-strategy.md`, `.ux-review/05-prototype-review.md`, and `.ux-review/06-adversarial-design-review.md`.

## Explicitly deferred non-UX dependencies

GHL/provider credentials and account mappings, provider terminal state values, handoff contract, legal/contractual configuration and production retention are preserved as deferred implementation/pre-production constraints. The current iOS build-91 call evidence is a separate release-verification lane. None changes this UX package absent a material user-visible fact.

## Decision question

Is Direction A now a coherent, responsive, accessible, role-safe, capability-preserving UX design package at the design-contract level? Target: **UX Design Readiness ≥95/100**. Approval does not authorize implementation or release.
