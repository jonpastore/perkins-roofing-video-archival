import { useEffect, useState } from "react";
import {
  getKnowifyStatus,
  listKnowifyCustomers,
  listKnowifyInvoices,
  listKnowifyPayments,
  listKnowifyRaw,
  triggerKnowifySync,
  knowifyReconnect,
} from "../api";
import type {
  KnowifySyncHealth,
  KnowifyCustomer,
  KnowifyInvoice,
  KnowifyPayment,
  KnowifyRawRecord,
  KnowifyRawPage,
} from "../api";
import {
  BRAND,
  FONT,
  Button,
  Card,
  PageTitle,
  Badge,
  Loading,
  ErrorMsg,
  SectionLabel,
  StatCard,
} from "../ui";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtUSD(s: string | null): string {
  if (s == null) return "—";
  const n = Number(s);
  if (isNaN(n)) return s;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtDateShort(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function statusTone(s: string): "green" | "amber" | "red" | "gray" {
  if (s === "ok") return "green";
  if (s === "auth_error" || s === "error") return "red";
  if (s === "partial" || s === "stale") return "amber";
  return "gray";
}

function invoiceStatusTone(s: string): "green" | "amber" | "blue" | "gray" | "red" {
  if (s === "paid") return "green";
  if (s === "partial") return "amber";
  if (s === "sent" || s === "viewed") return "blue";
  if (s === "voided" || s === "void") return "red";
  return "gray";
}

const TH: React.CSSProperties = {
  padding: "10px 14px",
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
  padding: "10px 14px",
  fontSize: 13,
  borderBottom: `1px solid ${BRAND.border}`,
  verticalAlign: "middle",
};

const RAW_ENTITIES = ["invoices", "payments", "customers", "items", "projects"];
const RAW_PAGE_SIZE = 25;

// ── Sync health panel ──────────────────────────────────────────────────────────

function SyncHealthPanel() {
  const [health, setHealth] = useState<KnowifySyncHealth[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [reconnectInfo, setReconnectInfo] = useState<{ status: string; instructions: string; oauth_server_status: string } | null>(null);
  const [reconnectErr, setReconnectErr] = useState<string | null>(null);

  useEffect(() => {
    getKnowifyStatus()
      .then(setHealth)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const hasAuthError = health?.some((h) => h.last_status === "auth_error") ?? false;

  async function handleSyncNow() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await triggerKnowifySync();
      setSyncMsg(result.triggered ? `Sync triggered. Status: ${result.status ?? "running"}` : `Not triggered: ${result.error ?? "unknown"}`);
    } catch (e: unknown) {
      setSyncMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSyncing(false);
    }
  }

  async function handleReconnect() {
    setReconnecting(true);
    setReconnectErr(null);
    setReconnectInfo(null);
    try {
      const result = await knowifyReconnect();
      setReconnectInfo(result);
    } catch (e: unknown) {
      setReconnectErr(e instanceof Error ? e.message : String(e));
    } finally {
      setReconnecting(false);
    }
  }

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>Sync Health</div>
        <Button onClick={handleSyncNow} disabled={syncing} style={{ fontSize: 13 }}>
          {syncing ? "Triggering…" : "Sync now"}
        </Button>
      </div>

      {syncMsg && (
        <div style={{ marginBottom: 12, padding: "8px 12px", background: "#f0f3fa", borderRadius: 8, fontSize: 13, color: BRAND.navyText }}>
          {syncMsg}
        </div>
      )}

      {/* Auth-error banner */}
      {hasAuthError && (
        <div style={{
          marginBottom: 16,
          padding: "12px 16px",
          background: "#fef2f2",
          border: `1px solid ${BRAND.redDark}`,
          borderRadius: 10,
          display: "flex",
          alignItems: "center",
          gap: 14,
          flexWrap: "wrap",
        }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontWeight: 700, color: BRAND.redDark, fontSize: 14, marginBottom: 2 }}>
              Legacy data connection needs re-auth
            </div>
            <div style={{ fontSize: 13, color: BRAND.redDark }}>
              The stored refresh token has lapsed. A human must re-authenticate to restore sync.
            </div>
          </div>
          <Button variant="danger" onClick={handleReconnect} disabled={reconnecting} style={{ fontSize: 13, flexShrink: 0 }}>
            {reconnecting ? "Checking…" : "Reconnect"}
          </Button>
        </div>
      )}

      {reconnectErr && <ErrorMsg>Reconnect error: {reconnectErr}</ErrorMsg>}

      {reconnectInfo && (
        <div style={{ marginBottom: 16, padding: "12px 16px", background: "#fff3e0", border: `1px solid #b45309`, borderRadius: 10, fontSize: 13 }}>
          <div style={{ fontWeight: 700, color: "#b45309", marginBottom: 4 }}>
            Reconnect — {reconnectInfo.status} (OAuth server: {reconnectInfo.oauth_server_status})
          </div>
          <div style={{ color: BRAND.ink, whiteSpace: "pre-wrap" }}>{reconnectInfo.instructions}</div>
        </div>
      )}

      {loading && <Loading label="Loading sync status…" />}
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}

      {health && health.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th style={TH}>Entity</th>
                <th style={TH}>Status</th>
                <th style={TH}>Last run</th>
                <th style={TH}>Rows seen</th>
                <th style={TH}>High water</th>
                <th style={TH}>Error</th>
              </tr>
            </thead>
            <tbody>
              {health.map((h) => (
                <tr key={h.entity}>
                  <td style={{ ...TD, fontWeight: 600, color: BRAND.navyText, fontFamily: "monospace" }}>{h.entity}</td>
                  <td style={TD}>
                    <Badge tone={statusTone(h.last_status)}>
                      {h.last_status}
                    </Badge>
                  </td>
                  <td style={{ ...TD, color: BRAND.sub }}>{fmtDate(h.last_run_at)}</td>
                  <td style={{ ...TD, fontVariantNumeric: "tabular-nums" }}>{h.rows_seen.toLocaleString()}</td>
                  <td style={{ ...TD, color: BRAND.sub, fontSize: 12 }}>{fmtDate(h.last_high_water)}</td>
                  <td style={{ ...TD, color: BRAND.redDark, fontSize: 12, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {h.last_error ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {health && health.length === 0 && (
        <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No sync records yet. Run a sync to populate.</p>
      )}
    </Card>
  );
}

// ── Customers table ────────────────────────────────────────────────────────────

function CustomersPanel() {
  const [rows, setRows] = useState<KnowifyCustomer[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listKnowifyCustomers()
      .then(setRows)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading label="Loading customers…" />;
  if (err) return <ErrorMsg>Error: {err}</ErrorMsg>;
  if (!rows || rows.length === 0) return <p style={{ color: BRAND.sub, fontSize: 13 }}>No mirrored customers.</p>;

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <StatCard label="Customers" value={rows.length} />
      </div>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th style={TH}>Name</th>
                <th style={TH}>Company</th>
                <th style={TH}>Email</th>
                <th style={TH}>Phone</th>
                <th style={TH}>Source ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td style={{ ...TD, fontWeight: 600, color: BRAND.navyText }}>{c.display_name}</td>
                  <td style={TD}>{c.company_name ?? "—"}</td>
                  <td style={{ ...TD, color: BRAND.sub }}>{c.email ?? "—"}</td>
                  <td style={{ ...TD, color: BRAND.sub }}>{c.phone ?? "—"}</td>
                  <td style={{ ...TD, fontFamily: "monospace", fontSize: 12, color: BRAND.sub }}>{c.knowify_customer_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

// ── Invoices table ─────────────────────────────────────────────────────────────

function InvoicesPanel() {
  const [rows, setRows] = useState<KnowifyInvoice[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listKnowifyInvoices()
      .then(setRows)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading label="Loading invoices…" />;
  if (err) return <ErrorMsg>Error: {err}</ErrorMsg>;
  if (!rows || rows.length === 0) return <p style={{ color: BRAND.sub, fontSize: 13 }}>No mirrored invoices.</p>;

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <StatCard label="Invoices" value={rows.length} />
      </div>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th style={TH}>Source #</th>
                <th style={TH}>Our #</th>
                <th style={TH}>Status</th>
                <th style={{ ...TH, textAlign: "right" }}>Total</th>
                <th style={TH}>Invoice date</th>
                <th style={TH}>Source Invoice ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((inv) => (
                <tr key={inv.id}>
                  <td style={{ ...TD, fontWeight: 600, color: BRAND.navyText }}>
                    {inv.knowify_invoice_number ?? "—"}
                  </td>
                  <td style={{ ...TD, color: BRAND.sub }}>{inv.invoice_number ?? "—"}</td>
                  <td style={TD}>
                    <Badge tone={invoiceStatusTone(inv.status)}>{inv.status}</Badge>
                  </td>
                  <td style={{ ...TD, textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                    {fmtUSD(inv.total)}
                  </td>
                  <td style={{ ...TD, color: BRAND.sub }}>{fmtDateShort(inv.invoice_date)}</td>
                  <td style={{ ...TD, fontFamily: "monospace", fontSize: 12, color: BRAND.sub }}>{inv.knowify_invoice_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

// ── Payments table ─────────────────────────────────────────────────────────────

function PaymentsPanel() {
  const [rows, setRows] = useState<KnowifyPayment[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    listKnowifyPayments()
      .then(setRows)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading label="Loading payments…" />;
  if (err) return <ErrorMsg>Error: {err}</ErrorMsg>;
  if (!rows || rows.length === 0) return <p style={{ color: BRAND.sub, fontSize: 13 }}>No mirrored payments.</p>;

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <StatCard label="Payments" value={rows.length} />
      </div>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th style={{ ...TH, textAlign: "right" }}>Amount</th>
                <th style={TH}>Date</th>
                <th style={TH}>Method</th>
                <th style={TH}>Reference</th>
                <th style={TH}>Invoice ID (ours)</th>
                <th style={TH}>Source Payment ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td style={{ ...TD, textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                    {fmtUSD(p.amount)}
                  </td>
                  <td style={{ ...TD, color: BRAND.sub }}>{fmtDateShort(p.payment_date)}</td>
                  <td style={TD}>{p.method ?? "—"}</td>
                  <td style={{ ...TD, color: BRAND.sub }}>{p.reference ?? "—"}</td>
                  <td style={{ ...TD, color: BRAND.sub }}>#{p.invoice_id}</td>
                  <td style={{ ...TD, fontFamily: "monospace", fontSize: 12, color: BRAND.sub }}>{p.knowify_payment_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

// ── Raw viewer ─────────────────────────────────────────────────────────────────

function RawViewer() {
  const [entity, setEntity] = useState<string>(RAW_ENTITIES[0]);
  const [page, setPage] = useState<KnowifyRawPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  // full record payload for expanded row — fetched lazily via the raw page items
  const [payloads, setPayloads] = useState<Record<number, string>>({});

  function load(ent: string, off: number) {
    setLoading(true);
    setErr(null);
    setExpanded(null);
    listKnowifyRaw(ent, { limit: RAW_PAGE_SIZE, offset: off })
      .then((p) => { setPage(p); setOffset(off); })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(entity, 0); }, [entity]);

  function handleEntityChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setEntity(e.target.value);
    setOffset(0);
    setPayloads({});
  }

  async function toggleExpand(item: KnowifyRawRecord) {
    if (expanded === item.id) { setExpanded(null); return; }
    setExpanded(item.id);
    if (payloads[item.id] !== undefined) return;
    // The raw list endpoint returns metadata only (not payload).
    // Show a placeholder — the full payload is in the DB, not returned by this endpoint.
    setPayloads((prev) => ({ ...prev, [item.id]: `(payload for knowify_id=${item.knowify_id} — fetch full record from DB or extend the API)` }));
  }

  const total = page?.total ?? 0;
  const hasNext = offset + RAW_PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <SectionLabel>Entity</SectionLabel>
        <select
          value={entity}
          onChange={handleEntityChange}
          style={{ padding: "7px 10px", border: `1px solid ${BRAND.border}`, borderRadius: 8, fontSize: 13, cursor: "pointer", fontFamily: FONT }}
        >
          {RAW_ENTITIES.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        {total > 0 && (
          <span style={{ color: BRAND.sub, fontSize: 13 }}>
            {offset + 1}–{Math.min(offset + RAW_PAGE_SIZE, total)} of {total.toLocaleString()}
          </span>
        )}
      </div>

      {loading && <Loading label="Loading raw records…" />}
      {err && <ErrorMsg>Error: {err}</ErrorMsg>}

      {page && page.items.length === 0 && !loading && (
        <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>No raw records for this entity.</p>
      )}

      {page && page.items.length > 0 && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={TH}>Source Payment ID</th>
                  <th style={TH}>Fetched at</th>
                  <th style={TH}>Present</th>
                  <th style={TH}>High water</th>
                  <th style={TH}>Expand</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => {
                  const tombstoned = !item.is_present;
                  return (
                    <>
                      <tr
                        key={item.id}
                        style={{ opacity: tombstoned ? 0.45 : 1, background: tombstoned ? "#fef2f2" : undefined }}
                      >
                        <td style={{ ...TD, fontFamily: "monospace", fontWeight: 600, color: BRAND.navyText }}>
                          {item.knowify_id}
                        </td>
                        <td style={{ ...TD, color: BRAND.sub }}>{fmtDate(item.fetched_at)}</td>
                        <td style={TD}>
                          {tombstoned
                            ? <Badge tone="red">tombstoned</Badge>
                            : <Badge tone="green">present</Badge>}
                        </td>
                        <td style={{ ...TD, fontSize: 12, color: BRAND.sub }}>{fmtDate(item.high_water)}</td>
                        <td style={TD}>
                          <button
                            onClick={() => toggleExpand(item)}
                            style={{ background: "none", border: "none", color: BRAND.navyText, cursor: "pointer", fontSize: 13, fontWeight: 600, padding: "2px 6px", borderRadius: 4 }}
                          >
                            {expanded === item.id ? "▲ collapse" : "▼ expand"}
                          </button>
                        </td>
                      </tr>
                      {expanded === item.id && (
                        <tr key={`exp-${item.id}`}>
                          <td colSpan={5} style={{ padding: "0 14px 14px", borderBottom: `1px solid ${BRAND.border}` }}>
                            <pre style={{
                              margin: 0,
                              padding: 12,
                              background: "#f7f8fa",
                              borderRadius: 8,
                              fontSize: 12,
                              overflowX: "auto",
                              color: BRAND.ink,
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                            }}>
                              {payloads[item.id] ?? "Loading…"}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
            <Button variant="ghost" disabled={!hasPrev || loading} onClick={() => load(entity, offset - RAW_PAGE_SIZE)} style={{ fontSize: 12 }}>
              Previous
            </Button>
            <Button variant="ghost" disabled={!hasNext || loading} onClick={() => load(entity, offset + RAW_PAGE_SIZE)} style={{ fontSize: 12 }}>
              Next
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

type SubTab = "health" | "customers" | "invoices" | "payments" | "raw";

const SUB_TABS: [SubTab, string][] = [
  ["health", "Sync Health"],
  ["customers", "Customers"],
  ["invoices", "Invoices"],
  ["payments", "Payments"],
  ["raw", "Raw Viewer"],
];

export function Knowify() {
  const [activeTab, setActiveTab] = useState<SubTab>("health");

  return (
    <main style={{ maxWidth: 1100, fontFamily: FONT }}>
      <PageTitle>Legacy Data</PageTitle>

      {/* Read-only banner */}
      <div style={{
        marginBottom: 20,
        padding: "10px 16px",
        background: "#f0f3fa",
        border: `1px solid ${BRAND.border}`,
        borderRadius: 10,
        fontSize: 13,
        color: BRAND.sub,
      }}>
        Legacy data mirrored from Knowify (read-only). Edit in the Sales section by adopting to a v2 record.
      </div>

      {/* Sub-tab bar — same pattern as AdminConfig */}
      <div style={{ display: "flex", gap: 2, borderBottom: `2px solid ${BRAND.border}`, marginBottom: 24, overflowX: "auto" }}>
        {SUB_TABS.map(([key, label]) => {
          const active = activeTab === key;
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              style={{
                padding: "10px 18px",
                background: "none",
                border: "none",
                borderBottom: active ? `2px solid ${BRAND.red}` : "2px solid transparent",
                marginBottom: -2,
                color: active ? BRAND.navyText : "#667085",
                fontWeight: active ? 600 : 400,
                fontSize: 14,
                cursor: "pointer",
                whiteSpace: "nowrap",
                fontFamily: FONT,
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {activeTab === "health" && <SyncHealthPanel />}
      {activeTab === "customers" && <CustomersPanel />}
      {activeTab === "invoices" && <InvoicesPanel />}
      {activeTab === "payments" && <PaymentsPanel />}
      {activeTab === "raw" && <RawViewer />}
    </main>
  );
}
