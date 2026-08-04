// Which overhead day-series a roof type books against, and what to put in the day cells.
//
// Tim, 2026-08-03: "Maybe only offer suggested pricing and a suggested # of days that can be
// edited within the cell." The cells were editable but started BLANK — the API derives the days
// when `daily_series` is empty, so the model's suggestion was USED and never SHOWN, and the
// estimator could not see the number they were meant to adjust.
//
// Extracted from Quoting.tsx so the decision can be tested without mounting the page.

export const INSTALL_SERIES_BY_ROOF: Record<string, string> = {
  "13_tile": "tile", barrel_tile: "tile",
  standing_seam_metal: "metal",
  "3tab_shingle": "shingle", dimensional_shingle: "shingle",
};

export const DEMO_SERIES = "demo_dry_in_flat";

// Low slope books its OWN series. It used to fall through to `demo_dry_in_flat` because that was
// the only rate covering flat work ("Demo & Flat: $1,050 per day"); since 2026-08-03 there is a
// fitted `low_slope` series, and sending demo_dry_in_flat would book flat INSTALL days against
// the TEAR-OFF rate — invisible under branch-basis overhead, where the rate is the branch burn,
// and wrong on any branch priced from the per-activity rates.
export const LOW_SLOPE_SERIES = "low_slope";

/** Low-slope systems are config-driven (tpo_adhered, polyglass_sav_sap, pb_silicone_*), so they
 *  cannot be enumerated — resolve by SLOPE, not by listing system keys. */
export function installSeriesFor(roofType: string, isLowSlope: boolean): string | null {
  return INSTALL_SERIES_BY_ROOF[roofType] ?? (isLowSlope ? LOW_SLOPE_SERIES : null);
}

export type DaySeries = { series: string; days: number };

/**
 * What the two day cells should show after a quote returns.
 *
 * Only fills a cell the operator left EMPTY. Overwriting a typed value would silently discard
 * their override on every re-quote — the opposite of "can be edited within the cell".
 *
 * The flat half of a MIXED roof books `low_slope` while the install cell belongs to the sloped
 * series; it has no cell of its own and is deliberately not folded into either one, because
 * adding it to the sloped cell would re-submit those days against the SLOPED rate.
 */
export function suggestedDayCells(
  derived: DaySeries[] | undefined,
  roofType: string,
  isLowSlope: boolean,
  currentDemo: string,
  currentInstall: string,
): { demo?: string; install?: string } {
  const out: { demo?: string; install?: string } = {};
  if (!derived?.length) return out;
  const installSeries = installSeriesFor(roofType, isLowSlope);

  // ⚠️ THE CELLS ARE AN OVERRIDE CHANNEL, NOT A DISPLAY. The server derives days only when
  // `daily_series` arrives EMPTY (core/estimator.py: `if overhead_mode == "daily" and not
  // daily_series`). So filling any cell makes the next quote authoritative for ALL series — and
  // a MIXED sloped+flat roof derives three (install + demo + low_slope) while there are only two
  // cells. Pre-filling two of three silently deleted the flat crew's days on every re-quote:
  // measured -$2,940 on 30sq tile + 12sq flat and -$5,880 on 30+28, with the
  // `daily_days_auto_filled` warning removed by the same act, on 36% of the sold book.
  //
  // So: if the model derived a series that has no cell, suggest NOTHING and leave the cells
  // empty, which keeps the server deriving all three. Mixed roofs lose the suggestion; they do
  // not lose money. Giving the flat section its own cell (and making derivation additive
  // server-side) is the real fix and is deliberately not attempted here.
  const mapped = new Set([DEMO_SERIES, installSeries].filter(Boolean) as string[]);
  if (derived.some((d) => !mapped.has(d.series))) return out;

  const dayOf = (name: string | null) =>
    name ? derived.find((d) => d.series === name)?.days : undefined;

  const demo = dayOf(DEMO_SERIES);
  if (demo != null && currentDemo === "") out.demo = String(demo);

  // On a pure low-slope quote the install series IS low_slope, so this is its own cell.
  const install = dayOf(installSeries);
  if (install != null && currentInstall === "") out.install = String(install);
  return out;
}
