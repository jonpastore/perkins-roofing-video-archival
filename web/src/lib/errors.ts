/** Human-readable messages from FastAPI error bodies.
 *
 * FastAPI 422 validation errors put an ARRAY of {loc, msg, type} objects in
 * `detail`. Naive `String(detail)` / template interpolation renders
 * "[object Object]" in the UI — every error surface must go through here.
 */

/** Format any FastAPI-ish error payload (string, 422 array, nested object). */
export function formatDetail(d: unknown): string | null {
  if (typeof d === "string") return d.trim() || null;
  if (Array.isArray(d)) {
    const parts = d
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const { loc, msg } = item as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(loc)
            ? loc.filter((p) => p !== "body" && p !== "query" && p !== "path").join(".")
            : "";
          if (msg) return field ? `${field}: ${msg}` : msg;
        }
        return JSON.stringify(item);
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (d && typeof d === "object") {
    const body = d as { detail?: unknown; message?: unknown; error?: unknown; msg?: unknown };
    for (const v of [body.detail, body.message, body.error, body.msg]) {
      const s = formatDetail(v);
      if (s) return s;
    }
    return null;
  }
  return null;
}

const STATUS_HINTS: Record<number, string> = {
  401: "You are not signed in (or your session expired)",
  403: "You do not have permission to do this",
  404: "Not found",
  409: "Conflict — the item changed underneath you",
  422: "Some fields are invalid",
  500: "Server error — try again or contact support",
};

/** Read the error body off a failed Response and return a human-readable message. */
export async function errText(res: Response): Promise<string> {
  const d = await res
    .clone()
    .json()
    .catch(() => null);
  const msg = formatDetail(d);
  if (msg) return msg;
  const hint = STATUS_HINTS[res.status];
  return hint ? `${hint} (${res.status})` : `${res.status} ${res.statusText}`;
}
