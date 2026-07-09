import { getIdToken } from "./auth";

const BASE = import.meta.env.VITE_API_BASE as string;

// ── Pricing config types ───────────────────────────────────────────────────────

export interface PricingConfigVersion {
  id: number;
  branch: string;
  version: number;
  label: string | null;
  config_hash: string;       // full 64-char SHA-256 hex
  is_active: boolean;
  created_at: string;        // ISO 8601
  created_by: string;
}

export interface PricingConfigDetail extends PricingConfigVersion {
  config: Record<string, unknown>;   // full JSONB payload
}

export interface PricingConfigDiff {
  from_id: number;
  to_id: number;
  changes: Array<{
    path: string;             // dot-separated JSON path, e.g. "sloped_base_cost_lm.HVHZ.13_tile"
    from_value: unknown;
    to_value: unknown;
  }>;
}

// ── Pricing config API client ──────────────────────────────────────────────────

/** List all versions for a branch, newest first. */
export async function listPricingConfigs(branch: string): Promise<PricingConfigVersion[]> {
  const res = await apiFetch(`/estimator/configs?branch=${encodeURIComponent(branch)}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** Get full detail (including config JSONB) for one version. */
export async function getPricingConfig(id: number): Promise<PricingConfigDetail> {
  const res = await apiFetch(`/estimator/configs/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** Get the currently active config for a branch (detail + config JSONB). */
export async function getActivePricingConfig(branch: string): Promise<PricingConfigDetail> {
  const res = await apiFetch(`/estimator/configs/active?branch=${encodeURIComponent(branch)}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** Create a new immutable version. Returns the new version row. */
export async function createPricingConfig(payload: {
  branch: string;
  label?: string;
  config: Record<string, unknown>;
}): Promise<PricingConfigVersion> {
  const res = await apiFetch("/estimator/configs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Activate a version (idempotent). */
export async function activatePricingConfig(id: number): Promise<PricingConfigVersion> {
  const res = await apiFetch(`/estimator/configs/${id}/activate`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Field-level diff between two versions. */
export async function diffPricingConfigs(fromId: number, toId: number): Promise<PricingConfigDiff> {
  const res = await apiFetch(`/estimator/configs/diff?from_id=${fromId}&to_id=${toId}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// Fetch the API with the Firebase ID token. If the token has expired (401), force a
// refresh and retry once — so a long-open tab never gets stuck on stale-token 401s.
export async function apiFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const call = async (forceRefresh: boolean) => {
    const token = await getIdToken(forceRefresh);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${BASE}${path}`, { ...options, headers });
  };

  let res = await call(false);
  if (res.status === 401) res = await call(true); // token likely expired — refresh + retry
  return res;
}

/** Like apiFetch but does NOT set Content-Type — required for multipart/form-data uploads
 *  so the browser can set the boundary automatically. */
export async function apiFetchMultipart(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const call = async (forceRefresh: boolean) => {
    const token = await getIdToken(forceRefresh);
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${BASE}${path}`, { ...options, headers });
  };

  let res = await call(false);
  if (res.status === 401) res = await call(true);
  return res;
}
