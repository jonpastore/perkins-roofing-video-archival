# Ez-Bids Plan — Council Review (Grok-4 + GPT-5), 2026-07-10

Both models red-teamed the consensus-approved plan independently. **Both returned
DO-NOT-SHIP** — not because the foundation is wrong, but because v1 under-specifies a
set of security/abuse controls. The RLS core is sound; the gaps are at the edges
(identity binding, client-side trust boundary, control-plane governance, abuse).

## Convergent findings (both models) — these change the plan

1. **Grandfather-as-absence is the #1 hazard (Decision 2).** "No firebase.tenant claim →
   tenant 1" makes an OMITTED attribute semantically meaningful; it leaks into jobs,
   support tools, and future code as a silent default-to-Perkins. FIX: bind tenant 1 with
   an EXPLICIT internal tenant mapping at session establishment; every authed request must
   have an explicitly resolved tenant where token/host/mapping agree — never inferred from
   a missing claim.

2. **The shared admin+staff bundle is packaging, not a security boundary.** The quote.{d}
   split is right; but platform-admin + tenant-staff sharing one bundle needs client-side
   hardening: DISTINCT GCIP auth audiences/clients per surface, separate browser-storage
   keys, no shared service worker, per-surface CSP + frame-ancestors, host-route allowlists,
   and browser tests proving an admin token is unusable on a staff origin.

3. **Runtime-owned authorized_domains needs guardrails, not just an auditor.** It's identity
   perimeter config at the PROJECT level (one bad write can break auth for ALL tenants incl.
   Perkins). Add: append-only journal w/ actor+request correlation, domain-ownership gate
   BEFORE add, quota alarms, break-glass for suspicious domains, and a formal ADR that TF is
   explicitly NOT source of truth for this one field.

4. **"31 RLS tables" is not the full isolation inventory.** Missing coverage: views,
   materialized views, SECURITY DEFINER functions, GCS object paths + signed-URL scoping,
   audit/outbox/email-log/notification tables. A leak via a non-RLS object defeats the RLS
   story. Add a per-wave inventory gate.

5. **Signup abuse / tenant squatting is missing entirely.** Public signup + runtime domain
   config = abuse magnet. Add: rate limits, CAPTCHA/Turnstile, disposable-email block,
   domain moderation/manual-review path, tenant-namespace reservation.

6. **Domain onboarding is more than a state machine.** Add proof-of-control before a domain
   is trusted for auth/email, collision policy (tenant A owns company.com vs tenant B wants
   app.company.com), dangling-DNS/takeover detection, and deprovisioning on churn.

7. **Magic-link + accept-token: bearer-token surface.** Single-use, short TTL, bound to
   recipient+tenant+host+proposal; email-scanner-safe redemption (no state change on GET);
   separate "establish session" from "accept proposal"; review e-sign legal evidence
   sufficiency.

8. **Stripe stub → live cutover cliff.** Even stubbed, design NOW: canonical immutable
   billing-event model, webhook signature+idempotency, entitlement snapshotting, grace/dunning
   semantics, and what a suspended tenant's quote portal does.

9. **Per-tenant sender domains = phishing/deliverability minefield.** Consider a
   platform-controlled sending domain as the v1 default (branded display-name/reply-to);
   gate custom per-tenant sender domains behind the abuse controls above.

10. **Non-request execution contexts.** Cron/workers/CLI/support tooling/exports must use
    tenant-scoped sessions or they bypass the app-path RLS tests.

## Already addressed by facts the council lacked (note for the revision)

- **"Show me a hard failure on unset GUC"** — DONE and prod-verified TODAY: `strict=True`
  makes an unstamped tenant session RAISE on Postgres (not return empty rows). This directly
  answers Grok's & GPT-5's central GUC-fragility concern; the plan should surface it.
- **CORS TOCTOU** — the plan already mandates an app-owned exact-match table; fold in the
  council's hardening (Vary: Origin, tenant/host/origin alignment, preflight parity tests).

## Net assessment
Not a teardown. The RLS + strict-session foundation is sound and already fail-closed. The
council's DO-NOT-SHIP is a "harden these edges before onboarding tenant #2," and every item
is an additive control that folds into the existing wave structure (mostly W0/W1/W2/W4/W6).
Recommend one planner revision to absorb items 1–10 as explicit wave scope + gates, then
final Jon validation.
