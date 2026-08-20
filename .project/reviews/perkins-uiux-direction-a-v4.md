# Perkins Roofing UX Design Package — Direction A Hybrid (v4)

Status: FROZEN — UX-ONLY FINAL CONSENSUS REVIEW  
Date: 2026-08-20  
Supersedes: `.project/reviews/perkins-uiux-direction-a-v3.md`

## Decision

Direction A hybrid is the proposed, capability-preserving product UX: a role- and branch-scoped revenue command center for immediate work; separate Customer/Property, Sales Work, Schedule, Knowledge/Content, Reports, Product Admin and Platform Operations workspaces. No current meaningful capability is removed; the canonical disposition is `.ux-review/feature-capability-parity.md`.

## Non-negotiable UX contract

1. A tenant-global canonical Person is visually distinct from the currently authorized branch operational relationship; cross-branch association is authorized/audited, never automatic.
2. Automated messaging uses `Perkins Roofing — <Branch> Team` (fallback `Perkins Roofing Team`) with sender/template provenance. Human activity is distinct.
3. Branch/sales navigation never exposes Reports, Content Operations or Platform Operations. Corporate includes Reports and Content Operations, but not Platform Operations. Platform Admin includes Platform Operations but not Content Operations, and withholds branch/customer/revenue context until an audited support scope exists.
4. Mobile records are full-viewport dialogs with inert/hidden background, focus containment, Escape and initiating-row focus return.
5. Shared controls outside this focused mock provide a concise prototype-boundary response, not a silent dead end.
6. Payment labels remain user-safe abstractions: Payment pending, Payment verified, Payment exception, Policy review required. The latter is directly rendered with blocked commercial action.

## Fresh evidence

| Condition                                                                  | Evidence                                                                                                     |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Branch-manager navigation + desktop queue                                  | `output/playwright/ux-v4-manager-nav.png`                                                                    |
| Corporate navigation: Reports + Content Operations, no Platform Operations | `output/playwright/ux-v4-corporate-nav.png`                                                                  |
| Desktop record/sender provenance                                           | `output/playwright/ux-v3-desktop-sender-provenance.png`                                                      |
| Tablet labels/density                                                      | `output/playwright/ux-v3-tablet.png`                                                                         |
| Mobile policy-review dialog                                                | `output/playwright/ux-v3-mobile-record-dialog.png`                                                           |
| Platform-only shell, no branch/customer/revenue context                    | `output/playwright/ux-v3-platform-isolated-final.png`                                                        |
| Layout-equivalent 200% desktop zoom                                        | `output/playwright/ux-v3-200pct-zoom-layout.png`                                                             |
| Specialist mobile return routes                                            | `output/playwright/ux-estimate-mobile-navigation.png`; `output/playwright/ux-platform-mobile-navigation.png` |

Fresh static syntax/format checks and browser-console checks passed. The zoom result is a bounded prototype layout check. Real assistive-technology/OS text scaling, authorization enforcement, routes/APIs/data and integrations remain implementation acceptance evidence.

## Boundary

GHL/provider IDs/credentials, terminal state mapping, handoff, legal/contract configuration, retention and iOS build-91 call revalidation are preserved but deferred dependencies. None is a UX-design blocker in the absence of a material user-visible change. Approval of this UX package does not authorize implementation or production release.

## Final review question

Is this Direction A package ready for product-owner final UX approval at **UX Design Readiness ≥95/100**?
