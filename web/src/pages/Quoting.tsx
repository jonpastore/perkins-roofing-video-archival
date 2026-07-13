import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, FONT, Button, Card, PageTitle, inputStyle, Loading, ErrorMsg, Badge, InitialsAvatar, TierCard, SectionLabel } from "../ui";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Customer {
  id: number;
  display_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
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

interface QuoteResult {
  region: string;
  roof_type: string;
  num_squares: number;
  per_square_total: number;
  squares_subtotal: number;
  project_fixed_costs: Record<string, number>;
  line_items: Record<string, number>;
  pm_incentive: number;
  project_total: number;
  profit_dollars: number;
  profit_pct: number;
  estimated_commission: number;
  margin_ok: boolean;
}

interface EstimateRecord {
  id: number;
  input_json: Record<string, unknown>;
  result_json: Partial<QuoteResult> & { project_total?: number };
  pricing_config_hash: string | null;
  created_at: string | null;
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

// ── Sub-views ─────────────────────────────────────────────────────────────────

function CustomerForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial?: Partial<Customer>;
  onSave: (data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes">) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [companyName, setCompanyName] = useState(initial?.company_name ?? "");
  const [email, setEmail] = useState(initial?.email ?? "");
  const [phone, setPhone] = useState(initial?.phone ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <FieldLabel>Name *</FieldLabel>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="Full name" />
        </div>
        <div>
          <FieldLabel>Company</FieldLabel>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="Optional" />
        </div>
        <div>
          <FieldLabel>Email</FieldLabel>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="customer@email.com" />
        </div>
        <div>
          <FieldLabel>Phone</FieldLabel>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="(555) 555-5555" />
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <FieldLabel>Notes</FieldLabel>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} style={{ ...inputStyle, width: "100%", fontSize: 13, resize: "vertical" }} placeholder="Internal notes…" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={() => onSave({ display_name: displayName, company_name: companyName || null, email: email || null, phone: phone || null, notes: notes || null })} disabled={saving || !displayName.trim()} style={{ fontSize: 13 }}>
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
        Need a fast ballpark without a customer? A standalone <strong>Quick Estimate Calculator</strong>{" "}
        (legacy) still exists for unattached what-if pricing, but estimates you intend to send should be
        built here so they stay linked to a customer, property, and measurement.
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

  // Customer detail
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerDetail | null>(null);
  const [customerDetailLoading, setCustomerDetailLoading] = useState(false);
  const [customerDetailError, setCustomerDetailError] = useState<string | null>(null);
  const [editingCustomer, setEditingCustomer] = useState(false);
  const [savingCustomerEdit, setSavingCustomerEdit] = useState(false);
  const [showNewProperty, setShowNewProperty] = useState(false);
  const [savingProperty, setSavingProperty] = useState(false);
  const [propertyError, setPropertyError] = useState<string | null>(null);

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
  const [quoteResult, setQuoteResult] = useState<QuoteResult | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [creatingProposal, setCreatingProposal] = useState(false);
  const [proposalCreated, setProposalCreated] = useState<{ id: number } | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);

  // Selected property for proposal creation
  const [selectedPropertyId, setSelectedPropertyId] = useState<number | null>(null);

  const roofTypes = [
    { value: "13_tile", label: "13\" Flat Tile" },
    { value: "barrel_tile", label: "Barrel Tile" },
    { value: "3tab_shingle", label: "3-Tab Shingle" },
    { value: "dimensional_shingle", label: "Dimensional Shingle" },
    { value: "standing_seam_metal", label: "Standing Seam Metal" },
  ];

  function labelRoofType(key: string): string {
    return roofTypes.find((r) => r.value === key)?.label ?? key.replace(/_/g, " ");
  }

  function loadCustomers() {
    setCustomersLoading(true);
    setCustomersError(null);
    apiFetch("/quoting/customers?limit=200")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
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
    loadCustomers();
  }, []);

  function loadCustomerDetail(id: number) {
    setCustomerDetailLoading(true);
    setCustomerDetailError(null);
    apiFetch(`/quoting/customers/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
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

  async function handleCreateCustomer(data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes">) {
    setSavingCustomer(true);
    setCustomerFormError(null);
    try {
      const r = await apiFetch("/quoting/customers", { method: "POST", body: JSON.stringify(data) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
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

  async function handleUpdateCustomer(data: Pick<Customer, "display_name" | "company_name" | "email" | "phone" | "notes">) {
    if (!selectedCustomer) return;
    setSavingCustomerEdit(true);
    try {
      const r = await apiFetch(`/quoting/customers/${selectedCustomer.id}`, {
        method: "PUT",
        body: JSON.stringify({ display_name: data.display_name, company_name: data.company_name, email: data.email, phone: data.phone, notes: data.notes }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
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
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((rows: Measurement[]) => {
        setMeasurements(Array.isArray(rows) ? rows : []);
        setSelectedMeasurement(null);
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
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
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

  async function handleAddMeasurement(data: Omit<Measurement, "id" | "provider" | "status" | "created_at" | "created_by" | "confidence">) {
    setSavingMeasurement(true);
    setMeasurementError(null);
    try {
      const r = await apiFetch("/measurements", { method: "POST", body: JSON.stringify({ ...data, property_id: selectedPropertyId }) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
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
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((rows: EstimateRecord[]) => setEstimateHistory(Array.isArray(rows) ? rows : []))
      .catch(() => setEstimateHistory([]))
      .finally(() => setEstimatesLoading(false));
  }

  useEffect(() => {
    loadEstimatesForMeasurement(selectedMeasurement?.id ?? null);
  }, [selectedMeasurement?.id]);

  async function handleCalculateQuote() {
    if (!selectedMeasurement?.total_sq) {
      setQuoteError("Select a measurement with total squares filled in.");
      return;
    }
    setQuoting(true);
    setQuoteError(null);
    setQuoteResult(null);
    setProposalCreated(null);

    const body = {
      region: quoteRegion,
      roof_type: quoteRoofType,
      num_squares: selectedMeasurement.total_sq,
      measurement_id: selectedMeasurement.id,
      project_kind: "residential",
      roof_cuts: "low",
      roof_height: "1_story",
      tile_pointing: "no",
      pitch_7_12: false,
      demo: false,
      secondary_water_barrier: false,
      winterguard: false,
      include_dumpster: false,
      stucco_metal_lf: 0,
      penetrations: 0,
      ridge_vent_lf: 0,
    };

    try {
      const r = await apiFetch("/estimator/quote", { method: "POST", body: JSON.stringify(body) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const data: QuoteResult = await r.json();
      setQuoteResult(data);
      loadEstimatesForMeasurement(selectedMeasurement.id);
    } catch (e: unknown) {
      setQuoteError(e instanceof Error ? e.message : String(e));
    } finally {
      setQuoting(false);
    }
  }

  async function handleCreateProposal() {
    if (!selectedCustomer || !quoteResult || !selectedPropertyId) {
      setProposalError("Need a customer, property, and calculated quote to create a proposal.");
      return;
    }
    setCreatingProposal(true);
    setProposalError(null);

    const snapshot = {
      region: quoteResult.region,
      roof_type: quoteResult.roof_type,
      num_squares: quoteResult.num_squares,
      tiers: {
        good: { label: "Good", description: "Standard materials", total: quoteResult.project_total },
        better: { label: "Better", description: "Enhanced materials", total: Math.round(quoteResult.project_total * 1.15) },
        best: { label: "Best", description: "Premium materials", total: Math.round(quoteResult.project_total * 1.30) },
      },
      deposit_policy: { mode: "percent", value: 50, instructions: "Check payable to Perkins Roofing" },
    };

    try {
      const r = await apiFetch("/quoting/proposals", {
        method: "POST",
        body: JSON.stringify({
          customer_id: selectedCustomer.id,
          property_id: selectedPropertyId,
          title: `Roof Proposal — ${selectedCustomer.display_name}`,
          quote_snapshot: snapshot,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const proposal = await r.json();
      setProposalCreated({ id: proposal.id });
    } catch (e: unknown) {
      setProposalError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingProposal(false);
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
        {contacts.length > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <div style={{ marginBottom: 12, fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Contacts</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {contacts.map((c) => (
                <div key={c.id} style={{ display: "flex", gap: 16, fontSize: 13, padding: "6px 0", borderBottom: `1px solid ${BRAND.border}` }}>
                  <span style={{ fontWeight: 600, color: BRAND.navyText, minWidth: 140 }}>{c.name}</span>
                  {c.is_primary && <Badge tone="blue">Primary</Badge>}
                  {c.role && <span style={{ color: BRAND.sub }}>{c.role}</span>}
                  {c.email && <a href={`mailto:${c.email}`} style={{ color: BRAND.navyText }}>{c.email}</a>}
                  {c.phone && <span style={{ color: BRAND.sub }}>{c.phone}</span>}
                </div>
              ))}
            </div>
          </Card>
        )}

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

        <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
          <Card>
            <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 14 }}>Estimate inputs</div>

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
              </div>
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

          {/* Result panel */}
          <div>
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
                    </div>
                    <span style={{
                      fontSize: 12, fontWeight: 700, padding: "3px 12px", borderRadius: 20,
                      background: quoteResult.margin_ok ? "#e6f9f0" : "#fef2f2",
                      color: quoteResult.margin_ok ? "#1a7f4b" : BRAND.red,
                    }}>
                      {quoteResult.margin_ok ? "Margin OK" : "Margin LOW"}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <TierCard label="Good" value={usd(quoteResult.project_total)} />
                    <TierCard label="Better" value={usd(Math.round(quoteResult.project_total * 1.15))} recommended />
                    <TierCard label="Best" value={usd(Math.round(quoteResult.project_total * 1.30))} />
                  </div>
                  <SectionLabel>Profitability</SectionLabel>
                  <ResultRow label="Profit" value={usd(quoteResult.profit_dollars)} />
                  <ResultRow label="Profit %" value={(quoteResult.profit_pct * 100).toFixed(1) + "%"} />
                  <ResultRow label="Est. Commission" value={usd(quoteResult.estimated_commission)} />
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
                    <Button onClick={handleCreateProposal} disabled={creatingProposal || !selectedPropertyId} style={{ fontSize: 13, width: "100%" }}>
                      {creatingProposal ? "Creating…" : "Create proposal draft"}
                    </Button>
                  )}
                  {proposalError && <div style={{ marginTop: 8 }}><ErrorMsg>Error: {proposalError}</ErrorMsg></div>}
                </Card>
              </div>
            )}
          </div>
        </div>
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
          <CustomerForm onSave={handleCreateCustomer} onCancel={() => { setShowNewCustomer(false); setCustomerFormError(null); }} saving={savingCustomer} />
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

      {customersLoading && <Loading label="Loading customers…" />}
      {customersError && <ErrorMsg>Error: {customersError}</ErrorMsg>}

      {!customersLoading && !customersError && search.trim() && filteredCustomers.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No customers matching "{search}". Use + New customer to add them.
          </p>
        </Card>
      )}

      {!search.trim() && !showNewCustomer && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            Start typing to find a customer, then choose the property, measurement, and estimate.
          </p>
        </Card>
      )}

      {search.trim() && filteredCustomers.length > 0 && (
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
