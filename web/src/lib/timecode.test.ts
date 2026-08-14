import { describe, expect, it } from "vitest";
import { fmtHMS, parseHMS } from "./timecode";

describe("fmtHMS", () => {
  it("zero-pads hours minutes seconds", () => {
    expect(fmtHMS(0)).toBe("00:00:00");
    expect(fmtHMS(65)).toBe("00:01:05");
    expect(fmtHMS(3723)).toBe("01:02:03");
  });

  it("floors negatives and NaN-ish to zero", () => {
    expect(fmtHMS(-4)).toBe("00:00:00");
  });
});

describe("parseHMS", () => {
  it("accepts hh:mm:ss, mm:ss, and bare seconds", () => {
    expect(parseHMS("01:02:03")).toBe(3723);
    expect(parseHMS("02:03")).toBe(123);
    expect(parseHMS("45")).toBe(45);
  });

  it("is lenient about empty segments so typing 01: stays numeric", () => {
    expect(parseHMS("01:")).toBe(60);
    expect(parseHMS("01:02:")).toBe(3720);
  });

  it("rejects non-numeric parts", () => {
    expect(parseHMS("ab:00")).toBeNull();
    expect(parseHMS("1:x:2")).toBeNull();
  });
});
