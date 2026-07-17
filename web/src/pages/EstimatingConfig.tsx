import { useEffect, useState, useCallback } from "react";
import {
  BRAND,
  FONT,
  Card,
  Button,
  Loading,
  ErrorMsg,
  Badge,
  inputStyle,
} from "../ui";
import {
  listPricingConfigs,
  getPricingConfig,
  createPricingConfig,
  activatePricingConfig,
  diffPricingConfigs,
  listBranches,
  type PricingConfigVersion,
  type PricingConfigDetail,
  type PricingConfigDiff,
  type BranchRow,
} from "../api";

// ── Types & constants ─────────────────────────────────────────────────────────

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

/** Roles that may save new versions or activate configs. */
function canManage(role: Role): boolean {
  return role === "admin" || role === "web_admin" || role === "platform_admin";
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function shortHash(hash: string): string {
  return hash.slice(0, 12);
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function copyToClipboard(text: string) {
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

// Flatten a nested object into "dot.separated.paths": value pairs.
function flattenObj(
  obj: unknown,
  prefix = ""
): Record<string, unknown> {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    return { [prefix]: obj };
  }
  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(result, flattenObj(v, path));
    } else {
      result[path] = v;
    }
  }
  return result;
}

// Client-side diff fallback: compute field-level diff from two config objects.
function computeClientDiff(
  fromId: number,
  fromConfig: Record<string, unknown>,
  toId: number,
  toConfig: Record<string, unknown>
): PricingConfigDiff {
  const flatFrom = flattenObj(fromConfig);
  const flatTo = flattenObj(toConfig);
  const allPaths = new Set([...Object.keys(flatFrom), ...Object.keys(flatTo)]);
  const changes: PricingConfigDiff["changes"] = [];
  for (const path of allPaths) {
    const fv = flatFrom[path];
    const tv = flatTo[path];
    if (JSON.stringify(fv) !== JSON.stringify(tv)) {
      changes.push({ path, from_value: fv, to_value: tv });
    }
  }
  return { from_id: fromId, to_id: toId, changes };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: BRAND.sub,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        margin: "18px 0 8px",
      }}
    >
      {children}
    </div>
  );
}

function HashDisplay({
  hash,
  short = false,
}: {
  hash: string;
  short?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const display = short ? shortHash(hash) : hash;
  return (
    <span
      style={{
        fontFamily: "monospace",
        fontSize: short ? 12 : 11,
        color: BRAND.sub,
        background: BRAND.bg,
        padding: "1px 6px",
        borderRadius: 4,
        cursor: "pointer",
        userSelect: "all",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
      }}
      title={short ? `Full hash: ${hash}\nClick to copy` : "Click to copy"}
      onClick={() => {
        copyToClipboard(hash);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {display}
      {copied && (
        <span style={{ fontSize: 10, color: "#1a7f4b" }}>copied</span>
      )}
    </span>
  );
}

// Pending-Tim field: renders a clearly-labeled "Pending Tim" badge for null fields.
function PendingField({ label }: { label: string }) {
  return (
    <div
      style={{
        padding: "8px 12px",
        border: `1px dashed ${BRAND.border}`,
        borderRadius: 6,
        background: "#fffbf0",
        marginBottom: 6,
      }}
    >
      <span style={{ fontSize: 12, color: BRAND.sub }}>{label}</span>
      <span
        style={{
          marginLeft: 8,
          fontSize: 11,
          fontWeight: 700,
          color: "#b45309",
          background: "#fff3e0",
          padding: "1px 7px",
          borderRadius: 10,
        }}
      >
        Pending Tim
      </span>
    </div>
  );
}

// ── Version list row ──────────────────────────────────────────────────────────

function VersionRow({
  v,
  selected,
  onSelect,
}: {
  v: PricingConfigVersion;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 8,
        cursor: "pointer",
        background: selected ? "#eef1f5" : "transparent",
        border: selected ? `1px solid ${BRAND.border}` : "1px solid transparent",
        transition: "background 0.1s",
      }}
    >
      <span
        style={{
          minWidth: 28,
          fontWeight: 700,
          fontSize: 13,
          color: BRAND.navyText,
        }}
      >
        v{v.version}
      </span>
      {v.is_active && <Badge tone="green">Active</Badge>}
      <span style={{ flex: 1, fontSize: 13, color: BRAND.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {v.label ?? `Version ${v.version}`}
      </span>
      <HashDisplay hash={v.config_hash} short />
      <span style={{ fontSize: 11, color: BRAND.sub, whiteSpace: "nowrap" }}>
        {fmtDate(v.created_at)}
      </span>
    </div>
  );
}

// ── Diff view ─────────────────────────────────────────────────────────────────

function DiffView({
  diff,
  fromVersion,
  toVersion,
  onClose,
}: {
  diff: PricingConfigDiff;
  fromVersion: number;
  toVersion: number;
  onClose: () => void;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 14, color: BRAND.navyText }}>
          Diff: v{fromVersion} → v{toVersion}
        </span>
        <Button variant="ghost" style={{ padding: "5px 12px", fontSize: 12 }} onClick={onClose}>
          Close diff
        </Button>
      </div>
      {diff.changes.length === 0 ? (
        <p style={{ color: BRAND.sub, fontSize: 13 }}>No changes between these versions.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {diff.changes.map((c) => (
            <div
              key={c.path}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 8,
                fontSize: 12,
                padding: "6px 10px",
                borderRadius: 6,
                background: "#fff8f0",
                border: `1px solid #ffe0b2`,
                fontFamily: "monospace",
              }}
            >
              <span style={{ color: BRAND.sub, wordBreak: "break-all" }}>{c.path}</span>
              <span style={{ color: BRAND.red, textDecoration: "line-through" }}>
                {JSON.stringify(c.from_value)}
              </span>
              <span style={{ color: "#1a7f4b" }}>{JSON.stringify(c.to_value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Structured config editor ──────────────────────────────────────────────────
// Renders sections of the pricing config as human-readable fields.
// Falls back to raw JSON textarea for the full payload so nothing is hidden.

function NumericField({
  label,
  value,
  onChange,
  disabled,
  unit,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  disabled: boolean;
  unit?: string;
}) {
  if (value === null || value === undefined) {
    return <PendingField label={label} />;
  }
  return (
    <div style={{ marginBottom: 8 }}>
      <label
        style={{
          display: "block",
          fontSize: 11,
          fontWeight: 600,
          color: BRAND.sub,
          marginBottom: 2,
          textTransform: "uppercase",
          letterSpacing: 0.3,
        }}
      >
        {label} {unit && <span style={{ fontWeight: 400, textTransform: "none" }}>({unit})</span>}
      </label>
      <input
        type="number"
        disabled={disabled}
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : parseFloat(e.target.value))
        }
        style={{
          ...inputStyle,
          padding: "6px 10px",
          fontSize: 13,
          width: "100%",
          background: disabled ? BRAND.bg : "#fff",
          cursor: disabled ? "default" : "text",
        }}
      />
    </div>
  );
}

// Nested zone/type table rendered as a 2-column grid (HVHZ | FBC × roof_type).
function ZoneTypeTable({
  label,
  data,
  onChange,
  disabled,
}: {
  label: string;
  data: Record<string, Record<string, number | null>>;
  onChange: (updated: Record<string, Record<string, number | null>>) => void;
  disabled: boolean;
}) {
  // "_pending_*" keys are Tim-note comments riding inside the zone dicts, not rate
  // rows — render them as tooltips on their cell, never as editable rows.
  const zones = Object.keys(data).filter((k) => !k.startsWith("_"));
  const types = zones.length > 0 ? Object.keys(data[zones[0]]).filter((k) => !k.startsWith("_")) : [];

  function pendingNote(zone: string, type: string): string | undefined {
    const note = (data[zone] as Record<string, unknown> | undefined)?.[`_pending_${type}_${zone.toLowerCase()}`];
    return typeof note === "string" ? note : undefined;
  }

  function handleChange(zone: string, type: string, val: number | null) {
    onChange({
      ...data,
      [zone]: { ...data[zone], [type]: val },
    });
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <SectionLabel>{label}</SectionLabel>
      <div
        style={{
          overflowX: "auto",
          border: `1px solid ${BRAND.border}`,
          borderRadius: 8,
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: BRAND.bg }}>
              <th
                style={{
                  padding: "8px 12px",
                  textAlign: "left",
                  color: BRAND.sub,
                  fontWeight: 700,
                  borderBottom: `1px solid ${BRAND.border}`,
                }}
              >
                Type
              </th>
              {zones.map((z) => (
                <th
                  key={z}
                  style={{
                    padding: "8px 12px",
                    textAlign: "right",
                    color: BRAND.sub,
                    fontWeight: 700,
                    borderBottom: `1px solid ${BRAND.border}`,
                    minWidth: 100,
                  }}
                >
                  {z}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {types.map((type) => (
              <tr
                key={type}
                style={{ borderBottom: `1px solid ${BRAND.border}` }}
              >
                <td
                  style={{
                    padding: "6px 12px",
                    color: BRAND.ink,
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                >
                  {type}
                </td>
                {zones.map((z) => {
                  const val = data[z][type];
                  const note = pendingNote(z, type);
                  return (
                    <td key={z} style={{ padding: "4px 8px", textAlign: "right" }}>
                      {(
                        <input
                          type="number"
                          disabled={disabled}
                          value={val ?? ""}
                          placeholder={val === null ? "Pending Tim" : undefined}
                          title={note}
                          onChange={(e) =>
                            handleChange(
                              z,
                              type,
                              e.target.value === "" ? null : parseFloat(e.target.value)
                            )
                          }
                          style={{
                            ...inputStyle,
                            padding: "4px 8px",
                            fontSize: 12,
                            width: 90,
                            textAlign: "right",
                            background: disabled ? BRAND.bg : "#fff",
                            cursor: disabled ? "default" : "text",
                            ...(val === null ? { borderColor: "#fcd34d", background: "#fffbf0" } : {}),
                          }}
                        />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Gutter style rate table — keyed by whatever style keys exist in gutters.styles
// (core/estimator.py looks them up by key; scripts/seed_gutters_config.py seeds the set).
// New style keys are added via Raw JSON; this table edits the rates of existing ones.
interface GutterStyle {
  label?: string;
  per_lf?: number | null;
  two_story_per_lf?: number | null;
  elbow_each?: number | null;
}

function GutterStylesTable({
  styles,
  onChange,
  disabled,
}: {
  styles: Record<string, GutterStyle>;
  onChange: (updated: Record<string, GutterStyle>) => void;
  disabled: boolean;
}) {
  const keys = Object.keys(styles);

  function setField(key: string, field: keyof GutterStyle, value: string | number | null) {
    onChange({ ...styles, [key]: { ...styles[key], [field]: value } });
  }

  function numCell(key: string, field: "per_lf" | "two_story_per_lf" | "elbow_each") {
    const val = styles[key][field];
    return (
      <input
        type="number"
        disabled={disabled}
        value={val ?? ""}
        placeholder={val === null || val === undefined ? "Pending Tim" : undefined}
        onChange={(e) => setField(key, field, e.target.value === "" ? null : parseFloat(e.target.value))}
        style={{
          ...inputStyle,
          padding: "4px 8px",
          fontSize: 12,
          width: 90,
          textAlign: "right",
          background: disabled ? BRAND.bg : "#fff",
          ...(val === null || val === undefined ? { borderColor: "#fcd34d", background: "#fffbf0" } : {}),
        }}
      />
    );
  }

  if (keys.length === 0) {
    return <PendingField label="Gutter styles" />;
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <SectionLabel>Gutter styles</SectionLabel>
      <div style={{ overflowX: "auto", border: `1px solid ${BRAND.border}`, borderRadius: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: BRAND.bg }}>
              {["Style", "Label", "$/LF", "2-story $/LF", "Elbow $/each"].map((h) => (
                <th key={h} style={{ padding: "8px 12px", textAlign: h === "Style" || h === "Label" ? "left" : "right", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                <td style={{ padding: "6px 12px", color: BRAND.ink, fontFamily: "monospace", fontSize: 11 }}>{k}</td>
                <td style={{ padding: "4px 8px" }}>
                  <input
                    type="text"
                    disabled={disabled}
                    value={styles[k].label ?? ""}
                    onChange={(e) => setField(k, "label", e.target.value)}
                    style={{ ...inputStyle, padding: "4px 8px", fontSize: 12, width: "100%", background: disabled ? BRAND.bg : "#fff" }}
                  />
                </td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>{numCell(k, "per_lf")}</td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>{numCell(k, "two_story_per_lf")}</td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>{numCell(k, "elbow_each")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Collapsible section group ─────────────────────────────────────────────────

function CollapsibleGroup({
  title,
  defaultOpen = true,
  children,
  accent,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  accent?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      style={{
        border: `1px solid ${BRAND.border}`,
        borderRadius: 10,
        marginBottom: 14,
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: accent ?? BRAND.bg,
          border: "none",
          cursor: "pointer",
          fontFamily: "inherit",
          textAlign: "left",
        }}
      >
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: BRAND.navyText,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {title}
        </span>
        <span style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && (
        <div style={{ padding: "14px 16px 4px" }}>{children}</div>
      )}
    </div>
  );
}

// ── Main structured editor ────────────────────────────────────────────────────

interface ConfigEditorProps {
  config: Record<string, unknown>;
  onChange: (updated: Record<string, unknown>) => void;
  disabled: boolean;
}

function ConfigEditor({ config, onChange, disabled }: ConfigEditorProps) {
  // Raw JSON fallback for advanced editing / unknown keys.
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState(() => JSON.stringify(config, null, 2));
  const [rawError, setRawError] = useState<string | null>(null);

  // Sync rawText when config changes from parent (e.g., loading a new version).
  useEffect(() => {
    setRawText(JSON.stringify(config, null, 2));
    setRawError(null);
  }, [config]);

  function handleRawChange(text: string) {
    setRawText(text);
    try {
      const parsed = JSON.parse(text);
      setRawError(null);
      onChange(parsed);
    } catch {
      setRawError("Invalid JSON — fix before saving.");
    }
  }

  // Helpers to update nested paths cleanly.
  function set(path: string[], value: unknown) {
    const updated = JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
    let cur: Record<string, unknown> = updated;
    for (let i = 0; i < path.length - 1; i++) {
      if (typeof cur[path[i]] !== "object" || cur[path[i]] === null) cur[path[i]] = {};
      cur = cur[path[i]] as Record<string, unknown>;
    }
    cur[path[path.length - 1]] = value;
    onChange(updated);
  }

  function getNum(path: string[]): number | null | undefined {
    let cur: unknown = config;
    for (const k of path) {
      if (cur === null || typeof cur !== "object") return undefined;
      cur = (cur as Record<string, unknown>)[k];
    }
    return cur as number | null | undefined;
  }

  function getObj(path: string[]): Record<string, Record<string, number | null>> {
    let cur: unknown = config;
    for (const k of path) {
      if (cur === null || typeof cur !== "object") return {};
      cur = (cur as Record<string, unknown>)[k];
    }
    return (cur ?? {}) as Record<string, Record<string, number | null>>;
  }

  function getStr(path: string[], fallback: string): string {
    let cur: unknown = config;
    for (const k of path) {
      if (cur === null || typeof cur !== "object") return fallback;
      cur = (cur as Record<string, unknown>)[k];
    }
    return typeof cur === "string" ? cur : fallback;
  }

  const profitScale = (config.profit_scale ?? []) as Array<[number | null, number]>;

  // daily_overhead_rates keys in display order
  const dailyRateKeys: [string, string][] = [
    ["demo_dry_in_flat", "Demo / Dry-in / Flat"],
    ["tile", "Tile"],
    ["metal", "Metal"],
    ["shingle", "Shingle"],
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <Button
          variant="ghost"
          style={{ fontSize: 12, padding: "4px 10px" }}
          onClick={() => setRawMode((m) => !m)}
        >
          {rawMode ? "Structured view" : "Raw JSON"}
        </Button>
      </div>

      {rawMode ? (
        <div>
          <textarea
            value={rawText}
            onChange={(e) => handleRawChange(e.target.value)}
            disabled={disabled}
            rows={28}
            style={{
              ...inputStyle,
              width: "100%",
              fontFamily: "monospace",
              fontSize: 12,
              background: disabled ? BRAND.bg : "#fff",
              resize: "vertical",
            }}
          />
          {rawError && <ErrorMsg>{rawError}</ErrorMsg>}
        </div>
      ) : (
        <div>
          {/* ── Group 1: Base Pricing ── */}
          <CollapsibleGroup title="Base Pricing">
            <ZoneTypeTable
              label="Sloped base cost L+M ($/sq)"
              data={getObj(["sloped_base_cost_lm"])}
              onChange={(v) => set(["sloped_base_cost_lm"], v)}
              disabled={disabled}
            />
            <ZoneTypeTable
              label="Sloped overhead ($/sq)"
              data={getObj(["sloped_overhead"])}
              onChange={(v) => set(["sloped_overhead"], v)}
              disabled={disabled}
            />
            <SectionLabel>Profit sliding scale ($/sq)</SectionLabel>
            <div
              style={{
                border: `1px solid ${BRAND.border}`,
                borderRadius: 8,
                overflow: "hidden",
                marginBottom: 16,
              }}
            >
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: BRAND.bg }}>
                    <th style={{ padding: "8px 12px", textAlign: "left", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>
                      Max SQ (exclusive, null = catch-all)
                    </th>
                    <th style={{ padding: "8px 12px", textAlign: "right", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>
                      Profit $/sq
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {profitScale.map(([max, pft], i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                      <td style={{ padding: "6px 12px", color: BRAND.ink }}>
                        {max === null ? "∞ (catch-all)" : `< ${max} SQ`}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>
                        <input
                          type="number"
                          disabled={disabled}
                          value={pft}
                          onChange={(e) => {
                            const updated = profitScale.map((tier, j) =>
                              j === i ? [tier[0], parseFloat(e.target.value) || 0] : tier
                            ) as Array<[number | null, number]>;
                            set(["profit_scale"], updated);
                          }}
                          style={{
                            ...inputStyle,
                            padding: "4px 8px",
                            fontSize: 12,
                            width: 90,
                            textAlign: "right",
                            background: disabled ? BRAND.bg : "#fff",
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CollapsibleGroup>

          {/* ── Group 2: Day-Based Overhead & Profit (v2) ── */}
          <CollapsibleGroup title="Day-Based Overhead & Profit (Estimator v2)" accent="#f0f4ff">
            <p style={{ margin: "0 0 12px", fontSize: 12, color: BRAND.sub, lineHeight: 1.5 }}>
              Daily overhead rates and profit controls used by the Estimator v2 day-based engine.
              These keys are absent in pre-v2 config versions — fields will show the saved value or the engine default.
            </p>
            <SectionLabel>Daily overhead rates ($/day)</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              {dailyRateKeys.map(([key, label]) => {
                const rates = (config.daily_overhead_rates ?? {}) as Record<string, number | null>;
                const val = key in rates ? rates[key] : undefined;
                return (
                  <NumericField
                    key={key}
                    label={label}
                    value={val as number | null | undefined}
                    onChange={(v) => {
                      const cur = JSON.parse(
                        JSON.stringify((config.daily_overhead_rates ?? {}) as Record<string, unknown>)
                      ) as Record<string, unknown>;
                      cur[key] = v;
                      set(["daily_overhead_rates"], cur);
                    }}
                    disabled={disabled}
                    unit="$/day, step 5"
                  />
                );
              })}
            </div>
            <SectionLabel>Profit floors ($)</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField
                label="Weekly profit floor"
                value={
                  config.weekly_profit_floor !== undefined
                    ? (config.weekly_profit_floor as number | null)
                    : 2500
                }
                onChange={(v) => set(["weekly_profit_floor"], v)}
                disabled={disabled}
                unit="$"
              />
              <NumericField
                label="Job profit floor"
                value={
                  config.job_profit_floor !== undefined
                    ? (config.job_profit_floor as number | null)
                    : 2500
                }
                onChange={(v) => set(["job_profit_floor"], v)}
                disabled={disabled}
                unit="$"
              />
            </div>
            <SectionLabel>Rounding & profit mode</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>
                <label
                  style={{
                    display: "block",
                    fontSize: 11,
                    fontWeight: 600,
                    color: BRAND.sub,
                    marginBottom: 2,
                    textTransform: "uppercase",
                    letterSpacing: 0.3,
                  }}
                >
                  Weeks rounding mode
                </label>
                <select
                  disabled={disabled}
                  value={getStr(["daily_overhead_weeks_rounding_mode"], "ceil")}
                  onChange={(e) => set(["daily_overhead_weeks_rounding_mode"], e.target.value)}
                  style={{
                    ...inputStyle,
                    padding: "6px 10px",
                    fontSize: 13,
                    width: "100%",
                    background: disabled ? BRAND.bg : "#fff",
                    cursor: disabled ? "default" : "pointer",
                  }}
                >
                  <option value="ceil">ceil (round up)</option>
                  <option value="floor">floor (round down)</option>
                </select>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label
                  style={{
                    display: "block",
                    fontSize: 11,
                    fontWeight: 600,
                    color: BRAND.sub,
                    marginBottom: 2,
                    textTransform: "uppercase",
                    letterSpacing: 0.3,
                  }}
                >
                  Default profit mode
                </label>
                <select
                  disabled={disabled}
                  value={getStr(["profit_mode_default"], "scale")}
                  onChange={(e) => set(["profit_mode_default"], e.target.value)}
                  style={{
                    ...inputStyle,
                    padding: "6px 10px",
                    fontSize: 13,
                    width: "100%",
                    background: disabled ? BRAND.bg : "#fff",
                    cursor: disabled ? "default" : "pointer",
                  }}
                >
                  <option value="scale">scale (sliding $/sq)</option>
                  <option value="flat">flat (fixed weekly floor)</option>
                </select>
              </div>
            </div>
          </CollapsibleGroup>

          {/* ── Group 3: Adders ── */}
          <CollapsibleGroup title="Adders">
            <SectionLabel>Per-square adders ($)</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16 }}>
              {(
                [
                  ["pitch_7_12_add", "Pitch ≥ 7/12 (tile)"],
                  ["tile_demo_add", "Tile demo/tear-off"],
                  ["metal_demo_add", "Metal demo/tear-off"],
                  ["secondary_water_barrier_add", "Secondary water barrier"],
                  ["winterguard_add", "WinterGuard"],
                ] as [string, string][]
              ).map(([key, label]) => (
                <NumericField
                  key={key}
                  label={label}
                  value={getNum([key])}
                  onChange={(v) => set([key], v)}
                  disabled={disabled}
                />
              ))}
            </div>
            <SectionLabel>Linear / each adders</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField label="Stucco metal ($/LF)" value={getNum(["stucco_metal_per_lf"])} onChange={(v) => set(["stucco_metal_per_lf"], v)} disabled={disabled} />
              <NumericField label="Penetration ($/each)" value={getNum(["penetration_each"])} onChange={(v) => set(["penetration_each"], v)} disabled={disabled} />
              <NumericField label="Ridge vent ($/LF)" value={getNum(["ridge_vent_per_lf"])} onChange={(v) => set(["ridge_vent_per_lf"], v)} disabled={disabled} />
            </div>
            <SectionLabel>Project fixed costs ($)</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField label="Delivery / plywood / vents" value={getNum(["delivery_plywood_vents"])} onChange={(v) => set(["delivery_plywood_vents"], v)} disabled={disabled} />
              <NumericField label="New bonus values" value={getNum(["new_bonus_values"])} onChange={(v) => set(["new_bonus_values"], v)} disabled={disabled} />
              <NumericField label="Permit processing" value={getNum(["permit_processing"])} onChange={(v) => set(["permit_processing"], v)} disabled={disabled} />
              <NumericField label="Permit commercial add" value={getNum(["permit_commercial_add"])} onChange={(v) => set(["permit_commercial_add"], v)} disabled={disabled} />
              <NumericField label="3–5 story flat add ($)" value={getNum(["roof_height_3_5_flat_add"])} onChange={(v) => set(["roof_height_3_5_flat_add"], v)} disabled={disabled} />
            </div>
          </CollapsibleGroup>

          {/* ── Group 4: Incentives & Commission ── */}
          <CollapsibleGroup title="Incentives & Commission">
            <SectionLabel>PM incentive matrix ($ flat)</SectionLabel>
            <div
              style={{
                border: `1px solid ${BRAND.border}`,
                borderRadius: 8,
                overflow: "hidden",
                marginBottom: 16,
              }}
            >
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: BRAND.bg }}>
                    <th style={{ padding: "8px 12px", textAlign: "left", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>Band</th>
                    <th style={{ padding: "8px 12px", textAlign: "right", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>HVHZ</th>
                    <th style={{ padding: "8px 12px", textAlign: "right", color: BRAND.sub, fontWeight: 700, borderBottom: `1px solid ${BRAND.border}` }}>FBC</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["residential_lt20", "Residential < 20 SQ"],
                      ["commercial_20_50", "Commercial 20–50 SQ"],
                      ["commercial_gt50", "Commercial > 50 SQ"],
                    ] as [string, string][]
                  ).map(([key, label]) => {
                    const pm = (config.pm_incentive ?? {}) as Record<string, Record<string, number>>;
                    return (
                      <tr key={key} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                        <td style={{ padding: "6px 12px", color: BRAND.ink }}>{label}</td>
                        {(["HVHZ", "FBC"] as const).map((zone) => (
                          <td key={zone} style={{ padding: "4px 8px", textAlign: "right" }}>
                            <input
                              type="number"
                              disabled={disabled}
                              value={(pm[zone]?.[key] ?? 0)}
                              onChange={(e) => {
                                const updated = JSON.parse(JSON.stringify(pm)) as Record<string, Record<string, number>>;
                                if (!updated[zone]) updated[zone] = {};
                                updated[zone][key] = parseFloat(e.target.value) || 0;
                                set(["pm_incentive"], updated);
                              }}
                              style={{
                                ...inputStyle,
                                padding: "4px 8px",
                                fontSize: 12,
                                width: 90,
                                textAlign: "right",
                                background: disabled ? BRAND.bg : "#fff",
                              }}
                            />
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <SectionLabel>Commission rates</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField
                label="Sloped (%)"
                value={
                  typeof (config.commission_pct as Record<string, unknown> | undefined)?.sloped === "number"
                    ? ((config.commission_pct as Record<string, number>).sloped * 100)
                    : null
                }
                onChange={(v) => {
                  const cur = (config.commission_pct ?? {}) as Record<string, number>;
                  set(["commission_pct"], { ...cur, sloped: v !== null ? v / 100 : null });
                }}
                disabled={disabled}
                unit="e.g. 10 = 10%"
              />
              <NumericField
                label="Low-slope (%)"
                value={
                  typeof (config.commission_pct as Record<string, unknown> | undefined)?.low_slope === "number"
                    ? ((config.commission_pct as Record<string, number>).low_slope * 100)
                    : null
                }
                onChange={(v) => {
                  const cur = (config.commission_pct ?? {}) as Record<string, number>;
                  set(["commission_pct"], { ...cur, low_slope: v !== null ? v / 100 : null });
                }}
                disabled={disabled}
                unit="e.g. 15 = 15%"
              />
            </div>
            <SectionLabel>Margin floors</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField
                label="Profit floor (%)"
                value={typeof config.profit_floor_pct === "number" ? (config.profit_floor_pct as number) * 100 : null}
                onChange={(v) => set(["profit_floor_pct"], v !== null ? v / 100 : null)}
                disabled={disabled}
                unit="e.g. 13 = 13%"
              />
              <NumericField
                label="Profit+OH floor (%)"
                value={typeof config.profit_plus_oh_floor_pct === "number" ? (config.profit_plus_oh_floor_pct as number) * 100 : null}
                onChange={(v) => set(["profit_plus_oh_floor_pct"], v !== null ? v / 100 : null)}
                disabled={disabled}
                unit="e.g. 33 = 33%"
              />
            </div>
            <SectionLabel>Tile dumpster</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField
                label="Cost per dumpster ($)"
                value={getNum(["tile_dumpster_cost"])}
                onChange={(v) => set(["tile_dumpster_cost"], v)}
                disabled={disabled}
              />
              <NumericField
                label="HVHZ threshold (SQ)"
                value={getNum(["tile_dumpster_threshold", "HVHZ"])}
                onChange={(v) => set(["tile_dumpster_threshold", "HVHZ"], v)}
                disabled={disabled}
              />
              <NumericField
                label="FBC threshold (SQ)"
                value={getNum(["tile_dumpster_threshold", "FBC"])}
                onChange={(v) => set(["tile_dumpster_threshold", "FBC"], v)}
                disabled={disabled}
              />
            </div>
          </CollapsibleGroup>

          {/* ── Group 5: Low-Slope (Pending Tim) ── */}
          <CollapsibleGroup title="Low-Slope (Pending Tim)" accent="#fffbf0">
            <div
              style={{
                border: `1px dashed #fcd34d`,
                borderRadius: 8,
                padding: "12px 14px",
                background: "#fffbf0",
                marginBottom: 14,
              }}
            >
              <p style={{ margin: 0, fontSize: 13, color: "#92400e" }}>
                All low-slope rates below are <strong>pending Tim's Exhibit B §4 values</strong>. Null fields will show "Pending Tim" — the engine raises a <code>ConfigError</code> if any null is exercised.
              </p>
            </div>
            <ZoneTypeTable
              label="Low-slope base cost L+M ($/sq)"
              data={getObj(["low_slope", "base_cost_lm"])}
              onChange={(v) => set(["low_slope", "base_cost_lm"], v)}
              disabled={disabled}
            />
            <ZoneTypeTable
              label="Low-slope overhead ($/sq)"
              data={getObj(["low_slope", "overhead"])}
              onChange={(v) => set(["low_slope", "overhead"], v)}
              disabled={disabled}
            />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 8, marginBottom: 8 }}>
              <NumericField
                label="Tapered cost ($/sq, no OH/profit)"
                value={getNum(["low_slope", "tapered_cost_per_sq"])}
                onChange={(v) => set(["low_slope", "tapered_cost_per_sq"], v)}
                disabled={disabled}
              />
              <NumericField
                label="Tear-off per layer ($/sq)"
                value={getNum(["low_slope", "tear_off_per_layer_per_sq"])}
                onChange={(v) => set(["low_slope", "tear_off_per_layer_per_sq"], v)}
                disabled={disabled}
              />
            </div>
          </CollapsibleGroup>

          <CollapsibleGroup title="Gutters" accent="#f0f4ff">
            <p style={{ margin: "0 0 12px", fontSize: 12, color: BRAND.sub, lineHeight: 1.5 }}>
              Rates keyed by gutter style (matches <code>core/estimator.py</code>'s <code>gutters.styles.&lt;key&gt;</code> lookup).
              A style or field left blank prices nothing until filled — a quote that uses it shows a clear "pending" error.
              New style keys can be added via Raw JSON.
            </p>
            <GutterStylesTable
              styles={((config.gutters as Record<string, unknown> | undefined)?.styles ?? {}) as Record<string, GutterStyle>}
              onChange={(v) => set(["gutters", "styles"], v)}
              disabled={disabled}
            />
            <SectionLabel>Removal, leaf guard & leaderheads</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16 }}>
              <NumericField label="Removal ($/LF)" value={getNum(["gutters", "removal_per_lf"])} onChange={(v) => set(["gutters", "removal_per_lf"], v)} disabled={disabled} />
              <NumericField label="Leaf guard, standard ($/LF)" value={getNum(["gutters", "leaf_guard_std_per_lf"])} onChange={(v) => set(["gutters", "leaf_guard_std_per_lf"], v)} disabled={disabled} />
              <NumericField label="Leaf guard, upgraded ($/LF)" value={getNum(["gutters", "leaf_guard_upgraded_per_lf"])} onChange={(v) => set(["gutters", "leaf_guard_upgraded_per_lf"], v)} disabled={disabled} />
              <NumericField label="Leaderhead, residential ($ each)" value={getNum(["gutters", "leaderhead_res_each"])} onChange={(v) => set(["gutters", "leaderhead_res_each"], v)} disabled={disabled} />
              <NumericField label="Leaderhead, commercial ($ each)" value={getNum(["gutters", "leaderhead_comm_each"])} onChange={(v) => set(["gutters", "leaderhead_comm_each"], v)} disabled={disabled} />
              <NumericField label="Small-job add ($/LF)" value={getNum(["gutters", "small_job_add_per_lf"])} onChange={(v) => set(["gutters", "small_job_add_per_lf"], v)} disabled={disabled} unit="under threshold" />
              <NumericField label="Small-job threshold (LF)" value={getNum(["gutters", "small_job_threshold_lf"])} onChange={(v) => set(["gutters", "small_job_threshold_lf"], v)} disabled={disabled} />
            </div>
          </CollapsibleGroup>
        </div>
      )}
    </div>
  );
}

// ── Activate confirm modal ────────────────────────────────────────────────────

function ActivateModal({
  version,
  hash,
  onConfirm,
  onCancel,
  busy,
}: {
  version: number;
  hash: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        fontFamily: FONT,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: 28,
          maxWidth: 420,
          width: "90%",
          boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
        }}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: 16, color: BRAND.navyText }}>
          Activate v{version}?
        </h3>
        <p style={{ margin: "0 0 14px", fontSize: 13, color: BRAND.ink, lineHeight: 1.6 }}>
          This will set <strong>v{version}</strong> as the active config and deactivate the current version.
          All new quotes will use this config immediately. Hash:
        </p>
        <div style={{ marginBottom: 18 }}>
          <HashDisplay hash={hash} />
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? "Activating…" : "Activate"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Main EstimatingConfig component ──────────────────────────────────────────

interface EstimatingConfigProps {
  role: Role;
}

export function EstimatingConfig({ role }: EstimatingConfigProps) {
  const manage = canManage(role);
  const [branches, setBranches] = useState<BranchRow[]>([]);
  const [branch, setBranch] = useState<string>("miami");

  // Version list
  const [versions, setVersions] = useState<PricingConfigVersion[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // Selected version for detail/edit
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PricingConfigDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Draft config being edited
  const [draftConfig, setDraftConfig] = useState<Record<string, unknown> | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [isDirty, setIsDirty] = useState(false);

  // Save (new version)
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Activate
  const [activateTarget, setActivateTarget] = useState<PricingConfigVersion | null>(null);
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);

  // Diff
  const [diffFromId, setDiffFromId] = useState<number | null>(null);
  const [diffToId, setDiffToId] = useState<number | null>(null);
  const [diff, setDiff] = useState<PricingConfigDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const loadVersions = useCallback(
    (b: string) => {
      setListLoading(true);
      setListError(null);
      setVersions([]);
      setSelectedId(null);
      setDetail(null);
      setDraftConfig(null);
      setIsDirty(false);
      setDiff(null);
      setSaveSuccess(false);
      listPricingConfigs(b)
        .then((vs) => {
          // Sort newest first.
          const sorted = [...vs].sort((a, b) => b.version - a.version);
          setVersions(sorted);
          // Auto-select the active version if present, else the first.
          const active = sorted.find((v) => v.is_active) ?? sorted[0];
          if (active) setSelectedId(active.id);
        })
        .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
        .finally(() => setListLoading(false));
    },
    []
  );

  useEffect(() => {
    listBranches()
      .then((bs) => {
        setBranches(bs);
        if (bs.length > 0 && !bs.some((b) => b.key === branch)) {
          setBranch(bs.find((b) => b.key === "miami")?.key ?? bs[0].key);
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadVersions(branch);
  }, [branch, loadVersions]);

  // Load detail when selectedId changes.
  useEffect(() => {
    if (selectedId === null) return;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    setDraftConfig(null);
    setIsDirty(false);
    setDiff(null);
    setSaveSuccess(false);
    setSaveError(null);
    getPricingConfig(selectedId)
      .then((d) => {
        setDetail(d);
        setDraftConfig(JSON.parse(JSON.stringify(d.config)));
        setDraftLabel(d.label ?? "");
      })
      .catch((e: unknown) => setDetailError(e instanceof Error ? e.message : String(e)))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  function handleBranchChange(b: string) {
    if (b === branch) return;
    // Switching branch reloads the config and drops in-progress edits — confirm first.
    if (isDirty && !window.confirm("Discard unsaved changes to this branch's config?")) return;
    setIsDirty(false);
    setBranch(b);
  }

  function handleConfigChange(updated: Record<string, unknown>) {
    setDraftConfig(updated);
    setIsDirty(true);
    setSaveSuccess(false);
  }

  async function handleSave() {
    if (!draftConfig) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const created = await createPricingConfig({
        branch,
        label: draftLabel.trim() || undefined,
        config: draftConfig,
      });
      setSaveSuccess(true);
      setIsDirty(false);
      // Reload version list; select the new version.
      const vs = await listPricingConfigs(branch);
      const sorted = [...vs].sort((a, b) => b.version - a.version);
      setVersions(sorted);
      setSelectedId(created.id);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleActivate() {
    if (!activateTarget) return;
    setActivating(true);
    setActivateError(null);
    try {
      await activatePricingConfig(activateTarget.id);
      setActivateTarget(null);
      // Reload so the active badge updates.
      const vs = await listPricingConfigs(branch);
      const sorted = [...vs].sort((a, b) => b.version - a.version);
      setVersions(sorted);
    } catch (e: unknown) {
      setActivateError(e instanceof Error ? e.message : String(e));
      setActivateTarget(null);
    } finally {
      setActivating(false);
    }
  }

  async function handleDiff() {
    if (!diffFromId || !diffToId) return;
    setDiffLoading(true);
    setDiffError(null);
    setDiff(null);
    try {
      const result = await diffPricingConfigs(diffFromId, diffToId);
      setDiff(result);
    } catch {
      // Backend diff endpoint may not be implemented yet — fall back to client-side.
      try {
        const [fromDetail, toDetail] = await Promise.all([
          getPricingConfig(diffFromId),
          getPricingConfig(diffToId),
        ]);
        setDiff(
          computeClientDiff(
            diffFromId,
            fromDetail.config,
            diffToId,
            toDetail.config
          )
        );
      } catch (e2: unknown) {
        setDiffError(e2 instanceof Error ? e2.message : String(e2));
      }
    } finally {
      setDiffLoading(false);
    }
  }

  const selectedVersion = versions.find((v) => v.id === selectedId);

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Activate modal */}
      {activateTarget && (
        <ActivateModal
          version={activateTarget.version}
          hash={activateTarget.config_hash}
          onConfirm={handleActivate}
          onCancel={() => setActivateTarget(null)}
          busy={activating}
        />
      )}

      {/* Branch selector */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: BRAND.sub }}>Branch:</span>
        <div
          style={{
            display: "flex",
            borderRadius: 6,
            overflow: "hidden",
            border: `1px solid ${BRAND.border}`,
          }}
        >
          {branches.map((b, i) => {
            const active = branch === b.key;
            return (
              <button
                key={b.key}
                onClick={() => handleBranchChange(b.key)}
                style={{
                  padding: "7px 18px",
                  fontSize: 13,
                  fontWeight: 600,
                  border: "none",
                  borderRight:
                    i < branches.length - 1 ? `1px solid ${BRAND.border}` : "none",
                  cursor: "pointer",
                  background: active ? BRAND.navy : "#fff",
                  color: active ? "#fff" : BRAND.sub,
                  transition: "background 0.1s, color 0.1s",
                  fontFamily: FONT,
                }}
              >
                {b.name}
              </button>
            );
          })}
        </div>
        {!manage && (
          <Badge tone="amber">Read-only — requires estimating_manage role</Badge>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "280px 1fr",
          gap: 20,
          alignItems: "start",
        }}
      >
        {/* ── Left: version list ── */}
        <div>
          <Card style={{ padding: "12px 8px" }}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: BRAND.sub,
                textTransform: "uppercase",
                letterSpacing: 0.4,
                padding: "0 8px 10px",
                borderBottom: `1px solid ${BRAND.border}`,
                marginBottom: 8,
              }}
            >
              Versions
            </div>

            {listLoading && (
              <div style={{ padding: 16, textAlign: "center" }}>
                <Loading label="Loading versions…" />
              </div>
            )}
            {listError && <ErrorMsg>Error: {listError}</ErrorMsg>}

            {!listLoading && versions.length === 0 && !listError && (
              <p style={{ fontSize: 13, color: BRAND.sub, padding: "8px 8px" }}>
                No config versions found for {branch}.
              </p>
            )}

            {versions.map((v) => (
              <VersionRow
                key={v.id}
                v={v}
                selected={v.id === selectedId}
                onSelect={() => setSelectedId(v.id)}
              />
            ))}
          </Card>

          {/* Diff picker */}
          {versions.length >= 2 && (
            <Card style={{ marginTop: 12, padding: 14 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: BRAND.sub,
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  marginBottom: 10,
                }}
              >
                Compare versions
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div>
                  <label style={{ fontSize: 11, color: BRAND.sub, display: "block", marginBottom: 2 }}>From</label>
                  <select
                    value={diffFromId ?? ""}
                    onChange={(e) => setDiffFromId(e.target.value ? Number(e.target.value) : null)}
                    style={{ ...inputStyle, padding: "5px 8px", fontSize: 12, width: "100%" }}
                  >
                    <option value="">— select —</option>
                    {versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version} {v.is_active ? "(active)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 11, color: BRAND.sub, display: "block", marginBottom: 2 }}>To</label>
                  <select
                    value={diffToId ?? ""}
                    onChange={(e) => setDiffToId(e.target.value ? Number(e.target.value) : null)}
                    style={{ ...inputStyle, padding: "5px 8px", fontSize: 12, width: "100%" }}
                  >
                    <option value="">— select —</option>
                    {versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        v{v.version} {v.is_active ? "(active)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  variant="ghost"
                  disabled={!diffFromId || !diffToId || diffFromId === diffToId || diffLoading}
                  onClick={handleDiff}
                  style={{ fontSize: 12, padding: "6px 10px" }}
                >
                  {diffLoading ? "Loading…" : "Show diff"}
                </Button>
                {diffError && <ErrorMsg>{diffError}</ErrorMsg>}
              </div>
            </Card>
          )}
        </div>

        {/* ── Right: detail + editor ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Diff panel — shown above the editor when active */}
          {diff && (
            <Card>
              <DiffView
                diff={diff}
                fromVersion={versions.find((v) => v.id === diff.from_id)?.version ?? diff.from_id}
                toVersion={versions.find((v) => v.id === diff.to_id)?.version ?? diff.to_id}
                onClose={() => setDiff(null)}
              />
            </Card>
          )}

          {detailLoading && (
            <Card>
              <Loading label="Loading config…" />
            </Card>
          )}
          {detailError && <ErrorMsg>Error loading version: {detailError}</ErrorMsg>}

          {detail && draftConfig && (
            <Card>
              {/* Header row */}
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  marginBottom: 16,
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      marginBottom: 4,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 16,
                        fontWeight: 700,
                        color: BRAND.navyText,
                      }}
                    >
                      v{detail.version}
                    </span>
                    {detail.is_active && <Badge tone="green">Active</Badge>}
                    {isDirty && <Badge tone="amber">Unsaved changes</Badge>}
                  </div>
                  <div style={{ fontSize: 12, color: BRAND.sub }}>
                    Created {fmtDate(detail.created_at)} by {detail.created_by}
                  </div>
                  <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 11, color: BRAND.sub }}>Hash (SHA-256):</span>
                    <HashDisplay hash={detail.config_hash} />
                  </div>
                </div>

                {/* Action buttons */}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  {manage && !detail.is_active && (
                    <Button
                      variant="ghost"
                      onClick={() => setActivateTarget(selectedVersion ?? detail)}
                      disabled={activating}
                      style={{ fontSize: 13 }}
                    >
                      Activate
                    </Button>
                  )}
                  {manage && (
                    <Button
                      onClick={handleSave}
                      disabled={saving || !isDirty}
                      style={{ fontSize: 13 }}
                    >
                      {saving ? "Saving…" : "Save as new version"}
                    </Button>
                  )}
                </div>
              </div>

              {activateError && <ErrorMsg>Activate error: {activateError}</ErrorMsg>}
              {saveError && <ErrorMsg>Save error: {saveError}</ErrorMsg>}
              {saveSuccess && (
                <div
                  style={{
                    fontSize: 13,
                    color: "#1a7f4b",
                    background: "#e6f9f0",
                    padding: "8px 12px",
                    borderRadius: 6,
                    marginBottom: 12,
                  }}
                >
                  New version saved. Select it in the list to view or activate.
                </div>
              )}

              {/* Label field */}
              {manage && (
                <div style={{ marginBottom: 16 }}>
                  <label
                    style={{
                      display: "block",
                      fontSize: 11,
                      fontWeight: 600,
                      color: BRAND.sub,
                      marginBottom: 4,
                      textTransform: "uppercase",
                      letterSpacing: 0.3,
                    }}
                  >
                    Version label (optional)
                  </label>
                  <input
                    type="text"
                    value={draftLabel}
                    placeholder="e.g. 2026-Q3 Exhibit B"
                    onChange={(e) => {
                      setDraftLabel(e.target.value);
                      setIsDirty(true);
                    }}
                    style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%" }}
                  />
                </div>
              )}

              {/* Config editor */}
              <ConfigEditor
                config={draftConfig}
                onChange={handleConfigChange}
                disabled={!manage}
              />
            </Card>
          )}

          {!detailLoading && !detailError && !detail && !listLoading && (
            <Card style={{ background: BRAND.bg, border: "none", textAlign: "center", padding: "40px 20px" }}>
              <p style={{ margin: 0, fontSize: 13, color: BRAND.sub }}>
                Select a version from the list to view or edit.
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
