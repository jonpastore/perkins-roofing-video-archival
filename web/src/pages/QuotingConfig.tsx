import { useEffect, useState, useCallback } from "react";
import { BRAND, FONT, Card, Button, Loading, ErrorMsg, Badge, inputStyle } from "../ui";
import {
  getQuotingSettings,
  putQuotingSettings,
  listProposalTemplates,
  createProposalTemplate,
  updateProposalTemplate,
  deleteProposalTemplate,
  type QuotingSettings,
  type ProposalTemplate,
} from "../api";
import { ContractFaq } from "./ContractFaq";

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

function canManage(role: Role): boolean {
  return role === "admin" || role === "web_admin" || role === "platform_admin";
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: BRAND.sub, marginBottom: 3, textTransform: "uppercase", letterSpacing: 0.3 }}>
      {children}
    </label>
  );
}

function HelpText({ children }: { children: React.ReactNode }) {
  return <p style={{ margin: "3px 0 0", fontSize: 11, color: BRAND.sub, lineHeight: 1.4 }}>{children}</p>;
}

// Editable list of reminder day-offsets (e.g. 3, 7, 14 days after send).
function CadenceEditor({ days, onChange, disabled }: { days: number[]; onChange: (d: number[]) => void; disabled: boolean }) {
  const [val, setVal] = useState("");
  function add() {
    const n = parseInt(val, 10);
    if (!Number.isFinite(n) || n < 1 || days.includes(n)) return;
    onChange([...days, n].sort((a, b) => a - b));
    setVal("");
  }
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
        {days.length === 0 && <span style={{ fontSize: 13, color: BRAND.sub }}>No reminders scheduled.</span>}
        {days.map((d) => (
          <span key={d} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 16, background: BRAND.bg, border: `1px solid ${BRAND.border}`, fontSize: 13, color: BRAND.ink }}>
            Day {d}
            {!disabled && (
              <button onClick={() => onChange(days.filter((x) => x !== d))} title="Remove" style={{ background: "none", border: "none", cursor: "pointer", color: BRAND.red, fontSize: 15, lineHeight: 1, padding: 0 }}>
                &times;
              </button>
            )}
          </span>
        ))}
      </div>
      {!disabled && (
        <div style={{ display: "flex", gap: 8 }}>
          <input type="number" min={1} max={365} value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Days after send…" style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: 160 }} />
          <Button variant="ghost" style={{ fontSize: 13, padding: "7px 14px" }} onClick={add} disabled={!val.trim()}>
            Add reminder
          </Button>
        </div>
      )}
    </div>
  );
}

// Inline template editor row — collapsed to name+default, expands to edit fields.
function TemplateRow({ tpl, manage, onSaved, onDeleted }: { tpl: ProposalTemplate; manage: boolean; onSaved: (t: ProposalTemplate) => void; onDeleted: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(tpl);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => setDraft(tpl), [tpl]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(tpl);

  async function save() {
    setBusy(true); setErr(null);
    try {
      const saved = await updateProposalTemplate(tpl.id, {
        name: draft.name, is_default: draft.is_default, html_body: draft.html_body,
        cover_page_html: draft.cover_page_html, footer_text: draft.footer_text,
        primary_color: draft.primary_color, accent_color: draft.accent_color, logo_url: draft.logo_url,
      });
      onSaved(saved);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(`Delete template "${tpl.name}"?`)) return;
    setBusy(true); setErr(null);
    try { await deleteProposalTemplate(tpl.id); onDeleted(tpl.id); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  }

  return (
    <div style={{ border: `1px solid ${BRAND.border}`, borderRadius: 8, marginBottom: 8, background: "#fff" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>{tpl.name}</span>
        {tpl.is_default && <Badge tone="green">Default</Badge>}
        <span style={{ color: BRAND.sub, fontSize: 12 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 14px 14px" }}>
          <FieldLabel>Name</FieldLabel>
          <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} disabled={!manage} style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", marginBottom: 10 }} />

          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: BRAND.ink, marginBottom: 10 }}>
            <input type="checkbox" checked={draft.is_default} onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })} disabled={!manage} />
            Use as default template for new proposals
          </label>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 10 }}>
            <div>
              <FieldLabel>Primary color</FieldLabel>
              <input value={draft.primary_color ?? ""} onChange={(e) => setDraft({ ...draft, primary_color: e.target.value })} disabled={!manage} placeholder="#1a3c5e" style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", fontFamily: "monospace" }} />
            </div>
            <div>
              <FieldLabel>Accent color</FieldLabel>
              <input value={draft.accent_color ?? ""} onChange={(e) => setDraft({ ...draft, accent_color: e.target.value })} disabled={!manage} placeholder="#f4a226" style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", fontFamily: "monospace" }} />
            </div>
          </div>

          <FieldLabel>Footer text</FieldLabel>
          <input value={draft.footer_text ?? ""} onChange={(e) => setDraft({ ...draft, footer_text: e.target.value })} disabled={!manage} style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", marginBottom: 10 }} />

          <FieldLabel>HTML body</FieldLabel>
          <textarea value={draft.html_body} onChange={(e) => setDraft({ ...draft, html_body: e.target.value })} disabled={!manage} rows={10} style={{ ...inputStyle, padding: "8px 10px", fontSize: 12, width: "100%", fontFamily: "monospace", lineHeight: 1.4, resize: "vertical" }} />
          <HelpText>Jinja-style placeholders (e.g. &#123;&#123; customer_name &#125;&#125;, &#123;&#123; quote_line_items &#125;&#125;) are filled at render time. Leave a template as-is to use the built-in default.</HelpText>

          {err && <ErrorMsg>{err}</ErrorMsg>}
          {manage && (
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button style={{ fontSize: 13 }} onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : "Save"}</Button>
              <Button variant="ghost" style={{ fontSize: 13, color: BRAND.red }} onClick={del} disabled={busy}>Delete</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface QuotingConfigProps {
  role: Role;
}

const STARTER_HTML = "<h1>{{ proposal_title }}</h1>\n<p>Prepared for {{ customer_name }} — {{ property_address }}</p>\n{{ quote_line_items }}";

export function QuotingConfig({ role }: QuotingConfigProps) {
  const manage = canManage(role);

  const [settings, setSettings] = useState<QuotingSettings | null>(null);
  const [draft, setDraft] = useState<QuotingSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [templates, setTemplates] = useState<ProposalTemplate[]>([]);
  const [tplError, setTplError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const dirty = !!settings && JSON.stringify(settings) !== JSON.stringify(draft);

  const load = useCallback(() => {
    setLoading(true); setLoadError(null);
    Promise.all([getQuotingSettings(), listProposalTemplates()])
      .then(([s, t]) => {
        setSettings(s);
        setDraft(JSON.parse(JSON.stringify(s)));
        setTemplates(t);
        setSaveSuccess(false);
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  function update<K extends keyof QuotingSettings>(key: K, value: QuotingSettings[K]) {
    setDraft((p) => (p ? { ...p, [key]: value } : p));
    setSaveSuccess(false);
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true); setSaveError(null); setSaveSuccess(false);
    try {
      await putQuotingSettings(draft);
      setSettings(JSON.parse(JSON.stringify(draft)));
      setSaveSuccess(true);
    } catch (e) { setSaveError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  }

  async function handleCreateTemplate() {
    setCreating(true); setTplError(null);
    try {
      const created = await createProposalTemplate({
        name: `New template ${templates.length + 1}`,
        html_body: STARTER_HTML,
        is_default: templates.length === 0,
      });
      setTemplates((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) { setTplError(e instanceof Error ? e.message : String(e)); }
    finally { setCreating(false); }
  }

  if (loading) return <Card style={{ marginTop: 8 }}><Loading label="Loading quoting settings…" /></Card>;
  if (loadError) {
    return (
      <Card style={{ marginTop: 8 }}>
        <ErrorMsg>Failed to load: {loadError}</ErrorMsg>
        <Button variant="ghost" style={{ fontSize: 13, marginTop: 8 }} onClick={load}>Retry</Button>
      </Card>
    );
  }
  if (!draft) return null;

  const deposit = draft.deposit ?? {};

  return (
    <div style={{ fontFamily: FONT }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText }}>Quoting Config</span>
          {dirty && <Badge tone="amber">Unsaved changes</Badge>}
          {!manage && <Badge tone="gray">Read-only</Badge>}
        </div>
        {manage && (
          <Button style={{ fontSize: 13 }} onClick={handleSave} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        )}
      </div>

      {saveError && <ErrorMsg>Save error: {saveError}</ErrorMsg>}
      {saveSuccess && (
        <div style={{ fontSize: 13, color: "#1a7f4b", background: "#e6f9f0", padding: "8px 12px", borderRadius: 6, marginBottom: 12 }}>
          Settings saved.
        </div>
      )}

      {/* Deposit policy */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>Deposit Policy</div>
        <HelpText>Applied to new proposals as the default deposit requirement. Sales can still override per-proposal.</HelpText>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 14 }}>
          <div>
            <FieldLabel>Mode</FieldLabel>
            <select value={deposit.mode ?? "percent"} onChange={(e) => update("deposit", { ...deposit, mode: e.target.value as "percent" | "fixed" })} disabled={!manage} style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", background: !manage ? BRAND.bg : "#fff" }}>
              <option value="percent">Percent of total</option>
              <option value="fixed">Fixed dollar amount</option>
            </select>
          </div>
          <div>
            <FieldLabel>{deposit.mode === "fixed" ? "Amount ($)" : "Percent (%)"}</FieldLabel>
            <input type="number" min={0} step={deposit.mode === "fixed" ? 50 : 1} value={deposit.value ?? ""} onChange={(e) => update("deposit", { ...deposit, value: parseFloat(e.target.value) || 0 })} disabled={!manage} style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", background: !manage ? BRAND.bg : "#fff" }} />
          </div>
        </div>
      </Card>

      {/* Reminder cadence */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>Follow-up Reminders</div>
        <HelpText>Days after a proposal is sent to remind the customer if it hasn't been accepted.</HelpText>
        <div style={{ marginTop: 14 }}>
          <CadenceEditor days={draft.reminder_cadence_days ?? []} onChange={(d) => update("reminder_cadence_days", d)} disabled={!manage} />
        </div>
      </Card>

      {/* License number */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>Contractor License</div>
        <HelpText>Florida license number printed on proposals and contracts.</HelpText>
        <div style={{ marginTop: 14, maxWidth: 320 }}>
          <input value={draft.license_number ?? ""} onChange={(e) => update("license_number", e.target.value)} disabled={!manage} placeholder="CCC1234567" style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", fontFamily: "monospace" }} />
        </div>
      </Card>

      {/* Proposal templates */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 2 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText }}>Proposal Templates</div>
          {manage && (
            <Button variant="ghost" style={{ fontSize: 13 }} onClick={handleCreateTemplate} disabled={creating}>
              {creating ? "Creating…" : "+ New template"}
            </Button>
          )}
        </div>
        <HelpText>Branded HTML shells for rendered proposal PDFs. The default is used when a proposal doesn't pick one.</HelpText>
        <div style={{ marginTop: 14 }}>
          {templates.length === 0 ? (
            <div style={{ padding: "16px 14px", fontSize: 13, color: BRAND.sub, border: `1px dashed ${BRAND.border}`, borderRadius: 8 }}>
              No custom templates — proposals render with the built-in default.
            </div>
          ) : (
            templates.map((t) => (
              <TemplateRow
                key={t.id}
                tpl={t}
                manage={manage}
                onSaved={(saved) => setTemplates((prev) => prev.map((x) => (x.id === saved.id ? saved : x)).sort((a, b) => a.name.localeCompare(b.name)))}
                onDeleted={(id) => setTemplates((prev) => prev.filter((x) => x.id !== id))}
              />
            ))
          )}
          {tplError && <ErrorMsg>{tplError}</ErrorMsg>}
        </div>
      </Card>

      {/* T&C library (reuses the Contract FAQ / T&C management surface) */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>Terms &amp; Conditions Library</div>
        <HelpText>Versioned T&amp;C text, approved FAQ, and AI-review prompts that flow into every generated proposal.</HelpText>
        <div style={{ marginTop: 12 }}>
          <ContractFaq />
        </div>
      </Card>
    </div>
  );
}
