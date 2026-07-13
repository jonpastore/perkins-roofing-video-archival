import { useContext, useEffect, useState, useCallback, useRef } from "react";
import {
  apiFetch,
  listQuotingCustomersPaged,
  getQuotingCustomer,
  createCustomer,
  updateCustomer,
  deactivateCustomer,
  addCustomerContact,
  addCustomerProperty,
  updateProperty,
  deleteProperty,
} from "../api";
import type {
  QuotingCustomer,
  QuotingCustomerDetail,
  QuotingProperty,
  CustomerInput,
  ContactInput,
  PropertyInput,
} from "../api";
import { NavContext } from "../App";
import { DataTable } from "../ui/DataTable";
import type { QueryState, ColDef } from "../ui/DataTable";
import {
  BRAND,
  FONT,
  Button,
  Card,
  Badge,
  Loading,
  ErrorMsg,
  PageTitle,
  inputStyle,
  SectionLabel,
} from "../ui";

type CustomerListRow = QuotingCustomer & {
  property_count?: number;
  measurement_count?: number;
};

type PropertyDetailRow = QuotingProperty & {
  measurement_count?: number;
  latest_measurement_total_sq?: number | null;
};

function ModalShell({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "32px 16px", overflowY: "auto" }}>
      <div style={{ width: "min(860px, 96vw)", background: "#fff", borderRadius: 12, boxShadow: "0 20px 50px rgba(16,24,40,0.22)", fontFamily: FONT }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: `1px solid ${BRAND.border}` }}>
          <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 16 }}>{title}</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 22, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: 20 }}>{children}</div>
      </div>
    </div>
  );
}

// ── New Customer form ─────────────────────────────────────────────────────────

interface NewCustomerFormProps {
  onSaved: (c: QuotingCustomer) => void;
  onCancel: () => void;
}

function NewCustomerForm({ onSaved, onCancel }: NewCustomerFormProps) {
  const [form, setForm] = useState<CustomerInput>({ display_name: "", company_name: "", email: "", phone: "" });
  const [property, setProperty] = useState<PropertyInput>({ street: "", city: "", state: "FL", zip: "", county: "", code_zone: "FBC" });
  const [measurementSq, setMeasurementSq] = useState("");
  const [measurementNote, setMeasurementNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(field: keyof CustomerInput, value: string) {
    setForm((f) => ({ ...f, [field]: value || null }));
  }
  function setProp(field: keyof PropertyInput, value: string) {
    setProperty((f) => ({ ...f, [field]: value || null }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.display_name.trim()) { setErr("Display name is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      const c = await createCustomer({ ...form, display_name: form.display_name.trim() });
      if (property.street?.trim()) {
        const prop = await addCustomerProperty(c.id, { ...property, street: property.street.trim() });
        if (measurementSq.trim()) {
          await apiFetch("/measurements", {
            method: "POST",
            body: JSON.stringify({
              property_id: prop.id,
              total_sq: Number(measurementSq),
              provenance_note: measurementNote.trim() || "Manual entry during customer setup",
            }),
          });
        }
      }
      onSaved(c);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card style={{ marginBottom: 20 }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, marginBottom: 16 }}>New Customer</div>
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
          <div>
            <SectionLabel>Display Name *</SectionLabel>
            <input style={{ ...inputStyle, width: "100%" }} value={form.display_name} onChange={(e) => set("display_name", e.target.value)} placeholder="Full name" autoFocus />
          </div>
          <div>
            <SectionLabel>Company</SectionLabel>
            <input style={{ ...inputStyle, width: "100%" }} value={form.company_name ?? ""} onChange={(e) => set("company_name", e.target.value)} placeholder="Company name" />
          </div>
          <div>
            <SectionLabel>Email</SectionLabel>
            <input type="email" style={{ ...inputStyle, width: "100%" }} value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} placeholder="email@example.com" />
          </div>
          <div>
            <SectionLabel>Phone</SectionLabel>
            <input type="tel" style={{ ...inputStyle, width: "100%" }} value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} placeholder="(555) 555-5555" />
          </div>
        </div>
        <div style={{ borderTop: `1px solid ${BRAND.border}`, paddingTop: 14, marginTop: 14 }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 13, marginBottom: 8 }}>Initial property and measurement (optional)</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div style={{ gridColumn: "1 / -1" }}>
              <SectionLabel>Property street</SectionLabel>
              <input style={{ ...inputStyle, width: "100%" }} value={property.street ?? ""} onChange={(e) => setProp("street", e.target.value)} placeholder="123 Main St" />
            </div>
            <div><SectionLabel>City</SectionLabel><input style={{ ...inputStyle, width: "100%" }} value={property.city ?? ""} onChange={(e) => setProp("city", e.target.value)} /></div>
            <div><SectionLabel>State</SectionLabel><input style={{ ...inputStyle, width: "100%" }} value={property.state ?? ""} onChange={(e) => setProp("state", e.target.value)} /></div>
            <div><SectionLabel>ZIP</SectionLabel><input style={{ ...inputStyle, width: "100%" }} value={property.zip ?? ""} onChange={(e) => setProp("zip", e.target.value)} /></div>
            <div><SectionLabel>Code Zone</SectionLabel><input style={{ ...inputStyle, width: "100%" }} value={property.code_zone ?? ""} onChange={(e) => setProp("code_zone", e.target.value)} /></div>
            <div><SectionLabel>Roof squares</SectionLabel><input type="number" min="0" step="0.5" style={{ ...inputStyle, width: "100%" }} value={measurementSq} onChange={(e) => setMeasurementSq(e.target.value)} placeholder="Optional" /></div>
            <div><SectionLabel>Measurement note</SectionLabel><input style={{ ...inputStyle, width: "100%" }} value={measurementNote} onChange={(e) => setMeasurementNote(e.target.value)} placeholder="Roofr, EagleView, manual…" /></div>
          </div>
        </div>
        {err && <ErrorMsg>{err}</ErrorMsg>}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Create Customer"}</Button>
        </div>
      </form>
    </Card>
  );
}

// ── Edit Customer form ────────────────────────────────────────────────────────

interface EditCustomerFormProps {
  customer: QuotingCustomer;
  onSaved: (c: QuotingCustomer) => void;
  onCancel: () => void;
}

function EditCustomerForm({ customer, onSaved, onCancel }: EditCustomerFormProps) {
  const [form, setForm] = useState<CustomerInput>({
    display_name: customer.display_name,
    company_name: customer.company_name,
    email: customer.email,
    phone: customer.phone,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(field: keyof CustomerInput, value: string) {
    setForm((f) => ({ ...f, [field]: value || null }));
  }
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.display_name.trim()) { setErr("Display name is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      const c = await updateCustomer(customer.id, { ...form, display_name: form.display_name.trim() });
      onSaved(c);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <SectionLabel>Display Name *</SectionLabel>
          <input style={{ ...inputStyle, width: "100%" }} value={form.display_name} onChange={(e) => set("display_name", e.target.value)} />
        </div>
        <div>
          <SectionLabel>Company</SectionLabel>
          <input style={{ ...inputStyle, width: "100%" }} value={form.company_name ?? ""} onChange={(e) => set("company_name", e.target.value)} />
        </div>
        <div>
          <SectionLabel>Email</SectionLabel>
          <input type="email" style={{ ...inputStyle, width: "100%" }} value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} />
        </div>
        <div>
          <SectionLabel>Phone</SectionLabel>
          <input type="tel" style={{ ...inputStyle, width: "100%" }} value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} />
        </div>
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save Changes"}</Button>
      </div>
    </form>
  );
}

// ── Add Contact form ──────────────────────────────────────────────────────────

interface AddContactFormProps {
  customerId: number;
  onSaved: () => void;
  onCancel: () => void;
}

function AddContactForm({ customerId, onSaved, onCancel }: AddContactFormProps) {
  const [form, setForm] = useState<ContactInput>({ name: "", role: "", email: "", phone: "" });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(field: keyof ContactInput, value: string) {
    setForm((f) => ({ ...f, [field]: value || null }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { setErr("Contact name is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      await addCustomerContact(customerId, { ...form, name: form.name.trim() });
      onSaved();
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginTop: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <SectionLabel>Name *</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Contact name" autoFocus />
        </div>
        <div>
          <SectionLabel>Role</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.role ?? ""} onChange={(e) => set("role", e.target.value)} placeholder="e.g. Owner" />
        </div>
        <div>
          <SectionLabel>Email</SectionLabel>
          <input type="email" style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} />
        </div>
        <div>
          <SectionLabel>Phone</SectionLabel>
          <input type="tel" style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} />
        </div>
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
      <div style={{ display: "flex", gap: 8 }}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving} style={{ fontSize: 13 }}>Cancel</Button>
        <Button type="submit" disabled={saving} style={{ fontSize: 13 }}>{saving ? "Saving…" : "Add Contact"}</Button>
      </div>
    </form>
  );
}

// ── Add Property form ─────────────────────────────────────────────────────────

interface AddPropertyFormProps {
  customerId: number;
  onSaved: (p: QuotingProperty) => void;
  onCancel: () => void;
}

function AddPropertyForm({ customerId, onSaved, onCancel }: AddPropertyFormProps) {
  const [form, setForm] = useState<PropertyInput>({ street: "", city: "", state: "", zip: "", county: "", code_zone: "" });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(field: keyof PropertyInput, value: string) {
    setForm((f) => ({ ...f, [field]: value || null }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.street?.trim()) { setErr("Street address is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      const p = await addCustomerProperty(customerId, { ...form, street: form.street!.trim() });
      onSaved(p);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginTop: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div style={{ gridColumn: "1 / -1" }}>
          <SectionLabel>Street *</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.street ?? ""} onChange={(e) => set("street", e.target.value)} placeholder="123 Main St" autoFocus />
        </div>
        <div>
          <SectionLabel>City</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.city ?? ""} onChange={(e) => set("city", e.target.value)} />
        </div>
        <div>
          <SectionLabel>State</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.state ?? ""} onChange={(e) => set("state", e.target.value)} placeholder="FL" />
        </div>
        <div>
          <SectionLabel>ZIP</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.zip ?? ""} onChange={(e) => set("zip", e.target.value)} />
        </div>
        <div>
          <SectionLabel>County</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.county ?? ""} onChange={(e) => set("county", e.target.value)} />
        </div>
        <div>
          <SectionLabel>Code Zone</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.code_zone ?? ""} onChange={(e) => set("code_zone", e.target.value)} placeholder="HVHZ / non-HVHZ" />
        </div>
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
      <div style={{ display: "flex", gap: 8 }}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving} style={{ fontSize: 13 }}>Cancel</Button>
        <Button type="submit" disabled={saving} style={{ fontSize: 13 }}>{saving ? "Saving…" : "Add Property"}</Button>
      </div>
    </form>
  );
}

interface EditPropertyFormProps {
  property: QuotingProperty;
  onSaved: (p: QuotingProperty) => void;
  onCancel: () => void;
}

function EditPropertyForm({ property, onSaved, onCancel }: EditPropertyFormProps) {
  const [form, setForm] = useState<PropertyInput>({
    street: property.street,
    city: property.city,
    state: property.state,
    zip: property.zip,
    county: property.county,
    code_zone: property.code_zone,
    notes: property.notes ?? null,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(field: keyof PropertyInput, value: string) {
    setForm((f) => ({ ...f, [field]: value || null }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.street?.trim()) { setErr("Street address is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      const p = await updateProperty(property.id, { ...form, street: form.street.trim() });
      onSaved(p);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${BRAND.border}` }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div style={{ gridColumn: "1 / -1" }}>
          <SectionLabel>Street *</SectionLabel>
          <input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.street ?? ""} onChange={(e) => set("street", e.target.value)} autoFocus />
        </div>
        <div><SectionLabel>City</SectionLabel><input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.city ?? ""} onChange={(e) => set("city", e.target.value)} /></div>
        <div><SectionLabel>State</SectionLabel><input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.state ?? ""} onChange={(e) => set("state", e.target.value)} /></div>
        <div><SectionLabel>ZIP</SectionLabel><input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.zip ?? ""} onChange={(e) => set("zip", e.target.value)} /></div>
        <div><SectionLabel>County</SectionLabel><input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.county ?? ""} onChange={(e) => set("county", e.target.value)} /></div>
        <div><SectionLabel>Code Zone</SectionLabel><input style={{ ...inputStyle, width: "100%", fontSize: 13 }} value={form.code_zone ?? ""} onChange={(e) => set("code_zone", e.target.value)} /></div>
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
      <div style={{ display: "flex", gap: 8 }}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving} style={{ fontSize: 13 }}>Cancel</Button>
        <Button type="submit" disabled={saving} style={{ fontSize: 13 }}>{saving ? "Saving…" : "Save Property"}</Button>
      </div>
    </form>
  );
}

// ── Customer detail panel ─────────────────────────────────────────────────────

interface DetailPanelProps {
  customerId: number;
  onClose: () => void;
  onCustomerUpdated: (c: QuotingCustomer) => void;
}

type DetailSubPanel = "edit" | "addContact" | "addProperty" | null;

function DetailPanel({ customerId, onClose, onCustomerUpdated }: DetailPanelProps) {
  const [detail, setDetail] = useState<QuotingCustomerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [subPanel, setSubPanel] = useState<DetailSubPanel>(null);
  const [deactivating, setDeactivating] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [editingPropertyId, setEditingPropertyId] = useState<number | null>(null);
  const [removingPropertyId, setRemovingPropertyId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setErr(null);
    getQuotingCustomer(customerId)
      .then(setDetail)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  async function handleDeactivate() {
    if (!confirmDeactivate) { setConfirmDeactivate(true); return; }
    setDeactivating(true);
    try {
      const updated = await deactivateCustomer(customerId);
      onCustomerUpdated(updated);
      setDetail((d) => d ? { ...d, is_active: false } : d);
      setConfirmDeactivate(false);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setDeactivating(false);
    }
  }

  async function handleRemoveProperty(propertyId: number) {
    setRemovingPropertyId(propertyId);
    setErr(null);
    try {
      await deleteProperty(propertyId);
      setDetail((d) => d ? { ...d, properties: d.properties.filter((p) => p.id !== propertyId) } : d);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setRemovingPropertyId(null);
    }
  }

  return (
    <Card style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>
          {detail ? detail.display_name : "Customer Detail"}
        </div>
        <Button variant="ghost" onClick={onClose} style={{ fontSize: 13, padding: "6px 14px" }}>Close</Button>
      </div>

      {loading && <Loading label="Loading customer…" />}
      {err && <ErrorMsg>{err}</ErrorMsg>}

      {detail && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <Badge tone={detail.is_active ? "green" : "gray"}>
              {detail.is_active ? "Active" : "Inactive"}
            </Badge>
            {detail.company_name && (
              <span style={{ fontSize: 13, color: BRAND.sub }}>{detail.company_name}</span>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 20, fontSize: 13 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>Email</div>
              <div style={{ color: BRAND.ink }}>{detail.email ?? "—"}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>Phone</div>
              <div style={{ color: BRAND.ink }}>{detail.phone ?? "—"}</div>
            </div>
          </div>

          {subPanel === null && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
              <Button variant="ghost" onClick={() => setSubPanel("edit")} style={{ fontSize: 13 }}>Edit</Button>
              <Button variant="ghost" onClick={() => setSubPanel("addProperty")} style={{ fontSize: 13 }}>Add Property</Button>
              <Button variant="ghost" onClick={() => setSubPanel("addContact")} style={{ fontSize: 13 }}>Add Contact</Button>
              {detail.is_active && (
                confirmDeactivate ? (
                  <>
                    <span style={{ fontSize: 13, color: BRAND.redDark, alignSelf: "center" }}>
                      Deactivate (soft delete — customer becomes inactive)?
                    </span>
                    <Button variant="danger" onClick={handleDeactivate} disabled={deactivating} style={{ fontSize: 13 }}>
                      {deactivating ? "Deactivating…" : "Confirm Deactivate"}
                    </Button>
                    <Button variant="ghost" onClick={() => setConfirmDeactivate(false)} style={{ fontSize: 13 }}>Cancel</Button>
                  </>
                ) : (
                  <Button variant="danger" onClick={handleDeactivate} style={{ fontSize: 13 }}>
                    Deactivate
                  </Button>
                )
              )}
            </div>
          )}

          {subPanel === "edit" && (
            <EditCustomerForm
              customer={detail}
              onSaved={(c) => {
                setDetail((d) => d ? { ...d, ...c } : d);
                onCustomerUpdated(c);
                setSubPanel(null);
              }}
              onCancel={() => setSubPanel(null)}
            />
          )}
          {subPanel === "addContact" && (
            <AddContactForm
              customerId={detail.id}
              onSaved={() => setSubPanel(null)}
              onCancel={() => setSubPanel(null)}
            />
          )}
          {subPanel === "addProperty" && (
            <AddPropertyForm
              customerId={detail.id}
              onSaved={(p) => {
                setDetail((d) => d ? { ...d, properties: [...d.properties, p] } : d);
                setSubPanel(null);
              }}
              onCancel={() => setSubPanel(null)}
            />
          )}

          {detail.properties.length > 0 && (
            <>
              <SectionLabel>Properties ({detail.properties.length})</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {detail.properties.map((prop) => {
                  const propWithMeasurements = prop as PropertyDetailRow;
                  return (
                    <div
                      key={prop.id}
                      style={{
                        padding: "10px 14px",
                        background: BRAND.bg,
                        borderRadius: 8,
                        fontSize: 13,
                        border: `1px solid ${BRAND.border}`,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                        <div style={{ fontWeight: 600, color: BRAND.navyText }}>{prop.street}</div>
                        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                          <button
                            type="button"
                            onClick={() => setEditingPropertyId((prev) => prev === prop.id ? null : prop.id)}
                            style={{ background: "none", border: "none", color: BRAND.navyText, cursor: "pointer", fontSize: 12, fontWeight: 700 }}
                          >
                            {editingPropertyId === prop.id ? "Cancel edit" : "Edit"}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (window.confirm("Remove this property? Properties linked to measurements/proposals will be blocked.")) {
                                void handleRemoveProperty(prop.id);
                              }
                            }}
                            disabled={removingPropertyId === prop.id}
                            style={{ background: "none", border: "none", color: BRAND.redDark, cursor: "pointer", fontSize: 12, fontWeight: 700 }}
                          >
                            {removingPropertyId === prop.id ? "Removing…" : "Remove"}
                          </button>
                        </div>
                      </div>
                      <div style={{ color: BRAND.sub, marginTop: 2, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span>{[prop.city, prop.state, prop.zip].filter(Boolean).join(", ")}</span>
                        {prop.county && <span>· {prop.county} County</span>}
                        {prop.code_zone && (
                          <Badge tone={prop.code_zone.toUpperCase().includes("HVHZ") ? "amber" : "blue"}>
                            {prop.code_zone}
                          </Badge>
                        )}
                        {propWithMeasurements.measurement_count != null && (
                          <Badge tone={propWithMeasurements.measurement_count > 0 ? "green" : "gray"}>
                            {propWithMeasurements.measurement_count > 0
                              ? `${propWithMeasurements.measurement_count} measurement${propWithMeasurements.measurement_count === 1 ? "" : "s"}`
                              : "No measurements"}
                          </Badge>
                        )}
                        {propWithMeasurements.latest_measurement_total_sq != null && (
                          <span>· latest {propWithMeasurements.latest_measurement_total_sq.toFixed(1)} sq</span>
                        )}
                      </div>
                      {editingPropertyId === prop.id && (
                        <EditPropertyForm
                          property={prop}
                          onSaved={(updated) => {
                            setDetail((d) => d ? {
                              ...d,
                              properties: d.properties.map((p) => p.id === updated.id ? updated : p),
                            } : d);
                            setEditingPropertyId(null);
                          }}
                          onCancel={() => setEditingPropertyId(null)}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {detail.properties.length === 0 && subPanel !== "addProperty" && (
            <div style={{ fontSize: 13, color: BRAND.sub, marginTop: 8 }}>
              No properties yet. Use "Add Property" above.
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function Customers() {
  const { params } = useContext(NavContext);
  const [rows, setRows] = useState<QuotingCustomer[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [query, setQuery] = useState<QueryState>({ search: "", sort: null, page: 1, pageSize: 50 });
  // undefined = all, true = active only
  const [activeFilter, setActiveFilter] = useState<true | undefined>(true);

  const [showNewForm, setShowNewForm] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const seqRef = useRef(0);

  const doFetch = useCallback((q: QueryState, isActive: true | undefined) => {
    const seq = ++seqRef.current;
    setLoading(true);
    setErr(null);
    listQuotingCustomersPaged({
      search: q.search || undefined,
      sort: q.sort?.key,
      order: q.sort?.dir,
      page: q.page,
      limit: q.pageSize,
      is_active: isActive,
    })
      .then(({ items, total: t }) => {
        if (seq !== seqRef.current) return;
        setRows(items);
        setTotal(t);
      })
      .catch((e: unknown) => {
        if (seq !== seqRef.current) return;
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => { if (seq === seqRef.current) setLoading(false); });
  }, []);

  useEffect(() => { doFetch(query, activeFilter); }, [doFetch, query, activeFilter]);

  useEffect(() => {
    const raw = params.customerId;
    if (!raw) return;
    const id = Number(raw);
    if (Number.isFinite(id) && id > 0) setSelectedId(id);
  }, [params.customerId]);

  function handleQueryChange(q: QueryState) {
    setQuery(q);
  }

  function handleCustomerUpdated(c: QuotingCustomer) {
    setRows((prev) => prev.map((r) => (r.id === c.id ? { ...r, ...c } : r)));
  }

  function handleNewSaved(c: QuotingCustomer) {
    setShowNewForm(false);
    setQuery((q) => ({ ...q, page: 1 }));
    setSelectedId(c.id);
  }

  // Columns — display_name uses a clickable button for row selection
  const columns: ColDef<CustomerListRow>[] = [
    {
      key: "display_name" as const,
      header: "Name",
      sortable: true,
      render: (r: CustomerListRow) => (
        <button
          onClick={() => { setShowNewForm(false); setSelectedId((prev) => (prev === r.id ? null : r.id)); }}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            color: BRAND.navyText,
            fontWeight: 600,
            fontSize: 13,
            cursor: "pointer",
            textAlign: "left",
            fontFamily: FONT,
            textDecoration: selectedId === r.id ? "underline" : "none",
          }}
        >
          {r.display_name}
        </button>
      ),
    },
    {
      key: "company_name" as const,
      header: "Company",
      sortable: true,
      render: (r: CustomerListRow) => r.company_name ?? "—",
    },
    {
      key: "email" as const,
      header: "Email",
      sortable: true,
      render: (r: CustomerListRow) => r.email ?? "—",
    },
    {
      key: "phone" as const,
      header: "Phone",
      sortable: false,
      render: (r: CustomerListRow) => r.phone ?? "—",
    },
    {
      key: "property_count" as const,
      header: "Property / Measure",
      sortable: false,
      render: (row: CustomerListRow) => {
        // Flags only render when the API supplies the counts (older payloads omit them).
        if (row.property_count == null && row.measurement_count == null) return "—";
        const propCount = row.property_count ?? 0;
        const measCount = row.measurement_count ?? 0;
        return (
          <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
            <Badge tone={propCount > 0 ? "blue" : "gray"}>
              {propCount > 0 ? `${propCount} prop${propCount === 1 ? "" : "s"}` : "No property"}
            </Badge>
            <Badge tone={measCount > 0 ? "green" : "gray"}>
              {measCount > 0 ? `${measCount} measure${measCount === 1 ? "" : "s"}` : "No measure"}
            </Badge>
          </span>
        );
      },
    },
    {
      key: "is_active" as const,
      header: "Status",
      sortable: false,
      render: (r: CustomerListRow) => (
        <Badge tone={r.is_active ? "green" : "gray"}>{r.is_active ? "Active" : "Inactive"}</Badge>
      ),
    },
  ];

  return (
    <main style={{ maxWidth: 1100, fontFamily: FONT }}>
      <PageTitle right={
        <Button
          onClick={() => { setShowNewForm(true); setSelectedId(null); }}
          style={{ fontSize: 13 }}
        >
          New Customer
        </Button>
      }>
        Customers
      </PageTitle>

      {/* Active filter toggle */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {([["Active only", true], ["All", undefined]] as [string, true | undefined][]).map(([label, val]) => {
          const active = activeFilter === val;
          return (
            <button
              key={label}
              onClick={() => setActiveFilter(val)}
              style={{
                padding: "7px 18px",
                borderRadius: 20,
                border: active ? `2px solid ${BRAND.navy}` : `2px solid ${BRAND.border}`,
                background: active ? BRAND.navy : "#fff",
                color: active ? "#fff" : BRAND.sub,
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                fontFamily: FONT,
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {showNewForm && (
        <ModalShell title="New Customer" onClose={() => setShowNewForm(false)}>
          <NewCustomerForm
            onSaved={handleNewSaved}
            onCancel={() => setShowNewForm(false)}
          />
        </ModalShell>
      )}

      {selectedId !== null && (
        <ModalShell title="Customer" onClose={() => setSelectedId(null)}>
          <DetailPanel
            customerId={selectedId}
            onClose={() => setSelectedId(null)}
            onCustomerUpdated={handleCustomerUpdated}
          />
        </ModalShell>
      )}

      {err && <ErrorMsg>{err}</ErrorMsg>}

      <DataTable<CustomerListRow>
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={loading}
        error={null}
        onQueryChange={handleQueryChange}
        totalRows={total}
        defaultPageSize={50}
      />
    </main>
  );
}
