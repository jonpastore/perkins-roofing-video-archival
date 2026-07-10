import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Button, Card, ErrorMsg, FONT, Loading, PageTitle, inputStyle } from "../ui";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Segment {
  pitch_degrees: number;
  azimuth_degrees: number;
  azimuth_compass: string;
  area_m2: number;
  area_sqft: number;
  squares: number;
}

interface MeasureResult {
  id: number;
  measurement_id: number;
  total_sq: number;
  predominant_pitch: number | null;
  imagery_date: string | null;
  imagery_quality: string | null;
  staleness_warning: boolean;
  per_segment: Segment[];
  address: string | null;
  provider: string;
  created_at: string | null;
}

interface MeasurementRow {
  id: number;
  total_sq: number | null;
  address: string | null;
  imagery_date: string | null;
  imagery_quality: string | null;
  created_at: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt1(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toFixed(1);
}

function qualityBadge(quality: string | null) {
  const color =
    quality === "HIGH" ? "#1a7f4b" : quality === "MEDIUM" ? "#b45309" : "#667085";
  const bg =
    quality === "HIGH" ? "#e6f9f0" : quality === "MEDIUM" ? "#fffbeb" : "#f7f8fa";
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 700,
        padding: "2px 8px",
        borderRadius: 12,
        background: bg,
        color,
        textTransform: "uppercase" as const,
        letterSpacing: 0.3,
      }}
    >
      {quality ?? "unknown"}
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function Squares() {
  const [address, setAddress] = useState("");
  const [measuring, setMeasuring] = useState(false);
  const [result, setResult] = useState<MeasureResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [rofrSquares, setRofrSquares] = useState("");

  const [history, setHistory] = useState<MeasurementRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const addressRef = useRef<HTMLInputElement>(null);

  function loadHistory() {
    setHistoryLoading(true);
    setHistoryError(null);
    apiFetch("/squares/measurements")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: MeasurementRow[]) => setHistory(data))
      .catch((e: unknown) =>
        setHistoryError(e instanceof Error ? e.message : String(e))
      )
      .finally(() => setHistoryLoading(false));
  }

  useEffect(() => {
    loadHistory();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleMeasure() {
    const addr = address.trim();
    if (!addr) {
      setError("Enter a property address.");
      return;
    }
    setMeasuring(true);
    setError(null);
    setResult(null);
    setRofrSquares("");
    try {
      const r = await apiFetch("/squares/measure", {
        method: "POST",
        body: JSON.stringify({ address: addr }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(
          (detail as { detail?: string }).detail ?? `${r.status} ${r.statusText}`
        );
      }
      const data: MeasureResult = await r.json();
      setResult(data);
      loadHistory();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setMeasuring(false);
    }
  }

  function handleUseInEstimate() {
    if (!result) return;
    localStorage.setItem(
      "estimate_prefill",
      JSON.stringify({
        num_squares: result.total_sq,
        measurement_id: result.measurement_id,
        address: result.address ?? address,
      })
    );
    // Hint — navigate to Estimates tab; the tab router picks it up on mount
    const hint = document.getElementById("_sq_hint");
    if (hint) hint.style.display = "block";
  }

  function handleReopen(row: MeasurementRow) {
    setResult({
      id: row.id,
      measurement_id: row.id,
      total_sq: row.total_sq ?? 0,
      predominant_pitch: null,
      imagery_date: row.imagery_date,
      imagery_quality: row.imagery_quality,
      staleness_warning:
        row.imagery_quality !== "HIGH" ||
        (() => {
          if (!row.imagery_date) return true;
          const days = (Date.now() - new Date(row.imagery_date).getTime()) / 86400000;
          return days / 365.25 > 3;
        })(),
      per_segment: [],
      address: row.address,
      provider: "google_solar",
      created_at: row.created_at,
    });
    setAddress(row.address ?? "");
    setError(null);
    setRofrSquares("");
    window.scrollTo(0, 0);
  }

  const rofrVal = parseFloat(rofrSquares);
  const deltaVal =
    result && rofrSquares && !isNaN(rofrVal) && rofrVal > 0
      ? ((result.total_sq - rofrVal) / rofrVal) * 100
      : null;

  return (
    <main style={{ maxWidth: 900, fontFamily: FONT }}>
      <PageTitle>Squares</PageTitle>

      {/* ── Address input ─────────────────────────────────────────────── */}
      <Card style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 10, fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
          Property Address
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <input
            ref={addressRef}
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleMeasure(); }}
            placeholder="e.g. 1234 SW 5th Ave, Miami, FL 33130"
            style={{ ...inputStyle, flex: 1, padding: "9px 12px", fontSize: 14 }}
          />
          <Button onClick={handleMeasure} disabled={measuring}>
            {measuring ? "Measuring…" : "Measure"}
          </Button>
        </div>
        {measuring && (
          <div style={{ marginTop: 12 }}>
            <Loading label="Fetching roof data from Google Solar…" />
          </div>
        )}
        {error && (
          <div style={{ marginTop: 10 }}>
            <ErrorMsg>{error}</ErrorMsg>
          </div>
        )}
      </Card>

      {/* ── Result ───────────────────────────────────────────────────── */}
      {result && (
        <>
          {result.staleness_warning && (
            <div
              style={{
                background: "#fffbeb",
                border: "1px solid #f59e0b",
                borderRadius: 8,
                padding: "10px 16px",
                marginBottom: 14,
                fontSize: 13,
                color: "#92400e",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span style={{ fontWeight: 700 }}>Field validation recommended</span>
              {" — "}
              imagery from {result.imagery_date ?? "unknown date"} (quality{" "}
              {result.imagery_quality ?? "unknown"}). Verify measurements on-site.
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
            {/* Big squares stat */}
            <Card style={{ textAlign: "center", padding: "28px 20px" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                Total Squares
              </div>
              <div style={{ fontSize: 48, fontWeight: 800, color: BRAND.navyText, lineHeight: 1 }}>
                {fmt1(result.total_sq)}
              </div>
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 4 }}>squares (1 sq = 100 sqft)</div>
              {result.predominant_pitch != null && (
                <div style={{ marginTop: 8, fontSize: 13, color: BRAND.ink }}>
                  Predominant pitch: <strong>{fmt1(result.predominant_pitch)}°</strong>
                </div>
              )}
            </Card>

            {/* Imagery info */}
            <Card>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
                Imagery
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ color: BRAND.sub }}>Date</span>
                  <span>{result.imagery_date ?? "—"}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ color: BRAND.sub }}>Quality</span>
                  {qualityBadge(result.imagery_quality)}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ color: BRAND.sub }}>Source</span>
                  <span style={{ fontSize: 11, color: BRAND.sub }}>Google Solar API</span>
                </div>
              </div>
            </Card>
          </div>

          {/* Per-segment table */}
          {result.per_segment.length > 0 && (
            <Card style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
                Roof Segments
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ borderBottom: `2px solid ${BRAND.border}` }}>
                      {["#", "Pitch (°)", "Azimuth", "Area (sqft)", "Squares"].map((h) => (
                        <th key={h} style={{ textAlign: "left", padding: "6px 10px", color: BRAND.sub, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.per_segment.map((seg, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                        <td style={{ padding: "6px 10px", color: BRAND.sub }}>{i + 1}</td>
                        <td style={{ padding: "6px 10px" }}>{fmt1(seg.pitch_degrees)}</td>
                        <td style={{ padding: "6px 10px" }}>{seg.azimuth_compass} ({fmt1(seg.azimuth_degrees)}°)</td>
                        <td style={{ padding: "6px 10px", fontVariantNumeric: "tabular-nums" }}>{seg.area_sqft.toLocaleString()}</td>
                        <td style={{ padding: "6px 10px", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>{fmt1(seg.squares)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* Roofr comparison */}
          <Card style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 10 }}>
              Compare to Roofr
            </div>
            <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
              <div>
                <label style={{ display: "block", fontSize: 12, color: BRAND.sub, marginBottom: 4 }}>
                  Roofr Report Squares
                </label>
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={rofrSquares}
                  onChange={(e) => setRofrSquares(e.target.value)}
                  placeholder="e.g. 24.5"
                  style={{ ...inputStyle, width: 140, padding: "8px 10px", fontSize: 14 }}
                />
              </div>
              {deltaVal != null && (
                <div style={{ paddingTop: 18 }}>
                  <span style={{ fontSize: 13, color: BRAND.sub }}>Delta: </span>
                  <span
                    style={{
                      fontSize: 15,
                      fontWeight: 700,
                      color: Math.abs(deltaVal) > 5 ? BRAND.red : "#1a7f4b",
                    }}
                  >
                    {deltaVal > 0 ? "+" : ""}
                    {deltaVal.toFixed(1)}%
                  </span>
                  <span style={{ fontSize: 11, color: BRAND.sub, marginLeft: 6 }}>
                    ({deltaVal > 0 ? "Solar larger" : "Roofr larger"})
                  </span>
                </div>
              )}
            </div>
            {deltaVal != null && Math.abs(deltaVal) > 5 && (
              <p style={{ margin: "8px 0 0", fontSize: 12, color: BRAND.sub }}>
                Delta &gt; 5% — verify pitch and overhangs on-site before quoting.
              </p>
            )}
          </Card>

          {/* Use in Estimate */}
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Button onClick={handleUseInEstimate}>Use in Estimate</Button>
            <span id="_sq_hint" style={{ display: "none", fontSize: 13, color: "#1a7f4b" }}>
              Prefill saved — open the Estimates tab to continue.
            </span>
          </div>
        </>
      )}

      {/* ── Recent measurements ──────────────────────────────────────── */}
      <div style={{ marginTop: 32 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
          Recent Measurements
        </div>
        {historyLoading && <Loading label="Loading…" />}
        {historyError && <ErrorMsg>{historyError}</ErrorMsg>}
        {!historyLoading && !historyError && history.length === 0 && (
          <p style={{ fontSize: 13, color: BRAND.sub }}>No measurements yet.</p>
        )}
        {history.map((row) => (
          <Card key={row.id} style={{ marginBottom: 8, padding: "12px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>
                  {row.address ?? `Measurement #${row.id}`}
                </div>
                <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                  {fmt1(row.total_sq)} sq
                  {row.imagery_date ? ` — imagery ${row.imagery_date}` : ""}
                  {row.created_at
                    ? ` — ${new Date(row.created_at).toLocaleDateString()}`
                    : ""}
                </div>
              </div>
              <Button variant="ghost" style={{ fontSize: 12, padding: "5px 12px" }} onClick={() => handleReopen(row)}>
                Re-open
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </main>
  );
}
