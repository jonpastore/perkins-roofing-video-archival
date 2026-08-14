import { describe, expect, it } from "vitest";
import { hms, ytLink } from "./ui";

describe("ytLink", () => {
  it("deep-links a finite start time", () => {
    expect(ytLink("abc123", 90)).toBe("https://youtu.be/abc123?t=90");
    expect(ytLink("abc123", 90.9)).toBe("https://youtu.be/abc123?t=90");
  });

  it("omits ?t= when start is missing or not finite", () => {
    expect(ytLink("abc123", null)).toBe("https://youtu.be/abc123");
    expect(ytLink("abc123", undefined)).toBe("https://youtu.be/abc123");
    expect(ytLink("abc123", Number.NaN)).toBe("https://youtu.be/abc123");
  });
});

describe("hms", () => {
  it("uses M:SS under an hour and H:MM:SS above", () => {
    expect(hms(65)).toBe("1:05");
    expect(hms(3723)).toBe("1:02:03");
  });

  it("returns an em dash for missing or non-finite", () => {
    expect(hms(null)).toBe("—");
    expect(hms(undefined)).toBe("—");
    expect(hms(Number.NaN)).toBe("—");
  });
});
