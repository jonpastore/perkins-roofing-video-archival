# GHL lifecycle consensus — cycle 2, v1

Status: FROZEN — independent review pending
Cycle: 2
Iteration: 1
Evidence Readiness: 82/100; hard cap 89/100.
Residual Uncertainty: `EXT-GL-01`, `EXT-GL-02`, `EXT-GL-04`, and `EXT-GL-05`.
Reviewer Verdicts: pending independent Architect, Critic, and Evidence Verifier review.
Blocking Findings: external factual/legal evidence prevents implementation readiness.
Open User Decisions: none.

## Frozen revision

This new cycle is authorized by explicit product-owner approvals `DEC-GL-06` and `DEC-GL-07`.
Provider-specific terminal-success states map to `DEPOSIT_VERIFIED`; authorization is never
sufficient; independent verified payments may accumulate; and post-handoff negative payment
events preserve Won/handoff history while entering an alerted remediation exception state.

The app is canonical for customer identity. GHL is an operational projection: it may update only
unambiguous mapped facts, never destructively merge/delete app identity, and GHL messaging honors
the most restrictive applicable consent/opt-out state until reconciliation completes.

No exposed credential is reused. Exact GHL mapping, OAuth/private-integration discovery method,
provider contract and legal/privacy validation remain externally unverified. The bounded read-only
design is conditionally approved; delivery planning and implementation are not authorized.
