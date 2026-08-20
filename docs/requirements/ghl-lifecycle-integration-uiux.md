# UI/UX: GHL lifecycle integration

Status: DRAFT — supplements, does not replace, `.ux-review/03-ux-strategy.md`

- Today exposes risk reason, owner, due state, last confirmed activity and sync state. It must
  distinguish `GHL pending`, `retrying`, `needs review` and `failed` from server-confirmed facts.
- Phone supports decisive work—contact, activity capture, appointment status and payment-link
  status—without presenting local completion as lifecycle truth.
- Payment UI distinguishes `payment pending`, `DEPOSIT_VERIFIED`, and post-handoff
  `PAYMENT_EXCEPTION`/`PAYMENT_AT_RISK`; an exception preserves Won/handoff history, blocks later
  gated actions, identifies the remediation owner and never implies the handoff was undone.
- Contact reconciliation shows source/alias/correlation history and the most restrictive channel
  consent state; GHL merge/delete is presented for authorized deterministic reconciliation rather
  than as a destructive app-identity update.
- `POLICY_REVIEW_REQUIRED` is a visible, role-scoped work state with reason, policy version/hash,
  affected action, owner and safe next action. It is accessible by keyboard and mobile, avoids raw
  restricted payloads, and does not present retry as a way to bypass policy review.
- Customer/property and Estimate workspace preserve contact/provenance/pricing/version data;
  signed artifacts enter a revision/change-order path.
- Scope controls show only authorized data. UI visibility is not an authorization decision.
- Automated customer messages use the approved `Perkins Roofing — <Branch> Team` identity and
  fall back to `Perkins Roofing Team` when branch identity is unavailable or inappropriate. The UI
  labels template/source and does not imply a human authored automated outreach; it never selects
  an individual sender unless an existing approved workflow explicitly requires it.
- Production critical flows follow TST-GL accessibility and responsive verification.
