# Current-state discovery — Perkins Roofing platform

Status: COMPLETE WITH RUNTIME LIMITATIONS
Phase: Discovery
Last Updated: 2026-08-19
Inputs Used: Completed `rendered_ux`, `visual_audit`, and `security_review` reports; owner answers in the active review; root continuation handoffs; `DeGenito-Perkins-Marketing-Management-2026-08.pdf`; `DeGenito-Perkins-Partnership-Proposal-2026-08.pdf`
Open Questions: Authenticated rendered workflows; GHL configuration and authority boundaries; production edge controls; final role/capability policy
Blocking Findings: Authenticated UI could not be rendered; valid public proposal flow could not be exercised locally
Next Recommended Phase: Product synthesis and owner interview

## Scope and evidence quality

This report preserves the completed discovery evidence without reopening repository-wide exploration. Source-backed specialist findings are FACT. Owner-stated direction is PRODUCT INTENT. Unexercised runtime behavior remains UNKNOWN.

## Product surface

### FACT

- The repository implements a React/Vite authenticated web application plus a Python API and operational jobs.
- Existing product areas include video archive/search/Ask Tim, clip creation and social publishing; articles, FAQs and portfolio/project pages; estimating, quoting and proposals; customers, invoices, payments and scheduling; CompanyCam and Knowify data; branches, users and administration.
- Authentication uses Firebase bearer tokens. The server derives effective role and tenant from verified claims plus database mappings, and PostgreSQL RLS is intended as the primary cross-tenant boundary.
- Public proposals use high-entropy URL tokens and a restricted public projection.
- The broader product ecosystem includes the forthcoming public Astro/Cloudflare site, GHL, CallRail, CompanyCam, GCP and other vendor integrations.

### PRODUCT INTENT

- `app.perkinsroofing.net` is intended to become the controller/router and knowledge/operational source of truth.
- GHL owns workflow automation, scheduling and the lead lifecycle; proposal, execution and payment events from the app should advance GHL stages.
- CallRail is attribution input, not a competing workflow system.
- Branch users need branch-scoped estimating, proposals, invoices, customers and operational reporting, plus access to FAQs/knowledge. They should not see corporate-wide marketing operations.
- Corporate users need cross-branch oversight, branch comparisons and revenue/royalty visibility. Chris initially needs broad access while helping define operations.
- Post-sale project execution remains outside this product for now.

## Rendered and visual evidence

### FACT

- The unauthenticated login was rendered at 1440×900, 1280×800, 768×1024 and 390×844. Keyboard Tab reached the Google sign-in button.
- Authenticated UI could not be exercised without an authorized Firebase identity.
- A local public-proposal request failed at CORS before a meaningful product response, so valid, invalid-token and recovery behavior remain unverified.
- The frontend has a shared primitive layer, including cards, buttons, status components and a reusable data table.
- Styling is highly distributed: the visual audit counted 3,248 inline `style` objects and 1,586 inline `fontSize` declarations, with two partially inconsistent token sources and local input/style variants.
- Responsive rules are concentrated in the shell/global CSS; page-level breakpoint coverage is sparse. The data table provides horizontal scrolling.

### UNKNOWN

- Mobile login overflow evidence conflicts between two rendered/source assessments; it requires a controlled re-test rather than selecting the convenient result.
- Authenticated information hierarchy, dense data behavior, responsive pages, loading/error/empty/success consistency and normal mutation behavior are not browser-verified.

## Security evidence

### FACT

- Server-side auth, tenant resolution, signed OAuth state, sanitized article HTML and webhook HMAC validation are present.
- Public proposal accept/decline/revision transitions perform read-then-write mutations without a row lock or conditional prior-status update. Concurrent requests can create contradictory outcomes or duplicate effects. Severity: HIGH.
- Privileged PDF/video uploads can consume substantial CPU or memory; extraction/concurrency limits and deployed edge controls were not established. Severity: MEDIUM.
- A browser-visible Google Maps key exists; its claimed referrer restrictions are unverified. Severity: LOW.

### INFERENCE / UNKNOWN

- Electronic-signature IP evidence depends on whether deployed ingress sanitizes `X-Forwarded-For`.
- Production RLS privileges, tenant policies, Cloudflare rate limits, GCS IAM/CORS, security headers, logging policy and Firebase configuration were not dynamically verified.
- Although role and tenant machinery exists, the owner reports that current user assignments effectively make most users administrators. The policy/assignment layer therefore remains a product and security concern.

## Technical constraints relevant to later strategy

- This is a broad product with operational, sales, marketing, content and administration surfaces serving overlapping users.
- The existing visual system has reusable foundations but widespread one-off inline decisions; consistent redesign will require consolidation rather than page-by-page restyling.
- Authenticated browser evidence requires a safe authorized login or representative isolated environment.
- GHL, CallRail, public-site and app responsibilities must be expressed as explicit domain and event ownership to avoid competing records.
- Branch isolation and cross-branch exceptions must be server-enforced; navigation visibility alone is insufficient.
- External integrations require visible delayed, failed, duplicated and out-of-order event handling.
- Normal application data interactions must remain asynchronous and reconcile affected state without page reloads.

