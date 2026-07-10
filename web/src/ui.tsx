// Shared Perkins-branded UI primitives + design tokens. One source of truth for the
// brand palette so every console page is consistent.
import type { CSSProperties, ReactNode, ButtonHTMLAttributes, HTMLAttributes } from "react";

export const BRAND = {
  red: "#ef3c1a",
  redDark: "#cf2e2e",
  navy: "#1b2a52",
  navyActive: "#26386b",
  navyText: "#2b3c73",
  ink: "#1a202c",
  sub: "#667085",
  border: "#e5e7eb",
  bg: "#f7f8fa",
};
export const FONT = "system-ui, 'Segoe UI', Roboto, sans-serif";

// Build a youtu.be deep-link.  When start is not a finite number the bare URL is returned
// (no ?t= param) — omitting the param is better than emitting ?t=NaN which YouTube ignores.
export function ytLink(videoId: string, start: number | null | undefined): string {
  if (start == null || !Number.isFinite(start)) return `https://youtu.be/${videoId}`;
  return `https://youtu.be/${videoId}?t=${Math.floor(start)}`;
}

// seconds -> H:MM:SS (or M:SS when under an hour). Use everywhere durations/timestamps show.
export function hms(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !isFinite(totalSeconds)) return "—";
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function PageTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
      <h2 style={{ margin: 0, color: BRAND.navyText, fontSize: 22 }}>{children}</h2>
      {right}
    </div>
  );
}

export function Card({ children, style, ...rest }: { children: ReactNode; style?: CSSProperties } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      style={{
        background: "#fff",
        border: `1px solid ${BRAND.border}`,
        borderRadius: 12,
        padding: 20,
        boxShadow: "0 1px 3px rgba(16,24,40,0.06)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" };
export function Button({ variant = "primary", style, disabled, ...rest }: BtnProps) {
  const palette =
    variant === "primary"
      ? { bg: BRAND.red, fg: "#fff", border: BRAND.red }
      : variant === "danger"
      ? { bg: "#fff", fg: BRAND.redDark, border: BRAND.redDark }
      : { bg: "#fff", fg: BRAND.navyText, border: BRAND.border };
  return (
    <button
      disabled={disabled}
      style={{
        padding: "9px 18px",
        background: disabled ? "#ccc" : palette.bg,
        color: disabled ? "#fff" : palette.fg,
        border: `1px solid ${disabled ? "#ccc" : palette.border}`,
        borderRadius: 8,
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: 14,
        fontWeight: 600,
        ...style,
      }}
      {...rest}
    />
  );
}

export const inputStyle: CSSProperties = {
  padding: "10px 12px",
  border: `1px solid ${BRAND.border}`,
  borderRadius: 8,
  fontSize: 14,
  fontFamily: FONT,
  outline: "none",
  boxSizing: "border-box",
};

export function Spinner({ small }: { small?: boolean }) {
  return <span className={small ? "spinner-ring spinner-ring--sm" : "spinner-ring"} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: BRAND.sub, fontSize: 14 }}>
      <Spinner />
      {label}
    </span>
  );
}

export function ErrorMsg({ children }: { children: ReactNode }) {
  return <p style={{ color: BRAND.red, fontSize: 14 }}>{children}</p>;
}

export function Badge({ tone, children }: { tone: "green" | "amber" | "blue" | "gray" | "red"; children: ReactNode }) {
  const c = {
    green: { bg: "#e6f9f0", fg: "#1a7f4b" },
    amber: { bg: "#fff3e0", fg: "#b45309" },
    blue: { bg: "#e8eefc", fg: BRAND.navyText },
    gray: { bg: "#eef1f5", fg: "#667085" },
    red: { bg: "#fef2f2", fg: BRAND.redDark },
  }[tone];
  return (
    <span style={{ background: c.bg, color: c.fg, padding: "2px 10px", borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
      {children}
    </span>
  );
}

export function StatusPill({
  status,
}: {
  status: "draft" | "sent" | "viewed" | "accepted" | "declined" | "superseded" | "revision_requested";
}) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    draft:              { bg: "#eef1f5", fg: "#667085",       label: "Draft" },
    sent:               { bg: "#e8eefc", fg: BRAND.navyText,  label: "Sent" },
    viewed:             { bg: "#fff3e0", fg: "#b45309",       label: "Viewed" },
    accepted:           { bg: "#e6f9f0", fg: "#1a7f4b",       label: "Accepted" },
    declined:           { bg: "#fef2f2", fg: BRAND.redDark,   label: "Declined" },
    superseded:         { bg: "#eef1f5", fg: "#667085",       label: "Superseded" },
    revision_requested: { bg: "#fff3e0", fg: "#b45309",       label: "Revision req." },
  };
  const c = map[status] ?? { bg: "#eef1f5", fg: "#667085", label: status };
  return (
    <span style={{
      display: "inline-block",
      background: c.bg,
      color: c.fg,
      padding: "3px 12px",
      borderRadius: 20,
      fontSize: 12,
      fontWeight: 700,
      letterSpacing: 0.2,
    }}>
      {c.label}
    </span>
  );
}

export function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={{
      background: "#fff",
      border: `1px solid ${BRAND.border}`,
      borderRadius: 12,
      padding: "16px 20px",
      boxShadow: "0 1px 3px rgba(16,24,40,0.06)",
      display: "flex",
      flexDirection: "column" as const,
      gap: 4,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase" as const, letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: BRAND.sub }}>{sub}</div>}
    </div>
  );
}

export function PillButton({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "7px 18px",
        borderRadius: 20,
        border: active ? `2px solid ${BRAND.navy}` : `2px solid ${BRAND.border}`,
        background: active ? BRAND.navy : "#fff",
        color: active ? "#fff" : BRAND.sub,
        cursor: "pointer",
        fontSize: 13,
        fontWeight: 600,
        transition: "background 0.12s, color 0.12s, border-color 0.12s",
      }}
    >
      {children}
    </button>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{
      fontSize: 11,
      fontWeight: 700,
      color: BRAND.sub,
      textTransform: "uppercase" as const,
      letterSpacing: 0.5,
      margin: "14px 0 6px",
    }}>
      {children}
    </div>
  );
}

export function TierCard({
  label,
  value,
  recommended,
  selected,
}: {
  label: string;
  value: string;
  recommended?: boolean;
  selected?: boolean;
}) {
  return (
    <div style={{
      border: recommended
        ? `2px solid ${BRAND.red}`
        : selected
        ? `2px solid ${BRAND.navy}`
        : `1px solid ${BRAND.border}`,
      borderRadius: 12,
      padding: "18px 20px",
      background: recommended ? "#fff8f7" : selected ? "#f0f3fa" : "#fff",
      boxShadow: recommended ? "0 2px 8px rgba(239,60,26,0.10)" : "0 1px 3px rgba(16,24,40,0.06)",
      position: "relative" as const,
      flex: 1,
      minWidth: 0,
    }}>
      {recommended && (
        <div style={{
          position: "absolute" as const,
          top: -12,
          left: "50%",
          transform: "translateX(-50%)",
          background: BRAND.red,
          color: "#fff",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.5,
          padding: "2px 10px",
          borderRadius: 20,
          whiteSpace: "nowrap" as const,
        }}>
          RECOMMENDED
        </div>
      )}
      <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase" as const, letterSpacing: 0.4, marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </div>
    </div>
  );
}

export function InitialsAvatar({ name, size = 36 }: { name: string; size?: number }) {
  const parts = name.trim().split(/\s+/);
  const initials = parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase();
  const colors = ["#1b2a52", "#2b3c73", "#26386b", "#ef3c1a", "#1a7f4b", "#b45309"];
  const colorIdx = name.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0) % colors.length;
  return (
    <div style={{
      width: size,
      height: size,
      borderRadius: "50%",
      background: colors[colorIdx],
      color: "#fff",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: size * 0.38,
      fontWeight: 700,
      flexShrink: 0,
      letterSpacing: 0.5,
    }}>
      {initials}
    </div>
  );
}
