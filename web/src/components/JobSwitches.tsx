import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { errText } from "../lib/errors";
import { BRAND, Badge, Button, Card, ErrorMsg } from "../ui";

const KEYS = {
  knowify: "KNOWIFY_SYNC_ENABLED",
  reminders: "PROPOSAL_REMINDERS_ENABLED",
} as const;

export function JobSwitches({ manage = true }: { manage?: boolean }) {
  const [knowify, setKnowify] = useState(false);
  const [reminders, setReminders] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    apiFetch("/config/job-switches")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: { knowify_sync?: boolean; proposal_reminders?: boolean }) => {
        setKnowify(data.knowify_sync === true);
        setReminders(data.proposal_reminders === true);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  async function save(key: string, next: boolean, apply: (v: boolean) => void) {
    if (!manage) return;
    setBusy(key);
    setError(null);
    apply(next);
    try {
      const r = await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ key, value: next ? "true" : "false" }),
      });
      if (!r.ok) throw new Error(await errText(r));
    } catch (e: unknown) {
      apply(!next);
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, marginBottom: 4 }}>
        Scheduled jobs
      </div>
      <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 12 }}>
        Turn these on when you want them to run. Off means the cron fires and exits without
        pulling Knowify or emailing customers. Login for Knowify still happens under Data sources.
      </div>
      <SwitchRow
        title="Knowify sync"
        help="Hourly 8am–6pm ET pull of invoices, customers, and jobs. Off until you turn it on — Knowify login stays manual."
        on={knowify}
        loaded={loaded}
        disabled={!manage || busy === KEYS.knowify}
        onToggle={(v) => save(KEYS.knowify, v, setKnowify)}
      />
      <SwitchRow
        title="Proposal reminders"
        help="Daily nudge emails to customers with an open proposal. Off until you review the copy and turn it on."
        on={reminders}
        loaded={loaded}
        disabled={!manage || busy === KEYS.reminders}
        onToggle={(v) => save(KEYS.reminders, v, setReminders)}
      />
      {error && <ErrorMsg>{error}</ErrorMsg>}
    </Card>
  );
}

function SwitchRow({
  title, help, on, loaded, disabled, onToggle,
}: {
  title: string;
  help: string;
  on: boolean;
  loaded: boolean;
  disabled: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <div
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
        <div style={{ fontWeight: 600, color: BRAND.navyText, fontSize: 13 }}>{title}</div>
        <div style={{ fontSize: 12, color: BRAND.sub }}>{help}</div>
      </div>
      <Badge tone={on ? "green" : "gray"}>{!loaded ? "…" : on ? "On" : "Off"}</Badge>
      {manageButton(disabled, on, onToggle)}
    </div>
  );
}

function manageButton(disabled: boolean, on: boolean, onToggle: (v: boolean) => void) {
  return (
    <Button
      variant="ghost"
      style={{ fontSize: 12, padding: "5px 12px" }}
      disabled={disabled}
      onClick={() => onToggle(!on)}
    >
      {on ? "Turn off" : "Turn on"}
    </Button>
  );
}
