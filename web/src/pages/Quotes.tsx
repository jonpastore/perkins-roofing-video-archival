import { useCallback, useEffect, useState } from "react";
import { listQuotes, getQuote } from "../api";
import type { QuoteListItem, QuoteDetail } from "../api";
import type { QueryState } from "../ui/DataTable";
import { DataTable } from "../ui/DataTable";
import {
  BRAND,
  FONT,
  Badge,
  Card,
  PageTitle,
  Loading,
  ErrorMsg,
  SectionLabel,
} from "../ui";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtUSD(s: string | null | undefined): string {
  if (s == null) return "—";
  const n = Number(s);
  if (isNaN(n)) return s;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function businessStateTone(s: string | null): "green" | "amber" | "blue" | "gray" | "red" {
  if (!s) return "gray";
  const lower = s.toLowerCase();
  if (lower === "approved" || lower === "accepted" || lower === "signed") return "green";
  if (lower === "pending" || lower === "sent") return "blue";
  if (lower === "expired") return "amber";
  if (lower === "declined" || lower === "cancelled" || lower === "voided") return "red";
  return "gray";
}

// ── Detail drawer ──────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: "8px 12px",
  color: BRAND.sub,
  fontWeight: 600,
  textAlign: "left",
  background: BRAND.bg,
  borderBottom: `2px solid ${BRAND.border}`,
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: 0.3,
  whiteSpace: "nowrap",
};

const TD: React.CSSProperties = {
  padding: "8px 12px",
  fontSize: 13,
  borderBottom: `1px solid ${BRAND.border}`,
  verticalAlign: "middle",
};

function DetailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [detail, setDetail] = useState<QuoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    setDetail(null);
    getQuote(id)
      .then(setDetail)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const addr = detail?.project_address;
  const addressLine = addr
    ? [addr.Address1, addr.City, addr.StateProvince, addr.Zip].filter(Boolean).join(", ") || null
    : null;

  return (
    <div style={{
      position: "fixed",
      inset: 0,
      zIndex: 1000,
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "flex-end",
    }}>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.18)" }}
      />

      {/* Panel */}
      <div style={{
        position: "relative",
        width: "min(640px, 95vw)",
        height: "100vh",
        background: "#fff",
        boxShadow: "-4px 0 24px rgba(16,24,40,0.12)",
        overflowY: "auto",
        padding: 28,
        fontFamily: FONT,
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
              Legacy Quote (read-only)
            </div>
            {detail && (
              <div style={{ fontSize: 20, fontWeight: 700, color: BRAND.navyText, lineHeight: 1.3 }}>
                {detail.ContractName || `Contract ${detail.contract_id}`}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: `1px solid ${BRAND.border}`,
              borderRadius: 8,
              cursor: "pointer",
              fontSize: 18,
              color: BRAND.sub,
              padding: "4px 10px",
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            ×
          </button>
        </div>

        {loading && <Loading label="Loading quote…" />}
        {err && <ErrorMsg>Error: {err}</ErrorMsg>}

        {detail && (
          <>
            {/* Contract summary */}
            <Card style={{ padding: 16 }}>
              <SectionLabel>Contract Summary</SectionLabel>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 20px", marginTop: 8 }}>
                <Field label="Contact" value={detail.ContactName} />
                <Field label="Business State">
                  <Badge tone={businessStateTone(detail.BusinessState)}>
                    {detail.BusinessState ?? "—"}
                  </Badge>
                </Field>
                <Field label="Original Contract Sum" value={fmtUSD(detail.OriginalContractSum)} mono />
                <Field label="Current Contract Sum" value={fmtUSD(detail.CurrentContractSum)} mono />
                <Field label="Deposit Amount" value={fmtUSD(detail.DepositAmount)} mono />
                <Field label="Type" value={detail.ContractType} />
                <Field label="Created" value={fmtDate(detail.DateCreated)} />
                <Field label="Expires" value={fmtDate(detail.ExpirationDate)} />
                {detail.PONumber && <Field label="PO Number" value={detail.PONumber} />}
                <Field label="Signed">
                  {detail.IsSigned == null
                    ? <span style={{ color: BRAND.sub }}>—</span>
                    : <Badge tone={detail.IsSigned ? "green" : "gray"}>{detail.IsSigned ? "Yes" : "No"}</Badge>}
                </Field>
              </div>
            </Card>

            {/* Project address */}
            {addressLine && (
              <Card style={{ padding: 16 }}>
                <SectionLabel>Project Address</SectionLabel>
                <div style={{ marginTop: 8, fontSize: 14, color: BRAND.ink, lineHeight: 1.6 }}>
                  {addr?.Address1 && <div>{addr.Address1}</div>}
                  <div>
                    {[addr?.City, addr?.StateProvince].filter(Boolean).join(", ")}
                    {addr?.Zip ? ` ${addr.Zip}` : ""}
                  </div>
                </div>
              </Card>
            )}

            {/* Line items (deliverables / scope) */}
            <div>
              <SectionLabel>Deliverables / Scope</SectionLabel>
              <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 10, marginTop: 4 }}>
                Note: Knowify has no roof measurements at Perkins — line-items below represent the
                contracted scope and deliverables for this project, not measurement data.
              </div>
              {detail.line_items.length === 0 ? (
                <p style={{ fontSize: 13, color: BRAND.sub, margin: 0 }}>No line items on this contract.</p>
              ) : (
                <Card style={{ padding: 0, overflow: "hidden" }}>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                      <thead>
                        <tr>
                          <th style={TH}>Description</th>
                          <th style={{ ...TH, textAlign: "right" }}>Qty</th>
                          <th style={{ ...TH, textAlign: "right" }}>Unit Price</th>
                          <th style={{ ...TH, textAlign: "right" }}>Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.line_items.map((li, i) => (
                          <tr key={li.Id ?? i}>
                            <td style={TD}>{li.Description || "—"}</td>
                            <td style={{ ...TD, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                              {li.Quantity ?? "—"}
                            </td>
                            <td style={{ ...TD, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                              {fmtUSD(li.UnitPrice)}
                            </td>
                            <td style={{ ...TD, textAlign: "right", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                              {fmtUSD(li.Price)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}
            </div>

            {/* Backend note */}
            {detail._note && (
              <div style={{ fontSize: 12, color: BRAND.sub, fontStyle: "italic" }}>{detail._note}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
  children,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2 }}>
        {label}
      </div>
      {children ?? (
        <div style={{ fontSize: 14, color: BRAND.ink, fontFamily: mono ? "monospace" : undefined }}>
          {value ?? "—"}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function Quotes() {
  const [rows, setRows] = useState<QuoteListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Columns defined inside so title render can close over setSelectedId
  const columns: import("../ui/DataTable").ColDef<QuoteListItem>[] = [
    {
      key: "ContractName",
      header: "Name",
      sortable: false,
      render: (r) => (
        <button
          onClick={() => setSelectedId(r.contract_id)}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            fontWeight: 600,
            color: BRAND.navyText,
            fontSize: 13,
            textAlign: "left",
            fontFamily: "inherit",
            textDecoration: "underline",
            textDecorationColor: BRAND.border,
          }}
        >
          {r.ContractName || `Contract ${r.contract_id}`}
        </button>
      ),
    },
    {
      key: "ContractType",
      header: "Type",
      sortable: false,
      render: (r) => <span style={{ color: BRAND.sub }}>{r.ContractType ?? "—"}</span>,
    },
    {
      key: "BusinessState",
      header: "Business State",
      sortable: true,
      render: (r) => (
        r.BusinessState
          ? <Badge tone={businessStateTone(r.BusinessState)}>{r.BusinessState}</Badge>
          : <span style={{ color: BRAND.sub }}>—</span>
      ),
    },
    {
      key: "OriginalContractSum",
      header: "Original Sum",
      sortable: true,
      align: "right",
      render: (r) => (
        <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {fmtUSD(r.OriginalContractSum)}
        </span>
      ),
    },
    {
      key: "CurrentContractSum",
      header: "Current Sum",
      sortable: false,
      align: "right",
      render: (r) => (
        <span style={{ fontVariantNumeric: "tabular-nums" }}>
          {fmtUSD(r.CurrentContractSum)}
        </span>
      ),
    },
    {
      key: "DateCreated",
      header: "Created",
      sortable: true,
      render: (r) => <span style={{ color: BRAND.sub }}>{fmtDate(r.DateCreated)}</span>,
    },
    {
      key: "IsSigned",
      header: "Signed",
      sortable: false,
      render: (r) => r.IsSigned == null
        ? <span style={{ color: BRAND.sub }}>—</span>
        : <Badge tone={r.IsSigned ? "green" : "gray"}>{r.IsSigned ? "Yes" : "No"}</Badge>,
    },
  ];

  const fetchQuotes = useCallback((q: QueryState) => {
    setLoading(true);
    setErr(null);

    // Map DataTable sort keys to backend whitelist names
    const sortKeyMap: Record<string, string> = {
      DateCreated: "DateCreated",
      OriginalContractSum: "OriginalContractSum",
      BusinessState: "BusinessState",
      Id: "Id",
    };
    const sortParam = q.sort ? (sortKeyMap[q.sort.key] ?? q.sort.key) : undefined;

    listQuotes({
      search: q.search || undefined,
      sort: sortParam,
      order: q.sort?.dir,
      page: q.page,
      limit: q.pageSize,
    })
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main style={{ maxWidth: 1100, fontFamily: FONT }}>
      <PageTitle>Legacy Quotes</PageTitle>

      <div style={{
        marginBottom: 16,
        padding: "10px 14px",
        background: "#f0f3fa",
        borderRadius: 8,
        fontSize: 13,
        color: BRAND.navyText,
        borderLeft: `3px solid ${BRAND.navy}`,
      }}>
        Legacy quote data from the Knowify mirror (re-synced hourly). This view is read-only —
        full quote CRUD lives in the Proposal/Estimator flow. Data may be empty until the sync
        runs with the contracts entity enabled.
      </div>

      <DataTable<QuoteListItem>
        columns={columns}
        rows={rows}
        rowKey={(r) => r.contract_id}
        loading={loading}
        error={err}
        onQueryChange={fetchQuotes}
        totalRows={total}
        defaultPageSize={25}
      />

      {selectedId !== null && (
        <DetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </main>
  );
}
