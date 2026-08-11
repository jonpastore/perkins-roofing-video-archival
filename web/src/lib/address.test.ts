import { describe, expect, it } from "vitest";
import { looksComplete, parseAddress } from "./address";

describe("parseAddress", () => {
  it("splits the shape estimators actually paste", () => {
    expect(parseAddress("1234 SW 5th St, Miami, FL 33169")).toEqual({
      street: "1234 SW 5th St", city: "Miami", state: "FL", zip: "33169",
    });
  });

  it("keeps a unit attached to the street line", () => {
    // Rejoining matters: "Apt 4" as its own field would land in `city`.
    expect(parseAddress("575 NW 152nd St, Apt 4, Miami, FL 33169")).toEqual({
      street: "575 NW 152nd St, Apt 4", city: "Miami", state: "FL", zip: "33169",
    });
  });

  it("handles ZIP+4, a trailing country, and a state with a period", () => {
    expect(parseAddress("15658 Alexander Run, Jupiter, Fl. 33478-1234, USA")).toEqual({
      street: "15658 Alexander Run", city: "Jupiter", state: "FL", zip: "33478",
    });
  });

  it("handles the state and ZIP arriving as separate fields", () => {
    expect(parseAddress("188 Lone Pine Dr, Palm Beach Gardens, FL, 33418")).toEqual({
      street: "188 Lone Pine Dr", city: "Palm Beach Gardens", state: "FL", zip: "33418",
    });
  });

  it("pulls the tail off a comma-less paste but does not guess the city", () => {
    // "123 Main St Miami FL 33169" — the state/ZIP tail is unambiguous, the street/city
    // boundary is not. A wrong city written silently is worse than an empty one.
    expect(parseAddress("1350 SW 21st Ter Fort Lauderdale FL 33312")).toEqual({
      street: "1350 SW 21st Ter Fort Lauderdale", city: "", state: "FL", zip: "33312",
    });
  });

  it("treats a bare street line as a street, not a city", () => {
    expect(parseAddress("123 Main St")).toEqual({ street: "123 Main St", city: "", state: "", zip: "" });
  });

  it("returns empty fields for empty input rather than throwing", () => {
    expect(parseAddress("")).toEqual({ street: "", city: "", state: "", zip: "" });
    expect(parseAddress("   ")).toEqual({ street: "", city: "", state: "", zip: "" });
  });

  it("collapses newlines from a letter or signature-block paste", () => {
    expect(parseAddress("575 NW 152nd St\nMiami, FL 33169")).toEqual({
      street: "575 NW 152nd St Miami", city: "", state: "FL", zip: "33169",
    });
  });
});

describe("looksComplete", () => {
  it("is true only when there is a street plus a city or ZIP", () => {
    expect(looksComplete("1234 SW 5th St, Miami, FL 33169")).toBe(true);
    expect(looksComplete("123 Main St")).toBe(false);
    expect(looksComplete("")).toBe(false);
  });
});
