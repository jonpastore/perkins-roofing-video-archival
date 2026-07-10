import { BRAND, FONT } from "../ui";

export function Squares() {
  return (
    <div style={{ fontFamily: FONT }}>
      <h2 style={{ margin: "0 0 8px", color: BRAND.navyText, fontSize: 22 }}>Squares</h2>
      <p style={{ margin: "0 0 28px", color: "#667085", fontSize: 14 }}>
        Roof measurement (SquareQuote integration) — address lookup, parcel footprint, and
        squares calculation feeding Estimates.
      </p>
      <div
        style={{
          background: "#fff", border: "1px solid #e3e7f0", borderRadius: 12,
          padding: "40px 32px", textAlign: "center", color: "#9aa3ba", fontSize: 15,
        }}
      >
        Squares — SquareQuote (eaglepoint) integration in progress
      </div>
    </div>
  );
}
