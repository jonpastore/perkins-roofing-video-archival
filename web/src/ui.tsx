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

export function Badge({ tone, children }: { tone: "green" | "amber" | "blue" | "gray"; children: ReactNode }) {
  const c = {
    green: { bg: "#e6f9f0", fg: "#1a7f4b" },
    amber: { bg: "#fff3e0", fg: "#b45309" },
    blue: { bg: "#e8eefc", fg: BRAND.navyText },
    gray: { bg: "#eef1f5", fg: "#667085" },
  }[tone];
  return (
    <span style={{ background: c.bg, color: c.fg, padding: "2px 10px", borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
      {children}
    </span>
  );
}
