import { useContext, useEffect, useRef, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  BarChart,
  Bar,
  Cell,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";
import { apiFetch, getDashboardBilling, getAgingDetail, getActiveUsers, getGcpSpend, getProductionReadiness, listBranches, type DashboardBilling, type AgingDetail, type ActiveUsersResponse, type GcpSpendResponse, type SpendDailyPoint, type SpendByService, type ProductionReadiness, type GateState, type BranchRow } from "../api";
import { NavContext } from "../App";
import { DataSources } from "../components/DataSources";
import { BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg, StatCard, inputStyle } from "../ui";
import { errText } from "../lib/errors";

type ToastTone = "green" | "red";
interface Toast { message: string; tone: ToastTone; }

type AgingBucketKey = "current" | "d1_30" | "d31_60" | "d61_90" | "d90_plus";

interface FailedStage {
  video_id: string;
  stage: string;
  error: string;
  title?: string | null;
  youtube_url?: string;
}

interface QueueItem {
  video_id: string;
  title?: string | null;
  stage: string;
  status: string;
}

interface ScheduledBucket {
  count: number;
  next_up: string | null; // ISO datetime
}

interface ScheduledBreakdown {
  articles: ScheduledBucket;
  social: Record<string, ScheduledBucket>;
}

interface StatusData {
  videos: number;
  videos_embedded: number;
  videos_archived: number;
  transcripts_done: number;
  articles: number;
  faq_count: number;
  scheduled_content: number;
  scheduled_breakdown?: ScheduledBreakdown;
  content_opportunities?: number;
  comments_to_answer?: number;
  videos_to_approve?: number;
  failed_stages: FailedStage[];
  queue: QueueItem[];
}

interface KpiCard {
  label: string;
  value: number;
  color?: string;
  navTarget?: string;
}

// ── Date-range helpers ────────────────────────────────────────────────────────

function fmt(d: Date): string {
  return d.toISOString().slice(0, 10);
}

type Preset =
  | "1d" | "this_week" | "last_week" | "7d"
  | "this_month" | "last_month" | "30d"
  | "this_quarter" | "last_quarter" | "90d"
  | "this_year" | "last_year" | "365d"
  | "custom";

interface DateRange { from: string; to: string; bucket: "day" | "week" | "month"; }

function rangeForPreset(preset: Preset, customFrom: string, customTo: string): DateRange {
  const now = new Date();
  const today = fmt(now);

  const startOfWeek = (d: Date) => {
    const r = new Date(d);
    r.setDate(d.getDate() - d.getDay());
    return r;
  };
  const startOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
  const startOfQuarter = (d: Date) => {
    const q = Math.floor(d.getMonth() / 3);
    return new Date(d.getFullYear(), q * 3, 1);
  };
  const startOfYear = (d: Date) => new Date(d.getFullYear(), 0, 1);

  const daysAgo = (n: number) => {
    const r = new Date(now);
    r.setDate(r.getDate() - n);
    return fmt(r);
  };

  let from: string;
  let to: string = today;

  switch (preset) {
    case "1d":
      from = today; break;
    case "this_week":
      from = fmt(startOfWeek(now)); break;
    case "last_week": {
      const sw = startOfWeek(now);
      const lw = new Date(sw);
      lw.setDate(sw.getDate() - 7);
      const ew = new Date(sw);
      ew.setDate(sw.getDate() - 1);
      from = fmt(lw); to = fmt(ew); break;
    }
    case "7d":
      from = daysAgo(7); break;
    case "this_month":
      from = fmt(startOfMonth(now)); break;
    case "last_month": {
      const sm = startOfMonth(now);
      const lm = new Date(sm);
      lm.setMonth(sm.getMonth() - 1);
      const em = new Date(sm);
      em.setDate(sm.getDate() - 1);
      from = fmt(lm); to = fmt(em); break;
    }
    case "30d":
      from = daysAgo(30); break;
    case "this_quarter":
      from = fmt(startOfQuarter(now)); break;
    case "last_quarter": {
      const sq = startOfQuarter(now);
      const lq = new Date(sq);
      lq.setMonth(sq.getMonth() - 3);
      const eq = new Date(sq);
      eq.setDate(sq.getDate() - 1);
      from = fmt(lq); to = fmt(eq); break;
    }
    case "90d":
      from = daysAgo(90); break;
    case "this_year":
      from = fmt(startOfYear(now)); break;
    case "last_year": {
      const sy = startOfYear(now);
      const ly = new Date(sy);
      ly.setFullYear(sy.getFullYear() - 1);
      const ey = new Date(sy);
      ey.setDate(sy.getDate() - 1);
      from = fmt(ly); to = fmt(ey); break;
    }
    case "365d":
      from = daysAgo(365); break;
    case "custom":
      from = customFrom || daysAgo(30);
      to = customTo || today;
      break;
    default:
      from = daysAgo(30);
  }

  const days = (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000;
  const bucket: "day" | "week" | "month" = days <= 45 ? "day" : days <= 180 ? "week" : "month";
  return { from, to, bucket };
}

const PRESETS: { key: Preset; label: string }[] = [
  { key: "1d", label: "Today" },
  { key: "7d", label: "Last 7d" },
  { key: "30d", label: "Last 30d" },
  { key: "this_week", label: "This week" },
  { key: "last_week", label: "Last week" },
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "90d", label: "Last 90d" },
  { key: "this_quarter", label: "This quarter" },
  { key: "last_quarter", label: "Last quarter" },
  { key: "this_year", label: "This year" },
  { key: "last_year", label: "Last year" },
  { key: "365d", label: "Last 365d" },
  { key: "custom", label: "Custom…" },
];

function usd(val: string | number): string {
  const n = typeof val === "string" ? parseFloat(val) : val;
  return Number.isFinite(n)
    ? n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "$—";
}

function usdFine(val: number, currency = "USD"): string {
  return Number.isFinite(val)
    ? val.toLocaleString("en-US", { style: "currency", currency, maximumFractionDigits: 2 })
    : "$—";
}

function addUtcDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function fillDailySeries(points: SpendDailyPoint[], from: string, to: string): SpendDailyPoint[] {
  const map = new Map(points.map((p) => [p.date, p.cost]));
  const out: SpendDailyPoint[] = [];
  for (let day = from; day <= to; day = addUtcDays(day, 1)) {
    out.push({ date: day, cost: map.get(day) ?? 0 });
  }
  return out;
}

// ── Billing section component ─────────────────────────────────────────────────

function BillingSection() {
  const [preset, setPreset] = useState<Preset>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [billing, setBilling] = useState<DashboardBilling | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRange, setLastRange] = useState<DateRange | null>(null);
  const [agingDetail, setAgingDetail] = useState<AgingDetail | null>(null);
  const [agingLoading, setAgingLoading] = useState(false);
  const [agingError, setAgingError] = useState<string | null>(null);
  const agingRequestId = useRef(0);
  const [branches, setBranches] = useState<BranchRow[]>([]);
  // undefined = "All branches"
  const [branch, setBranch] = useState<string | undefined>(undefined);

  useEffect(() => { listBranches().then(setBranches).catch(() => undefined); }, []);

  function fetch(p: Preset, cf: string, ct: string, br: string | undefined) {
    setLoading(true);
    setError(null);
    const { from, to, bucket } = rangeForPreset(p, cf, ct);
    setLastRange({ from, to, bucket });
    getDashboardBilling({ from, to, bucket, branch: br })
      .then(setBilling)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  function closeAgingBucket() {
    // Invalidate any in-flight drill-down request so a slow response cannot
    // re-open the full-screen overlay after the user closes it.
    agingRequestId.current += 1;
    setAgingLoading(false);
    setAgingDetail(null);
    setAgingError(null);
  }

  function openAgingBucket(bucket: AgingBucketKey) {
    const asOf = lastRange?.to;
    const requestId = agingRequestId.current + 1;
    agingRequestId.current = requestId;
    setAgingLoading(true);
    setAgingError(null);
    setAgingDetail(null);
    getAgingDetail(bucket, asOf, branch)
      .then((detail) => {
        if (agingRequestId.current === requestId) setAgingDetail(detail);
      })
      .catch((e: unknown) => {
        if (agingRequestId.current === requestId) setAgingError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (agingRequestId.current === requestId) setAgingLoading(false);
      });
  }

  useEffect(() => { fetch(preset, customFrom, customTo, branch); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handlePreset(p: Preset) {
    setPreset(p);
    if (p !== "custom") fetch(p, customFrom, customTo, branch);
  }

  function handleCustomApply() {
    fetch("custom", customFrom, customTo, branch);
  }

  function handleBranchChange(v: string) {
    const next = v === "" ? undefined : v;
    setBranch(next);
    fetch(preset, customFrom, customTo, next);
  }

  // Build chart data: merge payments + invoices by period
  const timeSeriesData = billing
    ? (() => {
        const map = new Map<string, { period: string; payments: number; invoices: number; inv_count: number; pay_count: number }>();
        for (const p of billing.payments_over_time) {
          map.set(p.period, { period: p.period, payments: parseFloat(p.total), invoices: 0, inv_count: 0, pay_count: p.count });
        }
        for (const i of billing.invoices_issued_over_time) {
          const existing = map.get(i.period);
          if (existing) {
            existing.invoices = parseFloat(i.total);
            existing.inv_count = i.count;
          } else {
            map.set(i.period, { period: i.period, payments: 0, invoices: parseFloat(i.total), inv_count: i.count, pay_count: 0 });
          }
        }
        return [...map.values()].sort((a, b) => a.period.localeCompare(b.period));
      })()
    : [];

  const agingData = billing
    ? [
        { key: "current" as const, name: "Current", value: parseFloat(billing.aging_buckets.current) },
        { key: "d1_30" as const, name: "1–30d", value: parseFloat(billing.aging_buckets.d1_30) },
        { key: "d31_60" as const, name: "31–60d", value: parseFloat(billing.aging_buckets.d31_60) },
        { key: "d61_90" as const, name: "61–90d", value: parseFloat(billing.aging_buckets.d61_90) },
        { key: "d90_plus" as const, name: "90d+", value: parseFloat(billing.aging_buckets.d90_plus) },
      ]
    : [];

  const funnelTimeData = billing?.proposal_funnel_over_time ?? [];

  const agingLabel = (bucket: string) => agingData.find((r) => r.key === bucket)?.name ?? bucket;
  const invoiceLabel = (row: { invoice_number: number | null; knowify_invoice_number: string | null; invoice_id: number }) => {
    if (row.invoice_number != null) return `#${row.invoice_number}`;
    if (row.knowify_invoice_number) return String(row.knowify_invoice_number);
    return `Invoice ${row.invoice_id}`;
  };

  const pillStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 12px",
    borderRadius: 16,
    border: active ? `1.5px solid ${BRAND.navy}` : `1.5px solid ${BRAND.border}`,
    background: active ? BRAND.navy : "#fff",
    color: active ? "#fff" : BRAND.sub,
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    whiteSpace: "nowrap" as const,
  });

  return (
    <>
      <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
        Billing &amp; Receivables
      </h3>

      {/* Preset bar */}
      <Card style={{ marginBottom: 20, padding: "12px 16px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          {PRESETS.map(({ key, label }) => (
            <button key={key} style={pillStyle(preset === key)} onClick={() => handlePreset(key)}>
              {label}
            </button>
          ))}
          <select
            value={branch ?? ""}
            onChange={(e) => handleBranchChange(e.target.value)}
            style={{ ...inputStyle, padding: "5px 8px", fontSize: 13, marginLeft: 8 }}
          >
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b.key} value={b.key}>{b.name}</option>
            ))}
          </select>
          {preset === "custom" && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: 8 }}>
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                style={{ ...inputStyle, padding: "5px 8px", fontSize: 13 }}
              />
              <span style={{ color: BRAND.sub, fontSize: 13 }}>to</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                style={{ ...inputStyle, padding: "5px 8px", fontSize: 13 }}
              />
              <Button
                onClick={handleCustomApply}
                disabled={!customFrom || !customTo}
                style={{ padding: "5px 14px", fontSize: 13 }}
              >
                Apply
              </Button>
            </div>
          )}
        </div>
      </Card>

      {loading && <Loading />}
      {error && <ErrorMsg>Billing error: {error}</ErrorMsg>}

      {!loading && !error && billing && (
        <>
          {/* AR summary stat cards */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
            <StatCard
              label="Open Invoices"
              value={billing.open_ar_summary.open_count.toLocaleString()}
              sub="unpaid invoices"
            />
            <StatCard
              label="Open AR Total"
              value={usd(billing.open_ar_summary.open_total)}
              sub="invoiced, not yet paid"
            />
            <StatCard
              label="Outstanding AR"
              value={usd(billing.open_ar_summary.outstanding_total)}
              sub="past due"
            />
            <StatCard
              label="Due Next 30 Days"
              value={usd(billing.receivables_due_next_30.total)}
              sub={`${billing.receivables_due_next_30.count} invoice${billing.receivables_due_next_30.count === 1 ? "" : "s"}`}
            />
            <StatCard
              label="Proposal Win Rate"
              value={`${(billing.proposal_funnel.win_rate * 100).toFixed(1)}%`}
              sub={`${billing.proposal_funnel.accepted} accepted`}
            />
          </div>

          {/* Payments + Invoices over time */}
          <Card style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
              Payments &amp; Invoices Issued
            </div>
            {timeSeriesData.length === 0 ? (
              <div style={{ color: BRAND.sub, fontSize: 13 }}>No data for this period.</div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={timeSeriesData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={BRAND.border} />
                  <XAxis dataKey="period" tick={{ fontSize: 11, fill: BRAND.sub }} />
                  <YAxis
                    tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                    tick={{ fontSize: 11, fill: BRAND.sub }}
                    width={56}
                  />
                  <Tooltip
                    formatter={(value, name) => [usd(Number(value)), name === "payments" ? "Payments" : "Invoiced"]}
                    labelStyle={{ color: BRAND.navyText, fontWeight: 600 }}
                  />
                  <Legend formatter={(v: string) => v === "payments" ? "Payments" : "Invoiced"} />
                  <Bar dataKey="invoices" name="invoices" fill={BRAND.navy} opacity={0.7} radius={[3, 3, 0, 0]} />
                  <Line dataKey="payments" name="payments" stroke={BRAND.red} strokeWidth={2} dot={false} type="monotone" />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </Card>

          {/* Aging buckets */}
          <Card style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
              AR Aging
            </div>
            <div style={{ color: BRAND.sub, fontSize: 12, marginBottom: 8 }}>
              Click a bar to see the customers and invoices in that aging bucket.
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={agingData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={BRAND.border} />
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: BRAND.sub }} />
                <YAxis
                  tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                  tick={{ fontSize: 11, fill: BRAND.sub }}
                  width={56}
                />
                <Tooltip formatter={(value) => [usd(Number(value)), "Balance"]} />
                <Bar
                  dataKey="value"
                  name="Balance"
                  radius={[4, 4, 0, 0]}
                  cursor="pointer"
                  onClick={(data) => {
                    const item = (data as { payload?: { key?: AgingBucketKey; value?: number } }).payload;
                    if (item?.key && (item.value ?? 0) > 0) openAgingBucket(item.key);
                  }}
                >
                  {agingData.map((entry, i) => (
                    <Cell key={entry.name} fill={i === 0 ? BRAND.navyText : i === 1 ? "#b45309" : i === 2 ? "#e07b39" : i === 3 ? "#d95050" : BRAND.red} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>

          {(agingDetail || agingLoading || agingError) && (
            <div
              role="dialog"
              aria-modal="true"
              aria-label="AR aging bucket detail"
              onClick={closeAgingBucket}
              style={{
                position: "fixed",
                inset: 0,
                zIndex: 1200,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "rgba(16,24,40,0.24)",
                padding: 24,
              }}
            >
              <Card onClick={(e) => e.stopPropagation()} style={{ width: "min(980px, 96vw)", maxHeight: "86vh", overflow: "auto", padding: 0 }}>
                <div style={{ padding: "18px 22px", borderBottom: `1px solid ${BRAND.border}`, display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: BRAND.navyText }}>
                      AR Aging — {agingDetail ? agingLabel(agingDetail.bucket) : "Loading…"}
                    </div>
                    {agingDetail && (
                      <div style={{ marginTop: 3, fontSize: 12, color: BRAND.sub }}>
                        As of {agingDetail.as_of} · {agingDetail.items.length} open invoice{agingDetail.items.length === 1 ? "" : "s"}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={closeAgingBucket}
                    style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1 }}
                    aria-label="Close aging detail"
                  >
                    ×
                  </button>
                </div>
                <div style={{ padding: 22 }}>
                  {agingLoading && <Loading label="Loading aging detail…" />}
                  {agingError && <ErrorMsg>Error: {agingError}</ErrorMsg>}
                  {agingDetail && agingDetail.items.length === 0 && (
                    <div style={{ color: BRAND.sub, fontSize: 13 }}>No open invoices in this bucket.</div>
                  )}
                  {agingDetail && agingDetail.items.length > 0 && (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                        <thead>
                          <tr>
                            <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Customer</th>
                            <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Invoice</th>
                            <th style={{ textAlign: "left", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Due</th>
                            <th style={{ textAlign: "right", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Total</th>
                            <th style={{ textAlign: "right", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Paid</th>
                            <th style={{ textAlign: "right", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Outstanding</th>
                            <th style={{ textAlign: "right", padding: "8px 10px", borderBottom: `2px solid ${BRAND.border}` }}>Days past</th>
                          </tr>
                        </thead>
                        <tbody>
                          {agingDetail.items.map((row) => (
                            <tr key={row.invoice_id}>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}` }}>{row.customer_name ?? `Customer ${row.customer_id ?? "—"}`}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}`, fontWeight: 600 }}>{invoiceLabel(row)}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}` }}>{row.due_date ? new Date(row.due_date).toLocaleDateString() : "—"}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}`, textAlign: "right" }}>{usd(Number(row.total))}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}`, textAlign: "right" }}>{usd(Number(row.paid))}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}`, textAlign: "right", fontWeight: 700 }}>{usd(Number(row.outstanding))}</td>
                              <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BRAND.border}`, textAlign: "right" }}>{Math.max(row.days_past_due, 0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </Card>
            </div>
          )}

          {/* Proposal funnel over time */}
          <Card style={{ marginBottom: 32 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
              Proposal Funnel Over Time
            </div>
            <div style={{ color: BRAND.sub, fontSize: 12, marginBottom: 12 }}>
              Grouped on the same {lastRange?.bucket ?? "day"} time scale as Payments/Invoiced above. Sent includes viewed proposals.
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={funnelTimeData} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={BRAND.border} />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: BRAND.sub }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: BRAND.sub }} width={44} />
                <Tooltip formatter={(value, name) => [Number(value).toLocaleString(), name]} />
                <Legend />
                <Bar dataKey="draft" name="Draft" fill="#667085" radius={[3, 3, 0, 0]} />
                <Bar dataKey="sent" name="Sent / Viewed" fill={BRAND.navyText} radius={[3, 3, 0, 0]} />
                <Bar dataKey="accepted" name="Accepted" fill="#1a7f4b" radius={[3, 3, 0, 0]} />
                <Bar dataKey="declined" name="Declined" fill={BRAND.red} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}
    </>
  );
}

// ── Active Users widget ───────────────────────────────────────────────────────

function ActiveUsersWidget() {
  const [data, setData] = useState<ActiveUsersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getActiveUsers({ days: 30 })
      .then(setData)
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        // 403 = not admin; degrade silently with inline note
        setError(msg.startsWith("403") || msg.includes("403") ? "admin-only" : msg);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (error === "admin-only") return null; // not shown to non-admins

  return (
    <Card style={{ marginBottom: 20, padding: "16px 20px" }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
        Active Users (last 30 days)
      </div>
      {error && <ErrorMsg>Users: {error}</ErrorMsg>}
      {data?.error && <div style={{ color: BRAND.red, fontSize: 13, marginBottom: 8 }}>Note: {data.error}</div>}
      {data && (
        <>
          <div style={{ display: "flex", gap: 24, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText }}>{data.active_users.toLocaleString()}</div>
              <div style={{ fontSize: 12, color: BRAND.sub }}>active / {data.window_days}d</div>
            </div>
            <div style={{ width: 1, background: BRAND.border, alignSelf: "stretch" }} />
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText }}>{data.total_users.toLocaleString()}</div>
              <div style={{ fontSize: 12, color: BRAND.sub }}>total users</div>
            </div>
          </div>
          {data.recent.length > 0 && (
            <div style={{ fontSize: 13 }}>
              {data.recent.slice(0, 5).map((u) => (
                <div key={u.email ?? "anon"} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: `1px solid ${BRAND.border}` }}>
                  <span style={{ color: BRAND.navyText }}>{u.email ?? "(no email)"}</span>
                  <span style={{ color: BRAND.sub, fontSize: 12 }}>
                    {u.last_sign_in ? new Date(u.last_sign_in).toLocaleDateString() : "—"}
                    {u.disabled && <span style={{ color: BRAND.red, marginLeft: 6 }}>disabled</span>}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ── GCP Spend widget ──────────────────────────────────────────────────────────

const SPEND_WINDOWS: { key: number; label: string }[] = [
  { key: 7, label: "7d" },
  { key: 30, label: "30d" },
  { key: 0, label: "This month" },
  { key: 90, label: "90d" },
];

function spendFetchDays(preset: number): number {
  const mtd = new Date().getUTCDate();
  return preset === 0 ? mtd : Math.max(preset, mtd);
}

function GcpSpendWidget() {
  const [preset, setPreset] = useState(30);
  const [data, setData] = useState<GcpSpendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGcpSpend({ days: spendFetchDays(preset) })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg.startsWith("403") || msg.includes("403") ? "admin-only" : msg);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [preset]);

  if (loading && !data) return <Loading />;
  if (error === "admin-only") return null;

  const today = fmt(new Date());
  const monthStart = `${today.slice(0, 8)}01`;
  const windowFrom = preset === 0 ? monthStart : addUtcDays(today, -preset);
  const configured = Boolean(data && data.configured);
  const currency = data && data.configured ? data.currency : "USD";
  const queryError = data && data.configured ? data.error : undefined;
  const exportNote = data && data.configured ? data.note : undefined;
  const dailyRaw: SpendDailyPoint[] = data && data.configured && Array.isArray(data.daily) ? data.daily : [];
  const byService: SpendByService[] = data && data.configured && Array.isArray(data.by_service) ? data.by_service : [];
  const chartFrom = dailyRaw.length ? dailyRaw[0].date : windowFrom;
  const chartTo = dailyRaw.length ? dailyRaw[dailyRaw.length - 1].date : today;
  const chartData = fillDailySeries(dailyRaw, chartFrom, chartTo);
  const windowTotal = chartData.reduce((s, p) => s + p.cost, 0);
  const mtdTotal = dailyRaw.filter((p) => p.date >= monthStart).reduce((s, p) => s + p.cost, 0);
  const empty = !queryError && dailyRaw.length === 0 && byService.length === 0;
  const topServices = byService.slice(0, 8);
  const windowLabel = preset === 0 ? "this month" : `${preset}d`;
  const yesterdayKey = addUtcDays(today, -1);
  const yesterday = dailyRaw.find((p) => p.date === yesterdayKey)?.cost;

  const pillStyle = (active: boolean): React.CSSProperties => ({
    padding: "4px 10px",
    borderRadius: 16,
    border: active ? `1.5px solid ${BRAND.navy}` : `1.5px solid ${BRAND.border}`,
    background: active ? BRAND.navy : "#fff",
    color: active ? "#fff" : BRAND.sub,
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    whiteSpace: "nowrap" as const,
  });

  return (
    <Card style={{ marginBottom: 20, padding: "16px 20px" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5 }}>
          GCP Spend
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {SPEND_WINDOWS.map((w) => (
            <button key={w.key} style={pillStyle(preset === w.key)} onClick={() => setPreset(w.key)}>
              {w.label}
            </button>
          ))}
        </div>
      </div>
      {error && <ErrorMsg>GCP Spend: {error}</ErrorMsg>}
      {queryError && <div style={{ color: BRAND.red, fontSize: 13, marginBottom: 8 }}>Note: {queryError}</div>}
      {exportNote && !queryError && (
        <div style={{ color: BRAND.sub, fontSize: 13, marginBottom: 10, lineHeight: 1.45 }}>{exportNote}</div>
      )}
      {empty && !error && (
        <div
          style={{
            background: "#f7f1e6",
            borderRadius: 10,
            padding: "16px 18px",
            margin: "4px 0 2px",
          }}
        >
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 4 }}>
            No spend data yet
          </div>
          <div style={{ color: BRAND.sub, fontSize: 13, lineHeight: 1.5 }}>
            Daily cloud spend will appear here after the first scheduled import completes.
          </div>
          <div style={{ color: BRAND.sub, fontSize: 12, marginTop: 6 }}>Expected cadence: once per day</div>
        </div>
      )}
      {!empty && configured && !queryError && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText, lineHeight: 1.1 }}>
                {usdFine(mtdTotal, currency)}
              </div>
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>This month</div>
              {yesterday != null && (
                <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                  Yesterday: {usdFine(yesterday, currency)}
                </div>
              )}
            </div>
            <div style={{ width: 1, background: BRAND.border, alignSelf: "stretch", minHeight: 40 }} />
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText, lineHeight: 1.1 }}>
                {usdFine(windowTotal, currency)}
              </div>
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>{windowLabel} total</div>
            </div>
          </div>
          <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Daily trend
          </div>
          <div style={{ width: "100%", minWidth: 0, marginBottom: 16 }}>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={BRAND.border} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: BRAND.sub }}
                  tickFormatter={(d: string) => {
                    const parts = d.split("-");
                    return `${Number(parts[1])}/${Number(parts[2])}`;
                  }}
                  interval="preserveStartEnd"
                  minTickGap={28}
                />
                <YAxis
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                  tick={{ fontSize: 11, fill: BRAND.sub }}
                  width={48}
                />
                <Tooltip
                  formatter={(v) => [usdFine(Number(v), currency), "Cost"]}
                  labelStyle={{ color: BRAND.navyText, fontWeight: 600 }}
                />
                <Area
                  type="monotone"
                  dataKey="cost"
                  stroke={BRAND.navyText}
                  fill={BRAND.navy}
                  fillOpacity={0.15}
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {topServices.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                Top services
              </div>
              <div>
                {topServices.map((s) => (
                  <div
                    key={s.service}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      padding: "6px 0",
                      borderBottom: `1px solid ${BRAND.border}`,
                      fontSize: 13,
                    }}
                  >
                    <span style={{ color: BRAND.navyText }}>{s.service}</span>
                    <span style={{ color: BRAND.sub, fontWeight: 600, whiteSpace: "nowrap" }}>{usdFine(s.cost, currency)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}

// ── Go-live checklist banner ──────────────────────────────────────────────────
// Non-WP leftovers only. Wendy / staging / Rank Math / permalinks / WP author
// and the prod app-password row stay off this list — that stack is being replaced.
const GO_LIVE_DISMISSED_KEY = "perkins.goLiveChecklistDismissed.v4";

interface GoLiveItem {
  label: string;
}

const GO_LIVE_ITEMS: GoLiveItem[] = [
  { label: "SEO submission creds provisioned IF enabling (IndexNow key + Google Indexing API service account) — toggle is OFF by default" },
  { label: "Remaining Tim pricing items confirmed (per-branch OH, gutter hangers, downspout $10.50, Verea field-tile, FBC low-slope deltas, T&C)" },
];

function GoLiveChecklistBanner() {
  const [dismissed, setDismissed] = useState(() => window.localStorage.getItem(GO_LIVE_DISMISSED_KEY) === "1");

  function dismiss() {
    window.localStorage.setItem(GO_LIVE_DISMISSED_KEY, "1");
    setDismissed(true);
  }

  if (dismissed) {
    return (
      <div style={{ marginBottom: 24, textAlign: "right" }}>
        <button
          onClick={() => { window.localStorage.removeItem(GO_LIVE_DISMISSED_KEY); setDismissed(false); }}
          style={{ background: "none", border: "none", color: BRAND.sub, fontSize: 12, cursor: "pointer", textDecoration: "underline" }}
        >
          Show go-live checklist
        </button>
      </div>
    );
  }

  return (
    <Card style={{ marginBottom: 24, padding: "14px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <span style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>
          Go-Live Checklist — {GO_LIVE_ITEMS.length} open
        </span>
        <button
          onClick={dismiss}
          title="Dismiss"
          style={{ background: "none", border: "none", color: BRAND.sub, fontSize: 16, cursor: "pointer", lineHeight: 1, padding: 0 }}
        >
          &times;
        </button>
      </div>
      <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: BRAND.ink, lineHeight: 1.9 }}>
        {GO_LIVE_ITEMS.map((item) => (
          <li key={item.label}>
            {item.label}
            <span style={{ marginLeft: 8 }}><Badge tone="amber">Manual</Badge></span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function LongformQueue() {
  const [rows, setRows] = useState<Array<{
    id: string;
    title: string;
    duration: number | null;
    youtube_url: string | null;
    longform_reprocessed_at: string | null;
  }>>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    apiFetch("/archive/videos?min_length=600&unchopped=true&limit=200")
      .then(async (res) => {
        if (!res.ok) throw new Error(await errText(res));
        return res.json();
      })
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, []);

  const open = rows;

  async function markDone(id: string) {
    setBusy(id);
    const clipUrls = (urls[id] || "").split(/\s+/).map((s) => s.trim()).filter(Boolean);
    try {
      const res = await apiFetch(`/archive/${id}/longform-reprocessed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: "chopped", urls: clipUrls }),
      });
      if (!res.ok) throw new Error(await errText(res));
      const updated = await res.json();
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...updated } : r)));
    } catch {
      /* badge stays */
    } finally {
      setBusy(null);
    }
  }

  if (loading) return null;
  return (
    <Card style={{ marginBottom: 16, padding: "14px 20px" }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, marginBottom: 4 }}>
        Long videos (≥10 min) — {open.length} not chopped
      </div>
      <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 10 }}>
        After you upload the slices, paste their YouTube URLs here. Those clips will not
        generate new articles, FAQs, or topic suggestions. We still cannot push to YouTube from this app.
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7, maxHeight: 360, overflow: "auto" }}>
        {open.slice(0, 20).map((r) => (
          <li key={r.id} style={{ marginBottom: 10 }}>
            {r.youtube_url ? (
              <a href={r.youtube_url} target="_blank" rel="noreferrer" style={{ color: BRAND.navyText }}>
                {r.title || r.id}
              </a>
            ) : (r.title || r.id)}
            <span style={{ color: BRAND.sub, marginLeft: 8 }}>{fmtDuration(r.duration)}</span>
            <div style={{ marginTop: 4 }}>
              <textarea
                placeholder="https://youtu.be/… (one clip URL per line)"
                value={urls[r.id] || ""}
                onChange={(e) => setUrls((prev) => ({ ...prev, [r.id]: e.target.value }))}
                style={{ ...inputStyle, width: "100%", minHeight: 52, fontSize: 12 }}
              />
              <button
                onClick={() => markDone(r.id)}
                disabled={busy === r.id}
                style={{ marginTop: 4, fontSize: 12, cursor: "pointer" }}
              >
                {busy === r.id ? "Saving…" : "Mark chopped + join clips"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ── Production Readiness banner ───────────────────────────────────────────────
// Compact status strip: N/M gates ready, a colored chip per gate, and a re-test
// button. Explanation + remediation for each gate lives in Admin Config; this is
// just the at-a-glance signal every admin sees on load.

const GATE_TONE: Record<GateState, "green" | "amber" | "red" | "gray"> = {
  ok: "green",
  warn: "amber",
  blocker: "red",
  unknown: "gray",
};

function ProductionReadinessBanner() {
  const [data, setData] = useState<ProductionReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function fetchReadiness() {
    setLoading(true);
    setError(null);
    getProductionReadiness()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { fetchReadiness(); }, []);

  return (
    <Card style={{ marginBottom: 24, padding: "14px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14 }}>
            Production Readiness
            {data && ` — ${data.summary.ok}/${data.summary.total} gates ready`}
          </span>
          {loading && <Loading label="Checking…" />}
          {error && <ErrorMsg>Error: {error}</ErrorMsg>}
          {!loading && !error && data && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {data.gates.map((g) => (
                <Badge key={g.id} tone={GATE_TONE[g.state]}>
                  {g.label}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <Button variant="ghost" onClick={fetchReadiness} disabled={loading}>
          Re-test
        </Button>
      </div>
      {!loading && !error && data && data.summary.blocker > 0 && (
        <div style={{ marginTop: 10, fontSize: 13, color: BRAND.redDark, fontWeight: 600 }}>
          {data.summary.blocker} blocker{data.summary.blocker > 1 ? "s" : ""} — see Admin Config → Platform Settings for remediation.
        </div>
      )}
    </Card>
  );
}

// ── Main Status page ──────────────────────────────────────────────────────────

export function Status() {
  const { navigate } = useContext(NavContext);
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null); // "video_id:stage" key
  const [toast, setToast] = useState<Toast | null>(null);

  function showToast(message: string, tone: ToastTone) {
    setToast({ message, tone });
    setTimeout(() => setToast(null), 4000);
  }

  function fetchStatus() {
    setLoading(true);
    setError(null);
    apiFetch("/status")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((d: StatusData) => setData(d))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  function retryStage(video_id: string, stage: string) {
    const key = `${video_id}:${stage}`;
    setRetrying(key);
    apiFetch("/status/retry", {
      method: "POST",
      body: JSON.stringify({ video_id, stage }),
    })
      .then((r) => {
        if (!r.ok) return errText(r).then((m) => { throw new Error(m); });
        return r.json();
      })
      .then((d: { reset: number }) => {
        showToast(`Re-queued ${d.reset} run(s) for next ingest. Refresh to confirm.`, "green");
        fetchStatus();
      })
      .catch((e: unknown) => showToast(`Retry failed: ${e instanceof Error ? e.message : String(e)}`, "red"))
      .finally(() => setRetrying(null));
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  const kpis: KpiCard[] = data
    ? [
        { label: "Total Videos", value: data.videos, color: BRAND.navyText, navTarget: "archive" },
        { label: "Embedded", value: data.videos_embedded, color: BRAND.navyText, navTarget: "archive" },
        { label: "Archived", value: data.videos_archived, color: BRAND.navyText, navTarget: "archive" },
        { label: "Transcripts Done", value: data.transcripts_done, color: BRAND.navyText, navTarget: "archive" },
        { label: "Articles", value: data.articles, color: BRAND.navyText, navTarget: "articles" },
        { label: "FAQ Entries", value: data.faq_count, color: BRAND.navyText, navTarget: "faq" },
        { label: "Scheduled Content", value: data.scheduled_content, color: BRAND.navyText, navTarget: "scheduling" },
        ...(data.content_opportunities != null
          ? [{ label: "Content Opportunities", value: data.content_opportunities, color: data.content_opportunities > 0 ? "#b45309" : BRAND.navyText, navTarget: "search-ask" }]
          : []),
        ...(data.comments_to_answer != null
          ? [{ label: "Comments to Answer", value: data.comments_to_answer, color: data.comments_to_answer > 0 ? "#b45309" : BRAND.navyText, navTarget: "comments" }]
          : []),
        ...(data.videos_to_approve != null
          ? [{ label: "Videos to Approve", value: data.videos_to_approve, color: data.videos_to_approve > 0 ? "#b45309" : BRAND.navyText, navTarget: "scheduling" }]
          : []),
      ]
    : [];

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle right={<Button onClick={fetchStatus} disabled={loading}>Refresh</Button>}>
        Platform Status
      </PageTitle>

      <DataSources />
      <ProductionReadinessBanner />
      <LongformQueue />

      {toast && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 16px",
            borderRadius: 8,
            background: toast.tone === "green" ? "#e6f9f0" : "#fdecea",
            color: toast.tone === "green" ? "#1a7f4b" : BRAND.red,
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          {toast.message}
        </div>
      )}

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && data && (
        <>
          {/* KPI grid */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 16,
              marginBottom: 32,
            }}
          >
            {kpis.map((kpi) => (
              <Card
                key={kpi.label}
                onClick={kpi.navTarget ? () => navigate(kpi.navTarget!) : undefined}
                style={{
                  flex: "1 1 140px",
                  minWidth: 140,
                  textAlign: "center",
                  cursor: kpi.navTarget ? "pointer" : "default",
                  transition: "box-shadow 0.15s",
                }}
                onMouseEnter={kpi.navTarget ? (e) => { (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(0,0,0,0.10)"; } : undefined}
                onMouseLeave={kpi.navTarget ? (e) => { (e.currentTarget as HTMLElement).style.boxShadow = ""; } : undefined}
              >
                <div
                  style={{
                    fontSize: 36,
                    fontWeight: 700,
                    color: kpi.color ?? BRAND.navyText,
                    lineHeight: 1.1,
                    marginBottom: 6,
                  }}
                >
                  {kpi.value.toLocaleString()}
                </div>
                <div style={{ fontSize: 13, color: BRAND.sub, fontWeight: 500 }}>
                  {kpi.label}
                </div>
              </Card>
            ))}
          </div>

          {/* Billing & Receivables section */}
          <BillingSection />

          <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
            Platform Metrics
          </h3>
          <ActiveUsersWidget />

          <GoLiveChecklistBanner />

          <GcpSpendWidget />

          {/* Scheduled content breakdown */}
          {data.scheduled_breakdown && (
            <>
              <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
                Scheduled Content Breakdown
              </h3>
              <Card style={{ marginBottom: 32, padding: "16px 20px" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                      Articles
                    </div>
                    <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText }}>
                      {data.scheduled_breakdown.articles.count}
                    </div>
                    {data.scheduled_breakdown.articles.next_up && (
                      <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                        Next: {new Date(data.scheduled_breakdown.articles.next_up).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                  <div style={{ width: 1, background: BRAND.border, alignSelf: "stretch" }} />
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                      Social Posts
                    </div>
                    <div style={{ display: "flex", gap: 16, alignItems: "baseline", flexWrap: "wrap" }}>
                      {Object.entries(data.scheduled_breakdown.social)
                        .filter(([, b]) => b.count > 0)
                        .map(([platform, b]) => (
                          <span key={platform}>
                            <span style={{ fontSize: 22, fontWeight: 700, color: BRAND.navyText }}>{b.count}</span>
                            <span style={{ fontSize: 12, color: BRAND.sub, marginLeft: 4, textTransform: "capitalize" }}>{platform}</span>
                            {b.next_up && (
                              <span style={{ fontSize: 11, color: BRAND.sub, marginLeft: 4 }}>
                                (next {new Date(b.next_up).toLocaleDateString()})
                              </span>
                            )}
                          </span>
                        ))}
                      {Object.values(data.scheduled_breakdown.social).every((b) => b.count === 0) && (
                        <span style={{ fontSize: 14, color: BRAND.sub }}>None scheduled</span>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            </>
          )}

          {/* Failed stages */}
          <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
            Failed Stages
          </h3>

          {data.failed_stages.length === 0 ? (
            <div style={{ marginBottom: 8 }}>
              <Badge tone="green">No failed stages</Badge>
            </div>
          ) : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Video</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Stage</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Error</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.failed_stages.map((f, i) => {
                    const key = `${f.video_id}:${f.stage}`;
                    const busy = retrying === key;
                    return (
                      <tr
                        key={`${f.video_id}-${f.stage}-${i}`}
                        style={{ borderBottom: `1px solid ${BRAND.border}` }}
                      >
                        <td style={{ padding: "10px 16px" }}>
                          <a
                            href={f.youtube_url ?? `https://youtu.be/${f.video_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none" }}
                          >
                            {f.title ?? "▶ watch on YouTube"}
                          </a>
                        </td>
                        <td style={{ padding: "10px 16px" }}>
                          <Badge tone="amber">{f.stage}</Badge>
                        </td>
                        <td style={{ padding: "10px 16px", color: BRAND.red, fontSize: 13 }}>
                          {f.error}
                        </td>
                        <td style={{ padding: "10px 16px" }}>
                          <Button
                            variant="ghost"
                            disabled={busy}
                            style={{ padding: "5px 12px", fontSize: 13 }}
                            onClick={() => retryStage(f.video_id, f.stage)}
                            title="Re-queues this stage for the next ingest run"
                          >
                            {busy ? "Queuing…" : "Retry"}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          )}

          {/* Processing / Queue */}
          <h3 style={{ margin: "32px 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
            Processing / Queue
          </h3>

          {data.queue.length === 0 ? (
            <div style={{ marginBottom: 8 }}>
              <Badge tone="green">Queue empty</Badge>
            </div>
          ) : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Video</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Stage</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.queue.map((q, i) => (
                    <tr
                      key={`${q.video_id}-${q.stage}-${i}`}
                      style={{ borderBottom: `1px solid ${BRAND.border}` }}
                    >
                      <td style={{ padding: "10px 16px" }}>
                        <a
                          href={`https://youtu.be/${q.video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: BRAND.navyText, fontWeight: 600, textDecoration: "none" }}
                        >
                          {q.title ?? q.video_id}
                        </a>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <Badge tone="amber">{q.stage}</Badge>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <Badge tone={q.status === "running" ? "green" : "amber"}>{q.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
