import { useEffect, useState } from "react";
import {
  listQuotingCustomers,
  getQuotingCustomer,
  generateProposal,
  openAuthedPdf,
  type QuotingCustomer,
  type QuotingCustomerDetail,
  type QuotingProperty,
  type ProposalScopeInput,
  type ProposalExtraLine,
  type ProposalDiscount,
  type GenerateProposalResult,
} from "../api";
import {
  BRAND,
  FONT,
  Button,
  Card,
  PageTitle,
  inputStyle,
  Loading,
  ErrorMsg,
  SectionLabel,
} from "../ui";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUSD(s: string): string {
  const n = parseFloat(s);
  if (isNaN(n)) return s;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function propLabel(p: QuotingProperty): string {
  return `${p.street}, ${p.city} ${p.state}${p.zip ? " " + p.zip : ""}`;
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
    <label
      style={{
        display: "block",
        fontSize: 12,
        fontWeight: 600,
        color: BRAND.sub,
        marginBottom: 4,
        textTransform: "uppercase",
        letterSpacing: 0.3,
      }}
    >
      {children}
    </label>
  );
}

// ── Scope row ─────────────────────────────────────────────────────────────────

interface ScopeRow {
  key: number;
  roof_system: string;
  tier: string;
  squares: string;
  unit_price: string;
  description: string;
  is_optional: boolean;
  included: boolean;
}

function ScopeRowEditor({
  row,
  onChange,
  onRemove,
  canRemove,
}: {
  row: ScopeRow;
  onChange: (r: ScopeRow) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const upd = (patch: Partial<ScopeRow>) => onChange({ ...row, ...patch });
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "130px 1fr 80px 90px 1fr auto auto auto",
        gap: 8,
        alignItems: "end",
        padding: "10px 0",
        borderBottom: `1px solid ${BRAND.border}`,
      }}
    >
      <div>
        <FieldLabel>System</FieldLabel>
        <select
          value={row.roof_system}
          onChange={(e) => upd({ roof_system: e.target.value })}
          style={selectStyle}
        >
          <option value="">— pick —</option>
          <option value="shingle">Shingle</option>
          <option value="tile">Tile</option>
          <option value="flat">Flat</option>
          <option value="metal">Metal</option>
        </select>
      </div>
      <div>
        <FieldLabel>Tier</FieldLabel>
        <input
          value={row.tier}
          onChange={(e) => upd({ tier: e.target.value })}
          placeholder="PROTECTOR / COASTAL / PREMIUM_CARIBBEAN"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Squares</FieldLabel>
        <input
          type="number"
          min="0"
          step="0.5"
          value={row.squares}
          onChange={(e) => upd({ squares: e.target.value })}
          placeholder="e.g. 28"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>$/sq</FieldLabel>
        <input
          type="number"
          min="0"
          step="0.01"
          value={row.unit_price}
          onChange={(e) => upd({ unit_price: e.target.value })}
          placeholder="override"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Description</FieldLabel>
        <input
          value={row.description}
          onChange={(e) => upd({ description: e.target.value })}
          placeholder="optional"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>Optional</FieldLabel>
        <input
          type="checkbox"
          checked={row.is_optional}
          onChange={(e) => upd({ is_optional: e.target.checked, included: e.target.checked ? row.included : false })}
          style={{ marginTop: 6, width: 16, height: 16, cursor: "pointer" }}
        />
      </div>
      {row.is_optional && (
        <div style={{ paddingBottom: 2 }}>
          <FieldLabel>Included</FieldLabel>
          <input
            type="checkbox"
            checked={row.included}
            onChange={(e) => upd({ included: e.target.checked })}
            style={{ marginTop: 6, width: 16, height: 16, cursor: "pointer" }}
          />
        </div>
      )}
      {!row.is_optional && <div />}
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>&nbsp;</FieldLabel>
        <Button
          variant="danger"
          disabled={!canRemove}
          onClick={onRemove}
          style={{ fontSize: 12, padding: "6px 10px" }}
        >
          ✕
        </Button>
      </div>
    </div>
  );
}

// ── Extra line row ────────────────────────────────────────────────────────────

interface ExtraRow {
  key: number;
  description: string;
  line_total: string;
  unit_price: string;
  qty: string;
  is_optional: boolean;
  is_metal: boolean;
}

function ExtraRowEditor({
  row,
  onChange,
  onRemove,
}: {
  row: ExtraRow;
  onChange: (r: ExtraRow) => void;
  onRemove: () => void;
}) {
  const upd = (patch: Partial<ExtraRow>) => onChange({ ...row, ...patch });
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 90px 90px 60px auto auto auto",
        gap: 8,
        alignItems: "end",
        padding: "10px 0",
        borderBottom: `1px solid ${BRAND.border}`,
      }}
    >
      <div>
        <FieldLabel>Description</FieldLabel>
        <input
          value={row.description}
          onChange={(e) => upd({ description: e.target.value })}
          placeholder="Extra line item"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Line total</FieldLabel>
        <input
          type="number"
          min="0"
          step="0.01"
          value={row.line_total}
          onChange={(e) => upd({ line_total: e.target.value })}
          placeholder="or unit+qty"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Unit price</FieldLabel>
        <input
          type="number"
          min="0"
          step="0.01"
          value={row.unit_price}
          onChange={(e) => upd({ unit_price: e.target.value })}
          placeholder="$/unit"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Qty</FieldLabel>
        <input
          type="number"
          min="0"
          step="1"
          value={row.qty}
          onChange={(e) => upd({ qty: e.target.value })}
          placeholder="1"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>Optional</FieldLabel>
        <input
          type="checkbox"
          checked={row.is_optional}
          onChange={(e) => upd({ is_optional: e.target.checked })}
          style={{ marginTop: 6, width: 16, height: 16, cursor: "pointer" }}
        />
      </div>
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>Metal (15-day expiry)</FieldLabel>
        <input
          type="checkbox"
          checked={row.is_metal}
          onChange={(e) => upd({ is_metal: e.target.checked })}
          style={{ marginTop: 6, width: 16, height: 16, cursor: "pointer" }}
        />
      </div>
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>&nbsp;</FieldLabel>
        <Button variant="danger" onClick={onRemove} style={{ fontSize: 12, padding: "6px 10px" }}>
          ✕
        </Button>
      </div>
    </div>
  );
}

// ── Discount row ──────────────────────────────────────────────────────────────

interface DiscountRow {
  key: number;
  description: string;
  amount: string;
}

function DiscountRowEditor({
  row,
  onChange,
  onRemove,
}: {
  row: DiscountRow;
  onChange: (r: DiscountRow) => void;
  onRemove: () => void;
}) {
  const upd = (patch: Partial<DiscountRow>) => onChange({ ...row, ...patch });
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 120px auto",
        gap: 8,
        alignItems: "end",
        padding: "10px 0",
        borderBottom: `1px solid ${BRAND.border}`,
      }}
    >
      <div>
        <FieldLabel>Description</FieldLabel>
        <input
          value={row.description}
          onChange={(e) => upd({ description: e.target.value })}
          placeholder="e.g. Senior discount"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div>
        <FieldLabel>Amount ($)</FieldLabel>
        <input
          type="number"
          min="0"
          step="0.01"
          value={row.amount}
          onChange={(e) => upd({ amount: e.target.value })}
          placeholder="500.00"
          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
        />
      </div>
      <div style={{ paddingBottom: 2 }}>
        <FieldLabel>&nbsp;</FieldLabel>
        <Button variant="danger" onClick={onRemove} style={{ fontSize: 12, padding: "6px 10px" }}>
          ✕
        </Button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

let _key = 0;
function nextKey() {
  return ++_key;
}

function emptyScope(): ScopeRow {
  return { key: nextKey(), roof_system: "", tier: "", squares: "", unit_price: "", description: "", is_optional: false, included: false };
}
function emptyExtra(): ExtraRow {
  return { key: nextKey(), description: "", line_total: "", unit_price: "", qty: "", is_optional: false, is_metal: false };
}
function emptyDiscount(): DiscountRow {
  return { key: nextKey(), description: "", amount: "" };
}

export function ProposalBuilder() {
  // Customer / property selection
  const [customers, setCustomers] = useState<QuotingCustomer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(false);
  const [customersError, setCustomersError] = useState<string | null>(null);

  const [selectedCustomerId, setSelectedCustomerId] = useState<number | "">("");
  const [customerDetail, setCustomerDetail] = useState<QuotingCustomerDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [selectedPropertyId, setSelectedPropertyId] = useState<number | "">("");

  // Editable printed name / address
  const [printedCustomer, setPrintedCustomer] = useState("");
  const [printedProperty, setPrintedProperty] = useState("");

  // Basic fields
  const [projectName, setProjectName] = useState("");
  const [hvhz, setHvhz] = useState(false);
  const [paymentVariant, setPaymentVariant] = useState<"standard" | "palmer">("standard");

  // Dynamic rows
  const [scopes, setScopes] = useState<ScopeRow[]>([emptyScope()]);
  const [extras, setExtras] = useState<ExtraRow[]>([]);
  const [discounts, setDiscounts] = useState<DiscountRow[]>([]);

  // Submit state
  const [submitting, setSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateProposalResult | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  // Load customers on mount (and on retry)
  const [customersRetry, setCustomersRetry] = useState(0);
  useEffect(() => {
    setCustomersLoading(true);
    setCustomersError(null);
    listQuotingCustomers({ limit: 200 })
      .then((data) => setCustomers(Array.isArray(data) ? data : []))
      .catch((e: unknown) => setCustomersError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCustomersLoading(false));
  }, [customersRetry]);

  // Load customer detail when selection changes
  useEffect(() => {
    if (!selectedCustomerId) {
      setCustomerDetail(null);
      setSelectedPropertyId("");
      setPrintedCustomer("");
      setPrintedProperty("");
      return;
    }
    setDetailLoading(true);
    getQuotingCustomer(selectedCustomerId as number)
      .then((detail) => {
        setCustomerDetail(detail);
        setPrintedCustomer(detail.display_name);
        const first = detail.properties[0] ?? null;
        if (first) {
          setSelectedPropertyId(first.id);
          setPrintedProperty(propLabel(first));
        } else {
          setSelectedPropertyId("");
          setPrintedProperty("");
        }
      })
      .catch(() => {
        setCustomerDetail(null);
      })
      .finally(() => setDetailLoading(false));
  }, [selectedCustomerId]);

  // Update printed property when property selection changes
  function handlePropertyChange(id: number) {
    setSelectedPropertyId(id);
    const prop = customerDetail?.properties.find((p) => p.id === id) ?? null;
    if (prop) setPrintedProperty(propLabel(prop));
  }

  // Scope helpers
  function updateScope(key: number, patch: Partial<ScopeRow>) {
    setScopes((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }
  function removeScope(key: number) {
    setScopes((prev) => prev.filter((r) => r.key !== key));
  }

  // Extra helpers
  function updateExtra(key: number, patch: Partial<ExtraRow>) {
    setExtras((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }
  function removeExtra(key: number) {
    setExtras((prev) => prev.filter((r) => r.key !== key));
  }

  // Discount helpers
  function updateDiscount(key: number, patch: Partial<DiscountRow>) {
    setDiscounts((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }
  function removeDiscount(key: number) {
    setDiscounts((prev) => prev.filter((r) => r.key !== key));
  }

  async function handleGenerate() {
    setValidationError(null);
    setSubmitError(null);

    // Validate
    if (!selectedCustomerId || !selectedPropertyId) {
      setValidationError("Select a customer and property before generating.");
      return;
    }
    const validScopes = scopes.filter((s) => s.roof_system);
    if (validScopes.length === 0) {
      setValidationError("Add at least one scope with a roof system selected.");
      return;
    }

    // Build scope inputs
    const scopeInputs: ProposalScopeInput[] = validScopes.map((s) => {
      const out: ProposalScopeInput = { roof_system: s.roof_system };
      if (s.tier.trim()) out.tier = s.tier.trim();
      if (s.squares.trim()) out.squares = s.squares.trim();
      else out.squares = null;
      if (s.unit_price.trim()) out.unit_price = s.unit_price.trim();
      else out.unit_price = null;
      if (s.description.trim()) out.description = s.description.trim();
      if (s.is_optional) out.is_optional = true;
      if (s.is_optional && s.included) out.included = true;
      return out;
    });

    // Build extra line inputs
    const extraInputs: ProposalExtraLine[] = extras
      .filter((e) => e.description.trim())
      .map((e) => {
        const out: ProposalExtraLine = { description: e.description.trim() };
        if (e.line_total.trim()) out.line_total = e.line_total.trim();
        if (e.unit_price.trim()) out.unit_price = e.unit_price.trim();
        else if (!e.line_total.trim()) out.unit_price = null;
        if (e.qty.trim()) out.qty = e.qty.trim();
        else if (!e.line_total.trim()) out.qty = null;
        if (e.is_optional) out.is_optional = true;
        if (e.is_metal) out.is_metal = true;
        return out;
      });

    // Build discount inputs
    const discountInputs: ProposalDiscount[] = discounts
      .filter((d) => d.description.trim() && d.amount.trim())
      .map((d) => ({ description: d.description.trim(), amount: d.amount.trim() }));

    setSubmitting(true);
    try {
      const res = await generateProposal({
        customer_id: selectedCustomerId as number,
        property_id: selectedPropertyId as number,
        inputs: {
          customer: printedCustomer,
          property: printedProperty,
          ...(projectName.trim() ? { project_name: projectName.trim() } : {}),
          ...(hvhz ? { hvhz: true } : {}),
          payment_variant: paymentVariant,
          scopes: scopeInputs,
          ...(extraInputs.length > 0 ? { extra_lines: extraInputs } : {}),
          ...(discountInputs.length > 0 ? { discounts: discountInputs } : {}),
        },
      });
      setResult(res);
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleViewPdf(id: number) {
    setPdfError(null);
    try {
      await openAuthedPdf(`/proposal-gen/${id}/pdf`);
    } catch (e: unknown) {
      setPdfError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleReset() {
    setResult(null);
    setSubmitError(null);
    setValidationError(null);
    setPdfError(null);
    setScopes([emptyScope()]);
    setExtras([]);
    setDiscounts([]);
    setProjectName("");
    setHvhz(false);
    setPaymentVariant("standard");
  }

  // ── Success view ─────────────────────────────────────────────────────────────

  if (result) {
    return (
      <main style={{ maxWidth: 720, fontFamily: FONT }}>
        <PageTitle>New Proposal</PageTitle>
        <Card>
          <div style={{ marginBottom: 20, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              background: "#e6f9f0",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 22,
            }}>
              ✓
            </div>
            <div>
              <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 16 }}>Proposal generated</div>
              <div style={{ fontSize: 13, color: BRAND.sub }}>Contract frozen and PDF ready</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 20 }}>
            <div style={{ background: BRAND.bg, borderRadius: 8, padding: "14px 16px" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                Contract Total
              </div>
              <div style={{ fontSize: 26, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>
                {fmtUSD(result.contract_total)}
              </div>
            </div>
            <div style={{ background: BRAND.bg, borderRadius: 8, padding: "14px 16px" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                Expiry
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, color: BRAND.navyText }}>
                Expires in {result.expiry_days} day{result.expiry_days !== 1 ? "s" : ""}
              </div>
            </div>
          </div>

          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 4 }}>Snapshot hash</div>
            <code style={{ fontFamily: "monospace", fontSize: 13, color: BRAND.navyText, background: BRAND.bg, padding: "4px 8px", borderRadius: 4 }}>
              {result.snapshot_hash.slice(0, 8)}
            </code>
          </div>

          {pdfError && <ErrorMsg>PDF error: {pdfError}</ErrorMsg>}

          <div style={{ display: "flex", gap: 10 }}>
            <Button onClick={() => handleViewPdf(result.id)}>View Contract PDF</Button>
            <Button variant="ghost" onClick={handleReset}>Start another</Button>
          </div>
        </Card>
      </main>
    );
  }

  // ── Form view ─────────────────────────────────────────────────────────────────

  const properties: QuotingProperty[] = customerDetail?.properties ?? [];

  return (
    <main style={{ maxWidth: 880, fontFamily: FONT }}>
      <PageTitle>New Proposal</PageTitle>

      {/* Customer + Property */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 14 }}>Customer &amp; Property</div>

        {customersLoading && <Loading label="Loading customers…" />}
        {customersError && (
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <ErrorMsg>Failed to load customers: {customersError}</ErrorMsg>
            <Button variant="ghost" onClick={() => setCustomersRetry((n) => n + 1)} style={{ fontSize: 12, padding: "6px 12px", flexShrink: 0 }}>
              Retry
            </Button>
          </div>
        )}

        {!customersLoading && !customersError && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <FieldLabel>Customer</FieldLabel>
              <select
                value={selectedCustomerId}
                onChange={(e) => setSelectedCustomerId(e.target.value ? Number(e.target.value) : "")}
                style={selectStyle}
              >
                <option value="">— Select customer —</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.display_name}</option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Property</FieldLabel>
              {detailLoading ? (
                <Loading label="Loading…" />
              ) : (
                <select
                  value={selectedPropertyId}
                  onChange={(e) => handlePropertyChange(Number(e.target.value))}
                  disabled={properties.length === 0}
                  style={selectStyle}
                >
                  {properties.length === 0 && <option value="">— Select customer first —</option>}
                  {properties.map((p) => (
                    <option key={p.id} value={p.id}>{propLabel(p)}</option>
                  ))}
                </select>
              )}
            </div>
            <div>
              <FieldLabel>Printed customer name</FieldLabel>
              <input
                value={printedCustomer}
                onChange={(e) => setPrintedCustomer(e.target.value)}
                placeholder="As it appears on the contract"
                style={{ ...inputStyle, width: "100%", fontSize: 13 }}
              />
            </div>
            <div>
              <FieldLabel>Printed property address</FieldLabel>
              <input
                value={printedProperty}
                onChange={(e) => setPrintedProperty(e.target.value)}
                placeholder="As it appears on the contract"
                style={{ ...inputStyle, width: "100%", fontSize: 13 }}
              />
            </div>
          </div>
        )}
      </Card>

      {/* Basic fields */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 14 }}>Project details</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 160px 180px", gap: 14, alignItems: "end" }}>
          <div>
            <FieldLabel>Project name (optional)</FieldLabel>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Full reroof — main house"
              style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            />
          </div>
          <div>
            <FieldLabel>Payment variant</FieldLabel>
            <select
              value={paymentVariant}
              onChange={(e) => setPaymentVariant(e.target.value as "standard" | "palmer")}
              style={selectStyle}
            >
              <option value="standard">Standard</option>
              <option value="palmer">Palmer</option>
            </select>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 10 }}>
            <input
              id="hvhz-check"
              type="checkbox"
              checked={hvhz}
              onChange={(e) => setHvhz(e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <label htmlFor="hvhz-check" style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText, cursor: "pointer" }}>
              HVHZ (Miami-Dade / Broward)
            </label>
          </div>
        </div>
      </Card>

      {/* Scopes */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Scopes</div>
          <Button
            variant="ghost"
            onClick={() => setScopes((prev) => [...prev, emptyScope()])}
            style={{ fontSize: 12 }}
          >
            + Add scope
          </Button>
        </div>
        <SectionLabel>Each scope becomes a line in the contract. Optional scopes excluded from total unless included.</SectionLabel>
        {scopes.map((s) => (
          <ScopeRowEditor
            key={s.key}
            row={s}
            onChange={(r) => updateScope(s.key, r)}
            onRemove={() => removeScope(s.key)}
            canRemove={scopes.length > 1}
          />
        ))}
      </Card>

      {/* Extra lines */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Extra lines</div>
          <Button
            variant="ghost"
            onClick={() => setExtras((prev) => [...prev, emptyExtra()])}
            style={{ fontSize: 12 }}
          >
            + Add line
          </Button>
        </div>
        <SectionLabel>Use line_total OR unit_price + qty. Metal lines trigger 15-day expiry.</SectionLabel>
        {extras.length === 0 && (
          <p style={{ margin: "8px 0 0", fontSize: 13, color: BRAND.sub }}>No extra lines.</p>
        )}
        {extras.map((e) => (
          <ExtraRowEditor
            key={e.key}
            row={e}
            onChange={(r) => updateExtra(e.key, r)}
            onRemove={() => removeExtra(e.key)}
          />
        ))}
      </Card>

      {/* Discounts */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>Discounts</div>
          <Button
            variant="ghost"
            onClick={() => setDiscounts((prev) => [...prev, emptyDiscount()])}
            style={{ fontSize: 12 }}
          >
            + Add discount
          </Button>
        </div>
        <SectionLabel>Enter positive amounts — billed as negative deductions.</SectionLabel>
        {discounts.length === 0 && (
          <p style={{ margin: "8px 0 0", fontSize: 13, color: BRAND.sub }}>No discounts.</p>
        )}
        {discounts.map((d) => (
          <DiscountRowEditor
            key={d.key}
            row={d}
            onChange={(r) => updateDiscount(d.key, r)}
            onRemove={() => removeDiscount(d.key)}
          />
        ))}
      </Card>

      {/* Validation / submit errors */}
      {validationError && <ErrorMsg>{validationError}</ErrorMsg>}
      {submitError && <ErrorMsg>Generation failed: {submitError}</ErrorMsg>}

      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Button onClick={handleGenerate} disabled={submitting}>
          {submitting ? "Generating…" : "Generate proposal"}
        </Button>
        {submitting && <Loading label="" />}
      </div>
    </main>
  );
}
