-- 0053_bid_projects_once_per_project_default.sql
-- Realign bid_projects.once_per_project_fees' server default with the code that prices bids.
--
-- 0052 shipped a THREE-key default and a comment arguing tile_dumpster is per-building:
--     "tile_dumpster is deliberately NOT here — a dump load is real and per-building."
-- core.bid_project.DEFAULT_ONCE_PER_PROJECT carries FOUR and includes it, because the argument
-- above misses what the fee actually is. `tile_dumpster` is NOT a flat fee, so "charge it once"
-- is also wrong: config.tile_dumpster_count() is a ceil() over squares, so calling it once per
-- building rounds UP once per building — 14 loads billed against the 10 a site needs. The code
-- recomputes one ceil over the SUMMED tile squares, which is why it belongs in the suppress set.
--
-- The four-key set is the measured one: it is what scores Tim's Evergrene bid at $390,230
-- against his $381,288 (+2.3%), and the roll-up prints "10 dumpsters over 284 summed tile
-- squares (one ceil for the site, not one per building)". 0052's default was never exercised —
-- every writer sets the column explicitly — so this changes no existing row's behaviour.
--
-- Idempotent: SET DEFAULT is absolute, not additive.

ALTER TABLE bid_projects
    ALTER COLUMN once_per_project_fees
    SET DEFAULT '["delivery_plywood_vents", "new_bonus_values", "permit_processing", "tile_dumpster"]';

COMMENT ON COLUMN bid_projects.once_per_project_fees IS
    'Fee keys charged ONCE for the site instead of per building. Authority is core.bid_project.DEFAULT_ONCE_PER_PROJECT; this default mirrors it. tile_dumpster is included because tile_dumpster_count is a ceil() and per-building calls over-count.';
