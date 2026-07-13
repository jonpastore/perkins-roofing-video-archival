import { useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  listInvoicesPaged,
  listInvoicePayments,
  issueInvoice,
  recordPayment,
  openAuthedPdf,
  listQuotingCustomers,
} from "../api";
import type { Invoice, IssueInvoiceRequest, Payment, QuotingCustomer } from "../api";
import { NavContext } from "../App";
import { DataTable } from "../ui/DataTable";
import type { QueryState } from "../ui/DataTable";
import {
  BRAND,
  FONT,
  Button,
  Card,
  PageTitle,
  inputStyle,
  Loading,
  ErrorMsg,
  Badge,
  StatCard,
  SectionLabel,
} from "../ui";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtUSD(s: string | null | undefined): string {
  if (s == null) return "—";
  const n = Number(s);
  if (isNaN(n)) return s;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtPct(frac: string | null): string {
  if (frac == null) return "—";
  const n = Number(frac);
  if (isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

function fmtDateShort(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function invoiceLabel(inv: Pick<Invoice, "invoice_number" | "knowify_invoice_number" | "id">): string {
  if (inv.invoice_number != null) return `#${inv.invoice_number}`;
  if (inv.knowify_invoice_number) return String(inv.knowify_invoice_number);
  return `Invoice ${inv.id}`;
}

function statusTone(status: string): "green" | "amber" | "blue" | "gray" | "red" {
  if (status === "paid") return "green";
  if (status === "partial") return "amber";
  if (status === "sent" || status === "viewed") return "blue";
  if (status === "void" || status === "voided") return "red";
  return "gray";
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  padding: "7px 10px",
  fontSize: 13,
  cursor: "pointer",
};

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label style={{
      display: "block",
      fontSize: 12,
      fontWeight: 600,
      color: BRAND.sub,
      marginBottom: 4,
      textTransform: "uppercase",
      letterSpacing: 0.3,
    }}>
      {children}
    </label>
  );
}

function CustomerLink({ customerId, label }: { customerId: number; label: string }) {
  const { navigate } = useContext(NavContext);
  return (
    <button
      onClick={() => navigate("customers", { customerId: String(customerId) })}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        color: BRAND.navyText,
        cursor: "pointer",
        font: "inherit",
        fontWeight: 600,
        textAlign: "left",
        textDecoration: "underline",
        textUnderlineOffset: 2,
      }}
      title="Open customer"
    >
      {label}
    </button>
  );
}

// ── Payment form (inline) ──────────────────────────────────────────────────────

interface PaymentFormProps {
  invoice: Invoice;
  onSuccess: (invoiceId: number, newStatus: string) => void;
  onCancel: () => void;
}

function PaymentForm({ invoice, onSuccess, onCancel }: PaymentFormProps) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("check");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [idempotencyKey] = useState(() => `pay-${crypto.randomUUID()}`);

  async function handleSubmit() {
    if (!amount.trim()) { setErr("Amount is required."); return; }
    setSaving(true);
    setErr(null);
    try {
      const result = await recordPayment(invoice.id, {
        amount: amount.trim(),
        method: method || undefined,
        reference: reference.trim() || undefined,
        notes: notes.trim() || undefined,
        idempotency_key: idempotencyKey,
      });
      onSuccess(result.invoice_id, result.status);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ marginTop: 8, padding: 16, background: BRAND.bg, borderRadius: 8 }}>
      <div style={{ marginBottom: 10, fontWeight: 600, color: BRAND.navyText, fontSize: 13 }}>
        Record payment — {invoiceLabel(invoice)}
      </div>
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <FieldLabel>Amount *</FieldLabel>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder={`e.g. ${fmtUSD(invoice.total)}`}
          />
        </div>
        <div>
          <FieldLabel>Method</FieldLabel>
          <select value={method} onChange={(e) => setMethod(e.target.value)} style={selectStyle}>
            <option value="check">Check</option>
            <option value="ach">ACH</option>
            <option value="card">Card</option>
            <option value="cash">Cash</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <FieldLabel>Reference</FieldLabel>
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder="Check # or transaction ID"
          />
        </div>
        <div>
          <FieldLabel>Notes</FieldLabel>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder="Optional"
          />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={handleSubmit} disabled={saving} style={{ fontSize: 13 }}>
          {saving ? "Saving…" : "Record payment"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Issue invoice form ─────────────────────────────────────────────────────────

interface ScopeRow { description: string; scope_value: string; }
interface DiscountRow { description: string; amount: string; discount_type: "amount" | "percent"; }
interface DiscountPreset { description: string; amount: string; discount_type: "amount" | "percent"; }

const INVOICE_DISCOUNT_PRESETS_KEY = "perkins.discountPresets.v1";
function loadDiscountPresets(): DiscountPreset[] {
  try {
    const raw = window.localStorage.getItem(INVOICE_DISCOUNT_PRESETS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((p) => p?.description && p?.amount) : [];
  } catch { return []; }
}
function saveDiscountPresets(presets: DiscountPreset[]) {
  window.localStorage.setItem(INVOICE_DISCOUNT_PRESETS_KEY, JSON.stringify(presets));
}

interface IssueFormProps {
  customers: QuotingCustomer[];
  onSuccess: (inv: Invoice) => void;
  onCancel: () => void;
}

function IssueForm({ customers, onSuccess, onCancel }: IssueFormProps) {
  const [jobId, setJobId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [milestonePct, setMilestonePct] = useState("");
  const [scopes, setScopes] = useState<ScopeRow[]>([{ description: "", scope_value: "" }]);
  const [discounts, setDiscounts] = useState<DiscountRow[]>([]);
  const [discountPresets, setDiscountPresets] = useState<DiscountPreset[]>(() => loadDiscountPresets());
  const [invoiceDate, setInvoiceDate] = useState("");
  const [comments, setComments] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function addScope() { setScopes((prev) => [...prev, { description: "", scope_value: "" }]); }
  function removeScope(i: number) { setScopes((prev) => prev.filter((_, idx) => idx !== i)); }
  function updateScope(i: number, field: keyof ScopeRow, val: string) {
    setScopes((prev) => prev.map((s, idx) => idx === i ? { ...s, [field]: val } : s));
  }

  function addDiscount() { setDiscounts((prev) => [...prev, { description: "", amount: "", discount_type: "amount" }]); }
  function addDiscountPreset(preset: DiscountPreset) { setDiscounts((prev) => [...prev, { ...preset }]); }
  function saveDiscountPreset(row: DiscountRow) {
    if (!row.description.trim() || !row.amount.trim()) return;
    const preset = { description: row.description.trim(), amount: row.amount.trim(), discount_type: row.discount_type };
    setDiscountPresets((prev) => {
      const next = [preset, ...prev.filter((p) => p.description.toLowerCase() !== preset.description.toLowerCase())].slice(0, 20);
      saveDiscountPresets(next);
      return next;
    });
  }
  function removeDiscount(i: number) { setDiscounts((prev) => prev.filter((_, idx) => idx !== i)); }
  function updateDiscount(i: number, field: keyof DiscountRow, val: string) {
    setDiscounts((prev) => prev.map((d, idx) => idx === i ? { ...d, [field]: val } : d));
  }

  async function handleSubmit() {
    if (!jobId.trim() || isNaN(Number(jobId))) { setErr("Job ID is required."); return; }
    if (!customerId) { setErr("Customer is required."); return; }
    const validScopes = scopes.filter((s) => s.description.trim() && s.scope_value.trim());
    if (validScopes.length === 0) { setErr("At least one scope with a value is required."); return; }
    const pct = Number(milestonePct);
    if (!milestonePct.trim() || isNaN(pct) || pct <= 0 || pct > 100) {
      setErr("Milestone % must be a whole number 1–100."); return;
    }
    const body: IssueInvoiceRequest = {
      job_id: Number(jobId),
      customer_id: Number(customerId),
      milestone_pct: (pct / 100).toFixed(2),
      scopes: validScopes.map((s) => ({ description: s.description.trim(), scope_value: s.scope_value.trim() })),
      invoice_date: invoiceDate || null,
      comments: comments.trim() || null,
    };
    const validDiscounts = discounts.filter((d) => d.description.trim() && d.amount.trim());
    if (validDiscounts.length > 0) {
      body.discounts = validDiscounts.map((d) => ({
        description: d.description.trim(),
        discount_type: d.discount_type,
        value: d.amount.trim(),
        ...(d.discount_type === "amount" ? { amount: d.amount.trim() } : {}),
      }));
    }
    setSaving(true);
    setErr(null);
    try {
      const inv = await issueInvoice(body);
      onSuccess(inv);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <div>
          <FieldLabel>Job ID *</FieldLabel>
          <input type="number" min="1" step="1" value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="e.g. 42" />
        </div>
        <div>
          <FieldLabel>Customer *</FieldLabel>
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} style={selectStyle}>
            <option value="">— Select customer —</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.display_name}{c.company_name ? ` (${c.company_name})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel>Milestone %</FieldLabel>
          <input type="number" min="1" max="100" step="1" value={milestonePct}
            onChange={(e) => setMilestonePct(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="e.g. 30" />
        </div>
        <div>
          <FieldLabel>Invoice Date</FieldLabel>
          <input type="date" value={invoiceDate}
            onChange={(e) => setInvoiceDate(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
        </div>
        <div style={{ gridColumn: "2 / -1" }}>
          <FieldLabel>Comments</FieldLabel>
          <input value={comments} onChange={(e) => setComments(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }} placeholder="Optional" />
        </div>
      </div>

      <div>
        <SectionLabel>Scopes</SectionLabel>
        {scopes.map((s, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 160px auto", gap: 8, marginBottom: 8 }}>
            <input value={s.description} onChange={(e) => updateScope(i, "description", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }} placeholder="Description" />
            <input type="number" min="0" step="0.01" value={s.scope_value}
              onChange={(e) => updateScope(i, "scope_value", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }} placeholder="Contract value" />
            {scopes.length > 1
              ? <button onClick={() => removeScope(i)}
                  style={{ background: "none", border: "none", color: BRAND.sub, cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px" }}>×</button>
              : <span />}
          </div>
        ))}
        <Button variant="ghost" onClick={addScope} style={{ fontSize: 12 }}>+ Add scope</Button>
      </div>

      <div>
        <SectionLabel>Discounts (optional)</SectionLabel>
        {discountPresets.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
            {discountPresets.map((p) => (
              <button key={`${p.description}-${p.discount_type}-${p.amount}`} onClick={() => addDiscountPreset(p)}
                style={{ border: `1px solid ${BRAND.border}`, background: BRAND.bg, borderRadius: 999, padding: "4px 10px", cursor: "pointer", fontSize: 12, color: BRAND.navyText }}>
                + {p.description} ({p.discount_type === "percent" ? `${p.amount}%` : `$${p.amount}`})
              </button>
            ))}
          </div>
        )}
        {discounts.map((d, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 90px 130px auto auto", gap: 8, marginBottom: 8, alignItems: "center" }}>
            <input value={d.description} onChange={(e) => updateDiscount(i, "description", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }} placeholder="Description" />
            <select value={d.discount_type} onChange={(e) => updateDiscount(i, "discount_type", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }}>
              <option value="amount">$</option>
              <option value="percent">%</option>
            </select>
            <input type="number" min="0" max={d.discount_type === "percent" ? "100" : undefined} step="0.01" value={d.amount}
              onChange={(e) => updateDiscount(i, "amount", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }} placeholder={d.discount_type === "percent" ? "10" : "Amount"} />
            <Button variant="ghost" onClick={() => saveDiscountPreset(d)} style={{ fontSize: 12, padding: "5px 8px" }}>Save</Button>
            <button onClick={() => removeDiscount(i)}
              style={{ background: "none", border: "none", color: BRAND.sub, cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px" }}>×</button>
          </div>
        ))}
        <Button variant="ghost" onClick={addDiscount} style={{ fontSize: 12 }}>+ Add discount</Button>
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={handleSubmit} disabled={saving} style={{ fontSize: 13 }}>
          {saving ? "Issuing…" : "Issue invoice"}
        </Button>
        <Button variant="ghost" onClick={onCancel} style={{ fontSize: 13 }}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Detail drawer ──────────────────────────────────────────────────────────────

interface DrawerProps {
  invoice: Invoice;
  onClose: () => void;
  onPaymentSuccess: (invoiceId: number, newStatus: string) => void;
}

function InvoiceDrawer({ invoice, onClose, onPaymentSuccess }: DrawerProps) {
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [paymentsLoading, setPaymentsLoading] = useState(true);
  const [paymentsErr, setPaymentsErr] = useState<string | null>(null);
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [pdfErr, setPdfErr] = useState<string | null>(null);

  const isLegacy = invoice.source === "knowify_import";

  useEffect(() => {
    listInvoicePayments(invoice.id)
      .then(setPayments)
      .catch((e: unknown) => setPaymentsErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setPaymentsLoading(false));
  }, [invoice.id]);

  async function handlePdf() {
    setPdfErr(null);
    try {
      await openAuthedPdf(`/invoices/${invoice.id}/pdf`);
    } catch (e: unknown) {
      setPdfErr(e instanceof Error ? e.message : String(e));
    }
  }

  function handlePaymentSuccess(invoiceId: number, newStatus: string) {
    onPaymentSuccess(invoiceId, newStatus);
    setShowPaymentForm(false);
    // refresh payments list
    setPaymentsLoading(true);
    listInvoicePayments(invoice.id)
      .then(setPayments)
      .catch((e: unknown) => setPaymentsErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setPaymentsLoading(false));
  }

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 50,
      display: "flex", justifyContent: "flex-end",
    }}>
      {/* backdrop */}
      <div
        onClick={onClose}
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.25)" }}
      />
      {/* panel */}
      <div style={{
        position: "relative",
        width: Math.min(520, window.innerWidth - 32),
        background: "#fff",
        boxShadow: "-4px 0 24px rgba(16,24,40,0.12)",
        overflowY: "auto",
        padding: 24,
        fontFamily: FONT,
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: BRAND.navyText }}>
              {invoiceLabel(invoice)}
            </div>
            {invoice.knowify_invoice_number && (
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                #{invoice.knowify_invoice_number}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Badge tone={statusTone(invoice.status)}>{capitalize(invoice.status)}</Badge>
            {isLegacy && <Badge tone="gray">Knowify import</Badge>}
            <button
              onClick={onClose}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1, padding: "2px 4px" }}
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Fields */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Customer</div>
            <div style={{ fontSize: 14, color: BRAND.navyText }}>
              <CustomerLink
                customerId={invoice.customer_id}
                label={invoice.customer_display_name ?? `#${invoice.customer_id}`}
              />
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Job</div>
            <div style={{ fontSize: 14, color: BRAND.navyText }}>#{invoice.job_id}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Invoice date</div>
            <div style={{ fontSize: 14 }}>{fmtDateShort(invoice.invoice_date)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Due date</div>
            <div style={{ fontSize: 14 }}>{fmtDateShort(invoice.due_date)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Milestone</div>
            <div style={{ fontSize: 14 }}>{fmtPct(invoice.milestone_pct)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Total</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(invoice.total)}</div>
          </div>
          {Number(invoice.tax_amount) > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>Tax</div>
              <div style={{ fontSize: 14 }}>{fmtUSD(invoice.tax_amount)}</div>
            </div>
          )}
        </div>

        {/* Line items */}
        {invoice.lines && invoice.lines.length > 0 && (
          <div>
            <SectionLabel>Line items</SectionLabel>
            <div style={{ border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
              {invoice.lines.map((line, i) => (
                <div key={i} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "9px 14px",
                  borderBottom: i < invoice.lines!.length - 1 ? `1px solid ${BRAND.border}` : "none",
                  background: i % 2 === 0 ? "#fff" : BRAND.bg,
                  fontSize: 13,
                }}>
                  <div style={{ flex: 1, color: BRAND.navyText }}>{line.description}</div>
                  {line.milestone_pct && (
                    <div style={{ color: BRAND.sub, whiteSpace: "nowrap" }}>{fmtPct(line.milestone_pct)}</div>
                  )}
                  <div style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{fmtUSD(line.subtotal)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Payments */}
        <div>
          <SectionLabel>Payments</SectionLabel>
          {paymentsLoading && <Loading label="Loading payments…" />}
          {paymentsErr && <ErrorMsg>Error: {paymentsErr}</ErrorMsg>}
          {payments && payments.length === 0 && !paymentsLoading && (
            <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No payments recorded.</p>
          )}
          {payments && payments.length > 0 && (
            <div style={{ border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
              {payments.map((p, i) => (
                <div key={p.id} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  padding: "9px 14px",
                  borderBottom: i < payments.length - 1 ? `1px solid ${BRAND.border}` : "none",
                  background: i % 2 === 0 ? "#fff" : BRAND.bg,
                  fontSize: 13,
                }}>
                  <div style={{ color: BRAND.sub }}>{fmtDateShort(p.payment_date)}</div>
                  <div style={{ color: BRAND.navyText }}>{p.method ?? "—"}{p.reference ? ` · ${p.reference}` : ""}</div>
                  <div style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{fmtUSD(p.amount)}</div>
                </div>
              ))}
            </div>
          )}

          {/* Record payment (v2-native only) */}
          {!isLegacy && invoice.status !== "paid" && invoice.status !== "void" && invoice.status !== "voided" && (
            <div style={{ marginTop: 12 }}>
              {showPaymentForm
                ? <PaymentForm invoice={invoice} onSuccess={handlePaymentSuccess} onCancel={() => setShowPaymentForm(false)} />
                : <Button variant="ghost" onClick={() => setShowPaymentForm(true)} style={{ fontSize: 13 }}>Record payment</Button>}
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="ghost" onClick={handlePdf} style={{ fontSize: 13 }}>View PDF</Button>
        </div>
        {pdfErr && <ErrorMsg>PDF error: {pdfErr}</ErrorMsg>}
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function Invoices() {
  const [rows, setRows] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [customers, setCustomers] = useState<QuotingCustomer[]>([]);
  const [showIssueForm, setShowIssueForm] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);

  // filter state (separate from DataTable's query — fed into onQueryChange)
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSource, setFilterSource] = useState("");

  // latest query from DataTable (server-side mode)
  const queryRef = useRef<QueryState>({ search: "", sort: null, page: 1, pageSize: 50 });
  const filterRef = useRef({ status: "", source: "" });

  const fetchPage = useCallback(async (q: QueryState, status: string, source: string) => {
    setLoading(true);
    setErr(null);
    try {
      const data = await listInvoicesPaged({
        status: status || undefined,
        source: source || undefined,
        sort: q.sort?.key,
        order: q.sort?.dir,
        page: q.page,
        limit: q.pageSize,
      });
      setRows(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Load customers once for the issue form
  useEffect(() => {
    listQuotingCustomers().then(setCustomers).catch(() => {/* non-critical */});
  }, []);

  // Initial load
  useEffect(() => {
    fetchPage(queryRef.current, filterStatus, filterSource);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleQueryChange(q: QueryState) {
    queryRef.current = q;
    fetchPage(q, filterRef.current.status, filterRef.current.source);
  }

  function applyFilters(status: string, source: string) {
    filterRef.current = { status, source };
    // reset to page 1 via a fresh query
    const q: QueryState = { ...queryRef.current, page: 1 };
    queryRef.current = q;
    fetchPage(q, status, source);
  }

  function handleStatusFilter(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    setFilterStatus(v);
    applyFilters(v, filterRef.current.source);
  }

  function handleSourceFilter(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    setFilterSource(v);
    applyFilters(filterRef.current.status, v);
  }

  function handlePaymentSuccess(invoiceId: number, newStatus: string) {
    setRows((prev) => prev.map((inv) => inv.id === invoiceId ? { ...inv, status: newStatus } : inv));
    if (selectedInvoice?.id === invoiceId) {
      setSelectedInvoice((prev) => prev ? { ...prev, status: newStatus } : prev);
    }
  }

  function handleIssueSuccess(inv: Invoice) {
    setRows((prev) => [inv, ...prev]);
    setTotal((t) => t + 1);
    setShowIssueForm(false);
  }

  // ponytail: columns defined inside component so setSelectedInvoice is in scope
  const columns: import("../ui/DataTable").ColDef<Invoice>[] = [
    {
      key: "invoice_number",
      header: "Invoice #",
      sortable: true,
      render: (inv) => <span style={{ fontWeight: 600, color: BRAND.navyText }}>{invoiceLabel(inv)}</span>,
    },
    {
      key: "customer_display_name",
      header: "Customer",
      sortable: false,
      render: (inv) => (
        <CustomerLink
          customerId={inv.customer_id}
          label={inv.customer_display_name ?? `#${inv.customer_id}`}
        />
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (inv) => <Badge tone={statusTone(inv.status)}>{capitalize(inv.status)}</Badge>,
    },
    {
      key: "invoice_date",
      header: "Invoice date",
      sortable: true,
      render: (inv) => fmtDateShort(inv.invoice_date),
    },
    {
      key: "due_date",
      header: "Due date",
      sortable: true,
      render: (inv) => fmtDateShort(inv.due_date),
    },
    {
      key: "total",
      header: "Total",
      sortable: true,
      align: "right",
      render: (inv) => <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>{fmtUSD(inv.total)}</span>,
    },
    {
      key: "source",
      header: "Source",
      sortable: false,
      render: (inv) => inv.source === "knowify_import"
        ? <Badge tone="gray">Knowify import</Badge>
        : <Badge tone="blue">v2</Badge>,
    },
    {
      key: "id",
      header: "",
      sortable: false,
      render: (inv) => (
        <Button variant="ghost" onClick={() => setSelectedInvoice(inv)} style={{ fontSize: 12, padding: "5px 12px" }}>
          View
        </Button>
      ),
    },
  ];

  return (
    <main style={{ maxWidth: 1100, fontFamily: FONT }}>
      <PageTitle
        right={
          !showIssueForm
            ? <Button onClick={() => { setShowIssueForm(true); setSelectedInvoice(null); }} style={{ fontSize: 13 }}>+ New invoice</Button>
            : undefined
        }
      >
        Invoices
      </PageTitle>

      {/* Stat row */}
      {!loading && total > 0 && (
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <StatCard label="Total" value={total.toLocaleString()} />
        </div>
      )}

      {/* Issue form */}
      {showIssueForm && (
        <Card style={{ marginBottom: 20 }}>
          <div style={{ marginBottom: 12, fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>New invoice</div>
          <IssueForm
            customers={customers}
            onSuccess={handleIssueSuccess}
            onCancel={() => setShowIssueForm(false)}
          />
        </Card>
      )}

      {/* Filter toolbar */}
      <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <FieldLabel>Status</FieldLabel>
          <select value={filterStatus} onChange={handleStatusFilter} style={{ ...selectStyle, width: 160 }}>
            <option value="">All statuses</option>
            <option value="sent">Sent</option>
            <option value="partial">Partial</option>
            <option value="paid">Paid</option>
            <option value="void">Void</option>
            <option value="draft">Draft</option>
          </select>
        </div>
        <div>
          <FieldLabel>Source</FieldLabel>
          <select value={filterSource} onChange={handleSourceFilter} style={{ ...selectStyle, width: 160 }}>
            <option value="">All sources</option>
            <option value="v2">v2 / Native</option>
            <option value="knowify_import">Knowify import</option>
          </select>
        </div>
      </div>

      {/* Error display */}
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}

      {/* DataTable (server-side) */}
      <DataTable<Invoice>
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={loading}
        error={err ?? undefined}
        totalRows={total}
        defaultPageSize={50}
        onQueryChange={handleQueryChange}
      />

      {/* Detail drawer */}
      {selectedInvoice && (
        <InvoiceDrawer
          invoice={selectedInvoice}
          onClose={() => setSelectedInvoice(null)}
          onPaymentSuccess={handlePaymentSuccess}
        />
      )}
    </main>
  );
}
