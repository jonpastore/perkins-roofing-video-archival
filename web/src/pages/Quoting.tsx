import { BRAND, FONT } from "../ui";

export function Quoting() {
  return (
    <div style={{ fontFamily: FONT }}>
      <h2 style={{ margin: "0 0 8px", color: BRAND.navyText, fontSize: 22 }}>Quoting</h2>
      <p style={{ margin: "0 0 28px", color: "#667085", fontSize: 14 }}>
        Proposal creation and tracking — coming in F3.
      </p>
      <div
        style={{
          background: "#fff",
          border: `1px solid ${BRAND.border ?? "#e3e7f0"}`,
          borderRadius: 12,
          padding: "40px 32px",
          textAlign: "center",
          color: "#9aa3ba",
          fontSize: 15,
        }}
      >
        Quoting — Coming in F3
      </div>
    </div>
  );
}
