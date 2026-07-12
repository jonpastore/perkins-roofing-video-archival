# Sales Flow Consolidation TRD

## Existing contracts
- Native proposals: `proposals.quote_snapshot` stores frozen pricing/scope JSON.
- Knowify quotes/contracts: `/quotes` reads `KnowifyRawRecord(entity='contracts')` and deliverables.
- Estimate engine: `/estimator/quote` persists `Estimate` rows.

## Target technical shape
- `Proposals.tsx` owns proposal list, detail, create drawer, and legacy quote import tab.
- `ProposalBuilder.tsx` logic is extracted/reused or embedded into Proposals; route key may remain backward-compatible.
- `/quoting/proposals/from-quote/{contract_id}` (or equivalent) creates a native draft from `/quotes/{id}` detail.
- Snapshot includes:
  - `source: "knowify_import" | "native" | "estimate"`
  - `source_ref`
  - `legacy_contract_fields`
  - `line_items`
- Idempotency checks existing proposals with same source/source_ref in `quote_snapshot` before create.

## Security
- Public sign surface remains token-gated.
- Cloudflare token never logged; read from Secret Manager only into env/TF_VAR.
- Webhook endpoints must verify signatures before writes.

## Tests
- Unit/API tests for quote-detail-to-proposal snapshot mapping.
- API test for idempotent quote import.
- UI static tests for sidebar hiding duplicate Quote/New Proposal entries.
- Web build + ruff + core coverage gate.
