import { useCallback, useEffect, useState } from "react";
import { BRAND, FONT, Card, Button, Loading, ErrorMsg, Badge, inputStyle } from "../ui";
import {
  listBranches, createBranch, updateBranch, type BranchRow,
  getActivePricingConfig, createPricingConfig, activatePricingConfig,
} from "../api";

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

function canManage(role: Role): boolean {
  // Must match backend authz: branch writes require `manage_config`, which is admin-only
  // (core/authz.py). Widening this to web_admin/platform_admin only shows buttons that 403.
  return role === "admin";
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: BRAND.sub, marginBottom: 3, textTransform: "uppercase", letterSpacing: 0.3 }}>
      {children}
    </label>
  );
}

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function NewBranchForm({ onSaved, onCancel }: { onSaved: (b: BranchRow) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [sort, setSort] = useState(0);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function handleNameChange(val: string) {
    setName(val);
    if (!key || key === slugify(name)) setKey(slugify(val));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !key.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      const b = await createBranch({ key: key.trim(), name: name.trim(), sort });
      onSaved(b);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card style={{ marginTop: 16 }}>
      <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 14, marginBottom: 12 }}>New Branch</div>
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 100px", gap: 12 }}>
          <div>
            <FieldLabel>Name</FieldLabel>
            <input value={name} onChange={(e) => handleNameChange(e.target.value)} placeholder="e.g. West Palm" required disabled={saving} style={{ ...inputStyle, width: "100%", fontSize: 13 }} autoFocus />
          </div>
          <div>
            <FieldLabel>Key (slug)</FieldLabel>
            <input
              value={key}
              onChange={(e) => setKey(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              placeholder="west-palm"
              required
              pattern="^[a-z0-9_-]+$"
              disabled={saving}
              style={{ ...inputStyle, width: "100%", fontSize: 13, fontFamily: "monospace" }}
            />
          </div>
          <div>
            <FieldLabel>Sort</FieldLabel>
            <input type="number" value={sort} onChange={(e) => setSort(Number(e.target.value) || 0)} disabled={saving} style={{ ...inputStyle, width: "100%", fontSize: 13 }} />
          </div>
        </div>
        {err && <ErrorMsg>{err}</ErrorMsg>}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 14 }}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>Cancel</Button>
          <Button type="submit" disabled={saving || !name.trim() || !key.trim()}>{saving ? "Saving…" : "Create branch"}</Button>
        </div>
      </form>
    </Card>
  );
}

function BranchRowView({ branch, onSaved, manage }: { branch: BranchRow; onSaved: (b: BranchRow) => void; manage: boolean }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(branch.name);
  const [sort, setSort] = useState(branch.sort);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function saveRename() {
    setBusy(true);
    setErr(null);
    try {
      const b = await updateBranch(branch.id, { name: name.trim(), sort });
      onSaved(b);
      setEditing(false);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive() {
    setBusy(true);
    setErr(null);
    try {
      const b = await updateBranch(branch.id, { active: !branch.active });
      onSaved(b);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 140px 90px 200px",
        alignItems: "center",
        gap: 12,
        padding: "10px 16px",
        borderBottom: `1px solid ${BRAND.border}`,
        background: branch.active ? "#fff" : BRAND.bg,
        opacity: branch.active ? 1 : 0.6,
      }}
    >
      {editing ? (
        <input value={name} onChange={(e) => setName(e.target.value)} disabled={busy} style={{ ...inputStyle, fontSize: 13, width: "100%" }} autoFocus />
      ) : (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>{branch.name}</div>
          <div style={{ fontSize: 11, color: BRAND.sub, fontFamily: "monospace", marginTop: 1 }}>{branch.key}</div>
        </div>
      )}

      <div>{branch.active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Inactive</Badge>}</div>

      {editing ? (
        <input type="number" value={sort} onChange={(e) => setSort(Number(e.target.value) || 0)} disabled={busy} style={{ ...inputStyle, fontSize: 13, width: "100%" }} />
      ) : (
        <div style={{ fontSize: 12, color: BRAND.sub }}>{branch.sort}</div>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        {!manage ? null : editing ? (
          <>
            <Button variant="ghost" style={{ fontSize: 12, padding: "5px 12px" }} onClick={() => { setEditing(false); setName(branch.name); setSort(branch.sort); }} disabled={busy}>Cancel</Button>
            <Button style={{ fontSize: 12, padding: "5px 12px" }} onClick={saveRename} disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save"}</Button>
          </>
        ) : (
          <>
            <Button variant="ghost" style={{ fontSize: 12, padding: "5px 12px" }} onClick={() => setEditing(true)} disabled={busy}>Rename</Button>
            <Button variant={branch.active ? "danger" : "ghost"} style={{ fontSize: 12, padding: "5px 12px" }} onClick={toggleActive} disabled={busy}>
              {busy ? "…" : branch.active ? "Deactivate" : "Activate"}
            </Button>
          </>
        )}
      </div>
      {err && <div style={{ gridColumn: "1 / -1" }}><ErrorMsg>{err}</ErrorMsg></div>}
    </div>
  );
}

interface BranchesConfigProps {
  role: Role;
}

/** Clone one branch's ACTIVE pricing config onto another branch, as a new active version.
 *
 * A branch with no pricing config cannot be quoted at all — the estimator returns 503 "no active
 * pricing config for branch X". Perkins Construction (`gc`) has been in the branch list since
 * migration 0041 and has never had one, so it has been unquotable the whole time. Seeding it by
 * hand meant a script and a prod DB session.
 *
 * Built from the three endpoints that already exist (read active -> create version -> activate)
 * rather than a new copy endpoint: configs are immutable-versioned, so a copy IS just a create,
 * and a bespoke endpoint would be a second way to write the same row.
 */
function CopyConfigPanel({ branches, manage }: { branches: BranchRow[]; manage: boolean }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const active = branches.filter((b) => b.active);

  async function handleCopy() {
    setBusy(true); setErr(null); setDone(null);
    try {
      const src = await getActivePricingConfig(from);
      const created = await createPricingConfig({
        branch: to,
        label: `copied from ${from} v${src.version}`,
        config: src.config as Record<string, unknown>,
      });
      await activatePricingConfig(created.id);
      setDone(`${to} now runs a copy of ${from} v${src.version}, active as v${created.version}.`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!manage) return null;

  return (
    <Card style={{ marginTop: 20 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText }}>Copy pricing config</div>
      <p style={{ margin: "4px 0 12px", fontSize: 12, color: BRAND.sub }}>
        Copies a branch's <strong>active</strong> pricing config onto another branch as a new active
        version. A branch with no config cannot be quoted — the estimator refuses with 503 rather
        than guessing a price. The source is left untouched, and the target keeps its old versions,
        so this is reversible by re-activating the previous one.
      </p>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ minWidth: 180 }}>
          <FieldLabel>Copy from</FieldLabel>
          <select value={from} onChange={(e) => setFrom(e.target.value)} style={inputStyle} disabled={busy}>
            <option value="">Select a branch…</option>
            {active.map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
          </select>
        </div>
        <div style={{ minWidth: 180 }}>
          <FieldLabel>Copy to</FieldLabel>
          <select value={to} onChange={(e) => setTo(e.target.value)} style={inputStyle} disabled={busy}>
            <option value="">Select a branch…</option>
            {active.filter((b) => b.key !== from).map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
          </select>
        </div>
        <Button onClick={handleCopy} disabled={busy || !from || !to || from === to} style={{ fontSize: 13 }}>
          {busy ? "Copying…" : "Copy config"}
        </Button>
      </div>
      {err && <div style={{ marginTop: 10 }}><ErrorMsg>Copy failed: {err}</ErrorMsg></div>}
      {done && <div style={{ marginTop: 10 }}><Badge tone="green">{done}</Badge></div>}
    </Card>
  );
}

export function BranchesConfig({ role }: BranchesConfigProps) {
  const manage = canManage(role);
  const [branches, setBranches] = useState<BranchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    listBranches(true)
      .then((bs) => setBranches([...bs].sort((a, b) => a.sort - b.sort || a.key.localeCompare(b.key))))
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleRowSaved(updated: BranchRow) {
    setBranches((prev) => [...prev.map((b) => (b.id === updated.id ? updated : b))].sort((a, b) => a.sort - b.sort || a.key.localeCompare(b.key)));
  }

  return (
    <div style={{ fontFamily: FONT }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <div>
          <span style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText }}>Branches</span>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: BRAND.sub }}>
            Drives every branch selector across the app (estimating config, customers, dashboard). Keys are
            immutable once created — deactivate rather than delete to keep existing assets pointing at them.
          </p>
        </div>
        {manage && !showForm && (
          <Button onClick={() => setShowForm(true)} style={{ fontSize: 13 }}>+ New Branch</Button>
        )}
      </div>
      {!manage && <Badge tone="amber">Read-only — requires manage_config role</Badge>}

      {showForm && <NewBranchForm onSaved={(b) => { setBranches((prev) => [...prev, b].sort((a, c) => a.sort - c.sort || a.key.localeCompare(c.key))); setShowForm(false); }} onCancel={() => setShowForm(false)} />}

      <Card style={{ marginTop: 20, padding: 0, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 90px 200px", gap: 12, padding: "10px 16px", background: BRAND.bg, borderBottom: `1px solid ${BRAND.border}` }}>
          {["Branch", "Status", "Sort", "Actions"].map((h) => (
            <div key={h} style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, ...(h === "Actions" ? { textAlign: "right" } : {}) }}>{h}</div>
          ))}
        </div>

        {loading && <div style={{ padding: 24 }}><Loading label="Loading branches…" /></div>}
        {loadError && <div style={{ padding: 16 }}><ErrorMsg>Failed to load branches: {loadError}</ErrorMsg></div>}
        {!loading && !loadError && branches.length === 0 && (
          <div style={{ padding: "24px 16px", fontSize: 13, color: BRAND.sub }}>No branches yet.</div>
        )}

        {branches.map((b) => <BranchRowView key={b.id} branch={b} onSaved={handleRowSaved} manage={manage} />)}
      </Card>

      <CopyConfigPanel branches={branches} manage={manage} />
    </div>
  );
}
