import { useEffect, useState } from "react";
import { listConnections, startOAuth, type Connection } from "../api";
import { BRAND, Badge, Button, Card, ErrorMsg } from "../ui";

const SOURCES: { id: string; label: string; help: string; statusId?: string }[] = [
  {
    id: "knowify",
    label: "Knowify",
    help: "Log in to refresh invoices and customers. Token refresh stays automatic after that.",
  },
  {
    id: "companycam",
    label: "CompanyCam",
    help: "Log in so project photos and videos keep syncing. Also accepts a new application key.",
  },
  {
    id: "youtube",
    statusId: "youtube_reply",
    label: "YouTube",
    help: "Log in as the Perkins channel owner so comment replies can post. Use this if OAuth breaks.",
  },
];

function tone(status: string | undefined): "green" | "amber" | "red" | "gray" {
  if (status === "healthy" || status === "ok" || status === "expiring") return "green";
  if (status === "broken") return "red";
  if (status === "unconfigured") return "gray";
  return "amber";
}

function labelFor(status: string | undefined): string {
  if (status === "healthy" || status === "ok") return "Connected";
  if (status === "expiring") return "Expiring — reconnect";
  if (status === "broken") return "Needs login";
  if (status === "unconfigured") return "Not connected";
  return status || "Unknown";
}

export function DataSources({ manage = true }: { manage?: boolean }) {
  const [rows, setRows] = useState<Record<string, Connection>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listConnections()
      .then((list) => setRows(Object.fromEntries(list.map((c) => [c.integration, c]))))
      .catch(() => undefined);
  }, []);

  async function connect(id: string) {
    setBusy(id);
    setError(null);
    try {
      window.location.href = await startOAuth(id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Could not start ${id} login`);
      setBusy(null);
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, marginBottom: 4 }}>
        Data sources
      </div>
      <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 12 }}>
        Knowify and CompanyCam need a person to log in until long-lived API access is in place.
        After login, refresh keeps the token alive.
      </div>
      {SOURCES.map((src) => {
        const statusRow = rows[src.statusId ?? src.id] ?? rows[src.id];
        const oauthRow = rows[src.id] ?? statusRow;
        const conn = statusRow;
        const status = conn?.status;
        const canLogin = manage && (oauthRow?.oauth_configured ?? conn?.oauth_configured ?? false);
        return (
          <div
            key={src.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 12px",
              border: `1px solid ${BRAND.border}`,
              borderRadius: 8,
              marginBottom: 8,
              background: "#fff",
              flexWrap: "wrap",
            }}
          >
            <div style={{ flex: 1, minWidth: 180 }}>
              <div style={{ fontWeight: 600, color: BRAND.navyText, fontSize: 13 }}>{src.label}</div>
              <div style={{ fontSize: 12, color: BRAND.sub }}>{src.help}</div>
              {conn?.last_error && (
                <div style={{ fontSize: 12, color: BRAND.redDark, marginTop: 4 }}>{conn.last_error}</div>
              )}
            </div>
            <Badge tone={tone(status)}>{labelFor(status)}</Badge>
            {canLogin && (
              <Button
                variant={status === "broken" ? "danger" : "ghost"}
                style={{ fontSize: 12, padding: "5px 12px" }}
                disabled={busy === src.id}
                onClick={() => connect(src.id)}
              >
                {busy === src.id ? "Opening…" : status === "healthy" || status === "ok" ? "Reconnect" : "Log in"}
              </Button>
            )}
          </div>
        );
      })}
      {error && <ErrorMsg>{error}</ErrorMsg>}
    </Card>
  );
}
