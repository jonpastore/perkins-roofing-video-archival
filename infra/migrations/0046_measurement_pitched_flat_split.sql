-- Measurements: store the pitched/flat split RoofR already reports.
--
-- Every RoofR report gives total_sqft, pitched_sqft and flat_sqft, and total = pitched + flat
-- exactly (verified across the golden set). We captured only total_sq, which made it AMBIGUOUS:
-- for Tim's 30-home set it holds his SLOPED count, so the flat area was never quoted at all; for a
-- measurement transcribed from a RoofR report it holds pitched+flat, so the flat area was quoted
-- at the SLOPED rate. Same column, two meanings, no way to tell them apart.
--
-- 9 of Tim's 30 homes have a flat section, up to a third of the roof.
--
-- total_sq is left alone: it stays whatever was entered, and remains the number the estimator
-- quotes from when the split is unknown. When pitched_sq/flat_sq are present the quote builder
-- uses them and the ambiguity is gone.
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS pitched_sq double precision;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS flat_sq     double precision;

COMMENT ON COLUMN measurements.pitched_sq IS
  'RoofR pitched_sqft / 100. Sloped area only. NULL = split unknown, fall back to total_sq.';
COMMENT ON COLUMN measurements.flat_sq IS
  'RoofR flat_sqft / 100. Low-slope area on the same roof. NULL = split unknown; 0 = no flat section.';
