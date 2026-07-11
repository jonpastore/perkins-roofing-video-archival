import { useEffect, useState } from "react";
import {
  BRAND,
  FONT,
  Card,
  Button,
  Loading,
  ErrorMsg,
  Badge,
  SectionLabel,
  inputStyle,
} from "../ui";
import {
  listPriceBookItems,
  createPriceBookItem,
  updatePriceBookItem,
  listPriceBookVersions,
  freezePriceBookVersion,
  type PriceBookItem,
  type PriceBookItemUpsert,
  type PriceBookVersion,
} from "../api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(val: string | null, prefix = ""): string {
  return val == null ? "—" : `${prefix}${val}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ── Row editor state ──────────────────────────────────────────────────────────

interface RowDraft {
  name: string;
  sku: string;
  supplier: string;
  unit: string;
  unit_coverage: string;
  unit_price: string;
  tax_rate: string;
  waste_rate: string;
}

function blankDraft(item?: PriceBookItem): RowDraft {
  return {
    name: item?.name ?? "",
    sku: item?.sku ?? "",
    supplier: item?.supplier ?? "",
    unit: item?.unit ?? "",
    unit_coverage: item?.unit_coverage ?? "",
    unit_price: item?.unit_price ?? "",
    tax_rate: item?.tax_rate ?? "",
    waste_rate: item?.waste_rate ?? "",
  };
}

function draftToUpsert(d: RowDraft): PriceBookItemUpsert {
  const nullIfEmpty = (s: string): string | null => s.trim() === "" ? null : s.trim();
  return {
    name: d.name.trim(),
    sku: nullIfEmpty(d.sku),
    supplier: nullIfEmpty(d.supplier),
    unit: nullIfEmpty(d.unit),
    unit_coverage: nullIfEmpty(d.unit_coverage),
    unit_price: nullIfEmpty(d.unit_price),
    tax_rate: d.tax_rate.trim() || undefined,
    waste_rate: d.waste_rate.trim() || undefined,
  };
}

// ── Shared table styles ───────────────────────────────────────────────────────

const TH_STYLE = {
  padding: "8px 10px",
  fontSize: 11,
  fontWeight: 700,
  color: BRAND.sub,
  textTransform: "uppercase" as const,
  letterSpacing: 0.4,
  borderBottom: `1px solid ${BRAND.border}`,
  background: BRAND.bg,
  whiteSpace: "nowrap" as const,
};

const TD_STYLE = {
  padding: "7px 10px",
  fontSize: 13,
  color: BRAND.ink,
  borderBottom: `1px solid ${BRAND.border}`,
  verticalAlign: "middle" as const,
};

const TD_NUM = {
  ...TD_STYLE,
  textAlign: "right" as const,
  fontVariantNumeric: "tabular-nums" as const,
};

const SMALL_INPUT = {
  ...inputStyle,
  padding: "5px 7px",
  fontSize: 12,
  width: "100%",
  minWidth: 60,
  boxSizing: "border-box" as const,
};

// ── EditableRow ───────────────────────────────────────────────────────────────

interface EditableRowProps {
  draft: RowDraft;
  onChange: (d: RowDraft) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
  isNew?: boolean;
}

function EditableRow({ draft, onChange, onSave, onCancel, saving, error, isNew }: EditableRowProps) {
  const set = (k: keyof RowDraft) => (e: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...draft, [k]: e.target.value });

  const canSave = draft.name.trim() !== "" && !saving;

  return (
    <>
      <tr style={{ background: "#f0f4ff" }}>
        <td style={{ ...TD_STYLE, minWidth: 140 }}>
          <input style={SMALL_INPUT} value={draft.name} onChange={set("name")} placeholder="Name *" autoFocus={isNew} />
        </td>
        <td style={TD_STYLE}>
          <input style={SMALL_INPUT} value={draft.sku} onChange={set("sku")} placeholder="SKU" />
        </td>
        <td style={TD_STYLE}>
          <input style={SMALL_INPUT} value={draft.supplier} onChange={set("supplier")} placeholder="Supplier" />
        </td>
        <td style={TD_STYLE}>
          <input style={SMALL_INPUT} value={draft.unit} onChange={set("unit")} placeholder="ea / sq / lf" />
        </td>
        <td style={{ ...TD_NUM }}>
          <input style={{ ...SMALL_INPUT, textAlign: "right" }} value={draft.unit_coverage} onChange={set("unit_coverage")} placeholder="0.00" />
        </td>
        <td style={{ ...TD_NUM }}>
          <input style={{ ...SMALL_INPUT, textAlign: "right" }} value={draft.unit_price} onChange={set("unit_price")} placeholder="null = unstocked" />
        </td>
        <td style={{ ...TD_NUM }}>
          <input style={{ ...SMALL_INPUT, textAlign: "right" }} value={draft.tax_rate} onChange={set("tax_rate")} placeholder="0.07" />
        </td>
        <td style={{ ...TD_NUM }}>
          <input style={{ ...SMALL_INPUT, textAlign: "right" }} value={draft.waste_rate} onChange={set("waste_rate")} placeholder="0.10" />
        </td>
        <td style={{ ...TD_NUM }}>—</td>
        <td style={{ ...TD_STYLE, whiteSpace: "nowrap" as const }}>
          <div style={{ display: "flex", gap: 6 }}>
            <Button style={{ padding: "5px 12px", fontSize: 12 }} onClick={onSave} disabled={!canSave}>
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button variant="ghost" style={{ padding: "5px 10px", fontSize: 12 }} onClick={onCancel} disabled={saving}>
              Cancel
            </Button>
          </div>
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={10} style={{ padding: "4px 10px" }}>
            <ErrorMsg>{error}</ErrorMsg>
          </td>
        </tr>
      )}
    </>
  );
}

// ── ItemRow ───────────────────────────────────────────────────────────────────

interface ItemRowProps {
  item: PriceBookItem;
  onUpdated: (item: PriceBookItem) => void;
}

function ItemRow({ item, onUpdated }: ItemRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<RowDraft>(blankDraft(item));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setDraft(blankDraft(item));
    setError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setError(null);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePriceBookItem(item.id, draftToUpsert(draft));
      onUpdated(updated);
      setEditing(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <EditableRow
        draft={draft}
        onChange={setDraft}
        onSave={save}
        onCancel={cancelEdit}
        saving={saving}
        error={error}
      />
    );
  }

  return (
    <tr>
      <td style={TD_STYLE}>{item.name}</td>
      <td style={TD_STYLE}>{item.sku ?? "—"}</td>
      <td style={TD_STYLE}>{item.supplier ?? "—"}</td>
      <td style={TD_STYLE}>{item.unit ?? "—"}</td>
      <td style={TD_NUM}>{fmt(item.unit_coverage)}</td>
      <td style={TD_NUM}>{item.unit_price == null ? <span style={{ color: BRAND.sub, fontSize: 12 }}>unstocked</span> : `$${item.unit_price}`}</td>
      <td style={TD_NUM}>{fmt(item.tax_rate)}</td>
      <td style={TD_NUM}>{fmt(item.waste_rate)}</td>
      <td style={TD_NUM}>{item.price_per_square == null ? "—" : `$${item.price_per_square}`}</td>
      <td style={TD_STYLE}>
        <Button variant="ghost" style={{ padding: "4px 12px", fontSize: 12 }} onClick={startEdit}>
          Edit
        </Button>
      </td>
    </tr>
  );
}

// ── NewItemRow ────────────────────────────────────────────────────────────────

interface NewItemRowProps {
  onCreated: (item: PriceBookItem) => void;
  onCancel: () => void;
}

function NewItemRow({ onCreated, onCancel }: NewItemRowProps) {
  const [draft, setDraft] = useState<RowDraft>(blankDraft());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const created = await createPriceBookItem(draftToUpsert(draft));
      onCreated(created);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }

  return (
    <EditableRow
      draft={draft}
      onChange={setDraft}
      onSave={save}
      onCancel={onCancel}
      saving={saving}
      error={error}
      isNew
    />
  );
}

// ── FreezeCard ────────────────────────────────────────────────────────────────

interface FreezeCardProps {
  onFrozen: (versions: PriceBookVersion[]) => void;
}

function FreezeCard({ onFrozen }: FreezeCardProps) {
  const [supplier, setSupplier] = useState("DEFAULT");
  const [label, setLabel] = useState("");
  const [activate, setActivate] = useState(true);
  const [freezing, setFreezing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{ version_number: number; item_count: number } | null>(null);

  async function handleFreeze() {
    setFreezing(true);
    setError(null);
    setConfirmation(null);
    try {
      const result = await freezePriceBookVersion({
        supplier: supplier.trim() || undefined,
        label: label.trim() || undefined,
        activate,
      });
      setConfirmation({ version_number: result.version_number, item_count: result.item_count });
      // reload versions
      const versions = await listPriceBookVersions();
      onFrozen(versions);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setFreezing(false);
    }
  }

  return (
    <Card style={{ marginBottom: 20 }}>
      <SectionLabel>Freeze version</SectionLabel>
      <p style={{ margin: "0 0 14px", fontSize: 12, color: BRAND.sub, lineHeight: 1.6 }}>
        Freezing snapshots the current live items into an immutable, hash-pinned version; issued estimates pin the version so later edits never retro-change a prior estimate.
      </p>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div style={{ flex: "1 1 160px" }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: BRAND.sub, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>
            Supplier
          </label>
          <input
            style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", boxSizing: "border-box" }}
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            placeholder="DEFAULT"
          />
        </div>
        <div style={{ flex: "2 1 200px" }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: BRAND.sub, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>
            Label (optional)
          </label>
          <input
            style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", boxSizing: "border-box" }}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. 2026-Q3 price update"
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 2 }}>
          <input
            type="checkbox"
            id="pb-activate"
            checked={activate}
            onChange={(e) => setActivate(e.target.checked)}
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <label htmlFor="pb-activate" style={{ fontSize: 13, color: BRAND.ink, cursor: "pointer" }}>
            Set as active
          </label>
        </div>
        <Button onClick={handleFreeze} disabled={freezing} style={{ whiteSpace: "nowrap" }}>
          {freezing ? "Freezing…" : "Freeze current items → new version"}
        </Button>
      </div>
      {error && <ErrorMsg>{error}</ErrorMsg>}
      {confirmation && (
        <div style={{ marginTop: 12, fontSize: 13, color: "#1a7f4b", background: "#e6f9f0", padding: "8px 12px", borderRadius: 6 }}>
          Version {confirmation.version_number} created — {confirmation.item_count} items frozen.
        </div>
      )}
    </Card>
  );
}

// ── VersionsTable ─────────────────────────────────────────────────────────────

function VersionsTable({ versions }: { versions: PriceBookVersion[] }) {
  if (versions.length === 0) {
    return <p style={{ fontSize: 13, color: BRAND.sub }}>No versions yet. Freeze items to create one.</p>;
  }

  return (
    <div style={{ overflowX: "auto", border: `1px solid ${BRAND.border}`, borderRadius: 8 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>#</th>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>Supplier</th>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>Label</th>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>Status</th>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>Hash</th>
            <th style={{ ...TH_STYLE, textAlign: "left" }}>Created</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td style={{ ...TD_STYLE, fontWeight: 700, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>
                {v.version_number}
              </td>
              <td style={TD_STYLE}>{v.supplier}</td>
              <td style={{ ...TD_STYLE, color: v.label ? BRAND.ink : BRAND.sub }}>
                {v.label ?? "—"}
              </td>
              <td style={TD_STYLE}>
                {v.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">—</Badge>}
              </td>
              <td style={TD_STYLE}>
                <span style={{ fontFamily: "monospace", fontSize: 12, color: BRAND.sub, background: BRAND.bg, padding: "1px 6px", borderRadius: 4 }}>
                  {v.config_hash.slice(0, 8)}
                </span>
              </td>
              <td style={TD_STYLE}>{fmtDate(v.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── PriceBook ─────────────────────────────────────────────────────────────────

export function PriceBook() {
  const [items, setItems] = useState<PriceBookItem[]>([]);
  const [versions, setVersions] = useState<PriceBookVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingNew, setAddingNew] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([listPriceBookItems(), listPriceBookVersions()])
      .then(([its, vers]) => {
        setItems(its);
        setVersions(vers);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  function handleUpdated(updated: PriceBookItem) {
    setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
  }

  function handleCreated(created: PriceBookItem) {
    setItems((prev) => [created, ...prev]);
    setAddingNew(false);
  }

  if (loading) return <Loading label="Loading price book…" />;
  if (error) return <ErrorMsg>Error: {error}</ErrorMsg>;

  return (
    <div style={{ fontFamily: FONT }}>
      {/* ── Live items ── */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <SectionLabel>Live items</SectionLabel>
          {!addingNew && (
            <Button variant="ghost" style={{ padding: "5px 14px", fontSize: 12 }} onClick={() => setAddingNew(true)}>
              + Add item
            </Button>
          )}
        </div>

        <div style={{ overflowX: "auto", border: `1px solid ${BRAND.border}`, borderRadius: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th style={{ ...TH_STYLE, textAlign: "left" }}>Name</th>
                <th style={{ ...TH_STYLE, textAlign: "left" }}>SKU</th>
                <th style={{ ...TH_STYLE, textAlign: "left" }}>Supplier</th>
                <th style={{ ...TH_STYLE, textAlign: "left" }}>Unit</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Coverage</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Unit Price</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Tax</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Waste</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>$/sq</th>
                <th style={{ ...TH_STYLE, textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {addingNew && (
                <NewItemRow
                  onCreated={handleCreated}
                  onCancel={() => setAddingNew(false)}
                />
              )}
              {items.map((item) => (
                <ItemRow key={item.id} item={item} onUpdated={handleUpdated} />
              ))}
              {items.length === 0 && !addingNew && (
                <tr>
                  <td colSpan={10} style={{ ...TD_STYLE, textAlign: "center", color: BRAND.sub, padding: "28px 10px" }}>
                    No items yet. Add one above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Freeze + versions ── */}
      <FreezeCard onFrozen={setVersions} />

      <Card>
        <SectionLabel>Frozen versions</SectionLabel>
        <div style={{ marginTop: 10 }}>
          <VersionsTable versions={versions} />
        </div>
      </Card>
    </div>
  );
}
