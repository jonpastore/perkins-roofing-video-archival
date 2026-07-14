# DDD: estimate-linked proposals

Estimate is an immutable pricing calculation. Proposal is a customer-facing contract draft/sent document generated from an estimate or legacy import. Proposal.quote_snapshot freezes customer-facing pricing. Proposal.estimate_id points to the Estimate row used to build a native proposal. Revisions are represented by new Estimate rows and new Proposal rows rather than mutating sent artifacts.
