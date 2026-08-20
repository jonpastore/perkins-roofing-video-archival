# Perkins Roofing UX Design Package — Direction A Hybrid (v5)

Status: FROZEN — APPROVED UX DESIGN BASELINE  
Date: 2026-08-20  
Supersedes: `.project/reviews/perkins-uiux-direction-a-v4.md`

## Decision

Direction A hybrid is the approved final UX baseline at **UX Design Readiness 97/100**: role- and branch-scoped revenue work in **Today**, with dedicated Customer/Property, Sales Work, Schedule, Knowledge/Content, Reports, Product Admin and Platform Operations workspaces. The canonical parity matrix retains every discovered capability/data group; no deprecation is proposed.

## Final UX contract

- A tenant-global canonical Person and its authorized branch operational relationship are separately visible. Cross-branch linkage is authorized/audited, never automatic.
- Automated sender provenance is `Perkins Roofing — <Branch> Team` (fallback `Perkins Roofing Team`); human activity is distinct.
- Branch/sales navigation contains operational workspaces only. Corporate adds **Reports** and **Content Operations** but not **Platform Operations**. Platform Admin exposes **Platform Operations only**; it has no Content Operations grant and no branch/customer/revenue context without audited support scope.
- Mobile records are full-viewport, focus-contained dialogs with background inert/hidden behavior, Escape and originating-row focus return.
- Stable payment language is user-facing only: Payment pending, Payment verified, Payment exception, Policy review required. Payment-pending and policy-review/blocked-action states are rendered.
- Shell controls outside the focused proof state their prototype boundary rather than silently failing.

## Evidence

| Condition                                                                                | Fresh evidence                                                                                               |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Branch-manager role navigation                                                           | `output/playwright/ux-v4-manager-nav.png`                                                                    |
| Corporate role navigation: Reports + Content Operations, no Platform Operations          | `output/playwright/ux-v4-corporate-nav.png`                                                                  |
| Platform Admin: Platform Operations only, no Content Operations/customer/revenue context | `output/playwright/ux-v4-platform-only-nav.png`                                                              |
| Sender provenance in record                                                              | `output/playwright/ux-v3-desktop-sender-provenance.png`                                                      |
| Tablet labels/density                                                                    | `output/playwright/ux-v3-tablet.png`                                                                         |
| Mobile policy-review modal                                                               | `output/playwright/ux-v3-mobile-record-dialog.png`                                                           |
| Layout-equivalent 200% desktop zoom                                                      | `output/playwright/ux-v3-200pct-zoom-layout.png`                                                             |
| Specialist mobile return routes                                                          | `output/playwright/ux-estimate-mobile-navigation.png`; `output/playwright/ux-platform-mobile-navigation.png` |

Current-source browser-console, syntax and format checks are clean. The 200%-zoom result is an explicitly bounded prototype layout check; real assistive technology/OS text scaling, production authorization/data/API/integrations, GHL/provider configuration, handoff, legal/contract policy configuration, retention and iOS build-91 runtime evidence remain deferred implementation/release evidence—not UX-design blockers.

## Authorization boundary

This approval freezes the UX design only. Production implementation remains unauthorized; system implementation readiness and release readiness remain separately tracked. Any material change to this baseline must return as a UX change proposal.
