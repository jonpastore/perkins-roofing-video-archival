import { describe, expect, it } from "vitest";
import { errText, formatDetail } from "./errors";

function resp(body: unknown, status = 422, statusText = "Unprocessable Entity"): Response {
  return new Response(JSON.stringify(body), { status, statusText });
}

describe("formatDetail", () => {
  it("passes plain string detail through", () => {
    expect(formatDetail({ detail: "customer not found" })).toBe("customer not found");
  });

  it("humanizes the FastAPI 422 validation array (the [object Object] regression)", () => {
    const body = {
      detail: [
        { type: "string_too_long", loc: ["body", "state"], msg: "String should have at most 2 characters" },
        { type: "missing", loc: ["body", "street"], msg: "Field required" },
      ],
    };
    const out = formatDetail(body);
    expect(out).toBe(
      "state: String should have at most 2 characters; street: Field required"
    );
    expect(out).not.toContain("[object Object]");
  });

  it("handles nested loc and non-body locations", () => {
    expect(
      formatDetail({ detail: [{ loc: ["query", "limit"], msg: "Input should be a valid integer" }] })
    ).toBe("limit: Input should be a valid integer");
  });

  it("falls back through message/error keys", () => {
    expect(formatDetail({ message: "boom" })).toBe("boom");
    expect(formatDetail({ error: "nope" })).toBe("nope");
  });

  it("returns null for empty/unknown bodies", () => {
    expect(formatDetail(null)).toBeNull();
    expect(formatDetail({})).toBeNull();
    expect(formatDetail("")).toBeNull();
  });
});

describe("errText", () => {
  it("never renders [object Object] for a 422 response", async () => {
    const msg = await errText(
      resp({ detail: [{ loc: ["body", "state"], msg: "String should have at most 2 characters" }] })
    );
    expect(msg).toBe("state: String should have at most 2 characters");
  });

  it("uses status hint when body is not JSON", async () => {
    const r = new Response("<html>oops</html>", { status: 500, statusText: "Internal Server Error" });
    expect(await errText(r)).toBe("Server error — try again or contact support (500)");
  });

  it("works even if the body was already consumed (clone-based read)", async () => {
    const r = resp({ detail: "already read" }, 409, "Conflict");
    await r.clone().json();
    expect(await errText(r)).toBe("already read");
  });
});
