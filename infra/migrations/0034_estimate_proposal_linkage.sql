-- 0034_estimate_proposal_linkage.sql
-- Link native proposals to immutable estimate revisions.

ALTER TABLE estimates ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES estimates(id);
ALTER TABLE estimates ADD COLUMN IF NOT EXISTS root_id INTEGER REFERENCES estimates(id);
ALTER TABLE estimates ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE estimates ADD COLUMN IF NOT EXISTS source_proposal_id INTEGER REFERENCES proposals(id);

ALTER TABLE proposals ADD COLUMN IF NOT EXISTS estimate_id INTEGER REFERENCES estimates(id);

CREATE INDEX IF NOT EXISTS ix_estimates_root ON estimates(root_id);
CREATE INDEX IF NOT EXISTS ix_estimates_source_proposal ON estimates(source_proposal_id);
CREATE INDEX IF NOT EXISTS ix_proposals_estimate ON proposals(estimate_id);
