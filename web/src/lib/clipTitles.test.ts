import { describe, expect, it } from "vitest";
import { cleanTitle, seriesTitle } from "./clipTitles";

describe("cleanTitle", () => {
  it("strips letter hashtags and keeps numeric references", () => {
    expect(cleanTitle("Roof Repair 101 #roofing #diy")).toBe("Roof Repair 101");
    expect(cleanTitle("Shingle Red Flag #2 Most People Ignore"))
      .toBe("Shingle Red Flag #2 Most People Ignore");
  });

  it("strips leading junk, markdown asterisks, and extra spaces", () => {
    expect(cleanTitle("—  Gutters   Guide  ")).toBe("Gutters Guide");
    expect(cleanTitle("*Shingle Red Flag* Explained")).toBe("Shingle Red Flag Explained");
  });

  it("hashtag-only titles collapse to empty", () => {
    expect(cleanTitle("#perkinsroofing #roofinginnovation")).toBe("");
  });
});

describe("seriesTitle", () => {
  it("appends the Clips suffix", () => {
    expect(seriesTitle("Metal roofs")).toBe("Metal roofs — Clips");
  });

  it("falls back when cleaning leaves nothing", () => {
    expect(seriesTitle("#only")).toBe("Clips");
  });

  it("truncates at a word boundary under 50 chars before the suffix", () => {
    const long = "The complete guide to standing seam metal roofing in hurricane zones";
    const out = seriesTitle(long);
    expect(out.endsWith(" — Clips")).toBe(true);
    const body = out.replace(" — Clips", "");
    expect(body.length).toBeLessThanOrEqual(50);
    expect(body.endsWith(" ")).toBe(false);
    expect(body.startsWith("The complete")).toBe(true);
  });
});
