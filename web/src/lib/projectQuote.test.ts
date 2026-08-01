/**
 * Behavioural validation for the multi-building bid surface (#430/#449 slice 4, R1).
 *
 * These cover the two pure seams the page's project flow rests on: the request body it POSTs to
 * /estimator/project-quote, and the rule that decides whether a roof may join the bid. They exist
 * because the R2 architect review found the SPA could file a bid against the wrong customer and
 * could not express the very bid it was built for — both silent, and neither catchable by a
 * compile check.
 */
import { describe, expect, it } from "vitest";

import {
  buildProjectQuoteBody,
  projectBidSignature,
  rejectBuildingCapture,
  type ProjectBuildingDraft,
  type ProjectItemDraft,
} from "./projectQuote";

function draft(name: string, over: Partial<ProjectBuildingDraft> = {}): ProjectBuildingDraft {
  return {
    name,
    squares: 10,
    quote: { branch: "jupiter", code_zone: "FBC", roof_type: "13_tile", num_squares: 10 },
    propertyId: 1,
    ...over,
  };
}

describe("buildProjectQuoteBody", () => {
  it("sends the fields the backend needs, including the ones that were previously omitted", () => {
    const body = buildProjectQuoteBody({
      name: "Evergrene",
      buildings: [draft("Clubhouse"), draft("Bus Stop", { squares: 3, days: 2 })],
      persist: true,
      propertyId: 42,
      projectItems: [{ key: "gc", label: "General Conditions", cost: 31800, markup: 1.15 }],
      permitCount: 9,
    });

    expect(body.name).toBe("Evergrene");
    // Without these the screen could not reproduce Tim's Evergrene bid: General Conditions is
    // $36,570 of it, and a nine-structure site may pull one permit per structure.
    expect(body.project_items).toEqual([
      { key: "gc", label: "General Conditions", cost: 31800, markup: 1.15 },
    ]);
    expect(body.permit_count).toBe(9);
    // Binds the bid to a site; the column was validated server-side and never exercised.
    expect(body.property_id).toBe(42);
    expect(body.persist).toBe(true);
  });

  it("sends only name/days/quote per building, matching BuildingInput", () => {
    const body = buildProjectQuoteBody({
      name: "P", buildings: [draft("Clubhouse", { days: 6 })], persist: false,
    });
    const buildings = body.buildings as Array<Record<string, unknown>>;
    expect(Object.keys(buildings[0]).sort()).toEqual(["days", "name", "quote"]);
    expect(buildings[0].name).toBe("Clubhouse");
    expect(buildings[0].days).toBe(6);
  });

  it("never sends an empty project name or a zero permit count", () => {
    const body = buildProjectQuoteBody({
      name: "   ", buildings: [draft("A")], persist: false, permitCount: 0,
    });
    expect(body.name).toBe("Untitled project");   // min_length=1 on the API
    expect(body.permit_count).toBe(1);            // ge=1 on the API
  });

  it("defaults persist to what the caller asked — the API default is False on purpose", () => {
    expect(buildProjectQuoteBody({ name: "P", buildings: [draft("A")], persist: false }).persist)
      .toBe(false);
  });
});

describe("rejectBuildingCapture", () => {
  const ok = { existing: [] as ProjectBuildingDraft[], propertyId: 1, discountCount: 0, days: "" };

  it("allows a well-formed capture", () => {
    expect(rejectBuildingCapture({ ...ok, name: "Clubhouse" })).toBeNull();
  });

  it("requires a name — a bid of anonymous roofs cannot be read", () => {
    expect(rejectBuildingCapture({ ...ok, name: "   " })).toMatch(/Name the structure/);
  });

  it("refuses a duplicate name case-insensitively", () => {
    const refusal = rejectBuildingCapture({
      ...ok, name: "clubhouse", existing: [draft("Clubhouse")],
    });
    expect(refusal).toMatch(/already in this bid/);
  });

  it("refuses a roof at a DIFFERENT property — a bid is one site", () => {
    const refusal = rejectBuildingCapture({
      ...ok, name: "Gate House", existing: [draft("Clubhouse", { propertyId: 1 })],
      propertyId: 2,
    });
    expect(refusal).toMatch(/SAME property/);
  });

  it("refuses a capture while discounts are on the form, naming the count", () => {
    // The API refuses per-building discounts; without this the user met a policy message with no
    // indication that the discount rows still on screen were the cause.
    const refusal = rejectBuildingCapture({ ...ok, name: "Clubhouse", discountCount: 2 });
    expect(refusal).toMatch(/Remove the 2 discount/);
  });

  it("refuses a non-numeric days value instead of silently dropping it", () => {
    // Number("3d") is NaN, which JSON.stringify emits as null and the API accepts as absent —
    // the user's input vanished with no message.
    expect(rejectBuildingCapture({ ...ok, name: "Clubhouse", days: "3d" }))
      .toMatch(/must be a number/);
    expect(rejectBuildingCapture({ ...ok, name: "Clubhouse", days: "6" })).toBeNull();
  });

  it("does not block the FIRST capture on the property rule", () => {
    expect(rejectBuildingCapture({ ...ok, name: "First", existing: [], propertyId: 7 })).toBeNull();
  });
});


describe("projectBidSignature — the duplicate-save gate", () => {
  const base = { name: "Evergrene", items: [] as ProjectItemDraft[], permitCount: "1" };

  it("changes when a building's ROOF CONFIG changes, not just its name or squares", () => {
    // Remove-and-re-add is the only way to edit a captured roof. A signature over name+squares
    // alone said "already saved" about a bid whose price had changed, and disabled the only
    // button that could save the correction.
    const before = projectBidSignature({ ...base, buildings: [draft("Clubhouse")] });
    const after = projectBidSignature({
      ...base,
      buildings: [draft("Clubhouse", {
        quote: { branch: "jupiter", code_zone: "FBC", roof_type: "barrel_tile", num_squares: 10 },
      })],
    });
    expect(after).not.toBe(before);
  });

  it("is stable for an identical bid", () => {
    expect(projectBidSignature({ ...base, buildings: [draft("A"), draft("B")] }))
      .toBe(projectBidSignature({ ...base, buildings: [draft("A"), draft("B")] }));
  });

  it("normalises permit count so an identical request cannot save twice", () => {
    // "1", "01" and "1.0" all send permit_count 1.
    const one = projectBidSignature({ ...base, buildings: [draft("A")], permitCount: "1" });
    expect(projectBidSignature({ ...base, buildings: [draft("A")], permitCount: "01" })).toBe(one);
    expect(projectBidSignature({ ...base, buildings: [draft("A")], permitCount: "1.0" })).toBe(one);
    expect(projectBidSignature({ ...base, buildings: [draft("A")], permitCount: "9" })).not.toBe(one);
  });

  it("changes when site-wide scope changes", () => {
    const without = projectBidSignature({ ...base, buildings: [draft("A")] });
    const withGc = projectBidSignature({
      ...base, buildings: [draft("A")],
      items: [{ key: "gc", label: "General Conditions", cost: 31800, markup: 1.15 }],
    });
    expect(withGc).not.toBe(without);
  });
});

describe("add-on blocks are sent separately from general conditions", () => {
  it("keeps Tim's two block types apart on the wire", () => {
    // Folding them prices identically but persists the misfiling slice 2 fixed.
    const body = buildProjectQuoteBody({
      name: "Evergrene", buildings: [draft("Clubhouse")], persist: true,
      projectItems: [{ key: "gc", label: "General Conditions", cost: 31800, markup: 1.15 }],
      addOnBlocks: [{ key: "sloped", label: "Sloped add-ons", cost: 42050, markup: 1 }],
    });
    expect((body.project_items as unknown[]).length).toBe(1);
    expect((body.add_on_blocks as unknown[]).length).toBe(1);
    expect((body.add_on_blocks as Array<{ key: string }>)[0].key).toBe("sloped");
  });
});

describe("rejectBuildingCapture — zone axis", () => {
  it("refuses a roof in a different code zone, naming both", () => {
    // The server refuses too, but by then it can only name the ZONES, not which of nine captured
    // structures is the odd one — and the list shows no zone.
    const refusal = rejectBuildingCapture({
      name: "Gate", existing: [draft("Clubhouse", { codeZone: "FBC" })],
      propertyId: 1, discountCount: 0, days: "", codeZone: "HVHZ",
    });
    expect(refusal).toMatch(/HVHZ/);
    expect(refusal).toMatch(/FBC/);
  });

  it("refuses negative days and tolerates whitespace", () => {
    const ok = { existing: [] as ProjectBuildingDraft[], propertyId: 1, discountCount: 0 };
    expect(rejectBuildingCapture({ ...ok, name: "A", days: "-3" })).toMatch(/cannot be negative/);
    expect(rejectBuildingCapture({ ...ok, name: "A", days: "  " })).toBeNull();
  });
});
