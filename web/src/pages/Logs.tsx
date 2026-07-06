import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Badge, Button, Card, ErrorMsg, Loading, PageTitle } from "../ui";

interface LogEntry {
  timestamp: string | null;
  severity: string;
  resource: string;
  message: string;
  log_name: string;
}

interface LogsResponse {
  entries: LogEntry[];
  project: string;
}

type TimeWindow = "1h" | "6h" | "24h" | "7d";
type SeverityFilter = "ERROR" | "WARNING" | "DEFAULT";

const TIME_OPTIONS: { label: string; value: TimeWindow; hours: number }[] = [
  { label: "1h", value: "1h", hours: 1 },
  { label: "6h", value: "6h", hours: 6 },
  { label: "24h", value: "24h", hours: 24 },
  { label: "7d", value: "7d", hours: 168 },
];

const SEVERITY_OPTIONS: { label: string; value: SeverityFilter }[] = [
  { label: "Errors only", value: "ERROR" },
  { label: "Warnings+", value: "WARNING" },
  { label: "All logs", value: "DEFAULT" },
];

function severityBadgeTone(severity: string): "green" | "amber" | "blue" | "gray" {
  const s = severity.toUpperCase();
  if (s === "ERROR" || s === "CRITICAL" || s === "ALERT" || s === "EMERGENCY") return "amber";
  if (s === "WARNING" || s === "NOTICE") return "blue";
  if (s === "INFO") return "green";
  return "gray";
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function MessageCell({ message }: { message: string }) {
  const [expanded, setExpanded] = useState(false);
  const TRUNCATE = 200;
  if (message.length <= TRUNCATE) {
    return <span style={{ fontFamily: "monospace", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{message}</span>;
  }
  return (
    <span style={{ fontFamily: "monospace", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
      {expanded ? message : message.slice(0, TRUNCATE) + "…"}
      {" "}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          background: "none",
          border: "none",
          color: BRAND.navyText,
          cursor: "pointer",
          fontSize: 12,
          padding: 0,
          fontWeight: 600,
          textDecoration: "underline",
        }}
      >
        {expanded ? "collapse" : "expand"}
      </button>
    </span>
  );
}

export function Logs() {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [severity, setSeverity] = useState<SeverityFilter>("ERROR");
  const [data, setData] = useState<LogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function fetchLogs(hours: number, sev: string) {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      hours: String(hours),
      severity: sev,
      limit: "100",
    });
    apiFetch(`/logs?${params}`)
      .then((r) => {
        if (!r.ok) return r.json().then((d: { detail?: string }) => { throw new Error(d.detail ?? `${r.status} ${r.statusText}`); });
        return r.json();
      })
      .then((d: LogsResponse) => setData(d))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    const tw = TIME_OPTIONS.find((t) => t.value === timeWindow)!;
    fetchLogs(tw.hours, severity);
  }, [timeWindow, severity]);

  function handleRefresh() {
    const tw = TIME_OPTIONS.find((t) => t.value === timeWindow)!;
    fetchLogs(tw.hours, severity);
  }

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle
        right={
          <Button onClick={handleRefresh} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </Button>
        }
      >
        GCP Logs
      </PageTitle>

      {/* Controls */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", alignItems: "center" }}>
        {/* Time window toggle */}
        <div style={{ display: "flex", gap: 0, border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
          {TIME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setTimeWindow(opt.value)}
              style={{
                padding: "7px 16px",
                background: timeWindow === opt.value ? BRAND.navy : "#fff",
                color: timeWindow === opt.value ? "#fff" : BRAND.navyText,
                border: "none",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                borderRight: `1px solid ${BRAND.border}`,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Severity toggle */}
        <div style={{ display: "flex", gap: 0, border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
          {SEVERITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setSeverity(opt.value)}
              style={{
                padding: "7px 16px",
                background: severity === opt.value ? BRAND.navy : "#fff",
                color: severity === opt.value ? "#fff" : BRAND.navyText,
                border: "none",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                borderRight: `1px solid ${BRAND.border}`,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {data && !loading && (
          <span style={{ fontSize: 13, color: BRAND.sub }}>
            {data.entries.length} {data.entries.length === 1 ? "entry" : "entries"} — project: <strong>{data.project}</strong>
          </span>
        )}
      </div>

      {loading && <Loading />}
      {error && (
        <ErrorMsg>
          {error.includes("503") || error.toLowerCase().includes("cloud logging") || error.toLowerCase().includes("credentials")
            ? "Cloud Logging unavailable — check GCP credentials or service account permissions."
            : `Error: ${error}`}
        </ErrorMsg>
      )}

      {!loading && !error && data && (
        <>
          {data.entries.length === 0 ? (
            <Card>
              <p style={{ margin: 0, color: BRAND.sub, fontSize: 14 }}>
                No log entries found for the selected time window and severity.
              </p>
            </Card>
          ) : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left", background: "#fafbfc" }}>
                    <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600, whiteSpace: "nowrap" }}>Timestamp</th>
                    <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Severity</th>
                    <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600 }}>Service</th>
                    <th style={{ padding: "10px 14px", color: BRAND.sub, fontWeight: 600, width: "55%" }}>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((entry, i) => (
                    <tr
                      key={i}
                      style={{
                        borderBottom: `1px solid ${BRAND.border}`,
                        verticalAlign: "top",
                        background: i % 2 === 0 ? "#fff" : "#fafbfc",
                      }}
                    >
                      <td style={{ padding: "10px 14px", whiteSpace: "nowrap", color: BRAND.sub }}>
                        {formatTimestamp(entry.timestamp)}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        <Badge tone={severityBadgeTone(entry.severity)}>{entry.severity}</Badge>
                      </td>
                      <td style={{ padding: "10px 14px", color: BRAND.navyText, fontWeight: 500, whiteSpace: "nowrap" }}>
                        {entry.resource}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        <MessageCell message={entry.message} />
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
