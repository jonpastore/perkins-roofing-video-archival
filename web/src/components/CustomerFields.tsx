import type { BranchRow } from "../api";
import { inputStyle, SectionLabel } from "../ui";

// Shared customer-detail fields for the add/edit forms in Customers.tsx and
// Quoting.tsx. Presentational only — parents own submit + any extra sections
// (property/measurement in Customers, edit-reuse in Quoting).
export interface CustomerFieldValues {
  display_name: string;
  company_name: string;
  email: string;
  phone: string;
  notes: string;
  branch: string;
}

export function emptyCustomerFields(
  initial?: Partial<Record<keyof CustomerFieldValues, string | null | undefined>>,
): CustomerFieldValues {
  return {
    display_name: initial?.display_name ?? "",
    company_name: initial?.company_name ?? "",
    email: initial?.email ?? "",
    phone: initial?.phone ?? "",
    notes: initial?.notes ?? "",
    branch: initial?.branch ?? "miami",
  };
}

// Map the form values onto the null-for-empty shape the API expects.
export function customerFieldsToInput(v: CustomerFieldValues) {
  return {
    display_name: v.display_name.trim(),
    company_name: v.company_name || null,
    email: v.email || null,
    phone: v.phone || null,
    notes: v.notes || null,
    branch: v.branch || null,
  };
}

export function CustomerFields({
  value,
  onChange,
  branches,
  autoFocus,
  disabled,
}: {
  value: CustomerFieldValues;
  onChange: (patch: Partial<CustomerFieldValues>) => void;
  branches: BranchRow[];
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const inp = { ...inputStyle, width: "100%", fontSize: 13 } as const;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <div>
        <SectionLabel>Name *</SectionLabel>
        <input value={value.display_name} onChange={(e) => onChange({ display_name: e.target.value })} style={inp} placeholder="Full name" autoFocus={autoFocus} disabled={disabled} />
      </div>
      <div>
        <SectionLabel>Company</SectionLabel>
        <input value={value.company_name} onChange={(e) => onChange({ company_name: e.target.value })} style={inp} placeholder="Optional" disabled={disabled} />
      </div>
      <div>
        <SectionLabel>Email</SectionLabel>
        <input type="email" value={value.email} onChange={(e) => onChange({ email: e.target.value })} style={inp} placeholder="email@example.com" disabled={disabled} />
      </div>
      <div>
        <SectionLabel>Phone</SectionLabel>
        <input type="tel" value={value.phone} onChange={(e) => onChange({ phone: e.target.value })} style={inp} placeholder="(555) 555-5555" disabled={disabled} />
      </div>
      <div>
        <SectionLabel>Branch</SectionLabel>
        <select value={value.branch || "miami"} onChange={(e) => onChange({ branch: e.target.value })} style={inp} disabled={disabled}>
          {branches.map((b) => (
            <option key={b.key} value={b.key}>{b.name}</option>
          ))}
        </select>
      </div>
      <div style={{ gridColumn: "1 / -1" }}>
        <SectionLabel>Notes</SectionLabel>
        <textarea value={value.notes} onChange={(e) => onChange({ notes: e.target.value })} rows={2} style={{ ...inp, resize: "vertical" }} placeholder="Internal notes…" disabled={disabled} />
      </div>
    </div>
  );
}
