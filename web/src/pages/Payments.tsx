import { useRef, useEffect, useState } from "react";
import { listPayments, getPayment } from "../api";
import type { Payment, ListPaymentsParams } from "../api";
import type { QueryState } from "../ui/DataTable";
import { DataTable } from "../ui/DataTable";
import {
  BRAND,
  FONT,
  Card,
  PageTitle,
  Loading,
  ErrorMsg,
  SectionLabel,
} from "../ui";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtUSD(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function invoiceLabel(p: Pick<Payment, "invoice_number" | "knowify_invoice_number" | "invoice_id">): string {
  if (p.invoice_number != null) return `#${p.invoice_number}`;
  if (p.knowify_invoice_number) return `Knowify #${p.knowify_invoice_number}`;
  return p.invoice_id != null ? `Invoice ${p.invoice_id}` : "—";
}

// ── Detail panel ───────────────────────────────────────────────────────────────

function PaymentDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const [payment, setPayment] = useState<Payment | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    setPayment(null);
    getPayment(id)
      .then(setPayment)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const field = (label: string, value: string | number | null | undefined) => (
    <tr key={label}>
      <td style={{ padding: "8px 0", color: BRAND.sub, fontSize: 13, fontWeight: 600, width: 160, verticalAlign: "top" }}>
        {label}
      </td>
      <td style={{ padding: "8px 0 8px 12px", fontSize: 13, color: BRAND.ink, verticalAlign: "top" }}>
        {value ?? "—"}
      </td>
    </tr>
  );

  return (
    <Card style={{ marginTop: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>Payment Detail</div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", color: BRAND.sub, fontSize: 20, lineHeight: 1, padding: "2px 6px" }}
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {loading && <Loading label="Loading payment…" />}
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}

      {payment && (
        <table style={{ borderCollapse: "collapse", fontFamily: FONT }}>
          <tbody>
            {field("ID", payment.id)}
            {field("Date", fmtDate(payment.payment_date))}
            {field("Amount", fmtUSD(payment.amount))}
            {field("Method", payment.method)}
            {field("Reference", payment.reference)}
            {field("Invoice #", invoiceLabel(payment))}
            {field("Invoice ID", payment.invoice_id)}
            {field("Customer", payment.customer_display_name)}
            {field("Notes", payment.notes)}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// ── Filter bar ─────────────────────────────────────────────────────────────────

const METHODS = ["check", "card", "ach", "cash", "other"];

interface Filters {
  method: string;
  date_from: string;
  date_to: string;
}

const inpStyle: React.CSSProperties = {
  padding: "7px 10px",
  border: `1px solid ${BRAND.border}`,
  borderRadius: 8,
  fontSize: 13,
  fontFamily: FONT,
  background: "#fff",
  color: BRAND.ink,
};

function FilterBar({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const dirty = filters.method || filters.date_from || filters.date_to;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
      <SectionLabel>Filter</SectionLabel>
      <select
        value={filters.method}
        onChange={(e) => onChange({ ...filters, method: e.target.value })}
        style={{ ...inpStyle, cursor: "pointer" }}
      >
        <option value="">All methods</option>
        {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <input
        type="date"
        value={filters.date_from}
        onChange={(e) => onChange({ ...filters, date_from: e.target.value })}
        style={{ ...inpStyle, width: 140 }}
        aria-label="From date"
      />
      <span style={{ color: BRAND.sub, fontSize: 13 }}>–</span>
      <input
        type="date"
        value={filters.date_to}
        onChange={(e) => onChange({ ...filters, date_to: e.target.value })}
        style={{ ...inpStyle, width: 140 }}
        aria-label="To date"
      />
      {dirty && (
        <button
          onClick={() => onChange({ method: "", date_from: "", date_to: "" })}
          style={{ background: "none", border: "none", cursor: "pointer", color: BRAND.sub, fontSize: 13, padding: "6px 8px" }}
        >
          Clear
        </button>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function Payments() {
  const [rows, setRows] = useState<Payment[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>({ method: "", date_from: "", date_to: "" });

  // Stable refs to avoid stale closures
  const seqRef = useRef(0);
  const queryRef = useRef<QueryState>({ search: "", sort: null, page: 1, pageSize: 50 });
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  function doFetch(q: QueryState, f: Filters) {
    const seq = ++seqRef.current;
    setLoading(true);
    setErr(null);

    const params: ListPaymentsParams = {
      search: q.search || undefined,
      sort: q.sort?.key,
      order: q.sort?.dir,
      page: q.page,
      limit: q.pageSize,
      method: f.method || undefined,
      date_from: f.date_from || undefined,
      date_to: f.date_to || undefined,
    };

    listPayments(params)
      .then((data) => {
        if (seq !== seqRef.current) return;
        setRows(data.items);
        setTotal(data.total);
      })
      .catch((e: unknown) => {
        if (seq !== seqRef.current) return;
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (seq === seqRef.current) setLoading(false);
      });
  }

  // Initial load
  useEffect(() => {
    doFetch(queryRef.current, filtersRef.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleQueryChange(q: QueryState) {
    queryRef.current = q;
    doFetch(q, filtersRef.current);
  }

  function handleFiltersChange(f: Filters) {
    setFilters(f);
    filtersRef.current = f;
    doFetch(queryRef.current, f);
  }

  // Columns — "View" button in last position triggers detail panel
  const columns = [
    {
      key: "payment_date" as const,
      header: "Date",
      sortable: true,
      render: (r: Payment) => fmtDate(r.payment_date),
    },
    {
      key: "invoice_number" as const,
      header: "Invoice #",
      sortable: true,
      render: (r: Payment) => invoiceLabel(r),
    },
    {
      key: "customer_display_name" as const,
      header: "Customer",
      sortable: true,
      render: (r: Payment) => r.customer_display_name ?? "—",
    },
    {
      key: "amount" as const,
      header: "Amount",
      sortable: true,
      align: "right" as const,
      render: (r: Payment) => (
        <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {fmtUSD(r.amount)}
        </span>
      ),
    },
    {
      key: "method" as const,
      header: "Method",
      sortable: true,
      render: (r: Payment) => r.method ?? "—",
    },
    {
      key: "reference" as const,
      header: "Reference",
      sortable: false,
      render: (r: Payment) => r.reference ?? "—",
    },
    {
      key: "id" as const,
      header: "",
      sortable: false,
      render: (r: Payment) => (
        <button
          onClick={() => setSelectedId(r.id === selectedId ? null : r.id)}
          style={{
            background: "none",
            border: `1px solid ${BRAND.border}`,
            borderRadius: 6,
            padding: "4px 10px",
            fontSize: 12,
            cursor: "pointer",
            color: BRAND.navyText,
            fontFamily: FONT,
          }}
        >
          {r.id === selectedId ? "Close" : "View"}
        </button>
      ),
    },
  ];

  return (
    <main style={{ maxWidth: 1100, fontFamily: FONT }}>
      <PageTitle>Payments</PageTitle>

      <FilterBar filters={filters} onChange={handleFiltersChange} />

      <DataTable<Payment>
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={loading}
        error={err}
        onQueryChange={handleQueryChange}
        totalRows={total}
        defaultPageSize={50}
      />

      {selectedId != null && (
        <PaymentDetail id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </main>
  );
}
