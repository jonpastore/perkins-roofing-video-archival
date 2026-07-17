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

// ── F6: tenant provisioning + per-tenant SSO ─────────────────────────────────

export interface Tenant {
  id: number;
  name: string;
  slug: string;
  status: "provisioning" | "active" | "provisioning_failed" | "offboarded";
  admin_email?: string | null;
  created_at?: string | null;
  mau?: number | null;
}

export interface TenantStatus {
  status: "provisioning" | "active" | "provisioning_failed";
  invite_link?: string;
  error?: string;
}

export type IdpType = "saml" | "oidc";

export interface SsoProvider {
  idp_id: string;
  type: IdpType;
  display_name: string;
  entity_id?: string;
  sso_url?: string;
  issuer_url?: string;
  client_id?: string;
  created_at?: string;
}

export type AddSsoProviderPayload =
  | { type: "saml"; display_name: string; entity_id: string; sso_url: string; certificate_pem: string }
  | { type: "oidc"; display_name: string; issuer_url: string; client_id: string; client_secret: string };

export function listTenants(): Promise<Tenant[]> {
  return apiFetch("/internal/tenants").then((r) => r.json());
}
export function provisionTenant(payload: { name: string; slug: string; admin_email: string }): Promise<{ id: number; status: string; invite_link?: string }> {
  return apiFetch("/internal/tenants", { method: "POST", body: JSON.stringify(payload) }).then((r) => r.json());
}
export function getTenantStatus(id: number): Promise<TenantStatus> {
  return apiFetch(`/internal/tenants/${id}/status`).then((r) => r.json());
}
export function resendTenantInvite(id: number): Promise<{ invite_link?: string }> {
  return apiFetch(`/internal/tenants/${id}/resend-invite`, { method: "POST" }).then((r) => r.json());
}
export function offboardTenant(id: number): Promise<void> {
  // Backend contract is DELETE /internal/tenants/{id} (F6 §3.4).
  return apiFetch(`/internal/tenants/${id}`, { method: "DELETE" }).then(() => undefined);
}
export function listSsoProviders(): Promise<SsoProvider[]> {
  return apiFetch("/admin/sso/providers").then((r) => r.json());
}
export function addSsoProvider(payload: AddSsoProviderPayload): Promise<SsoProvider> {
  return apiFetch("/admin/sso/providers", { method: "POST", body: JSON.stringify(payload) }).then((r) => r.json());
}
export function deleteSsoProvider(idpId: string): Promise<void> {
  return apiFetch(`/admin/sso/providers/${idpId}`, { method: "DELETE" }).then(() => undefined);
}

// ── Generic pagination wrapper ───────────────────────────────────────────────

export interface Paged<T> {
  items: T[];
  total: number;
}

// ── Shared helpers ───────────────────────────────────────────────────────────

/** Read the FastAPI `detail` off a failed response, falling back to status text. */
async function errText(res: Response): Promise<string> {
  const d = await res.json().catch(() => null);
  if (typeof d === "string" && d.trim()) return d;
  if (d && typeof d === "object") {
    const body = d as { detail?: unknown; message?: unknown; error?: unknown };
    for (const v of [body.detail, body.message, body.error]) {
      if (typeof v === "string" && v.trim()) return v;
      if (Array.isArray(v)) return v.map((x) => typeof x === "string" ? x : JSON.stringify(x)).join("; ");
      if (v && typeof v === "object") return JSON.stringify(v);
    }
  }
  return `${res.status} ${res.statusText}`;
}

/** Serialize a params object to a query string, skipping undefined/null values. */
function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Fetch an auth-gated PDF endpoint and open it in a new tab (the PDF routes require the
 *  Bearer token, so a plain link/anchor 401s). Mirrors Proposals.tsx handleViewPdf. */
export async function openAuthedPdf(path: string): Promise<void> {
  const r = await apiFetch(path);
  if (!r.ok) throw new Error(await errText(r));
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

// ── Quoting customers/properties (reused by proposal + invoice builders) ──────

export interface QuotingCustomer {
  id: number;
  display_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
}
export interface QuotingProperty {
  id: number;
  customer_id: number;
  street: string;
  city: string;
  state: string;
  zip: string | null;
  county: string | null;
  code_zone: string;
  notes?: string | null;
}
export interface QuotingContact {
  id: number;
  customer_id: number;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
}
export interface QuotingCustomerDetail extends QuotingCustomer {
  contacts: QuotingContact[];
  properties: QuotingProperty[];
}

export interface ListCustomersParams {
  search?: string;
  is_active?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  skip?: number;
  limit?: number;
  page?: number;
}

/** Returns bare array — backwards-compatible for existing callers (ProposalBuilder, Invoices). */
export async function listQuotingCustomers(params?: ListCustomersParams): Promise<QuotingCustomer[]> {
  const q = qs({ limit: 200, ...params });
  const r = await apiFetch(`/quoting/customers${q}`);
  if (!r.ok) throw new Error(await errText(r));
  const data: Paged<QuotingCustomer> = await r.json();
  return data.items;
}

/** Paged variant for the new Customers table (returns {items, total}). */
export async function listQuotingCustomersPaged(params?: ListCustomersParams): Promise<Paged<QuotingCustomer>> {
  const q = qs({ ...params });
  const r = await apiFetch(`/quoting/customers${q}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function getQuotingCustomer(id: number): Promise<QuotingCustomerDetail> {
  const r = await apiFetch(`/quoting/customers/${id}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Soft-delete a customer (sets is_active=false). */
export async function deactivateCustomer(id: number): Promise<QuotingCustomer> {
  const r = await apiFetch(`/quoting/customers/${id}/deactivate`, { method: "PATCH" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export interface CustomerInput {
  display_name: string;
  company_name?: string | null;
  email?: string | null;
  phone?: string | null;
  notes?: string | null;
}
export async function createCustomer(body: CustomerInput): Promise<QuotingCustomer> {
  const r = await apiFetch(`/quoting/customers`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function updateCustomer(id: number, body: Partial<CustomerInput>): Promise<QuotingCustomer> {
  const r = await apiFetch(`/quoting/customers/${id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export interface ContactInput {
  name: string; role?: string | null; email?: string | null; phone?: string | null; is_primary?: boolean;
}
export async function addCustomerContact(customerId: number, body: ContactInput): Promise<QuotingContact> {
  const r = await apiFetch(`/quoting/customers/${customerId}/contacts`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function updateContact(contactId: number, body: Partial<ContactInput>): Promise<QuotingContact> {
  const r = await apiFetch(`/quoting/contacts/${contactId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export interface PropertyInput {
  street: string; city?: string | null; state?: string | null; zip?: string | null;
  county?: string | null; code_zone?: string | null; notes?: string | null;
}
export async function addCustomerProperty(customerId: number, body: PropertyInput): Promise<QuotingProperty> {
  const r = await apiFetch(`/quoting/customers/${customerId}/properties`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function updateProperty(propertyId: number, body: Partial<PropertyInput>): Promise<QuotingProperty> {
  const r = await apiFetch(`/quoting/properties/${propertyId}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function deleteProperty(propertyId: number): Promise<{ deleted: boolean; id: number }> {
  const r = await apiFetch(`/quoting/properties/${propertyId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── JB1: Material price book ─────────────────────────────────────────────────

export interface PriceBookItem {
  id: number;
  sku: string | null;
  name: string;
  unit: string | null;
  unit_coverage: string | null;   // Decimal string; null = no coverage → no price/sq
  unit_price: string | null;      // Decimal string; null = not stocked (never 0)
  tax_rate: string | null;        // Decimal string, e.g. "0.07"
  waste_rate: string | null;      // Decimal string, e.g. "0.10"
  supplier: string | null;
  item_type: string | null;
  knowify_item_id: string | null;
  price_per_square: string | null; // computed server-side; null = not-stocked / no coverage
}
export interface PriceBookItemUpsert {
  name: string;
  unit?: string | null;
  unit_coverage?: string | null;
  unit_price?: string | null;
  tax_rate?: string;
  waste_rate?: string;
  supplier?: string | null;
  item_type?: string | null;
  sku?: string | null;
  knowify_item_id?: string | null;
}
export interface PriceBookVersion {
  id: number;
  supplier: string;
  version_number: number;
  label: string | null;
  config_hash: string;
  is_active: boolean;
  created_at: string | null;
}

export async function listPriceBookItems(): Promise<PriceBookItem[]> {
  const r = await apiFetch("/price-book/items");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function createPriceBookItem(body: PriceBookItemUpsert): Promise<PriceBookItem> {
  const r = await apiFetch("/price-book/items", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function updatePriceBookItem(id: number, body: PriceBookItemUpsert): Promise<PriceBookItem> {
  const r = await apiFetch(`/price-book/items/${id}`, { method: "PUT", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function listPriceBookVersions(): Promise<PriceBookVersion[]> {
  const r = await apiFetch("/price-book/versions");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function freezePriceBookVersion(
  body: { supplier?: string; label?: string; activate?: boolean },
): Promise<{ id: number; supplier: string; version_number: number; config_hash: string; is_active: boolean; item_count: number }> {
  const r = await apiFetch("/price-book/versions", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── JB3: Proposal generation (engine-driven) ─────────────────────────────────

export interface ProposalScopeInput {
  roof_system: string;            // "shingle" | "tile" | "flat" | "metal"
  tier?: string;                  // e.g. "PROTECTOR" | "COASTAL" | "PREMIUM_CARIBBEAN"
  squares?: string | null;
  description?: string;
  unit_price?: string | null;     // explicit $/sq override (bypasses table)
  is_optional?: boolean;          // excluded from contract_total unless included
  included?: boolean;             // accept an optional line into the total
}
export interface ProposalExtraLine {
  description: string;
  line_total?: string;            // explicit total
  unit_price?: string | null;
  qty?: string | null;
  is_optional?: boolean;
  included?: boolean;
  is_metal?: boolean;             // triggers 15-day expiry
}
export interface ProposalDiscount {
  description: string;
  amount?: string;                // positive dollars; billed negative (legacy amount path)
  discount_type?: "amount" | "percent";
  value?: string;                 // amount dollars or percent number, depending on discount_type
  percent?: string;               // accepted alias for percent rows
}
export interface ProposalGenInputs {
  customer: string;               // name
  property: string;               // address
  project_name?: string;
  hvhz?: boolean;
  payment_variant?: "standard" | "palmer";
  scopes: ProposalScopeInput[];
  extra_lines?: ProposalExtraLine[];
  discounts?: ProposalDiscount[];
}
export interface GenerateProposalResult {
  id: number;
  snapshot_hash: string;
  contract_total: string;
  expiry_days: number;
  proposal: Record<string, unknown>;
}
export async function generateProposal(body: {
  customer_id: number;
  property_id: number;
  inputs: ProposalGenInputs;
  date?: string;
  tenant_name?: string;
}): Promise<GenerateProposalResult> {
  const r = await apiFetch("/proposal-gen", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── JB4: Invoicing + payments (money path) ───────────────────────────────────

export interface InvoiceLine {
  line_type: string;
  description: string;
  milestone_pct: string | null;
  subtotal: string;
}
export interface Invoice {
  id: number;
  invoice_number: number | null;
  job_id: number;
  customer_id: number;
  status: string;                 // derived: sent|partial|paid|void|…
  invoice_date: string | null;
  due_date: string | null;
  milestone_pct: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  lines: InvoiceLine[];
  // new fields added in backend update
  customer_display_name: string | null;
  source: string | null;          // e.g. "native" | "knowify"
  knowify_invoice_number: string | null;
}
export interface InvoiceScopeInput {
  description: string;
  scope_value: string;            // per-scope CONTRACT value (Decimal string)
  scope_id?: number | null;
}
export interface IssueInvoiceRequest {
  job_id: number;
  customer_id: number;
  milestone_pct: string;          // fraction, e.g. "0.30"
  scopes: InvoiceScopeInput[];
  discounts?: ProposalDiscount[];
  proposal_id?: number | null;
  invoice_date?: string | null;
  due_date?: string | null;
  comments?: string | null;
}

export interface ListInvoicesParams {
  status?: string;
  customer_id?: number;
  source?: string;
  date_from?: string;
  date_to?: string;
  sort?: string;
  order?: "asc" | "desc";
  skip?: number;
  limit?: number;
  page?: number;
}

/** Returns bare array — backwards-compatible for existing callers (Invoices.tsx). */
export async function listInvoices(params?: ListInvoicesParams): Promise<Invoice[]> {
  const q = qs({ ...params });
  const r = await apiFetch(`/invoices${q}`);
  if (!r.ok) throw new Error(await errText(r));
  const data: Paged<Invoice> = await r.json();
  return data.items;
}

/** Paged variant for the new Invoices table (returns {items, total}). */
export async function listInvoicesPaged(params?: ListInvoicesParams): Promise<Paged<Invoice>> {
  const q = qs({ ...params });
  const r = await apiFetch(`/invoices${q}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function issueInvoice(body: IssueInvoiceRequest): Promise<Invoice> {
  const r = await apiFetch("/invoices", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function recordPayment(
  invoiceId: number,
  body: { amount: string; method?: string; reference?: string; notes?: string; idempotency_key?: string },
): Promise<{ invoice_id: number; status: string }> {
  const r = await apiFetch(`/invoices/${invoiceId}/payments`, { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** List all payments recorded against a single invoice. */
export async function listInvoicePayments(invoiceId: number): Promise<Payment[]> {
  const r = await apiFetch(`/invoices/${invoiceId}/payments`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Knowify mirror (Wave 6 — read-only sync health + data) ───────────────────

export interface KnowifySyncHealth {
  entity: string;
  last_status: string;          // never|ok|partial|error|auth_error|skipped
  last_run_at: string | null;
  last_high_water: string | null;
  rows_seen: number;
  last_error: string | null;
  updated_at: string | null;
}

export interface KnowifyCustomer {
  id: number;
  display_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  knowify_customer_id: string | null;
}

export interface KnowifyInvoice {
  id: number;
  invoice_number: number | null;
  knowify_invoice_id: string | null;
  knowify_invoice_number: string | null;   // Knowify user-facing string (may be non-numeric)
  job_id: number;
  customer_id: number;
  status: string;
  total: string | null;
  invoice_date: string | null;
  due_date: string | null;
}

export interface KnowifyPayment {
  id: number;
  invoice_id: number;
  knowify_payment_id: string | null;
  amount: string | null;
  method: string | null;
  reference: string | null;
  notes: string | null;
  payment_date: string | null;
}

export interface KnowifyRawRecord {
  id: number;
  knowify_id: string;
  content_hash: string;
  high_water: string | null;
  is_present: boolean;
  deleted_at: string | null;    // set when tombstoned (absent from last full pull)
  fetched_at: string | null;
}

export interface KnowifyRawPage {
  entity: string;
  total: number;
  offset: number;
  limit: number;
  items: KnowifyRawRecord[];
}

export interface KnowifySyncResult {
  triggered: boolean;
  status?: string;
  error?: string;
}

export interface KnowifyReconnectResult {
  status: string;
  instructions: string;
  oauth_server_status: string;
}

/** Per-entity sync health for the caller's tenant. Role: billing_manage. */
export async function getKnowifyStatus(): Promise<KnowifySyncHealth[]> {
  const r = await apiFetch("/knowify/status");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Tenant-scoped Knowify customers with crosswalk fields. Role: billing_manage. */
export async function listKnowifyCustomers(): Promise<KnowifyCustomer[]> {
  const r = await apiFetch("/knowify/customers");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Tenant-scoped invoices with Knowify crosswalk fields. Role: billing_manage. */
export async function listKnowifyInvoices(): Promise<KnowifyInvoice[]> {
  const r = await apiFetch("/knowify/invoices");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Tenant-scoped payments with Knowify crosswalk fields. Role: billing_manage. */
export async function listKnowifyPayments(): Promise<KnowifyPayment[]> {
  const r = await apiFetch("/knowify/payments");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Paged raw mirror records for any entity, including tombstoned rows. Role: billing_manage. */
export async function listKnowifyRaw(
  entity: string,
  opts: { limit?: number; offset?: number; is_present?: boolean } = {},
): Promise<KnowifyRawPage> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.is_present !== undefined) params.set("is_present", String(opts.is_present));
  const qs = params.toString() ? `?${params}` : "";
  const r = await apiFetch(`/knowify/raw/${encodeURIComponent(entity)}${qs}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Trigger an out-of-band Knowify sync run. Role: knowify_admin (admin-only). */
export async function triggerKnowifySync(): Promise<KnowifySyncResult> {
  const r = await apiFetch("/knowify/sync-now", { method: "POST" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

/** Surface Knowify OAuth reconnect status and operator instructions. Role: knowify_admin (admin-only). */
export async function knowifyReconnect(): Promise<KnowifyReconnectResult> {
  const r = await apiFetch("/knowify/reconnect", { method: "POST" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Payments (standalone router) ─────────────────────────────────────────────

export interface Payment {
  id: number;
  invoice_id: number | null;
  payment_date: string | null;
  amount: string;
  method: string | null;
  reference: string | null;
  notes: string | null;
  knowify_payment_id: string | null;
  created_at: string | null;
  invoice_number: number | null;
  knowify_invoice_number: string | null;
  customer_display_name: string | null;
  customer_id: number | null;
}

export interface ListPaymentsParams {
  search?: string;
  invoice_id?: number;
  method?: string;
  date_from?: string;
  date_to?: string;
  sort?: string;
  order?: "asc" | "desc";
  skip?: number;
  limit?: number;
  page?: number;
}

export async function listPayments(params?: ListPaymentsParams): Promise<Paged<Payment>> {
  const r = await apiFetch(`/payments${qs({ ...params })}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function getPayment(id: number): Promise<Payment> {
  const r = await apiFetch(`/payments/${id}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Legacy contracts / quotes ─────────────────────────────────────────────────

export interface QuoteLineItem {
  Id: string | null;
  ContractId: string | null;
  Description: string | null;
  Quantity: string | number | null;
  UnitName: string | null;
  UnitPrice: string | null;
  Price: string | null;
  PriceBilled: string | null;
  CostLabor: string | null;
  CostMaterials: string | null;
  ObjectState: string | null;
}

export interface QuoteListItem {
  contract_id: string;
  ContractType: string | null;
  BusinessState: string | null;
  ContractName: string | null;
  OriginalContractSum: string | null;
  CurrentContractSum: string | null;
  AdditionalContractSum: string | null;
  DepositAmount: string | null;
  ClientId: string | null;
  ProjectId: string | null;
  DateCreated: string | null;
  ExpirationDate: string | null;
  IsSigned: boolean | null;
  PONumber: string | null;
  ContactName: string | null;
}

export interface QuoteDetail extends QuoteListItem {
  line_items: QuoteLineItem[];
  project_address: {
    Id: string | null;
    Address1: string | null;
    City: string | null;
    StateProvince: string | null;
    Zip: string | null;
  } | null;
  _note: string;
}

export interface ListQuotesParams {
  search?: string;
  business_state?: string;
  client_id?: number;
  sort?: string;
  order?: "asc" | "desc";
  skip?: number;
  limit?: number;
  page?: number;
}

export async function listQuotes(params?: ListQuotesParams): Promise<Paged<QuoteListItem>> {
  const r = await apiFetch(`/quotes${qs({ ...params })}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function createProposalFromQuote(
  contractId: string,
  body: { customer_id?: number | null; property_id?: number | null; title?: string },
): Promise<Record<string, unknown>> {
  const r = await apiFetch(`/quoting/proposals/from-quote/${encodeURIComponent(contractId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function getQuote(id: string): Promise<QuoteDetail> {
  const r = await apiFetch(`/quotes/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Dashboard billing analytics ───────────────────────────────────────────────

export interface DashboardTimeSeries {
  period: string;
  total: string;
  count: number;
}

export interface DashboardAgingBuckets {
  current: string;
  d1_30: string;
  d31_60: string;
  d61_90: string;
  d90_plus: string;
}


export interface DashboardProposalFunnelPeriod {
  period: string;
  draft: number;
  sent: number;
  accepted: number;
  declined: number;
}

export interface DashboardProposalFunnel {
  draft: number;
  sent: number;
  viewed: number;
  accepted: number;
  declined: number;
  revision_requested: number;
  win_rate: number;
}

export interface DashboardBilling {
  payments_over_time: DashboardTimeSeries[];
  invoices_issued_over_time: DashboardTimeSeries[];
  open_ar_summary: {
    open_count: number;
    open_total: string;
    outstanding_total: string;
  };
  aging_buckets: DashboardAgingBuckets;
  receivables_due_next_30: {
    count: number;
    total: string;
  };
  proposal_funnel: DashboardProposalFunnel;
  proposal_funnel_over_time: DashboardProposalFunnelPeriod[];
}

export async function getDashboardBilling(params: {
  from?: string;
  to?: string;
  bucket?: string;
}): Promise<DashboardBilling> {
  const r = await apiFetch(`/dashboard/billing${qs(params)}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export interface AgingDetailRow {
  customer_id: number | null;
  customer_name: string | null;
  invoice_id: number;
  invoice_number: number | null;
  knowify_invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  status: string;
  total: string;
  paid: string;
  outstanding: string;
  days_past_due: number;
}

export interface AgingDetail {
  bucket: string;
  as_of: string;
  items: AgingDetailRow[];
}

/** Drill-down: open AR invoices/customers in one aging bucket. */
export async function getAgingDetail(bucket: string, asOf?: string): Promise<AgingDetail> {
  const r = await apiFetch(`/dashboard/billing/aging/${encodeURIComponent(bucket)}${qs({ as_of: asOf })}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Admin metrics ─────────────────────────────────────────────────────────────

export interface ActiveUserEntry {
  email: string | null;
  last_sign_in: string | null;
  disabled: boolean;
}

export interface ActiveUsersResponse {
  total_users: number;
  active_users: number;
  window_days: number;
  recent: ActiveUserEntry[];
  error?: string;
}

export interface SpendByService {
  service: string;
  cost: number;
}

export type GcpSpendResponse =
  | { configured: false; note: string }
  | { configured: true; total: number; currency: string; by_service: SpendByService[]; window_days: number; error?: string };

export async function getActiveUsers(params: { days?: number }): Promise<ActiveUsersResponse> {
  const r = await apiFetch(`/admin/metrics/active-users${qs(params)}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

export async function getGcpSpend(params: { days?: number }): Promise<GcpSpendResponse> {
  const r = await apiFetch(`/admin/metrics/gcp-spend${qs(params)}`);
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}

// ── Production readiness gates ──────────────────────────────────────────────

export type GateState = "ok" | "warn" | "blocker" | "unknown";

export interface ProductionGate {
  id: string;
  label: string;
  category: string;
  state: GateState;
  detail: string;
  remediation: string;
}

export interface ProductionReadinessSummary {
  ok: number;
  warn: number;
  blocker: number;
  total: number;
  ready: boolean;
}

export interface ProductionReadiness {
  gates: ProductionGate[];
  summary: ProductionReadinessSummary;
}

export async function getProductionReadiness(): Promise<ProductionReadiness> {
  const r = await apiFetch("/config/production-readiness");
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
