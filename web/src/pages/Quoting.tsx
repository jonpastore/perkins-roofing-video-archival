import { useEffect, useState } from "react";
import { apiFetch, listBranches, type BranchRow } from "../api";
import { BRAND, FONT, Button, Card, PageTitle, inputStyle, Loading, ErrorMsg, Badge, InitialsAvatar, PillButton, SectionLabel } from "../ui";
import { errText } from "../lib/errors";
import { CustomerFields, emptyCustomerFields, customerFieldsToInput, type CustomerFieldValues } from "../components/CustomerFields";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Customer {
  id: number;
  display_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
  branch: string | null;
  created_at: string | null;
}

interface Contact {
  id: number;
  customer_id: number;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
}

interface Property {
  id: number;
  customer_id: number;
  street: string;
  city: string;
  state: string;
  zip: string | null;
  county: string | null;
  code_zone: string;
  notes: string | null;
  gcs_pdf_prefix: string | null;
}

interface CustomerDetail extends Customer {
  contacts: Contact[];
  properties: Property[];
}

interface Measurement {
  id: number;
  property_id?: number | null;
  provider: string;
  status: string;
  total_sq: number | null;
  hips_lf: number | null;
  ridges_lf: number | null;
  valleys_lf: number | null;
  rakes_lf: number | null;
  eaves_lf: number | null;
  wall_flashings_lf: number | null;
  pitch_primary: number | null;
  provenance_note: string | null;
  created_at: string | null;
  created_by: string | null;
}

interface PackageOption {
  key: string;
  label: string;
  system: string;
  adder_per_sq: number | null;
  addl_price: number;
  total: number;
  standalone: boolean;
}

interface MarginInfo {
  profit_dollars: number;
  oh_dollars: number;
  eligible_base: number;
  profit_pct: number;
  combined_pct: number;
  profit_floor_ok: boolean;
  combined_floor_ok: boolean;
  margin_warnings: string[];
}

interface QuoteResult {
  region: string;
  branch?: string;
  pricing_config_hash?: string;
  floors?: { min_profit_pct: number; min_profit_plus_oh_pct: number };
  roof_type: string;
  num_squares: number;
  per_square_total: number;
  squares_subtotal: number;
  line_items_detail?: Array<{ key: string; label: string; amount: number; category: string; per_sq: number | null }>;
  project_fixed_costs: Record<string, number>;
  line_items: Record<string, number>;
  pm_incentive: number;
  project_total: number;
  pre_discount_total?: number;
  discount_total?: number;
  discounts?: Array<{ description: string; amount: string; discount_type?: string; value?: string }>;
  profit_dollars: number;
  profit_pct: number;
  estimated_commission: number;
  margin_ok: boolean;
  margin_warnings?: string[];
  margin?: MarginInfo;
  package_options?: PackageOption[];
  cut_calc?: {
    flat_base_per_sq: number;
    cut_base_per_sq: number;
    flat_project_total: number;
    cut_project_total: number;
    base_tile_brand?: string | null;
    warnings?: string[];
  };
  warnings?: string[];
  estimate_id?: number;
  estimate_version?: number;
  selected_tier?: "good" | "better" | "best";
}

interface EstimateRecord {
  id: number;
  version_number?: number;
  parent_id?: number | null;
  root_id?: number | null;
  source_proposal_id?: number | null;
  input_json: Record<string, unknown>;
  result_json: Partial<QuoteResult> & { project_total?: number };
  pricing_config_hash: string | null;
  created_at: string | null;
}

interface EstimateDiscountRow {
  key: number;
  description: string;
  discount_type: "amount" | "percent";
  value: string;
}

interface EstimatorRates {
  roof_types?: string[];
  sloped_roof_types?: string[];
  low_slope_roof_types?: string[];
  low_slope_pending?: boolean;
  daily_overhead_rates?: Record<string, number>;
  cut_calc_available?: boolean;
  tile_brands?: Record<string, string>;
  default_tile_brand?: string | null;
  low_slope?: {
    deck_types?: Record<string, number | null>;
    [k: string]: unknown;
  };
  repair?: {
    roof_types?: string[];
    daily_labor_rate?: { one_man?: number | null; two_man?: number | null };
  };
  scope_of_work?: { default_template?: string };
}

interface RepairQuoteResult {
  roof_type: string;
  days: number;
  crew_size: number;
  daily_labor_rate: number;
  labor_cost: number;
  material_cost: number;
  project_total: number;
  pricing_config_hash?: string;
  floors?: { min_profit_pct: number; min_profit_plus_oh_pct: number };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
}

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  padding: "8px 10px",
  fontSize: 13,
  cursor: "pointer",
  width: "100%",
};

const EXISTING_ROOF_OPTIONS: Array<{ value: "none" | "shingle" | "tile" | "metal" | "flat"; label: string }> = [
  { value: "none", label: "New construction" },
  { value: "shingle", label: "Shingle" },
  { value: "tile", label: "Tile" },
  { value: "metal", label: "Metal" },
  { value: "flat", label: "Flat" },
];

// Roof type -> the daily-overhead "install" series (the crew rate for putting the new roof on).
// The roof type is already chosen, so the builder asks for ONE "install days" number, not one per type.
// Low-slope/flat systems fall back to the demo/dry-in/flat daily rate.
const INSTALL_SERIES_BY_ROOF: Record<string, string> = {
  "13_tile": "tile", barrel_tile: "tile",
  standing_seam_metal: "metal",
  "3tab_shingle": "shingle", dimensional_shingle: "shingle",
  tpo: "demo_dry_in_flat", coatings: "demo_dry_in_flat", silicone: "demo_dry_in_flat", bur: "demo_dry_in_flat",
};

const GUTTER_STYLES: Array<{ value: string; label: string }> = [
  { value: "k6_alum", label: "6\" Alum K-Style" },
  { value: "k7_alum", label: "7\" Alum K-Style" },
  { value: "box6_comm", label: "6\" Commercial Box" },
  { value: "box7_comm", label: "7\" Commercial Box" },
  { value: "halfround_alum", label: "Half-Round Alum" },
  { value: "k6_copper", label: "6\" Copper K-Style" },
  { value: "k7_copper", label: "7\" Copper K-Style" },
  { value: "halfround_copper", label: "Copper Half-Round" },
];

// Only these styles have a two_story_per_lf rate in the pricing config; the rest 422
// on gutter_two_story:true. Hardcoded client-side since config isn't fetched per-style.
const TWO_STORY_GUTTER_STYLES = new Set(["k6_alum", "k7_alum"]);

let estimateDiscountKey = 0;
function newEstimateDiscount(): EstimateDiscountRow {
  estimateDiscountKey += 1;
  return { key: estimateDiscountKey, description: "", discount_type: "amount", value: "" };
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: BRAND.sub, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>
      {children}
    </label>
  );
}

function ResultRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      padding: "5px 0",
      borderBottom: `1px solid ${BRAND.border}`,
      fontSize: 13,
      fontWeight: bold ? 700 : 400,
      color: bold ? BRAND.navyText : BRAND.ink,
    }}>
      <span>{label}</span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

function EstimateCheckbox({
  checked,
  onChange,
  label,
  disabled,
  title,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <label title={title} style={{
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontSize: 13,
      fontWeight: 500,
      color: disabled ? BRAND.sub : BRAND.ink,
      minHeight: 38,
      lineHeight: 1.3,
      cursor: disabled ? "not-allowed" : "pointer",
      whiteSpace: "normal",
    }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 15, height: 15, flexShrink: 0, accentColor: BRAND.red }}
      />
      <span>{label}</span>
    </label>
  );
}

// ── Sub-views ─────────────────────────────────────────────────────────────────

function CustomerForm({
  initial,
  onSave,
  onCancel,
  saving,
  branches,
}: {
  initial?: Partial<Customer>;
  onSave: (data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes" | "branch">) => void;
  onCancel: () => void;
  saving: boolean;
  branches: BranchRow[];
}) {
  const [v, setV] = useState<CustomerFieldValues>(emptyCustomerFields(initial));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <CustomerFields value={v} onChange={(p) => setV((s) => ({ ...s, ...p }))} branches={branches} />
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={() => onSave(customerFieldsToInput(v))} disabled={saving || !v.display_name.trim()} style={{ fontSize: 13 }}>
          {saving ? "Saving…" : "Save customer"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

function PropertyForm({
  onSave,
  onCancel,
  saving,
}: {
  onSave: (data: Partial<Property>) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("FL");
  const [zip, setZip] = useState("");
  const [county, setCounty] = useState("");
  const [codeZone, setCodeZone] = useState("FBC");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ gridColumn: "1 / -1" }}>
          <FieldLabel>Street *</FieldLabel>
          <input value={street} onChange={(e) => setStreet(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="123 Main St" />
        </div>
        <div>
          <FieldLabel>City</FieldLabel>
          <input value={city} onChange={(e) => setCity(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div>
          <FieldLabel>State</FieldLabel>
          <input value={state} onChange={(e) => setState(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div>
          <FieldLabel>ZIP</FieldLabel>
          <input value={zip} onChange={(e) => setZip(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div>
          <FieldLabel>County</FieldLabel>
          <input value={county} onChange={(e) => setCounty(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div>
          <FieldLabel>Code Zone</FieldLabel>
          <select value={codeZone} onChange={(e) => setCodeZone(e.target.value)} style={selectStyle}>
            <option value="FBC">FBC</option>
            <option value="HVHZ">HVHZ</option>
          </select>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={() => onSave({ street, city, state, zip, county, code_zone: codeZone })} disabled={saving || !street.trim()} style={{ fontSize: 13 }}>
          {saving ? "Saving…" : "Save property"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

function ContactForm({
  onSave,
  onCancel,
  saving,
}: {
  onSave: (data: Pick<Contact, "name" | "role" | "email" | "phone" | "is_primary">) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <FieldLabel>Name *</FieldLabel>
          <input value={name} onChange={(e) => setName(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="Contact name" />
        </div>
        <div>
          <FieldLabel>Role</FieldLabel>
          <input value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="Owner, PM, board member…" />
        </div>
        <div>
          <FieldLabel>Email</FieldLabel>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div>
          <FieldLabel>Phone</FieldLabel>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <label style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: BRAND.ink }}>
          <input type="checkbox" checked={isPrimary} onChange={(e) => setIsPrimary(e.target.checked)} />
          Set as primary contact
        </label>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          onClick={() => onSave({ name, role: role || null, email: email || null, phone: phone || null, is_primary: isPrimary })}
          disabled={saving || !name.trim()}
          style={{ fontSize: 13 }}
        >
          {saving ? "Saving…" : "Save contact"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

function MeasurementForm({
  onSave,
  onCancel,
  saving,
}: {
  onSave: (data: Omit<Measurement, "id" | "provider" | "status" | "created_at" | "created_by" | "confidence">) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [totalSq, setTotalSq] = useState("");
  const [hipsLf, setHipsLf] = useState("");
  const [ridgesLf, setRidgesLf] = useState("");
  const [valleysLf, setValleysLf] = useState("");
  const [rakesLf, setRakesLf] = useState("");
  const [eavesLf, setEavesLf] = useState("");
  const [wallFlashingsLf, setWallFlashingsLf] = useState("");
  const [pitchPrimary, setPitchPrimary] = useState("");
  const [provenanceNote, setProvenanceNote] = useState("");

  function num(s: string): number | null {
    const v = parseFloat(s);
    return isNaN(v) ? null : v;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <div>
          <FieldLabel>Total Squares</FieldLabel>
          <input type="number" min="0" step="0.5" value={totalSq} onChange={(e) => setTotalSq(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="e.g. 28.5" />
        </div>
        <div>
          <FieldLabel>Hips (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={hipsLf} onChange={(e) => setHipsLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Ridges (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={ridgesLf} onChange={(e) => setRidgesLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Valleys (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={valleysLf} onChange={(e) => setValleysLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Rakes (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={rakesLf} onChange={(e) => setRakesLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Eaves (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={eavesLf} onChange={(e) => setEavesLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Wall Flashings (LF)</FieldLabel>
          <input type="number" min="0" step="1" value={wallFlashingsLf} onChange={(e) => setWallFlashingsLf(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="0" />
        </div>
        <div>
          <FieldLabel>Primary Pitch</FieldLabel>
          <input type="number" min="0" step="0.5" value={pitchPrimary} onChange={(e) => setPitchPrimary(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="e.g. 4.5" />
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <FieldLabel>Provenance Note</FieldLabel>
          <input value={provenanceNote} onChange={(e) => setProvenanceNote(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="e.g. EagleView report, field measure…" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          onClick={() => onSave({
            total_sq: num(totalSq),
            hips_lf: num(hipsLf),
            ridges_lf: num(ridgesLf),
            valleys_lf: num(valleysLf),
            rakes_lf: num(rakesLf),
            eaves_lf: num(eavesLf),
            wall_flashings_lf: num(wallFlashingsLf),
            pitch_primary: num(pitchPrimary),
            provenance_note: provenanceNote || null,
          })}
          disabled={saving}
          style={{ fontSize: 13 }}
        >
          {saving ? "Saving…" : "Save measurement"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type QuotingView = "customers" | "customer_detail" | "quote_builder";

// Canonical sales workflow presented on the Estimates page. Kept as data so the
// same ordered steps drive both the intro callout and the builder stepper.
const ESTIMATE_FLOW_STEPS = ["Customer", "Property", "Measurement", "Estimate", "Proposal"] as const;

function WorkflowCallout() {
  return (
    <Card style={{ marginBottom: 16, padding: "14px 18px", background: BRAND.bg, border: `1px solid ${BRAND.border}` }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 13, marginBottom: 6 }}>
        Estimates workflow
      </div>
      <p style={{ margin: "0 0 10px", fontSize: 13, color: BRAND.sub, lineHeight: 1.5 }}>
        This is the canonical path for building a customer-linked estimate. Work left to right:
        pick a <strong>customer</strong>, attach a <strong>property</strong>, record a{" "}
        <strong>measurement</strong>, then generate the <strong>estimate</strong> that becomes a{" "}
        <strong>proposal</strong>.
      </p>
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
        {ESTIMATE_FLOW_STEPS.map((step, i) => (
          <div key={step} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              fontSize: 12, fontWeight: 600, color: BRAND.navyText,
              background: "#fff", border: `1px solid ${BRAND.border}`, borderRadius: 20, padding: "3px 10px",
            }}>
              <span style={{
                width: 16, height: 16, borderRadius: "50%", background: BRAND.navy, color: "#fff",
                display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 700,
              }}>{i + 1}</span>
              {step}
            </span>
            {i < ESTIMATE_FLOW_STEPS.length - 1 && (
              <span style={{ color: BRAND.sub, fontSize: 12 }}>→</span>
            )}
          </div>
        ))}
      </div>
      <p style={{ margin: "10px 0 0", fontSize: 11, color: BRAND.sub, lineHeight: 1.5 }}>
        Build every estimate you intend to send here so it stays linked to a customer, property, and
        measurement.
      </p>
    </Card>
  );
}

export function Quoting() {
  const [view, setView] = useState<QuotingView>("customers");

  // Customer list
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(false);
  const [customersError, setCustomersError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showNewCustomer, setShowNewCustomer] = useState(false);
  const [savingCustomer, setSavingCustomer] = useState(false);
  const [customerFormError, setCustomerFormError] = useState<string | null>(null);
  const [branches, setBranches] = useState<BranchRow[]>([]);

  // Customer detail
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerDetail | null>(null);
  const [customerDetailLoading, setCustomerDetailLoading] = useState(false);
  const [customerDetailError, setCustomerDetailError] = useState<string | null>(null);
  const [editingCustomer, setEditingCustomer] = useState(false);
  const [savingCustomerEdit, setSavingCustomerEdit] = useState(false);
  const [showNewProperty, setShowNewProperty] = useState(false);
  const [savingProperty, setSavingProperty] = useState(false);
  const [propertyError, setPropertyError] = useState<string | null>(null);
  const [showNewContact, setShowNewContact] = useState(false);
  const [savingContact, setSavingContact] = useState(false);
  const [contactError, setContactError] = useState<string | null>(null);

  // Measurements
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [measurementsLoading, setMeasurementsLoading] = useState(false);
  const [showNewMeasurement, setShowNewMeasurement] = useState(false);
  const [savingMeasurement, setSavingMeasurement] = useState(false);
  const [measurementError, setMeasurementError] = useState<string | null>(null);

  // Quote builder
  const [selectedMeasurement, setSelectedMeasurement] = useState<Measurement | null>(null);
  const [estimateHistory, setEstimateHistory] = useState<EstimateRecord[]>([]);
  const [estimatesLoading, setEstimatesLoading] = useState(false);
  const [quoteRegion, setQuoteRegion] = useState<"FBC" | "HVHZ">("FBC");
  const [quoteRoofType, setQuoteRoofType] = useState("dimensional_shingle");
  const [rates, setRates] = useState<EstimatorRates | null>(null);
  const [ratesError, setRatesError] = useState<string | null>(null);
  const [quoteRoofCuts, setQuoteRoofCuts] = useState<"low" | "medium" | "high">("low");
  const [baseTileBrand, setBaseTileBrand] = useState<string>("");
  const [quoteRoofHeight, setQuoteRoofHeight] = useState<"1_story" | "2_stories" | "3_5_stories">("1_story");
  const [quoteExistingRoof, setQuoteExistingRoof] = useState<"none" | "shingle" | "tile" | "metal" | "flat">("none");
  const [quoteLayersToRemove, setQuoteLayersToRemove] = useState("0");
  // Low-slope builder inputs (deck/attach system + insulation/tapered) — only sent when the
  // selected roof_type is a low-slope system. Default deck = existing_concrete ($0 adder).
  const [quoteDeckType, setQuoteDeckType] = useState("existing_concrete");
  const [quoteIncludeInsulation, setQuoteIncludeInsulation] = useState(false);
  const [quoteIncludeTapered, setQuoteIncludeTapered] = useState(false);
  const [quoteSecondaryWater, setQuoteSecondaryWater] = useState(false);
  const [quoteWinterguard, setQuoteWinterguard] = useState(false);
  const [quoteStuccoMetalLf, setQuoteStuccoMetalLf] = useState("");
  const [quotePenetrations, setQuotePenetrations] = useState("");
  const [quoteRidgeVentLf, setQuoteRidgeVentLf] = useState("");
  const [quoteGutterStyle, setQuoteGutterStyle] = useState(GUTTER_STYLES[0].value);
  const [quoteGutterLf, setQuoteGutterLf] = useState("");
  const [quoteGutterTwoStory, setQuoteGutterTwoStory] = useState(false);
  const [quoteGutterElbows, setQuoteGutterElbows] = useState("");
  const [quoteGutterRemovalLf, setQuoteGutterRemovalLf] = useState("");
  const [quoteDownspoutLf, setQuoteDownspoutLf] = useState("");
  const [quoteLeafGuard, setQuoteLeafGuard] = useState<"none" | "std" | "upgraded">("none");
  const [quoteLeaderheadsRes, setQuoteLeaderheadsRes] = useState("");
  const [quoteLeaderheadsComm, setQuoteLeaderheadsComm] = useState("");
  const [quoteOverheadMode, setQuoteOverheadMode] = useState<"per_sq" | "daily">("per_sq");
  const [quoteDemoDays, setQuoteDemoDays] = useState("");
  const [quoteInstallDays, setQuoteInstallDays] = useState("");
  const [targetProfitPct, setTargetProfitPct] = useState("");
  const [targetProfitMinDollars, setTargetProfitMinDollars] = useState("");
  const [activeProfitPreset, setActiveProfitPreset] = useState<number | null>(null);
  const [commissionBasis, setCommissionBasis] = useState<"profit" | "job">("profit");
  const [commissionRate, setCommissionRate] = useState("30");  // percent; default 30% of profit / 10% of job
  const [recommendedTier, setRecommendedTier] = useState<"good" | "better" | "best">("good");
  const [estimateDiscounts, setEstimateDiscounts] = useState<EstimateDiscountRow[]>([]);
  const [quoteResult, setQuoteResult] = useState<QuoteResult | null>(null);
  const [inputsDirty, setInputsDirty] = useState(false);
  const [lastQuoteInput, setLastQuoteInput] = useState<Record<string, unknown> | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [creatingProposal, setCreatingProposal] = useState(false);
  const [proposalCreated, setProposalCreated] = useState<{ id: number } | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);

  // Repair vs re-roof mode (Zoom 2026-07-20 [41:04])
  const [jobMode, setJobMode] = useState<"reroof" | "repair">("reroof");

  // Repair quote (time-based — alternative to full replacement, Zoom 2026-07-20 [37:04]/[45:31])
  const [repairRoofType, setRepairRoofType] = useState<"shingle" | "tile" | "metal" | "flat">("shingle");
  const [repairDays, setRepairDays] = useState("");
  const [repairCrewSize, setRepairCrewSize] = useState<1 | 2>(1);
  const [repairMaterialCost, setRepairMaterialCost] = useState("");
  const [repairResult, setRepairResult] = useState<RepairQuoteResult | null>(null);
  const [repairQuoting, setRepairQuoting] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [creatingRepairProposal, setCreatingRepairProposal] = useState(false);
  const [repairProposalCreated, setRepairProposalCreated] = useState<{ id: number } | null>(null);
  const [repairProposalError, setRepairProposalError] = useState<string | null>(null);

  // Scope of work (Zoom 2026-07-20 [42:06]/[44:12]) — shared by both modes.
  const [scopeOfWork, setScopeOfWork] = useState("");
  const [scopeOfWorkPrefilled, setScopeOfWorkPrefilled] = useState(false);
  const [scopeInstruction, setScopeInstruction] = useState("");
  const [scopeRewriting, setScopeRewriting] = useState(false);
  const [scopeRewriteError, setScopeRewriteError] = useState<string | null>(null);

  // Selected property for proposal creation
  const [selectedPropertyId, setSelectedPropertyId] = useState<number | null>(null);

  const roofTypeLabels: Record<string, string> = {
    "13_tile": "13\" Flat Tile",
    barrel_tile: "Barrel Tile",
    "3tab_shingle": "3-Tab Shingle",
    dimensional_shingle: "Dimensional Shingle",
    standing_seam_metal: "Standing Seam Metal",
    tpo: "TPO (Low-slope)",
    coatings: "Coatings (Low-slope)",
    silicone: "Silicone (Low-slope)",
    bur: "BUR / Modified Bitumen (Low-slope)",
  };
  const defaultSlopedRoofTypes = [
    { value: "13_tile", label: "13\" Flat Tile" },
    { value: "barrel_tile", label: "Barrel Tile" },
    { value: "3tab_shingle", label: "3-Tab Shingle" },
    { value: "dimensional_shingle", label: "Dimensional Shingle" },
    { value: "standing_seam_metal", label: "Standing Seam Metal" },
  ];
  const lowSlopeTypes = rates?.low_slope_roof_types ?? [];
  const roofTypes = rates?.roof_types?.length
    ? rates.roof_types.map((value) => ({ value, label: roofTypeLabels[value] ?? value.replace(/_/g, " ") }))
    : defaultSlopedRoofTypes;
  const isLowSlopeRoofType = lowSlopeTypes.includes(quoteRoofType);

  function labelRoofType(key: string): string {
    return roofTypeLabels[key] ?? roofTypes.find((r) => r.value === key)?.label ?? key.replace(/_/g, " ");
  }

  function tierTotalsForQuote(q: QuoteResult): { good: number; better: number; best: number } {
    // good/better/best snapshot compat, derived from the real package_options menu:
    // good=PROTECTOR (engine total), better=PREFERRED, best=highest-total PREMIUM* tier
    // (falls back to PREFERRED's total when the system has no PREMIUM tier).
    const options = q.package_options ?? [];
    const protector = options.find((o) => o.key === "PROTECTOR")?.total ?? q.project_total;
    const preferred = options.find((o) => o.key === "PREFERRED")?.total ?? protector;
    const premiumOptions = options.filter((o) => o.key.startsWith("PREMIUM"));
    const premium = premiumOptions.length
      ? Math.max(...premiumOptions.map((o) => o.total))
      : preferred;
    return { good: protector, better: preferred, best: premium };
  }

  function loadCustomers(searchTerm = "") {
    setCustomersLoading(true);
    setCustomersError(null);
    const params = new URLSearchParams({ limit: "50" });
    const q = searchTerm.trim();
    if (q) params.set("search", q);
    apiFetch(`/quoting/customers?${params.toString()}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: Customer[] | { items?: Customer[] }) => {
        const rows = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
        setCustomers(rows);
      })
      .catch((e: unknown) => setCustomersError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCustomersLoading(false));
  }

  useEffect(() => {
    const timer = window.setTimeout(() => loadCustomers(search), search.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => { listBranches().then(setBranches).catch(() => undefined); }, []);

  useEffect(() => {
    setRatesError(null);
    apiFetch(`/estimator/rates?branch=${selectedCustomer?.branch || "miami"}&region=${quoteRegion}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: EstimatorRates) => setRates(data))
      .catch((e: unknown) => setRatesError(e instanceof Error ? e.message : String(e)));
  }, [quoteRegion, selectedCustomer?.branch]);

  // Pre-fill scope-of-work from the config template exactly once, so it never clobbers edits.
  useEffect(() => {
    if (scopeOfWorkPrefilled) return;
    const template = rates?.scope_of_work?.default_template;
    if (template) {
      setScopeOfWork(template);
      setScopeOfWorkPrefilled(true);
    }
  }, [rates, scopeOfWorkPrefilled]);

  function loadCustomerDetail(id: number) {
    setCustomerDetailLoading(true);
    setCustomerDetailError(null);
    apiFetch(`/quoting/customers/${id}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: CustomerDetail) => {
        setSelectedCustomer(data);
        const props = data.properties ?? [];
        if (props.length > 0) {
          setSelectedPropertyId(props[0].id);
          setQuoteRegion(props[0].code_zone?.toUpperCase().includes("HVHZ") ? "HVHZ" : "FBC");
        } else setSelectedPropertyId(null);
      })
      .catch((e: unknown) => setCustomerDetailError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCustomerDetailLoading(false));
  }

  async function handleCreateCustomer(data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes" | "branch">) {
    setSavingCustomer(true);
    setCustomerFormError(null);
    try {
      const r = await apiFetch("/quoting/customers", { method: "POST", body: JSON.stringify(data) });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const created: Customer = await r.json();
      setCustomers((prev) => [...prev, created].sort((a, b) => a.display_name.localeCompare(b.display_name)));
      setShowNewCustomer(false);
    } catch (e: unknown) {
      setCustomerFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingCustomer(false);
    }
  }

  async function handleUpdateCustomer(data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes" | "branch">) {
    if (!selectedCustomer) return;
    setSavingCustomerEdit(true);
    try {
      const r = await apiFetch(`/quoting/customers/${selectedCustomer.id}`, {
        method: "PUT",
        body: JSON.stringify({ display_name: data.display_name, company_name: data.company_name, email: data.email, phone: data.phone, notes: data.notes, branch: data.branch }),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const updated: Customer = await r.json();
      setSelectedCustomer((prev) => prev ? { ...prev, ...updated } : prev);
      setCustomers((prev) => prev.map((c) => c.id === updated.id ? { ...c, ...updated } : c));
      setEditingCustomer(false);
    } catch (e: unknown) {
      setCustomerDetailError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingCustomerEdit(false);
    }
  }

  function openCustomer(c: Customer) {
    setView("customer_detail");
    setShowNewCustomer(false);
    setMeasurements([]);
    setSelectedMeasurement(null);
    setQuoteResult(null);
    setProposalCreated(null);
    setEditingCustomer(false);
    setShowNewContact(false);
    setContactError(null);
    loadCustomerDetail(c.id);
  }


  function loadMeasurementsForProperty(propertyId: number | null) {
    if (!propertyId) {
      setMeasurements([]);
      setSelectedMeasurement(null);
      return;
    }
    setMeasurementsLoading(true);
    setMeasurementError(null);
    apiFetch(`/measurements?property_id=${propertyId}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((rows: Measurement[]) => {
        const list = Array.isArray(rows) ? rows : [];
        setMeasurements(list);
        // Auto-load the measurement by default when there's only one to choose from.
        setSelectedMeasurement(list.length === 1 ? list[0] : null);
      })
      .catch((e: unknown) => setMeasurementError(e instanceof Error ? e.message : String(e)))
      .finally(() => setMeasurementsLoading(false));
  }

  useEffect(() => {
    if (view === "customer_detail" || view === "quote_builder") {
      loadMeasurementsForProperty(selectedPropertyId);
    }
  }, [selectedPropertyId, view]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSelectProperty(id: number) {
    setSelectedPropertyId(id);
    setShowNewMeasurement(false);
    setQuoteResult(null);
    setProposalCreated(null);
    const prop = selectedCustomer?.properties?.find((p) => p.id === id);
    if (prop?.code_zone?.toUpperCase().includes("HVHZ")) setQuoteRegion("HVHZ");
    else if (prop) setQuoteRegion("FBC");
  }

  async function handleAddProperty(data: Partial<Property>) {
    if (!selectedCustomer) return;
    setSavingProperty(true);
    setPropertyError(null);
    try {
      const r = await apiFetch(`/quoting/customers/${selectedCustomer.id}/properties`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const prop: Property = await r.json();
      setSelectedCustomer((prev) => prev ? { ...prev, properties: [...(prev.properties ?? []), prop] } : prev);
      setSelectedPropertyId(prop.id);
      setShowNewProperty(false);
    } catch (e: unknown) {
      setPropertyError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingProperty(false);
    }
  }

  async function handleAddContact(data: Pick<Contact, "name" | "role" | "email" | "phone" | "is_primary">) {
    if (!selectedCustomer) return;
    setSavingContact(true);
    setContactError(null);
    try {
      const r = await apiFetch(`/quoting/customers/${selectedCustomer.id}/contacts`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const contact: Contact = await r.json();
      setSelectedCustomer((prev) => prev ? {
        ...prev,
        contacts: [
          ...(contact.is_primary ? prev.contacts.map((c) => ({ ...c, is_primary: false })) : prev.contacts),
          contact,
        ],
      } : prev);
      setShowNewContact(false);
    } catch (e: unknown) {
      setContactError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingContact(false);
    }
  }

  async function handleSetPrimaryContact(contactId: number) {
    setContactError(null);
    try {
      const r = await apiFetch(`/quoting/contacts/${contactId}`, {
        method: "PUT",
        body: JSON.stringify({ is_primary: true }),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const updated: Contact = await r.json();
      setSelectedCustomer((prev) => prev ? {
        ...prev,
        contacts: prev.contacts.map((c) => ({ ...c, is_primary: c.id === updated.id })),
      } : prev);
    } catch (e: unknown) {
      setContactError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleAddMeasurement(data: Omit<Measurement, "id" | "provider" | "status" | "created_at" | "created_by" | "confidence">) {
    setSavingMeasurement(true);
    setMeasurementError(null);
    try {
      const r = await apiFetch("/measurements", { method: "POST", body: JSON.stringify({ ...data, property_id: selectedPropertyId }) });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const m: Measurement = await r.json();
      setMeasurements((prev) => [m, ...prev.filter((row) => row.id !== m.id)]);
      setSelectedMeasurement(m);
      setShowNewMeasurement(false);
    } catch (e: unknown) {
      setMeasurementError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingMeasurement(false);
    }
  }


  function loadEstimatesForMeasurement(measurementId: number | null) {
    if (!measurementId) {
      setEstimateHistory([]);
      return;
    }
    setEstimatesLoading(true);
    apiFetch(`/estimator/estimates?measurement_id=${measurementId}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((rows: EstimateRecord[]) => setEstimateHistory(Array.isArray(rows) ? rows : []))
      .catch(() => setEstimateHistory([]))
      .finally(() => setEstimatesLoading(false));
  }

  useEffect(() => {
    loadEstimatesForMeasurement(selectedMeasurement?.id ?? null);
  }, [selectedMeasurement?.id]);

  useEffect(() => {
    if (!selectedMeasurement?.pitch_primary) return;
    const pitch = Number(selectedMeasurement.pitch_primary);
    if (pitch <= 2 && lowSlopeTypes.length > 0 && !lowSlopeTypes.includes(quoteRoofType)) {
      setQuoteRoofType(lowSlopeTypes[0]);
    }
  }, [selectedMeasurement?.pitch_primary, lowSlopeTypes.join(","), quoteRoofType]);

  // Prefill estimate inputs the measurement can unambiguously provide. Only fills fields
  // still blank (never overwrites a value the user already typed). num_squares is derived
  // straight from selectedMeasurement.total_sq in buildQuoteBody, so it needs no prefill here.
  useEffect(() => {
    if (!selectedMeasurement) return;
    if (selectedMeasurement.ridges_lf != null) {
      setQuoteRidgeVentLf((prev) => (prev === "" ? String(selectedMeasurement.ridges_lf) : prev));
    }
    if (selectedMeasurement.eaves_lf != null) {
      setQuoteGutterLf((prev) => (prev === "" ? String(selectedMeasurement.eaves_lf) : prev));
    }
  }, [selectedMeasurement?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function buildQuoteBody(overrides: Record<string, unknown> = {}): Record<string, unknown> | null {
    if (!selectedMeasurement?.total_sq) return null;
    // Build daily series from two inputs: demo days (tear-off rate) + install days (roof-type rate).
    // If both map to the same series (flat roofs), sum them.
    const demoD = Number(quoteDemoDays || 0);
    const installD = Number(quoteInstallDays || 0);
    const installSeries = INSTALL_SERIES_BY_ROOF[quoteRoofType] ?? "demo_dry_in_flat";
    const dailyMap: Record<string, number> = {};
    if (demoD > 0) dailyMap["demo_dry_in_flat"] = (dailyMap["demo_dry_in_flat"] ?? 0) + demoD;
    if (installD > 0) dailyMap[installSeries] = (dailyMap[installSeries] ?? 0) + installD;
    const dailySeries = Object.entries(dailyMap).map(([series, days]) => ({ series, days }));
    return {
      branch: selectedCustomer?.branch || "miami",
      code_zone: quoteRegion,
      roof_type: quoteRoofType,
      slope_type: isLowSlopeRoofType ? "low_slope" : "sloped",
      num_squares: selectedMeasurement.total_sq,
      measurement_id: selectedMeasurement.id,
      project_kind: "residential",
      roof_cuts: quoteRoofCuts,
      base_tile_brand: baseTileBrand || undefined,
      roof_height: quoteRoofHeight,
      tile_pointing: "no",
      pitch_7_12: false,
      existing_roof: quoteExistingRoof,
      demo: quoteExistingRoof !== "none",
      layers_to_remove: Number(quoteLayersToRemove || 0),
      deck_type: isLowSlopeRoofType ? quoteDeckType : undefined,
      include_insulation: isLowSlopeRoofType ? quoteIncludeInsulation : false,
      include_tapered: isLowSlopeRoofType ? quoteIncludeTapered : false,
      secondary_water_barrier: quoteSecondaryWater,
      winterguard: quoteWinterguard,
      stucco_metal_lf: Number(quoteStuccoMetalLf || 0),
      penetrations: Number(quotePenetrations || 0),
      ridge_vent_lf: Number(quoteRidgeVentLf || 0),
      gutter_style: quoteGutterStyle,
      gutter_lf: Number(quoteGutterLf || 0),
      gutter_two_story: quoteGutterTwoStory,
      gutter_elbows: Number(quoteGutterElbows || 0),
      gutter_removal_lf: Number(quoteGutterRemovalLf || 0),
      downspout_lf: Number(quoteDownspoutLf || 0),
      leaf_guard: quoteLeafGuard,
      leaderheads_res: Number(quoteLeaderheadsRes || 0),
      leaderheads_comm: Number(quoteLeaderheadsComm || 0),
      overhead_mode: quoteOverheadMode,
      daily_series: quoteOverheadMode === "daily" ? dailySeries : [],
      profit_mode: "scale",
      commission_basis: commissionBasis,
      commission_rate: Number(commissionRate || 0) / 100,
      selected_tier: recommendedTier,
      discounts: estimateDiscounts
        .filter((d) => d.description.trim() && d.value.trim())
        .map((d) => ({
          description: d.description.trim(),
          discount_type: d.discount_type,
          value: Number(d.value || 0),
          ...(d.discount_type === "amount" ? { amount: Number(d.value || 0) } : {}),
          ...(d.discount_type === "percent" ? { percent: Number(d.value || 0) } : {}),
        })),
      ...overrides,
    };
  }

  async function runQuote(overrides: Record<string, unknown> = {}) {
    const body = buildQuoteBody(overrides);
    if (!body) {
      setQuoteError("Select a measurement with total squares filled in.");
      return;
    }
    setQuoting(true);
    setQuoteError(null);
    setQuoteResult(null);
    setProposalCreated(null);
    try {
      setLastQuoteInput(body);
      const r = await apiFetch("/estimator/quote", { method: "POST", body: JSON.stringify(body) });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const data: QuoteResult = await r.json();
      setQuoteResult(data);
      setInputsDirty(false);
      loadEstimatesForMeasurement(selectedMeasurement!.id);
    } catch (e: unknown) {
      setQuoteError(e instanceof Error ? e.message : String(e));
    } finally {
      setQuoting(false);
    }
  }

  function handleCalculateQuote() {
    setActiveProfitPreset(null);
    return runQuote();
  }

  async function runRepairQuote() {
    const days = Number(repairDays || 0);
    if (!days || days <= 0) {
      setRepairError("Enter the number of days for this repair.");
      return;
    }
    setRepairQuoting(true);
    setRepairError(null);
    setRepairResult(null);
    try {
      const r = await apiFetch("/estimator/repair-quote", {
        method: "POST",
        body: JSON.stringify({
          branch: selectedCustomer?.branch || "miami",
          roof_type: repairRoofType,
          days,
          crew_size: repairCrewSize,
          material_cost: Number(repairMaterialCost || 0),
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const data: RepairQuoteResult = await r.json();
      setRepairResult(data);
    } catch (e: unknown) {
      setRepairError(e instanceof Error ? e.message : String(e));
    } finally {
      setRepairQuoting(false);
    }
  }

  async function handleRewriteScope() {
    if (!scopeInstruction.trim()) return;
    setScopeRewriting(true);
    setScopeRewriteError(null);
    try {
      const r = await apiFetch("/estimator/scope-of-work/rewrite", {
        method: "POST",
        body: JSON.stringify({
          template: scopeOfWork,
          instruction: scopeInstruction,
          job_context: { mode: jobMode, roof_type: jobMode === "repair" ? repairRoofType : quoteRoofType, branch: selectedCustomer?.branch || "miami" },
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const data: { text: string } = await r.json();
      setScopeOfWork(data.text);
    } catch (e: unknown) {
      setScopeRewriteError(e instanceof Error ? e.message : String(e));
    } finally {
      setScopeRewriting(false);
    }
  }

  // Any change to an estimate input (reuses buildQuoteBody as the single source of
  // truth for "what counts as an input") marks the last quote stale; runQuote clears it.
  const quoteBodyKey = JSON.stringify(buildQuoteBody());
  useEffect(() => { setInputsDirty(true); }, [quoteBodyKey]);

  async function applyTargetProfit(pct: number) {
    if (!quoteResult?.margin || !Number.isFinite(pct) || pct <= 0) return;
    setActiveProfitPreset(pct);
    setTargetProfitPct(String(pct));
    const minDollars = Number(targetProfitMinDollars || 0);
    const flatProfitDollars = Math.max((pct / 100) * quoteResult.margin.eligible_base, minDollars);
    await runQuote({ profit_mode: "flat", flat_profit_dollars: flatProfitDollars });
  }

  async function handleCreateProposal() {
    if (!selectedCustomer || !quoteResult || !selectedPropertyId) {
      setProposalError("Need a customer, property, and calculated quote to create a proposal.");
      return;
    }
    setCreatingProposal(true);
    setProposalError(null);

    const { good: goodTotal, better: betterTotal, best: bestTotal } = tierTotalsForQuote(quoteResult);
    const selectedTotal = recommendedTier === "best" ? bestTotal : recommendedTier === "better" ? betterTotal : goodTotal;
    const snapshot = {
      estimate_id: quoteResult.estimate_id ?? null,
      estimate_version: quoteResult.estimate_version ?? null,
      estimate_input: lastQuoteInput,
      recommended_tier: recommendedTier,
      selected_tier_default: recommendedTier,
      total: selectedTotal,
      estimate_result: quoteResult,
      region: quoteResult.region,
      code_zone: quoteResult.region,
      roof_type: quoteResult.roof_type,
      num_squares: quoteResult.num_squares,
      tiers: {
        good: { label: "Good", description: "Standard materials", total: goodTotal },
        better: { label: "Better", description: "Enhanced materials", total: betterTotal },
        best: { label: "Best", description: "Premium materials", total: bestTotal },
      },
      package_options: quoteResult.package_options ?? [],
      discounts: quoteResult.discounts ?? [],
      deposit_policy: { mode: "percent", value: 50, instructions: "Check payable to Perkins Roofing" },
      // Required by core/proposal.py validate_snapshot (fires on SEND, not draft-create).
      pricing_config_hash: quoteResult.pricing_config_hash ?? "",
      estimator_version: "1.0.0",
      // Fallback only for responses cached before the backend started returning floors.
      floors: quoteResult.floors ?? { min_profit_pct: 0.13, min_profit_plus_oh_pct: 0.33 },
      ...(scopeOfWork.trim() ? { scope_of_work_text: scopeOfWork.trim() } : {}),
    };

    try {
      const r = await apiFetch("/quoting/proposals", {
        method: "POST",
        body: JSON.stringify({
          customer_id: selectedCustomer.id,
          property_id: selectedPropertyId,
          title: `Roof Proposal — ${selectedCustomer.display_name}`,
          quote_snapshot: snapshot,
          estimate_id: quoteResult.estimate_id ?? null,
        }),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const proposal = await r.json();
      setProposalCreated({ id: proposal.id });
    } catch (e: unknown) {
      setProposalError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingProposal(false);
    }
  }

  async function handleCreateRepairProposal() {
    if (!selectedCustomer || !repairResult || !selectedPropertyId) {
      setRepairProposalError("Need a customer, property, and calculated repair quote to create a proposal.");
      return;
    }
    setCreatingRepairProposal(true);
    setRepairProposalError(null);

    const estimateInput = {
      branch: selectedCustomer?.branch || "miami",
      roof_type: repairRoofType,
      days: Number(repairDays || 0),
      crew_size: repairCrewSize,
      material_cost: Number(repairMaterialCost || 0),
    };
    const snapshot = {
      estimate_input: estimateInput,
      estimate_result: repairResult,
      total: repairResult.project_total,
      job_type: "repair",
      roof_type: repairRoofType,
      tiers: {
        good: { label: "Repair", description: "Time-based repair", total: repairResult.project_total },
      },
      recommended_tier: "good",
      selected_tier_default: "good",
      deposit_policy: { mode: "percent", value: 50, instructions: "Check payable to Perkins Roofing" },
      pricing_config_hash: repairResult.pricing_config_hash ?? "",
      floors: repairResult.floors ?? { min_profit_pct: 0.13, min_profit_plus_oh_pct: 0.33 },
      estimator_version: "1.0.0",
      ...(scopeOfWork.trim() ? { scope_of_work_text: scopeOfWork.trim() } : {}),
    };

    try {
      const r = await apiFetch("/quoting/proposals", {
        method: "POST",
        body: JSON.stringify({
          customer_id: selectedCustomer.id,
          property_id: selectedPropertyId,
          title: `Repair Proposal — ${selectedCustomer.display_name}`,
          quote_snapshot: snapshot,
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const proposal = await r.json();
      setRepairProposalCreated({ id: proposal.id });
    } catch (e: unknown) {
      setRepairProposalError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingRepairProposal(false);
    }
  }

  const customerRows = Array.isArray(customers) ? customers : [];
  const filteredCustomers = customerRows.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      c.display_name.toLowerCase().includes(q) ||
      (c.company_name ?? "").toLowerCase().includes(q) ||
      (c.email ?? "").toLowerCase().includes(q)
    );
  });

  // ── Render ─────────────────────────────────────────────────────────────────

  if (view === "customer_detail" && selectedCustomer) {
    const props = selectedCustomer.properties ?? [];
    const contacts = selectedCustomer.contacts ?? [];

    return (
      <main style={{ maxWidth: 960, fontFamily: FONT }}>
        <PageTitle
          right={
            <div style={{ display: "flex", gap: 8 }}>
              <Button variant="ghost" onClick={() => { setView("customers"); setSelectedCustomer(null); setEditingCustomer(false); }} style={{ fontSize: 13 }}>
                Back to customers
              </Button>
              {!editingCustomer && (
                <Button variant="ghost" onClick={() => setEditingCustomer(true)} style={{ fontSize: 13 }}>Edit</Button>
              )}
              {props.length > 0 && (
                <Button onClick={() => setView("quote_builder")} style={{ fontSize: 13 }}>
                  Build estimate
                </Button>
              )}
            </div>
          }
        >
          {selectedCustomer.display_name}
        </PageTitle>

        <WorkflowCallout />

        {customerDetailError && <ErrorMsg>Error: {customerDetailError}</ErrorMsg>}
        {customerDetailLoading && <Loading label="Loading customer…" />}

        {editingCustomer ? (
          <Card style={{ marginBottom: 20 }}>
            <div style={{ marginBottom: 12, fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Edit customer</div>
            <CustomerForm
              initial={selectedCustomer}
              onSave={handleUpdateCustomer}
              onCancel={() => setEditingCustomer(false)}
              saving={savingCustomerEdit}
              branches={branches}
            />
          </Card>
        ) : (
          <Card style={{ marginBottom: 20 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 14 }}>
              {selectedCustomer.company_name && (
                <div><span style={{ color: BRAND.sub, fontSize: 12 }}>Company</span><br />{selectedCustomer.company_name}</div>
              )}
              {selectedCustomer.email && (
                <div><span style={{ color: BRAND.sub, fontSize: 12 }}>Email</span><br />
                  <a href={`mailto:${selectedCustomer.email}`} style={{ color: BRAND.navyText }}>{selectedCustomer.email}</a>
                </div>
              )}
              {selectedCustomer.phone && (
                <div><span style={{ color: BRAND.sub, fontSize: 12 }}>Phone</span><br />{selectedCustomer.phone}</div>
              )}
              {selectedCustomer.notes && (
                <div style={{ gridColumn: "1 / -1" }}><span style={{ color: BRAND.sub, fontSize: 12 }}>Notes</span><br />{selectedCustomer.notes}</div>
              )}
            </div>
          </Card>
        )}

        {/* Properties */}
        <Card style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Property</div>
            {!showNewProperty && (
              <Button variant="ghost" onClick={() => setShowNewProperty(true)} style={{ fontSize: 12 }}>+ Add property</Button>
            )}
          </div>
          <p style={{ margin: "0 0 12px", color: BRAND.sub, fontSize: 12 }}>
            Select the roof location for this estimate. You can add a property if this customer has a new project address.
          </p>
          {propertyError && <ErrorMsg>Error: {propertyError}</ErrorMsg>}
          {showNewProperty && (
            <div style={{ marginBottom: 16, padding: 16, background: BRAND.bg, borderRadius: 8 }}>
              <PropertyForm onSave={handleAddProperty} onCancel={() => setShowNewProperty(false)} saving={savingProperty} />
            </div>
          )}
          {props.length === 0 ? (
            <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No properties yet. Add one to enable estimate building.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {props.map((p) => (
                <div key={p.id} style={{
                  padding: "10px 14px",
                  border: `1px solid ${selectedPropertyId === p.id ? BRAND.navy : BRAND.border}`,
                  borderRadius: 8,
                  cursor: "pointer",
                  background: selectedPropertyId === p.id ? "#f0f3fa" : "#fff",
                  fontSize: 14,
                }}
                  onClick={() => handleSelectProperty(p.id)}
                >
                  <div style={{ fontWeight: 600, color: BRAND.navyText }}>{p.street}, {p.city} {p.state} {p.zip ?? ""}</div>
                  <div style={{ color: BRAND.sub, fontSize: 12 }}>{p.county ? `${p.county} County · ` : ""}{p.code_zone}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Contacts */}
        <Card style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Contacts</div>
            {!showNewContact && (
              <Button variant="ghost" onClick={() => setShowNewContact(true)} style={{ fontSize: 12 }}>+ Add contact</Button>
            )}
          </div>
          {contactError && <ErrorMsg>Error: {contactError}</ErrorMsg>}
          {showNewContact && (
            <div style={{ marginBottom: 16, padding: 16, background: BRAND.bg, borderRadius: 8 }}>
              <ContactForm onSave={handleAddContact} onCancel={() => setShowNewContact(false)} saving={savingContact} />
            </div>
          )}
          {contacts.length === 0 ? (
            <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No contacts yet. Add one before sending a proposal.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {contacts.map((c) => (
                <div key={c.id} style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", fontSize: 13, padding: "6px 0", borderBottom: `1px solid ${BRAND.border}` }}>
                  <span style={{ fontWeight: 600, color: BRAND.navyText, minWidth: 140 }}>{c.name}</span>
                  {c.is_primary ? (
                    <Badge tone="blue">Primary</Badge>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleSetPrimaryContact(c.id)}
                      style={{ background: "none", border: `1px solid ${BRAND.border}`, borderRadius: 999, color: BRAND.navyText, cursor: "pointer", fontSize: 12, fontWeight: 700, padding: "2px 8px" }}
                    >
                      Set primary
                    </button>
                  )}
                  {c.role && <span style={{ color: BRAND.sub }}>{c.role}</span>}
                  {c.email && <a href={`mailto:${c.email}`} style={{ color: BRAND.navyText }}>{c.email}</a>}
                  {c.phone && <span style={{ color: BRAND.sub }}>{c.phone}</span>}
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Measurements */}
        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div>
              <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Measurement</div>
              <div style={{ color: BRAND.sub, fontSize: 12, marginTop: 2 }}>
                Measurements are property-scoped. Roofr imports should land here when wired; manual entries are available now.
              </div>
            </div>
            {!showNewMeasurement && (
              <Button variant="ghost" onClick={() => setShowNewMeasurement(true)} disabled={!selectedPropertyId} style={{ fontSize: 12 }}>
                {measurements.length > 0 ? "Replace / add measurement" : "+ Add measurement"}
              </Button>
            )}
          </div>

          {measurementError && <ErrorMsg>Error: {measurementError}</ErrorMsg>}

          {showNewMeasurement && (
            <div style={{ marginBottom: 16, padding: 16, background: BRAND.bg, borderRadius: 8 }}>
              <div style={{ marginBottom: 10, fontWeight: 600, color: BRAND.navyText, fontSize: 13 }}>New measurement</div>
              <MeasurementForm onSave={handleAddMeasurement} onCancel={() => setShowNewMeasurement(false)} saving={savingMeasurement} />
            </div>
          )}

          {measurementsLoading && <Loading label="Loading measurements…" />}

          {!measurementsLoading && measurements.length === 0 && !showNewMeasurement && (
            <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No measurements for this property yet. Add one to start estimating.</p>
          )}

          {!measurementsLoading && measurements.length > 0 && (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Squares</th>
                    <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Pitch</th>
                    <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Provider</th>
                    <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Provenance</th>
                    <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {measurements.map((m) => (
                    <tr key={m.id} style={{ borderBottom: `1px solid ${BRAND.border}`, background: selectedMeasurement?.id === m.id ? "#f0f3fa" : undefined }}>
                      <td style={{ padding: "8px 12px", fontWeight: 600 }}>{m.total_sq ?? "—"}</td>
                      <td style={{ padding: "8px 12px" }}>{m.pitch_primary ?? "—"}</td>
                      <td style={{ padding: "8px 12px" }}>{m.provider}</td>
                      <td style={{ padding: "8px 12px", color: BRAND.sub, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.provenance_note ?? "—"}</td>
                      <td style={{ padding: "8px 12px" }}>
                        <Button variant="ghost" onClick={() => { setSelectedMeasurement(m); setView("quote_builder"); }} style={{ fontSize: 12 }}>Use for estimate</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </Card>
      </main>
    );
  }

  if (view === "quote_builder" && selectedCustomer) {
    const props = selectedCustomer.properties ?? [];
    const activeProp = props.find((p) => p.id === selectedPropertyId) ?? props[0] ?? null;
    const customerBranchKey = selectedCustomer.branch || "miami";
    const customerBranchLabel = branches.find((b) => b.key === customerBranchKey)?.name ?? customerBranchKey;

    return (
      <main style={{ maxWidth: 960, fontFamily: FONT }}>
        <PageTitle
          right={
            <Button variant="ghost" onClick={() => setView("customer_detail")} style={{ fontSize: 13 }}>
              Back to customer
            </Button>
          }
        >
          Estimate builder — {selectedCustomer.display_name}
        </PageTitle>

        <WorkflowCallout />

        {/* Stepper */}
        <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: 20, userSelect: "none" }}>
          {ESTIMATE_FLOW_STEPS.map((step, i) => {
            const stepIndex = ESTIMATE_FLOW_STEPS.indexOf(step);
            const activeIndex = ESTIMATE_FLOW_STEPS.indexOf("Estimate");
            const done = stepIndex < activeIndex;
            const active = stepIndex === activeIndex;
            return (
              <div key={step} style={{ display: "flex", alignItems: "center" }}>
                <div style={{
                  display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
                }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: "50%",
                    background: active ? BRAND.red : done ? BRAND.navy : BRAND.border,
                    color: active || done ? "#fff" : BRAND.sub,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 700,
                  }}>
                    {done ? "✓" : i + 1}
                  </div>
                  <span style={{ fontSize: 10, fontWeight: active ? 700 : 500, color: active ? BRAND.navyText : BRAND.sub, whiteSpace: "nowrap" }}>
                    {step}
                  </span>
                </div>
                {i < ESTIMATE_FLOW_STEPS.length - 1 && (
                  <div style={{ width: 40, height: 2, background: done ? BRAND.navy : BRAND.border, margin: "0 4px", marginBottom: 16 }} />
                )}
              </div>
            );
          })}
        </div>

        {activeProp && (
          <div style={{ marginBottom: 16, fontSize: 13, color: BRAND.sub }}>
            Property: <strong style={{ color: BRAND.navyText }}>{activeProp.street}, {activeProp.city} {activeProp.state}</strong>
            {" · "}{activeProp.code_zone}
          </div>
        )}

        {/* Re-roof vs repair mode (Zoom 2026-07-20 [41:04]) */}
        <div style={{ display: "flex", marginBottom: 20 }}>
          <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
            {(["reroof", "repair"] as const).map((m, i) => (
              <button
                key={m} type="button"
                onClick={() => setJobMode(m)}
                style={{
                  padding: "8px 20px", fontSize: 13, fontWeight: 700, border: "none",
                  borderRight: i === 0 ? `1px solid ${BRAND.border}` : "none", cursor: "pointer",
                  background: jobMode === m ? BRAND.navy : "#fff",
                  color: jobMode === m ? "#fff" : BRAND.sub,
                }}
              >
                {m === "reroof" ? "Re-roof" : "Repair"}
              </button>
            ))}
          </div>
        </div>

        {/* Scope of work — shared by both modes (Zoom 2026-07-20 [42:06]/[44:12]) */}
        <Card style={{ marginBottom: 20 }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 10 }}>Scope of work</div>
          <textarea
            value={scopeOfWork}
            onChange={(e) => setScopeOfWork(e.target.value)}
            rows={6}
            style={{ ...inputStyle, width: "100%", fontSize: 13, resize: "vertical" }}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
            <input
              value={scopeInstruction}
              onChange={(e) => setScopeInstruction(e.target.value)}
              placeholder="How should this differ?"
              style={{ ...inputStyle, flex: 1, fontSize: 13 }}
            />
            <Button
              variant="ghost"
              onClick={handleRewriteScope}
              disabled={scopeRewriting || !scopeInstruction.trim()}
              style={{ fontSize: 13, whiteSpace: "nowrap" }}
            >
              {scopeRewriting ? "Rewriting…" : "Rewrite with AI"}
            </Button>
          </div>
          {scopeRewriteError && <div style={{ marginTop: 8 }}><ErrorMsg>Error: {scopeRewriteError}</ErrorMsg></div>}
        </Card>

        {jobMode === "reroof" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
              <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Estimate inputs</div>
              <div style={{ fontSize: 12, color: BRAND.sub }}>Pricing: <strong style={{ color: BRAND.navyText }}>{customerBranchLabel}</strong> branch</div>
            </div>

            {/* Measurement selector */}
            <div style={{ marginBottom: 16 }}>
              <FieldLabel>Measurement</FieldLabel>
              {measurements.length === 0 ? (
                <p style={{ fontSize: 13, color: BRAND.sub, margin: 0 }}>
                  No measurements — go back to the customer to add one.
                </p>
              ) : (
                <select
                  value={selectedMeasurement?.id ?? ""}
                  onChange={(e) => {
                    const m = measurements.find((x) => x.id === Number(e.target.value)) ?? null;
                    setSelectedMeasurement(m);
                  }}
                  style={selectStyle}
                >
                  <option value="">— Select measurement —</option>
                  {measurements.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.total_sq ?? "?"} sq · {m.provenance_note ?? m.provider}
                    </option>
                  ))}
                </select>
              )}
              {selectedMeasurement && (
                <div style={{ marginTop: 8, display: "flex", gap: 16, fontSize: 12, color: BRAND.sub }}>
                  <span>Squares: <strong>{selectedMeasurement.total_sq}</strong></span>
                  {selectedMeasurement.pitch_primary != null && <span>Pitch: <strong>{selectedMeasurement.pitch_primary}</strong></span>}
                  {selectedMeasurement.hips_lf != null && <span>Hips: <strong>{selectedMeasurement.hips_lf} LF</strong></span>}
                  {selectedMeasurement.ridges_lf != null && <span>Ridges: <strong>{selectedMeasurement.ridges_lf} LF</strong></span>}
                </div>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div>
                <FieldLabel>Region</FieldLabel>
                <select value={quoteRegion} onChange={(e) => setQuoteRegion(e.target.value as "FBC" | "HVHZ")} style={selectStyle}>
                  <option value="FBC">FBC — Palm Beach / Lee / St. Lucie</option>
                  <option value="HVHZ">HVHZ — Miami-Dade / Broward</option>
                </select>
              </div>
              <div>
                <FieldLabel>Roof Type</FieldLabel>
                <select value={quoteRoofType} onChange={(e) => setQuoteRoofType(e.target.value)} style={selectStyle}>
                  {roofTypes.map((rt) => (
                    <option key={rt.value} value={rt.value}>{rt.label}</option>
                  ))}
                </select>
                {selectedMeasurement?.pitch_primary != null && Number(selectedMeasurement.pitch_primary) <= 2 && (
                  <div style={{ marginTop: 5, fontSize: 11, color: lowSlopeTypes.length ? BRAND.sub : BRAND.red }}>
                    Roofr pitch is {selectedMeasurement.pitch_primary}/12, so this should use the low-slope calculator.
                    {lowSlopeTypes.length === 0
                      ? " Low-slope pricing is pending in the active config; Tim must fill those rates before it can calculate."
                      : " Low-slope calculator selected automatically."}
                  </div>
                )}
                {ratesError && <div style={{ marginTop: 5, fontSize: 11, color: BRAND.red }}>Rates unavailable: {ratesError}</div>}
              </div>
            </div>

            <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
              <div>
                <FieldLabel>Recommended tier</FieldLabel>
                <select value={recommendedTier} onChange={(e) => setRecommendedTier(e.target.value as "good" | "better" | "best")} style={selectStyle}>
                  <option value="good">Good</option>
                  <option value="better">Better</option>
                  <option value="best">Best</option>
                </select>
              </div>
              <div>
                <FieldLabel>Roof cuts</FieldLabel>
                <select value={quoteRoofCuts} onChange={(e) => setQuoteRoofCuts(e.target.value as "low" | "medium" | "high")} style={selectStyle}>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              {rates?.cut_calc_available
                && (quoteRoofType === "13_tile" || quoteRoofType === "barrel_tile")
                && rates.tile_brands && Object.keys(rates.tile_brands).length > 0 && (
                <div>
                  <FieldLabel>Base tile brand</FieldLabel>
                  <select value={baseTileBrand} onChange={(e) => setBaseTileBrand(e.target.value)} style={selectStyle}>
                    <option value="">
                      {`Default${rates.default_tile_brand ? ` — ${rates.tile_brands[rates.default_tile_brand] ?? rates.default_tile_brand}` : ""}`}
                    </option>
                    {Object.entries(rates.tile_brands).map(([k, label]) => (
                      <option key={k} value={k}>{label}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <FieldLabel>Height</FieldLabel>
                <select value={quoteRoofHeight} onChange={(e) => setQuoteRoofHeight(e.target.value as "1_story" | "2_stories" | "3_5_stories")} style={selectStyle}>
                  <option value="1_story">1 story</option>
                  <option value="2_stories">2 stories</option>
                  <option value="3_5_stories">3–5 stories</option>
                </select>
              </div>
            </div>

            <div style={{ marginTop: 14 }}>
              <FieldLabel>Existing roof (what are we tearing off?)</FieldLabel>
              <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
                {EXISTING_ROOF_OPTIONS.map((opt, i) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      setQuoteExistingRoof(opt.value);
                      setQuoteLayersToRemove(opt.value === "none" ? "0" : "1");
                    }}
                    style={{
                      flex: 1,
                      padding: "7px 8px",
                      fontSize: 12,
                      fontWeight: 600,
                      border: "none",
                      borderRight: i < EXISTING_ROOF_OPTIONS.length - 1 ? `1px solid ${BRAND.border}` : "none",
                      cursor: "pointer",
                      background: quoteExistingRoof === opt.value ? BRAND.navy : "#fff",
                      color: quoteExistingRoof === opt.value ? "#fff" : BRAND.sub,
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 120px", gap: 10, alignItems: "end" }}>
                <div title={quoteExistingRoof === "none" ? "No tear-off on new construction" : "Demo / tear-off crew days — priced when Overhead = By time (days)"}>
                  <FieldLabel>Demo days (tear-off)</FieldLabel>
                  <input
                    type="number" min="0" step="0.5"
                    disabled={quoteExistingRoof === "none"}
                    value={quoteDemoDays}
                    onChange={(e) => setQuoteDemoDays(e.target.value)}
                    style={{ ...inputStyle, width: "100%", opacity: quoteExistingRoof === "none" ? 0.5 : 1 }}
                  />
                </div>
                <div title={quoteExistingRoof === "none" ? "Select an existing roof type to set layers" : undefined}>
                  <FieldLabel>Layers</FieldLabel>
                  <input
                    type="number" min="0" step="1"
                    disabled={quoteExistingRoof === "none"}
                    value={quoteLayersToRemove}
                    onChange={(e) => setQuoteLayersToRemove(e.target.value)}
                    style={{ ...inputStyle, width: "100%", opacity: quoteExistingRoof === "none" ? 0.5 : 1 }}
                  />
                </div>
              </div>
            </div>
            {quoteExistingRoof === "tile" && (
              <div style={{ marginTop: 6, fontSize: 11, color: BRAND.sub }}>
                Tile demo adds the tile-demo rate and dumpsters automatically.
              </div>
            )}

            {isLowSlopeRoofType && (
              <div style={{ marginTop: 14 }}>
                <FieldLabel>Deck / attach system</FieldLabel>
                <select value={quoteDeckType} onChange={(e) => setQuoteDeckType(e.target.value)} style={selectStyle}>
                  {(() => {
                    const opts = Object.entries(rates?.low_slope?.deck_types ?? {}).filter(([k, v]) => !k.startsWith("_") && v !== null);
                    return opts.length === 0 ? (
                      <option value="">Pending Tim — no deck rates configured</option>
                    ) : opts.map(([k, v]) => (
                      <option key={k} value={k}>
                        {k.replace(/_/g, " ")}{Number(v) > 0 ? ` (+$${v}/sq)` : ""}
                      </option>
                    ));
                  })()}
                </select>
                <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <EstimateCheckbox checked={quoteIncludeInsulation} onChange={setQuoteIncludeInsulation} label="Insulation" />
                  <EstimateCheckbox checked={quoteIncludeTapered} onChange={setQuoteIncludeTapered} label="Tapered ISO" />
                </div>
              </div>
            )}

            <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, alignItems: "end" }}>
              <EstimateCheckbox checked={quoteSecondaryWater} onChange={setQuoteSecondaryWater} label="SWR" />
              <EstimateCheckbox checked={quoteWinterguard} onChange={setQuoteWinterguard} label="WinterGuard" />
              <div><FieldLabel>Penetrations</FieldLabel><input type="number" min="0" step="1" value={quotePenetrations} onChange={(e) => setQuotePenetrations(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
            </div>

            <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div><FieldLabel>Stucco metal LF</FieldLabel><input type="number" min="0" step="1" value={quoteStuccoMetalLf} onChange={(e) => setQuoteStuccoMetalLf(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
              <div><FieldLabel>Ridge vent LF</FieldLabel><input type="number" min="0" step="1" value={quoteRidgeVentLf} onChange={(e) => setQuoteRidgeVentLf(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
            </div>

            <div style={{ marginTop: 14 }}>
              <SectionLabel>Gutters</SectionLabel>
              <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 110px", gap: 10, alignItems: "end", marginTop: 6 }}>
                <div>
                  <FieldLabel>Style</FieldLabel>
                  <select
                    value={quoteGutterStyle}
                    onChange={(e) => {
                      const style = e.target.value;
                      setQuoteGutterStyle(style);
                      if (!TWO_STORY_GUTTER_STYLES.has(style)) setQuoteGutterTwoStory(false);
                    }}
                    style={selectStyle}
                  >
                    {GUTTER_STYLES.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                  </select>
                </div>
                <div><FieldLabel>Gutter LF</FieldLabel><input type="number" min="0" step="1" value={quoteGutterLf} onChange={(e) => setQuoteGutterLf(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                <div><FieldLabel>Elbows</FieldLabel><input type="number" min="0" step="1" value={quoteGutterElbows} onChange={(e) => setQuoteGutterElbows(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                <div><FieldLabel>Removal LF</FieldLabel><input type="number" min="0" step="1" value={quoteGutterRemovalLf} onChange={(e) => setQuoteGutterRemovalLf(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                <div><FieldLabel>Downspout LF (4×5)</FieldLabel><input type="number" min="0" step="1" value={quoteDownspoutLf} onChange={(e) => setQuoteDownspoutLf(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
              </div>
              <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 110px 130px", gap: 10, alignItems: "end" }}>
                <div>
                  <FieldLabel>Leaf guard</FieldLabel>
                  <select value={quoteLeafGuard} onChange={(e) => setQuoteLeafGuard(e.target.value as "none" | "std" | "upgraded")} style={selectStyle}>
                    <option value="none">None</option>
                    <option value="std">Standard</option>
                    <option value="upgraded">Upgraded</option>
                  </select>
                </div>
                <div><FieldLabel>Leaderheads (res)</FieldLabel><input type="number" min="0" step="1" value={quoteLeaderheadsRes} onChange={(e) => setQuoteLeaderheadsRes(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                <div><FieldLabel>Leaderheads (comm)</FieldLabel><input type="number" min="0" step="1" value={quoteLeaderheadsComm} onChange={(e) => setQuoteLeaderheadsComm(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
              </div>
              <div style={{ marginTop: 8 }}>
                <EstimateCheckbox
                  checked={quoteGutterTwoStory}
                  onChange={setQuoteGutterTwoStory}
                  label="2-story (uplift applies)"
                  disabled={!TWO_STORY_GUTTER_STYLES.has(quoteGutterStyle)}
                  title={TWO_STORY_GUTTER_STYLES.has(quoteGutterStyle) ? undefined : "no 2-story rate configured for this style"}
                />
              </div>
              <div style={{ marginTop: 6, fontSize: 11, color: BRAND.sub }}>Downspouts included in the per-LF rate.</div>
            </div>

            <div style={{ marginTop: 16 }}>
              <SectionLabel>Overhead</SectionLabel>
              <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 6, lineHeight: 1.5 }}>
                How job-site overhead is charged. <strong>Per-square</strong> uses the config guide rate per roofing square; <strong>By time</strong> bills the crew day-rate × install days.
              </div>
              <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}`, width: "fit-content" }}>
                {(["per_sq", "daily"] as const).map((mode, i) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setQuoteOverheadMode(mode)}
                    style={{
                      padding: "6px 14px",
                      fontSize: 12,
                      fontWeight: 600,
                      border: "none",
                      borderRight: i === 0 ? `1px solid ${BRAND.border}` : "none",
                      cursor: "pointer",
                      background: quoteOverheadMode === mode ? BRAND.navy : "#fff",
                      color: quoteOverheadMode === mode ? "#fff" : BRAND.sub,
                    }}
                  >
                    {mode === "per_sq" ? "Per-square (guide)" : "By time (days)"}
                  </button>
                ))}
              </div>
              {quoteOverheadMode === "daily" && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 8 }}>
                    By-time overhead <strong>replaces</strong> the per-square overhead (it doesn&apos;t add to it). Demo days are set in the tear-off section above.
                  </div>
                  {Object.keys(rates?.daily_overhead_rates ?? {}).length === 0 ? (
                    <div style={{ fontSize: 12, color: BRAND.sub }}>No daily overhead rates configured for this branch.</div>
                  ) : (() => {
                    const installSeries = INSTALL_SERIES_BY_ROOF[quoteRoofType] ?? "demo_dry_in_flat";
                    const rate = rates?.daily_overhead_rates?.[installSeries];
                    return (
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 120px", gap: 10, alignItems: "end" }}>
                        <div style={{ fontSize: 12, color: BRAND.sub }}>
                          Install crew rate: <strong>{rate != null ? usd(rate) : "—"}/day</strong> ({installSeries.replace(/_/g, " ")})
                        </div>
                        <div>
                          <FieldLabel>Install days</FieldLabel>
                          <input
                            type="number" min="0" step="0.5"
                            value={quoteInstallDays}
                            onChange={(e) => setQuoteInstallDays(e.target.value)}
                            style={{ ...inputStyle, width: "100%" }}
                          />
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>

            <div style={{ marginTop: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <SectionLabel>Discounts affect total and margin</SectionLabel>
                <Button variant="ghost" onClick={() => setEstimateDiscounts((prev) => [...prev, newEstimateDiscount()])} style={{ fontSize: 12 }}>+ Add discount</Button>
              </div>
              {estimateDiscounts.map((d) => (
                <div key={d.key} style={{ display: "grid", gridTemplateColumns: "1fr 110px 110px auto", gap: 8, marginBottom: 8 }}>
                  <input value={d.description} onChange={(e) => setEstimateDiscounts((prev) => prev.map((x) => x.key === d.key ? { ...x, description: e.target.value } : x))} placeholder="Referral, veteran, current special…" style={{ ...inputStyle, width: "100%" }} />
                  <select value={d.discount_type} onChange={(e) => setEstimateDiscounts((prev) => prev.map((x) => x.key === d.key ? { ...x, discount_type: e.target.value as "amount" | "percent" } : x))} style={selectStyle}>
                    <option value="amount">$ amount</option>
                    <option value="percent">% percent</option>
                  </select>
                  <input type="number" min="0" max={d.discount_type === "percent" ? "100" : undefined} step="0.01" value={d.value} onChange={(e) => setEstimateDiscounts((prev) => prev.map((x) => x.key === d.key ? { ...x, value: e.target.value } : x))} placeholder={d.discount_type === "percent" ? "10" : "500"} style={{ ...inputStyle, width: "100%" }} />
                  <Button variant="danger" onClick={() => setEstimateDiscounts((prev) => prev.filter((x) => x.key !== d.key))} style={{ fontSize: 12 }}>✕</Button>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <Button onClick={handleCalculateQuote} disabled={quoting || !selectedMeasurement} style={{ fontSize: 13 }}>
                {quoting ? "Calculating…" : "Calculate estimate"}
              </Button>
            </div>

            {quoteError && <div style={{ marginTop: 10 }}><ErrorMsg>Error: {quoteError}</ErrorMsg></div>}
          </Card>

          {selectedMeasurement && (
            <Card>
              <SectionLabel>Estimates for this measurement</SectionLabel>
              {estimatesLoading && <Loading label="Loading estimates…" />}
              {!estimatesLoading && estimateHistory.length === 0 && (
                <p style={{ margin: 0, color: BRAND.sub, fontSize: 13 }}>No estimates yet. Calculate a new estimate to save one.</p>
              )}
              {!estimatesLoading && estimateHistory.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {estimateHistory.map((est) => (
                    <div key={est.id} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, padding: "6px 0", borderBottom: `1px solid ${BRAND.border}` }}>
                      <span>Estimate #{est.id}</span>
                      <span style={{ color: BRAND.sub }}>{est.created_at ? new Date(est.created_at).toLocaleString() : "—"}</span>
                      <strong>{est.result_json?.project_total != null ? usd(est.result_json.project_total) : "—"}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* Result panel — span the full grid width so the package cards + margin panel
              render below the inputs/history row (not squeezed into the 380px rail, and
              not dropped bottom-left by CSS auto-placement when a measurement is selected). */}
          <div style={{ gridColumn: "1 / -1" }}>
            {quoting && <Card><Loading label="Building estimate…" /></Card>}

            {!quoting && !quoteResult && (
              <Card style={{ background: BRAND.bg, border: "none" }}>
                <p style={{ margin: 0, fontSize: 13, color: BRAND.sub, textAlign: "center", padding: "24px 0" }}>
                  Select a measurement and press <strong>Calculate estimate</strong> to see pricing.
                </p>
              </Card>
            )}

            {quoteResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Card style={{ padding: "20px 18px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
                      {labelRoofType(quoteResult.roof_type)} · {quoteResult.num_squares} sq
                      {quoteResult.branch && ` · ${branches.find((b) => b.key === quoteResult.branch)?.name ?? quoteResult.branch} branch`}
                    </div>
                    <span style={{
                      fontSize: 12, fontWeight: 700, padding: "3px 12px", borderRadius: 20,
                      background: quoteResult.margin_ok ? "#e6f9f0" : "#fef2f2",
                      color: quoteResult.margin_ok ? "#1a7f4b" : BRAND.red,
                    }}>
                      {quoteResult.margin_ok ? "Margin OK" : "Margin LOW"}
                    </span>
                  </div>
                  {quoteResult.cut_calc && (
                    <div style={{ marginBottom: 12, padding: "10px 12px", borderRadius: 8, background: "#eef2ff", border: "1px solid #c7d2fe" }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#3730a3", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6 }}>
                        RoofR cut calculator — reference
                      </div>
                      <div style={{ display: "flex", gap: 20, fontSize: 13, flexWrap: "wrap" }}>
                        <div>
                          <div style={{ color: "#475569", fontSize: 11 }}>Standard (flat) — used</div>
                          <div style={{ fontWeight: 700 }}>{usd(quoteResult.cut_calc.flat_base_per_sq)}/sq</div>
                          <div style={{ color: "#475569" }}>{usd(quoteResult.cut_calc.flat_project_total)}</div>
                        </div>
                        <div>
                          <div style={{ color: "#475569", fontSize: 11 }}>Cut-adjusted (RoofR)</div>
                          <div style={{ fontWeight: 700, color: "#3730a3" }}>{usd(quoteResult.cut_calc.cut_base_per_sq)}/sq</div>
                          <div style={{ color: "#475569" }}>{usd(quoteResult.cut_calc.cut_project_total)}</div>
                        </div>
                        <div style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: quoteResult.cut_calc.cut_base_per_sq >= quoteResult.cut_calc.flat_base_per_sq ? "#1a7f4b" : BRAND.red }}>
                          {quoteResult.cut_calc.cut_base_per_sq >= quoteResult.cut_calc.flat_base_per_sq ? "+" : "−"}
                          {usd(Math.abs(quoteResult.cut_calc.cut_base_per_sq - quoteResult.cut_calc.flat_base_per_sq))}/sq
                        </div>
                      </div>
                      <div style={{ fontSize: 11, color: "#475569", marginTop: 6 }}>
                        The headline quote uses the standard base (how Tim prices standard roofs). The cut-adjusted figure prices this roof&apos;s RoofR cuts and is shown for comparison on cut-heavy jobs — it is a reference, not a separate selection.
                      </div>
                    </div>
                  )}
                  {inputsDirty && (
                    <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 8, background: "#fff7ed", border: "1px solid #fed7aa", color: "#9a3412", fontSize: 12, fontWeight: 700 }}>
                      Inputs changed — recalculate
                    </div>
                  )}
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {(quoteResult.package_options ?? []).length === 0 && (
                      <div style={{ fontSize: 12, color: BRAND.sub }}>No package menu available for this roof type.</div>
                    )}
                    {(quoteResult.package_options ?? []).map((opt) => (
                      <div key={opt.key} style={{
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        padding: "10px 14px", borderRadius: 8,
                        border: opt.key === "PROTECTOR" ? `2px solid ${BRAND.navy}` : `1px solid ${BRAND.border}`,
                        background: opt.key === "PROTECTOR" ? "#f0f3fa" : "#fff",
                      }}>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.navyText }}>{opt.label}</div>
                          {opt.key !== "PROTECTOR" && (
                            <div style={{ fontSize: 11, color: BRAND.sub }}>
                              {opt.standalone ? "Standalone system" : `+${usd(opt.addl_price)}`}
                            </div>
                          )}
                        </div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>
                          {usd(opt.total)}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 8, fontSize: 12, color: BRAND.sub }}>
                    Estimate #{quoteResult.estimate_id ?? "—"} · recommended/default tier: <strong>{recommendedTier.toUpperCase()}</strong>
                  </div>
                  <SectionLabel>Profitability</SectionLabel>
                  {(() => {
                    const oh = quoteResult.line_items_detail?.find((li) => li.key === "overhead");
                    if (!oh) return null;
                    const mode = quoteOverheadMode === "daily" ? "by days" : "per-sq";
                    return <ResultRow label={`Overhead (${mode})`} value={usd(oh.amount)} />;
                  })()}
                  {quoteResult.pre_discount_total != null && (
                    <ResultRow label="Pre-discount total" value={usd(quoteResult.pre_discount_total)} />
                  )}
                  {quoteResult.discount_total != null && quoteResult.discount_total > 0 && (
                    <ResultRow label="Discounts" value={"-" + usd(quoteResult.discount_total)} />
                  )}
                  <ResultRow label="Profit" value={usd(quoteResult.profit_dollars)} />
                  <ResultRow label="Profit %" value={(quoteResult.profit_pct * 100).toFixed(1) + "%"} />
                  {quoteResult.margin && (
                    <>
                      <div style={{ fontSize: 11, color: BRAND.sub, margin: "8px 0 2px", lineHeight: 1.5 }}>
                        Margin checks — green is at or above the branch's minimum, <span style={{ color: BRAND.red, fontWeight: 700 }}>red — LOW</span> is below it. "OH" = overhead.
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 13 }}>
                        <span>Profit % vs floor</span>
                        <span style={{ fontWeight: 700, color: quoteResult.margin.profit_floor_ok ? BRAND.navyText : BRAND.red }}>
                          {(quoteResult.margin.profit_pct * 100).toFixed(1)}% {quoteResult.margin.profit_floor_ok ? "" : "— LOW"}
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 13 }}>
                        <span>Profit + OH % vs floor</span>
                        <span style={{ fontWeight: 700, color: quoteResult.margin.combined_floor_ok ? BRAND.navyText : BRAND.red }}>
                          {(quoteResult.margin.combined_pct * 100).toFixed(1)}% {quoteResult.margin.combined_floor_ok ? "" : "— LOW"}
                        </span>
                      </div>
                      <SectionLabel>Target margin (drives price)</SectionLabel>
                      {(() => {
                        const cur = targetProfitPct !== "" ? Number(targetProfitPct) : Math.round((quoteResult.profit_pct || 0) * 100);
                        return (
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                              <span style={{ color: BRAND.sub }}>Margin</span>
                              <strong>{cur}%</strong>
                            </div>
                            <input
                              type="range" min="0" max="40" step="0.5" value={cur}
                              onChange={(e) => setTargetProfitPct(e.target.value)}
                              onPointerUp={(e) => void applyTargetProfit(Number((e.target as HTMLInputElement).value))}
                              disabled={quoting}
                              style={{ width: "100%", accentColor: BRAND.red }}
                            />
                            <div style={{ fontSize: 11, color: BRAND.sub }}>Release to reprice the job to this margin.</div>
                          </div>
                        );
                      })()}
                      <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
                        {(() => {
                          // "Min" reflects the active config's profit floor, not a hardcoded 13%.
                          const minPct = Math.round((quoteResult.floors?.min_profit_pct ?? 0.13) * 100);
                          return <PillButton active={activeProfitPreset === minPct} onClick={() => void applyTargetProfit(minPct)}>Min {minPct}%</PillButton>;
                        })()}
                        <PillButton active={activeProfitPreset === 15} onClick={() => void applyTargetProfit(15)}>15%</PillButton>
                        <PillButton active={activeProfitPreset === 20} onClick={() => void applyTargetProfit(20)}>20%</PillButton>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "end" }}>
                        <div><FieldLabel>Target %</FieldLabel><input type="number" min="0" step="0.5" value={targetProfitPct} onChange={(e) => setTargetProfitPct(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                        <div><FieldLabel>Min $</FieldLabel><input type="number" min="0" step="50" value={targetProfitMinDollars} onChange={(e) => setTargetProfitMinDollars(e.target.value)} style={{ ...inputStyle, width: "100%" }} /></div>
                        <Button variant="ghost" onClick={() => void applyTargetProfit(Number(targetProfitPct || 0))} disabled={quoting || !targetProfitPct} style={{ fontSize: 12 }}>Apply</Button>
                      </div>
                      <SectionLabel>Commission</SectionLabel>
                      <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 6, lineHeight: 1.5 }}>
                        Sales rep's payout — either a percent of the job's <strong>profit</strong> or of the total <strong>job</strong> price. Switching the basis resets to the usual default rate.
                      </div>
                      <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}`, marginBottom: 8 }}>
                        {(["profit", "job"] as const).map((b, i) => (
                          <button
                            key={b} type="button"
                            onClick={() => { setCommissionBasis(b); setCommissionRate(b === "profit" ? "30" : "10"); }}
                            style={{
                              flex: 1, padding: "6px 8px", fontSize: 12, fontWeight: 600, border: "none",
                              borderRight: i === 0 ? `1px solid ${BRAND.border}` : "none", cursor: "pointer",
                              background: commissionBasis === b ? BRAND.navy : "#fff",
                              color: commissionBasis === b ? "#fff" : BRAND.sub,
                            }}
                          >
                            {b === "profit" ? "% of profit" : "% of job"}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, marginBottom: 4, gap: 8 }}>
                        <span style={{ color: BRAND.sub }}>Rate</span>
                        <input
                          type="number" min="0" max={commissionBasis === "profit" ? 50 : 20} step="0.5"
                          value={commissionRate}
                          onChange={(e) => setCommissionRate(e.target.value)}
                          style={{ ...inputStyle, width: 70, textAlign: "right", fontWeight: 700 }}
                        />
                      </div>
                      <input
                        type="range" min="0" max={commissionBasis === "profit" ? "50" : "20"} step="0.5"
                        value={commissionRate}
                        onChange={(e) => setCommissionRate(e.target.value)}
                        style={{ width: "100%", accentColor: BRAND.red }}
                      />
                      {(() => {
                        const rate = Number(commissionRate || 0) / 100;
                        const basisAmt = commissionBasis === "job" ? quoteResult.project_total : quoteResult.profit_dollars;
                        return <ResultRow label={`Commission (${commissionRate}% of ${commissionBasis})`} value={usd(basisAmt * rate)} />;
                      })()}
                    </>
                  )}
                  {quoteResult.margin_warnings && quoteResult.margin_warnings.length > 0 && (
                    <div style={{ marginTop: 8, fontSize: 12, color: BRAND.red }}>
                      Margin warnings: {quoteResult.margin_warnings.join(", ")}
                    </div>
                  )}
                  {quoteResult.warnings && quoteResult.warnings.length > 0 && (
                    <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 8, background: "#fff7ed", border: "1px solid #fed7aa", color: "#9a3412", fontSize: 12, lineHeight: 1.5 }}>
                      <div style={{ fontWeight: 800, marginBottom: 4 }}>Non-blocking estimate warning</div>
                      {quoteResult.warnings.map((w, i) => (
                        <div key={i}>{w}</div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card>
                  {props.length > 1 && (
                    <div style={{ marginBottom: 12 }}>
                      <FieldLabel>Property for proposal</FieldLabel>
                      <select value={selectedPropertyId ?? ""} onChange={(e) => setSelectedPropertyId(Number(e.target.value))} style={selectStyle}>
                        {props.map((p) => <option key={p.id} value={p.id}>{p.street}, {p.city}</option>)}
                      </select>
                    </div>
                  )}
                  {proposalCreated ? (
                    <div style={{ background: "#e6f9f0", borderRadius: 8, padding: "12px 14px", fontSize: 13, color: "#1a7f4b" }}>
                      Proposal #{proposalCreated.id} created. Switch to the <strong>Proposals</strong> tab to send it.
                    </div>
                  ) : (
                    <Button onClick={handleCreateProposal} disabled={creatingProposal || !selectedPropertyId || inputsDirty} style={{ fontSize: 13, width: "100%" }}>
                      {creatingProposal ? "Creating…" : "Create proposal draft"}
                    </Button>
                  )}
                  {proposalError && <div style={{ marginTop: 8 }}><ErrorMsg>Error: {proposalError}</ErrorMsg></div>}
                </Card>
              </div>
            )}
          </div>
        </div>
        )}

        {/* Repair estimate — time-based alternative to full replacement (Zoom 2026-07-20 [37:04]/[45:31]) */}
        {jobMode === "repair" && (
        <Card>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 4 }}>
            Repair estimate (time-based)
          </div>
          <p style={{ margin: "0 0 14px", fontSize: 12, color: BRAND.sub, lineHeight: 1.5 }}>
            For repair work (not a full replacement): days &times; the configured daily labor
            rate, plus material cost. Simple calculation, per Tim.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
            <div>
              <FieldLabel>Roof type</FieldLabel>
              <select
                value={repairRoofType}
                onChange={(e) => setRepairRoofType(e.target.value as "shingle" | "tile" | "metal" | "flat")}
                style={selectStyle}
              >
                {EXISTING_ROOF_OPTIONS.filter((o) => o.value !== "none").map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Days</FieldLabel>
              <input
                type="number" min="0" step="0.5"
                value={repairDays}
                onChange={(e) => setRepairDays(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div>
              <FieldLabel>Crew size</FieldLabel>
              <select
                value={repairCrewSize}
                onChange={(e) => setRepairCrewSize(Number(e.target.value) as 1 | 2)}
                style={selectStyle}
              >
                <option value={1}>1 man</option>
                <option value={2}>2 men</option>
              </select>
            </div>
            <div>
              <FieldLabel>Material cost ($)</FieldLabel>
              <input
                type="number" min="0" step="1"
                value={repairMaterialCost}
                onChange={(e) => setRepairMaterialCost(e.target.value)}
                style={inputStyle}
              />
            </div>
          </div>
          <Button onClick={runRepairQuote} disabled={repairQuoting} style={{ fontSize: 13 }}>
            {repairQuoting ? "Calculating…" : "Calculate repair"}
          </Button>
          {repairError && <div style={{ marginTop: 10 }}><ErrorMsg>Error: {repairError}</ErrorMsg></div>}
          {repairResult && (
            <div style={{ marginTop: 14, maxWidth: 380 }}>
              <ResultRow label={`Labor (${repairResult.days}d @ ${usd(repairResult.daily_labor_rate)}/day)`} value={usd(repairResult.labor_cost)} />
              <ResultRow label="Material cost" value={usd(repairResult.material_cost)} />
              <ResultRow label="Repair total" value={usd(repairResult.project_total)} bold />

              {props.length > 1 && (
                <div style={{ marginTop: 14, marginBottom: 12 }}>
                  <FieldLabel>Property for proposal</FieldLabel>
                  <select value={selectedPropertyId ?? ""} onChange={(e) => setSelectedPropertyId(Number(e.target.value))} style={selectStyle}>
                    {props.map((p) => <option key={p.id} value={p.id}>{p.street}, {p.city}</option>)}
                  </select>
                </div>
              )}
              {repairProposalCreated ? (
                <div style={{ marginTop: 14, background: "#e6f9f0", borderRadius: 8, padding: "12px 14px", fontSize: 13, color: "#1a7f4b" }}>
                  Proposal #{repairProposalCreated.id} created. Switch to the <strong>Proposals</strong> tab to send it.
                </div>
              ) : (
                <Button onClick={handleCreateRepairProposal} disabled={creatingRepairProposal || !selectedPropertyId} style={{ marginTop: 14, fontSize: 13, width: "100%" }}>
                  {creatingRepairProposal ? "Creating…" : "Create proposal draft"}
                </Button>
              )}
              {repairProposalError && <div style={{ marginTop: 8 }}><ErrorMsg>Error: {repairProposalError}</ErrorMsg></div>}
            </div>
          )}
        </Card>
        )}
      </main>
    );
  }

  // ── Customer list (default view) ───────────────────────────────────────────

  return (
    <main style={{ maxWidth: 960, fontFamily: FONT }}>
      <PageTitle
        right={
          !showNewCustomer
            ? <Button onClick={() => setShowNewCustomer(true)} style={{ fontSize: 13 }}>+ New customer</Button>
            : undefined
        }
      >
        Estimates
      </PageTitle>

      <WorkflowCallout />

      {showNewCustomer && (
        <Card style={{ marginBottom: 20 }}>
          <div style={{ marginBottom: 12, fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>New customer</div>
          {customerFormError && <ErrorMsg>Error: {customerFormError}</ErrorMsg>}
          <CustomerForm onSave={handleCreateCustomer} onCancel={() => { setShowNewCustomer(false); setCustomerFormError(null); }} saving={savingCustomer} branches={branches} />
        </Card>
      )}

      {/* Search */}
      <Card style={{ marginBottom: 16, padding: "12px 16px" }}>
        <div style={{ marginBottom: 8, fontWeight: 700, color: BRAND.navyText, fontSize: 13 }}>
          Start with a customer
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search customers by name, company, or email…"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </Card>

      {customersLoading && <Loading label={search.trim() ? "Searching all customers…" : "Loading customers…"} />}
      {customersError && <ErrorMsg>Error: {customersError}</ErrorMsg>}

      {!customersLoading && !customersError && search.trim() && filteredCustomers.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No customers matching "{search}". Use + New customer to add them.
          </p>
        </Card>
      )}

      {!search.trim() && !showNewCustomer && filteredCustomers.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No customers yet. Use + New customer to add one, then choose the property, measurement, and estimate.
          </p>
        </Card>
      )}

      {!showNewCustomer && filteredCustomers.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filteredCustomers.slice(0, 8).map((c) => (
            <Card
              key={c.id}
              style={{ padding: "14px 18px", cursor: "pointer" }}
              onClick={() => openCustomer(c)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <InitialsAvatar name={c.display_name} size={40} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>{c.display_name}</div>
                  <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2, display: "flex", gap: 12, flexWrap: "wrap" }}>
                    {c.company_name && <span>{c.company_name}</span>}
                    {c.email && <span>{c.email}</span>}
                    {c.phone && <span>{c.phone}</span>}
                  </div>
                </div>
                <div style={{ color: BRAND.sub, fontSize: 18, lineHeight: 1 }}>›</div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
