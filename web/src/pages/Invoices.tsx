import { useEffect, useState } from "react";
import {
  listInvoices,
  issueInvoice,
  recordPayment,
  openAuthedPdf,
  listQuotingCustomers,
} from "../api";
import type { Invoice, IssueInvoiceRequest, QuotingCustomer } from "../api";
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

function fmtUSD(s: string): string {
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

function statusTone(status: string): "green" | "amber" | "blue" | "gray" {
  if (status === "paid") return "green";
  if (status === "partial") return "amber";
  if (status === "sent") return "blue";
  return "gray";
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
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
        Record payment — Invoice #{invoice.invoice_number}
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
interface DiscountRow { description: string; amount: string; }

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
  const [invoiceDate, setInvoiceDate] = useState("");
  const [comments, setComments] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function addScope() {
    setScopes((prev) => [...prev, { description: "", scope_value: "" }]);
  }
  function removeScope(i: number) {
    setScopes((prev) => prev.filter((_, idx) => idx !== i));
  }
  function updateScope(i: number, field: keyof ScopeRow, val: string) {
    setScopes((prev) => prev.map((s, idx) => idx === i ? { ...s, [field]: val } : s));
  }

  function addDiscount() {
    setDiscounts((prev) => [...prev, { description: "", amount: "" }]);
  }
  function removeDiscount(i: number) {
    setDiscounts((prev) => prev.filter((_, idx) => idx !== i));
  }
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
      scopes: validScopes.map((s) => ({
        description: s.description.trim(),
        scope_value: s.scope_value.trim(),
      })),
      invoice_date: invoiceDate || null,
      comments: comments.trim() || null,
    };

    const validDiscounts = discounts.filter((d) => d.description.trim() && d.amount.trim());
    if (validDiscounts.length > 0) {
      body.discounts = validDiscounts.map((d) => ({
        description: d.description.trim(),
        amount: d.amount.trim(),
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
          <input
            type="number"
            min="1"
            step="1"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder="e.g. 42"
          />
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
          <input
            type="number"
            min="1"
            max="100"
            step="1"
            value={milestonePct}
            onChange={(e) => setMilestonePct(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder="e.g. 30"
          />
        </div>
        <div>
          <FieldLabel>Invoice Date</FieldLabel>
          <input
            type="date"
            value={invoiceDate}
            onChange={(e) => setInvoiceDate(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
          />
        </div>
        <div style={{ gridColumn: "2 / -1" }}>
          <FieldLabel>Comments</FieldLabel>
          <input
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            placeholder="Optional"
          />
        </div>
      </div>

      {/* Scopes */}
      <div>
        <SectionLabel>Scopes</SectionLabel>
        {scopes.map((s, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 160px auto", gap: 8, marginBottom: 8 }}>
            <input
              value={s.description}
              onChange={(e) => updateScope(i, "description", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }}
              placeholder="Description"
            />
            <input
              type="number"
              min="0"
              step="0.01"
              value={s.scope_value}
              onChange={(e) => updateScope(i, "scope_value", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }}
              placeholder="Contract value"
            />
            {scopes.length > 1 && (
              <button
                onClick={() => removeScope(i)}
                style={{ background: "none", border: "none", color: BRAND.sub, cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px" }}
                title="Remove scope"
              >
                ×
              </button>
            )}
            {scopes.length === 1 && <span />}
          </div>
        ))}
        <Button variant="ghost" onClick={addScope} style={{ fontSize: 12 }}>+ Add scope</Button>
      </div>

      {/* Discounts */}
      <div>
        <SectionLabel>Discounts (optional)</SectionLabel>
        {discounts.map((d, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 160px auto", gap: 8, marginBottom: 8 }}>
            <input
              value={d.description}
              onChange={(e) => updateDiscount(i, "description", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }}
              placeholder="Description"
            />
            <input
              type="number"
              min="0"
              step="0.01"
              value={d.amount}
              onChange={(e) => updateDiscount(i, "amount", e.target.value)}
              style={{ ...inputStyle, fontSize: 13 }}
              placeholder="Amount"
            />
            <button
              onClick={() => removeDiscount(i)}
              style={{ background: "none", border: "none", color: BRAND.sub, cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 4px" }}
              title="Remove discount"
            >
              ×
            </button>
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

// ── Main page ──────────────────────────────────────────────────────────────────

export function Invoices() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [customers, setCustomers] = useState<QuotingCustomer[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [showIssueForm, setShowIssueForm] = useState(false);
  const [paymentTarget, setPaymentTarget] = useState<number | null>(null); // invoice id

  const [pdfErr, setPdfErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listInvoices(), listQuotingCustomers()])
      .then(([invs, custs]) => {
        setInvoices(invs);
        setCustomers(custs);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  function customerName(id: number): string {
    const c = customers.find((x) => x.id === id);
    return c ? c.display_name : `Cust #${id}`;
  }

  function handlePaymentSuccess(invoiceId: number, newStatus: string) {
    setInvoices((prev) =>
      prev.map((inv) => inv.id === invoiceId ? { ...inv, status: newStatus } : inv)
    );
    setPaymentTarget(null);
  }

  async function handlePdf(inv: Invoice) {
    setPdfErr(null);
    try {
      await openAuthedPdf(`/invoices/${inv.id}/pdf`);
    } catch (e: unknown) {
      setPdfErr(e instanceof Error ? e.message : String(e));
    }
  }

  // Stat counts
  const statusCounts = invoices.reduce<Record<string, number>>((acc, inv) => {
    acc[inv.status] = (acc[inv.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <main style={{ maxWidth: 1000, fontFamily: FONT }}>
      <PageTitle
        right={
          !showIssueForm
            ? <Button onClick={() => { setShowIssueForm(true); setPaymentTarget(null); }} style={{ fontSize: 13 }}>+ New invoice</Button>
            : undefined
        }
      >
        Invoices
      </PageTitle>

      {loading && <Loading label="Loading invoices…" />}
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}
      {pdfErr && <ErrorMsg>PDF error: {pdfErr}</ErrorMsg>}

      {/* Stat row */}
      {!loading && invoices.length > 0 && (
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <StatCard label="Total" value={invoices.length} />
          {Object.entries(statusCounts).map(([status, count]) => (
            <StatCard key={status} label={capitalize(status)} value={count} />
          ))}
        </div>
      )}

      {/* Issue form */}
      {showIssueForm && (
        <Card style={{ marginBottom: 20 }}>
          <div style={{ marginBottom: 12, fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>New invoice</div>
          <IssueForm
            customers={customers}
            onSuccess={(inv) => {
              setInvoices((prev) => [inv, ...prev]);
              setShowIssueForm(false);
            }}
            onCancel={() => setShowIssueForm(false)}
          />
        </Card>
      )}

      {/* Invoices table */}
      {!loading && !err && invoices.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No invoices yet. Issue the first one above.
          </p>
        </Card>
      )}

      {invoices.length > 0 && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left", background: BRAND.bg }}>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>#</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Customer</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Job</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Milestone</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600, textAlign: "right" }}>Total</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <>
                  <tr
                    key={inv.id}
                    style={{
                      borderBottom: paymentTarget === inv.id ? "none" : `1px solid ${BRAND.border}`,
                      background: paymentTarget === inv.id ? "#f7f8fa" : undefined,
                    }}
                  >
                    <td style={{ padding: "10px 14px", fontWeight: 600, color: BRAND.navyText }}>
                      {inv.invoice_number}
                    </td>
                    <td style={{ padding: "10px 14px" }}>{customerName(inv.customer_id)}</td>
                    <td style={{ padding: "10px 14px", color: BRAND.sub }}>Job #{inv.job_id}</td>
                    <td style={{ padding: "10px 14px", fontVariantNumeric: "tabular-nums" }}>
                      {fmtPct(inv.milestone_pct)}
                    </td>
                    <td style={{ padding: "10px 14px", textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                      {fmtUSD(inv.total)}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <Badge tone={statusTone(inv.status)}>{capitalize(inv.status)}</Badge>
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <div style={{ display: "flex", gap: 6 }}>
                        <Button
                          variant="ghost"
                          onClick={() => handlePdf(inv)}
                          style={{ fontSize: 12, padding: "5px 12px" }}
                        >
                          PDF
                        </Button>
                        {inv.status !== "paid" && inv.status !== "void" && (
                          <Button
                            variant="ghost"
                            onClick={() => setPaymentTarget(paymentTarget === inv.id ? null : inv.id)}
                            style={{ fontSize: 12, padding: "5px 12px" }}
                          >
                            {paymentTarget === inv.id ? "Cancel" : "Record payment"}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {paymentTarget === inv.id && (
                    <tr key={`pay-${inv.id}`} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                      <td colSpan={7} style={{ padding: "0 14px 14px" }}>
                        <PaymentForm
                          invoice={inv}
                          onSuccess={handlePaymentSuccess}
                          onCancel={() => setPaymentTarget(null)}
                        />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </main>
  );
}
