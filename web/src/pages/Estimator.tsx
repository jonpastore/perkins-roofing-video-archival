import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

// ── Types ─────────────────────────────────────────────────────────────────────

type Region = "HVHZ" | "FBC";

interface RatesResponse {
  region: Region;
  roof_types: string[];
  specialty_tile: Record<string, number>;
  base_cost_lm: Record<string, number>;
  overhead: Record<string, number>;
}

interface QuoteResult {
  region: string;
  roof_type: string;
  num_squares: number;
  per_square_total: number;
  squares_subtotal: number;
  project_fixed_costs: Record<string, number>;
  line_items: Record<string, number>;
  pm_incentive: number;
  project_total: number;
  profit_dollars: number;
  profit_pct: number;
  estimated_commission: number;
  margin_ok: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
}

function pct(n: number): string {
  return (n * 100).toFixed(1) + "%";
}

function labelRoofType(key: string): string {
  const map: Record<string, string> = {
    "13_tile": "13\" Flat Tile",
    "barrel_tile": "Barrel Tile",
    "3tab_shingle": "3-Tab Shingle",
    "dimensional_shingle": "Dimensional Shingle",
    "standing_seam_metal": "Standing Seam Metal",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function labelSpecialtyTile(key: string): string {
  const map: Record<string, string> = {
    "santa_fe_clay_s": "Santa Fe Clay S",
    "verea_caribbean_s": "Verea Caribbean S",
    "verea_s": "Verea S",
    "terracottagres_s_rustic": "Terracottag Res S Rustic",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function labelKey(key: string): string {
  const map: Record<string, string> = {
    "delivery_plywood_vents": "Delivery / Plywood / Vents",
    "new_bonus_values": "New Bonus Values",
    "permit_processing": "Permit Processing",
    "tile_dumpster": "Tile Dumpster",
    "stories_3_5_delivery_chute": "3–5 Story Delivery + Trash Chute",
    "stucco_metal": "Stucco Metal",
    "penetrations": "Penetrations",
    "ridge_vents": "Ridge Vents",
    "blown_in_iso_r19": "Blown-In ISO R19",
    "turbine_vents": "Turbine Vents",
    "solar_vents": "Solar Vents",
  };
  return map[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Sub-components ────────────────────────────────────────────────────────────

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  padding: "8px 10px",
  fontSize: 13,
  cursor: "pointer",
  width: "100%",
};

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: BRAND.sub, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>
      {children}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: BRAND.ink }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 14, height: 14, accentColor: BRAND.red, cursor: "pointer", flexShrink: 0 }}
      />
      {label}
    </label>
  );
}

function ResultRow({ label, value, bold, large }: { label: string; value: string; bold?: boolean; large?: boolean }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      padding: "5px 0",
      borderBottom: `1px solid ${BRAND.border}`,
      fontSize: large ? 15 : 13,
      fontWeight: bold ? 700 : 400,
      color: bold ? BRAND.navyText : BRAND.ink,
    }}>
      <span>{label}</span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, margin: "14px 0 6px" }}>
      {children}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function Estimator() {
  const [region, setRegion] = useState<Region>("FBC");
  const [rates, setRates] = useState<RatesResponse | null>(null);
  const [ratesLoading, setRatesLoading] = useState(false);
  const [ratesError, setRatesError] = useState<string | null>(null);

  // Form state
  const [roofType, setRoofType] = useState("");
  const [numSquares, setNumSquares] = useState<string>("");
  const [projectKind, setProjectKind] = useState<"residential" | "commercial">("residential");
  const [roofCuts, setRoofCuts] = useState<"low" | "medium" | "high">("low");
  const [roofHeight, setRoofHeight] = useState<"1_story" | "2_stories" | "3_5_stories" | "6_plus">("1_story");
  const [tilePointing, setTilePointing] = useState<"no" | "yes">("no");
  const [specialtyTile, setSpecialtyTile] = useState("");
  const [pitch712, setPitch712] = useState(false);
  const [demo, setDemo] = useState(false);
  const [secondaryWaterBarrier, setSecondaryWaterBarrier] = useState(false);
  const [winterguard, setWinterguard] = useState(false);
  const [includeDumpster, setIncludeDumpster] = useState(false);
  const [stuccoMetalLf, setStuccoMetalLf] = useState<string>("");
  const [penetrations, setPenetrations] = useState<string>("");
  const [ridgeVentLf, setRidgeVentLf] = useState<string>("");

  // Quote result
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);

  function loadRates(r: Region) {
    setRatesLoading(true);
    setRatesError(null);
    setRates(null);
    setResult(null);
    apiFetch(`/estimator/rates?region=${r}`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json();
      })
      .then((data: RatesResponse) => {
        setRates(data);
        // Default to first roof type when region changes
        setRoofType(data.roof_types[0] ?? "");
        setSpecialtyTile("");
      })
      .catch((e: unknown) => setRatesError(e instanceof Error ? e.message : String(e)))
      .finally(() => setRatesLoading(false));
  }

  useEffect(() => {
    loadRates(region);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleRegion(r: Region) {
    setRegion(r);
    loadRates(r);
  }

  async function handleCalculate() {
    const sq = parseFloat(numSquares);
    if (!roofType) { setQuoteError("Select a roof type."); return; }
    if (!numSquares || isNaN(sq) || sq <= 0) { setQuoteError("Enter a valid number of squares (> 0)."); return; }

    setQuoting(true);
    setQuoteError(null);
    setResult(null);

    const body: Record<string, unknown> = {
      region,
      roof_type: roofType,
      num_squares: sq,
      project_kind: projectKind,
      roof_cuts: roofCuts,
      roof_height: roofHeight,
      tile_pointing: tilePointing,
      pitch_7_12: pitch712,
      demo,
      secondary_water_barrier: secondaryWaterBarrier,
      winterguard,
      include_dumpster: includeDumpster,
      stucco_metal_lf: parseFloat(stuccoMetalLf) || 0,
      penetrations: parseInt(penetrations) || 0,
      ridge_vent_lf: parseFloat(ridgeVentLf) || 0,
    };
    if (specialtyTile) body.specialty_tile = specialtyTile;

    try {
      const r = await apiFetch("/estimator/quote", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error((detail as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const data: QuoteResult = await r.json();
      setResult(data);
    } catch (e: unknown) {
      setQuoteError(e instanceof Error ? e.message : String(e));
    } finally {
      setQuoting(false);
    }
  }

  const specialtyTileKeys = rates?.specialty_tile ? Object.keys(rates.specialty_tile) : [];

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>Estimator</PageTitle>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
        {/* ── Left: Input form ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Region toggle */}
          <Card>
            <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
              <div>
                <FieldLabel>Region</FieldLabel>
                <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
                  {(["HVHZ", "FBC"] as Region[]).map((r) => (
                    <button
                      key={r}
                      onClick={() => handleRegion(r)}
                      style={{
                        padding: "7px 22px",
                        fontSize: 13,
                        fontWeight: 600,
                        border: "none",
                        borderRight: r === "HVHZ" ? `1px solid ${BRAND.border}` : "none",
                        cursor: "pointer",
                        background: region === r ? BRAND.navy : "#fff",
                        color: region === r ? "#fff" : BRAND.sub,
                        transition: "background 0.1s, color 0.1s",
                      }}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
              {region === "HVHZ" && (
                <span style={{ fontSize: 12, color: BRAND.sub, paddingTop: 18 }}>Miami-Dade / Broward</span>
              )}
              {region === "FBC" && (
                <span style={{ fontSize: 12, color: BRAND.sub, paddingTop: 18 }}>Palm Beach / Lee / St. Lucie</span>
              )}
            </div>

            {ratesLoading && <div style={{ marginTop: 12 }}><Loading label="Loading rates…" /></div>}
            {ratesError && <div style={{ marginTop: 12 }}><ErrorMsg>Error loading rates: {ratesError}</ErrorMsg></div>}

            {rates && (
              <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {Object.entries(rates.base_cost_lm).map(([rt, cost]) => (
                  <span key={rt} style={{ fontSize: 11, color: BRAND.sub, background: BRAND.bg, padding: "2px 8px", borderRadius: 12 }}>
                    {labelRoofType(rt)}: {usd(cost)}/sq
                  </span>
                ))}
              </div>
            )}
          </Card>

          {/* Core inputs */}
          <Card>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              {/* Roof type */}
              <div>
                <FieldLabel>Roof Type</FieldLabel>
                <select
                  value={roofType}
                  onChange={(e) => { setRoofType(e.target.value); setSpecialtyTile(""); }}
                  style={selectStyle}
                  disabled={!rates}
                >
                  {rates?.roof_types.map((rt) => (
                    <option key={rt} value={rt}>{labelRoofType(rt)}</option>
                  ))}
                </select>
              </div>

              {/* Squares */}
              <div>
                <FieldLabel>Squares (1 sq = 100 sqft)</FieldLabel>
                <input
                  type="number"
                  min="0.1"
                  step="0.5"
                  value={numSquares}
                  onChange={(e) => setNumSquares(e.target.value)}
                  placeholder="e.g. 28"
                  style={{ ...inputStyle, padding: "8px 10px", fontSize: 13, width: "100%" }}
                />
              </div>

              {/* Project kind */}
              <div>
                <FieldLabel>Project Kind</FieldLabel>
                <select
                  value={projectKind}
                  onChange={(e) => setProjectKind(e.target.value as "residential" | "commercial")}
                  style={selectStyle}
                >
                  <option value="residential">Residential</option>
                  <option value="commercial">Commercial</option>
                </select>
              </div>

              {/* Roof cuts */}
              <div>
                <FieldLabel>Roof Cuts</FieldLabel>
                <select
                  value={roofCuts}
                  onChange={(e) => setRoofCuts(e.target.value as typeof roofCuts)}
                  style={selectStyle}
                >
                  <option value="low">Low (+$0/sq)</option>
                  <option value="medium">Medium (+$25/sq)</option>
                  <option value="high">High (+$50/sq)</option>
                </select>
              </div>

              {/* Roof height */}
              <div>
                <FieldLabel>Roof Height</FieldLabel>
                <select
                  value={roofHeight}
                  onChange={(e) => setRoofHeight(e.target.value as typeof roofHeight)}
                  style={selectStyle}
                >
                  <option value="1_story">1 Story</option>
                  <option value="2_stories">2 Stories (+$50/sq)</option>
                  <option value="3_5_stories">3–5 Stories (+$1,200 flat)</option>
                  <option value="6_plus">6+ Stories (manual quote)</option>
                </select>
              </div>

              {/* Tile pointing */}
              <div>
                <FieldLabel>Tile Pointing</FieldLabel>
                <select
                  value={tilePointing}
                  onChange={(e) => setTilePointing(e.target.value as "no" | "yes")}
                  style={selectStyle}
                >
                  <option value="no">No</option>
                  <option value="yes">Yes (+$200/sq)</option>
                </select>
              </div>

              {/* Specialty tile */}
              <div style={{ gridColumn: "1 / -1" }}>
                <FieldLabel>Specialty Tile Upgrade (optional)</FieldLabel>
                <select
                  value={specialtyTile}
                  onChange={(e) => setSpecialtyTile(e.target.value)}
                  style={selectStyle}
                  disabled={!rates}
                >
                  <option value="">— None —</option>
                  {specialtyTileKeys.map((key) => (
                    <option key={key} value={key}>
                      {labelSpecialtyTile(key)} (+{usd(rates!.specialty_tile[key])}/sq)
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </Card>

          {/* Toggles */}
          <Card>
            <div style={{ marginBottom: 10, fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
              Adders
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <Toggle label="Pitch ≥ 7/12 (+$200/sq, tile only)" checked={pitch712} onChange={setPitch712} />
              <Toggle label="Demo / Tear-Off" checked={demo} onChange={setDemo} />
              <Toggle label="Secondary Water Barrier (+$75/sq)" checked={secondaryWaterBarrier} onChange={setSecondaryWaterBarrier} />
              <Toggle label="WinterGuard (+$140/sq)" checked={winterguard} onChange={setWinterguard} />
              <Toggle label="Include Tile Dumpster (+$300)" checked={includeDumpster} onChange={setIncludeDumpster} />
            </div>
          </Card>

          {/* Linear/each line items */}
          <Card>
            <div style={{ marginBottom: 10, fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
              Linear / Each
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
              <div>
                <FieldLabel>Stucco Metal (LF)</FieldLabel>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={stuccoMetalLf}
                  onChange={(e) => setStuccoMetalLf(e.target.value)}
                  placeholder="0"
                  style={{ ...inputStyle, padding: "8px 10px", fontSize: 13, width: "100%" }}
                />
                <span style={{ fontSize: 11, color: BRAND.sub }}>$9.00/LF</span>
              </div>
              <div>
                <FieldLabel>Penetrations (each)</FieldLabel>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={penetrations}
                  onChange={(e) => setPenetrations(e.target.value)}
                  placeholder="0"
                  style={{ ...inputStyle, padding: "8px 10px", fontSize: 13, width: "100%" }}
                />
                <span style={{ fontSize: 11, color: BRAND.sub }}>$75.00 each</span>
              </div>
              <div>
                <FieldLabel>Ridge Vent (LF)</FieldLabel>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={ridgeVentLf}
                  onChange={(e) => setRidgeVentLf(e.target.value)}
                  placeholder="0"
                  style={{ ...inputStyle, padding: "8px 10px", fontSize: 13, width: "100%" }}
                />
                <span style={{ fontSize: 11, color: BRAND.sub }}>$9.79/LF</span>
              </div>
            </div>
          </Card>

          {quoteError && <ErrorMsg>Error: {quoteError}</ErrorMsg>}

          <Button
            onClick={handleCalculate}
            disabled={quoting || !rates}
            style={{ fontSize: 14, padding: "11px 28px", alignSelf: "flex-start" }}
          >
            {quoting ? "Calculating…" : "Calculate"}
          </Button>
        </div>

        {/* ── Right: Result panel ── */}
        <div>
          {!result && !quoting && (
            <Card style={{ background: BRAND.bg, border: "none" }}>
              <p style={{ margin: 0, fontSize: 13, color: BRAND.sub, textAlign: "center", padding: "24px 0" }}>
                Fill in the inputs and press <strong>Calculate</strong> to see the itemized estimate.
              </p>
            </Card>
          )}

          {quoting && (
            <Card>
              <Loading label="Building estimate…" />
            </Card>
          )}

          {result && (
            <Card>
              <div style={{ marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
                  Quote — {region}
                </span>
                <span style={{
                  fontSize: 12,
                  fontWeight: 700,
                  padding: "2px 10px",
                  borderRadius: 20,
                  background: result.margin_ok ? "#e6f9f0" : "#fef2f2",
                  color: result.margin_ok ? "#1a7f4b" : BRAND.red,
                }}>
                  {result.margin_ok ? "Margin OK" : "Margin LOW"}
                </span>
              </div>

              <ResultRow label="Roof Type" value={labelRoofType(result.roof_type)} />
              <ResultRow label="Squares" value={result.num_squares.toString()} />
              <ResultRow label="Per-Square Total" value={usd(result.per_square_total)} bold />

              <SectionHeader>Squares Subtotal</SectionHeader>
              <ResultRow
                label={`${result.num_squares} sq × ${usd(result.per_square_total)}`}
                value={usd(result.squares_subtotal)}
                bold
              />

              <SectionHeader>Project Fixed Costs</SectionHeader>
              {Object.entries(result.project_fixed_costs).map(([k, v]) => (
                <ResultRow key={k} label={labelKey(k)} value={usd(v)} />
              ))}

              {Object.keys(result.line_items ?? {}).length > 0 && (
                <>
                  <SectionHeader>Line Items</SectionHeader>
                  {Object.entries(result.line_items).map(([k, v]) => (
                    <ResultRow key={k} label={labelKey(k)} value={usd(v)} />
                  ))}
                </>
              )}

              <SectionHeader>Incentive</SectionHeader>
              <ResultRow
                label={`PM Incentive (${result.region === "commercial" ? "commercial" : "residential"})`}
                value={usd(result.pm_incentive)}
              />

              {/* Project total — emphasized */}
              <div style={{
                margin: "14px 0 10px",
                padding: "12px 14px",
                background: BRAND.navy,
                borderRadius: 8,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: "#fff" }}>PROJECT TOTAL</span>
                <span style={{ fontSize: 18, fontWeight: 700, color: "#fff", fontVariantNumeric: "tabular-nums" }}>
                  {usd(result.project_total)}
                </span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <ResultRow label="Profit" value={usd(result.profit_dollars)} bold />
                <ResultRow label="Profit %" value={pct(result.profit_pct)} bold />
                <ResultRow label="Est. Commission (15%)" value={usd(result.estimated_commission)} />
              </div>

              <p style={{ marginTop: 14, marginBottom: 0, fontSize: 11, color: BRAND.sub, lineHeight: 1.5 }}>
                Cost estimate only — not a scope of work. Base numbers pend Tim's confirmation
                (see KEY-block vs per-type lookup note in core.estimator).
              </p>
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}
