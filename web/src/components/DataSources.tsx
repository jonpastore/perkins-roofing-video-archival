import { useEffect, useState } from "react";
import { listConnections, requestConnectionLogin, startOAuth, type Connection } from "../api";
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
    help: "Application Key in companycam-pat. Nightly sync at 06:00 ET. Rotate the key under Connections if it ever breaks.",
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

function needsLogin(id: string, status: string | undefined): boolean {
  if (id === "companycam") return false;
  return status === "broken" || status === "expiring" || status === "unconfigured";
}

export function DataSources({ manage = true }: { manage?: boolean }) {
  const [rows, setRows] = useState<Record<string, Connection>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    function refresh() {
      listConnections()
        .then((list) => {
          const byId = Object.fromEntries(list.map((c) => [c.integration, c]));
          setRows(byId);
          const mustOpen = SOURCES.some((src) => {
            const conn = byId[src.statusId ?? src.id] ?? byId[src.id];
            return needsLogin(src.id, conn?.status);
          });
          if (mustOpen) setOpen(true);
        })
        .catch(() => undefined)
        .finally(() => setLoaded(true));
    }
    refresh();
    const onVis = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
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

  async function requestLogin(id: string) {
    setBusy(`mail-${id}`);
    setError(null);
    try {
      await requestConnectionLogin(id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Could not email a ${id} login request`);
    } finally {
      setBusy(null);
    }
  }

  const loginNeeded = SOURCES.filter((src) => {
    const conn = rows[src.statusId ?? src.id] ?? rows[src.id];
    return needsLogin(src.id, conn?.status);
  });

  return (
    <Card style={{ marginBottom: 16 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          background: "none",
          border: 0,
          padding: 0,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, flex: 1 }}>
          {open ? "▾" : "▸"} Data sources
        </span>
        {loaded && loginNeeded.length > 0 && (
          <Badge tone="red">
            {loginNeeded.length === 1
              ? `${loginNeeded[0].label} needs login`
              : `${loginNeeded.length} need login`}
          </Badge>
        )}
        {loaded && loginNeeded.length === 0 && <Badge tone="green">Connected</Badge>}
      </button>
      {open && (
        <div style={{ fontSize: 13, color: BRAND.sub, margin: "10px 0 12px" }}>
          Log in here for Knowify and YouTube. CompanyCam uses an application key, not OAuth.
          Request login emails the operators if someone else has to complete a consent screen.
        </div>
      )}
      {open && SOURCES.map((src) => {
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
            {canLogin && src.id !== "companycam" && (
              <Button
                variant={status === "broken" ? "danger" : "ghost"}
                style={{ fontSize: 12, padding: "5px 12px" }}
                disabled={busy === src.id}
                onClick={() => connect(src.id)}
              >
                {busy === src.id ? "Opening…" : status === "healthy" || status === "ok" ? "Reconnect" : "Log in"}
              </Button>
            )}
            {manage && src.id !== "companycam" && (
              <Button
                variant="ghost"
                style={{ fontSize: 12, padding: "5px 12px" }}
                disabled={busy === `mail-${src.id}`}
                onClick={() => requestLogin(src.statusId ?? src.id)}
              >
                {busy === `mail-${src.id}` ? "Sending…" : "Request login"}
              </Button>
            )}
          </div>
        );
      })}
      {open && error && <ErrorMsg>{error}</ErrorMsg>}
    </Card>
  );
}
