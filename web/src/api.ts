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

// ── Quoting: public accept-page client (RESTORED — clobbered by a stale write) ──
// These three call the UNAUTHENTICATED token-gated accept surface with plain fetch
// (no Firebase token). Shapes match api/routes/proposals.py public projection.

export interface QuoteTier {
  label: string;
  description: string;
  total: number;
}

export interface QuoteOptionalItem {
  id: string;
  label: string;
  unit_price: number;
  qty: number;
}

export interface QuoteDepositPolicy {
  mode: "percent" | "fixed" | "none";
  value: number;
  instructions: string;
}

export interface QuoteSnapshot {
  tiers: Record<string, QuoteTier>;
  optional_items: QuoteOptionalItem[];
  deposit_policy: QuoteDepositPolicy;
}

export interface AcceptPageData {
  status: string;
  title: string;
  customer_name: string;
  property_address: string;
  quote_snapshot: QuoteSnapshot;
  tenant_name: string;
}

export async function getAcceptPage(token: string): Promise<AcceptPageData> {
  const res = await fetch(`${BASE}/p/${encodeURIComponent(token)}`);
  if (!res.ok) throw new Error(`accept page ${res.status}`);
  return res.json();
}

export async function submitAccept(
  token: string,
  body: { selected_tier: string; selected_options: string[]; consent_electronic: boolean; signed_name: string },
): Promise<{ ok: boolean; status: string }> {
  const res = await fetch(`${BASE}/p/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`accept ${res.status}`);
  return res.json();
}

export async function submitDecline(
  token: string,
  body: { note?: string },
): Promise<{ ok: boolean; status: string }> {
  const res = await fetch(`${BASE}/p/${encodeURIComponent(token)}/decline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`decline ${res.status}`);
  return res.json();
}

// ── F5: Brand kit + Marketing + KB tenant settings ──────────────────────────

export interface BrandKit {
  logo_gcs_uri?: string;
  primary_color?: string;
  accent_color?: string;
  font_heading?: string;
  font_body?: string;
  intro_gcs_uri?: string;
  outro_gcs_uri?: string;
  voice_sample_gcs_uri?: string;
}

export interface SocialAccountStatus {
  connected: boolean;
  account_id?: string;
}

export interface MarketingSettings {
  brand?: BrandKit;
  caption_prompt_version?: string;
  publish_cadence_days?: number;
  seed_pct?: number;
  royalty_free_music_catalog?: string;
  social_accounts?: Record<string, SocialAccountStatus>;
  safety_denylist?: string[];
}

export interface KbSettings {
  ingest_enabled?: boolean;
  abstain_threshold?: number;
  faq_policy?: "auto" | "manual";
  channel_sources?: string[];
}

export async function getAdminTenantSettings(): Promise<Record<string, unknown>> {
  const res = await apiFetch("/admin/tenant/settings");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function getMarketingSettings(): Promise<MarketingSettings> {
  const data = await getAdminTenantSettings();
  return { ...(data["marketing"] as object ?? {}), brand: data["brand"] } as MarketingSettings;
}

export async function putMarketingSettings(settings: MarketingSettings): Promise<MarketingSettings> {
  const res = await apiFetch("/admin/tenant/settings/marketing", { method: "PUT", body: JSON.stringify(settings) });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return (data["marketing"] ?? data) as MarketingSettings;
}

export async function getKbSettings(): Promise<KbSettings> {
  const data = await getAdminTenantSettings();
  return (data["kb"] ?? {}) as KbSettings;
}

export async function putKbSettings(settings: KbSettings): Promise<KbSettings> {
  const res = await apiFetch("/admin/tenant/settings/kb", { method: "PUT", body: JSON.stringify(settings) });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return (data["kb"] ?? data) as KbSettings;
}

const _CONTENT_TYPE: Record<string, string> = {
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", svg: "image/svg+xml",
  mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm",
  wav: "audio/wav", mp3: "audio/mpeg", m4a: "audio/mp4",
};

/** Presigned brand-asset upload. UI passes a BrandKit field key + file extension;
 *  this adapts to the backend contract ({asset_name, content_type} → {upload_url,
 *  gcs_uri}) and returns the UI shape {url, gcs_path}. */
export async function getBrandUploadUrl(
  assetKey: keyof BrandKit,
  ext: string,
): Promise<{ url: string; gcs_path: string }> {
  const base = String(assetKey).replace(/_gcs_uri$/, "");
  const asset_name = `${base}.${ext}`;
  const content_type = _CONTENT_TYPE[ext.toLowerCase()] ?? "application/octet-stream";
  const res = await apiFetch("/admin/tenant/brand/upload-url", {
    method: "POST",
    body: JSON.stringify({ asset_name, content_type }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return { url: data.upload_url, gcs_path: data.gcs_uri };
}
