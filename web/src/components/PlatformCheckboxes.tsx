import type { Connection } from "../api";
import { BRAND } from "../ui";

// Platforms social_job can actually publish today. Expands (facebook, youtube_shorts,
// linkedin, x, pinterest) once their adapters are unified into social_job.
const PUBLISHABLE = ["instagram", "tiktok"] as const;
const LABELS: Record<string, string> = { instagram: "Instagram", tiktok: "TikTok" };

// Multi-platform target as a checkbox group. A platform is checkable only when its
// integration is connected (status "ok"); otherwise it's disabled with a connect hint.
// Value is a comma-joined key list (the ScheduledContent.target shape).
export function PlatformCheckboxes({
  value,
  onChange,
  connections,
}: {
  value: string;
  onChange: (v: string) => void;
  connections: Connection[];
}) {
  const selected = value ? value.split(",").filter(Boolean) : [];
  const toggle = (p: string, on: boolean) => {
    const next = on ? [...selected, p] : selected.filter((x) => x !== p);
    onChange(Array.from(new Set(next)).join(","));
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 14, padding: "4px 0" }}>
      {PUBLISHABLE.map((p) => {
        const ok = connections.find((c) => c.integration === p)?.status === "ok";
        return (
          <label
            key={p}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13,
              color: ok ? BRAND.ink : BRAND.sub, cursor: ok ? "pointer" : "not-allowed",
            }}
          >
            <input type="checkbox" checked={selected.includes(p)} disabled={!ok} onChange={(e) => toggle(p, e.target.checked)} />
            {LABELS[p] ?? p}
            {!ok && <span style={{ fontSize: 11, color: BRAND.sub }}>(connect in Marketing)</span>}
          </label>
        );
      })}
    </div>
  );
}
