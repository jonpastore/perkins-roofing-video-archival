import { describe, expect, it } from "vitest";
import { installSeriesFor, LOW_SLOPE_SERIES, suggestedDayCells } from "./quoteDays";

describe("installSeriesFor", () => {
  it("maps each sloped roof type to its own series", () => {
    expect(installSeriesFor("13_tile", false)).toBe("tile");
    expect(installSeriesFor("barrel_tile", false)).toBe("tile");
    expect(installSeriesFor("standing_seam_metal", false)).toBe("metal");
    expect(installSeriesFor("dimensional_shingle", false)).toBe("shingle");
  });

  it("books low slope against low_slope, NOT the tear-off rate", () => {
    // Booking flat INSTALL days against demo_dry_in_flat ($1,050, the tear-off rate) is invisible
    // under branch-basis overhead and wrong on a per-activity branch.
    expect(installSeriesFor("tpo_adhered", true)).toBe(LOW_SLOPE_SERIES);
    expect(installSeriesFor("polyglass_sav_sap", true)).toBe(LOW_SLOPE_SERIES);
    expect(installSeriesFor("pb_silicone_2coat", true)).not.toBe("demo_dry_in_flat");
  });

  it("returns null for a roof type with no series rather than guessing one", () => {
    // The old `?? "demo_dry_in_flat"` fallback silently billed unknown roofs at the demo rate.
    expect(installSeriesFor("mystery_roof", false)).toBeNull();
  });
});

describe("suggestedDayCells", () => {
  const sloped = [
    { series: "tile", days: 3 },
    { series: "demo_dry_in_flat", days: 2 },
  ];

  it("fills both empty cells from the derived days", () => {
    expect(suggestedDayCells(sloped, "13_tile", false, "", "")).toEqual({ demo: "2", install: "3" });
  });

  it("never overwrites a number the operator typed", () => {
    // This is the whole point of "can be edited within the cell" — a re-quote must not discard it.
    expect(suggestedDayCells(sloped, "13_tile", false, "4", "5")).toEqual({});
    expect(suggestedDayCells(sloped, "13_tile", false, "4", "")).toEqual({ install: "3" });
  });

  it("does nothing when the API derived no days", () => {
    expect(suggestedDayCells([], "13_tile", false, "", "")).toEqual({});
    expect(suggestedDayCells(undefined, "13_tile", false, "", "")).toEqual({});
  });

  it("fills the install cell on a pure low-slope quote", () => {
    const lowSlope = [{ series: "low_slope", days: 2 }];
    expect(suggestedDayCells(lowSlope, "polyglass_sav_sap", true, "", "")).toEqual({ install: "2" });
  });

  it("suggests NOTHING on a mixed roof, so the flat days keep being derived", () => {
    // THE MONEY CASE. A mixed roof derives three series but there are two cells. Filling two of
    // them makes the next quote authoritative for all three and the server stops deriving, so the
    // flat crew's days vanish — measured -$2,940 on 30sq tile + 12sq flat and -$5,880 on 30+28,
    // silently, with the `daily_days_auto_filled` warning removed by the same act. Empty cells
    // keep the server deriving, so the price stays right even though no suggestion is shown.
    const mixed = [
      { series: "tile", days: 3 },
      { series: "demo_dry_in_flat", days: 2 },
      { series: "low_slope", days: 1 },
    ];
    expect(suggestedDayCells(mixed, "13_tile", false, "", "")).toEqual({});
  });

  it("suggests nothing when the model derived a series this roof type has no cell for", () => {
    // The same rule stated generally: ANY unmapped series disables the whole suggestion, so a
    // series added to the day model later cannot silently delete itself from the price.
    const unknownRoof = suggestedDayCells(sloped, "mystery_roof", false, "", "");
    expect(unknownRoof).toEqual({});
    const newSeries = [{ series: "tile", days: 3 }, { series: "brand_new", days: 4 }];
    expect(suggestedDayCells(newSeries, "13_tile", false, "", "")).toEqual({});
  });
});
