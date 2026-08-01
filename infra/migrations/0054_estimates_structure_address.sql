-- 0054_estimates_structure_address.sql
-- Per-building street addresses on a multi-building bid (#6).
--
-- Tim, 2026-08-02, asked whether each structure can carry its own address: "yes but they can
-- share." Both halves are load-bearing. Nine Evergrene buildings sit on one parkway, so the
-- column is NULL for almost every row and the bid project's property answers for them; two of
-- its gates are on different roads, which is the case that needs a column at all.
--
-- A COLUMN, not a key on the quote snapshot. The snapshot is rewritten wholesale by the SPA edit
-- path — that is precisely the failure core.proposal.validate_project_snapshot exists to police —
-- and an address stored only there would vanish on the next re-quote without anything noticing.
-- estimates already carries structure_name for the same reason; the address sits beside it.
--
-- Nullable with no default: absent means "the bid project's property", resolved at RENDER time
-- (core.proposal_render.structure_groups). It moves no money, so nothing in pricing reads it.
--
-- Idempotent: IF NOT EXISTS. This runner replays every migration on each run and has no ledger.

ALTER TABLE estimates
    ADD COLUMN IF NOT EXISTS structure_address VARCHAR(300);

COMMENT ON COLUMN estimates.structure_address IS
    'Optional street address for THIS structure within a multi-building bid. NULL = the bid project''s property address. Rendered grouped: structures sharing an address collapse to one line.';
