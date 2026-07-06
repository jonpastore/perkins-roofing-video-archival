import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, inputStyle, Loading, ErrorMsg } from "../ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SettingEntry {
  key: string;
  label: string;
  value: string;
  editable: boolean;
  source: "db" | "env";
  updated_at: string | null;
  updated_by: string | null;
}

interface KnownModels {
  llm: string[];
  embed: string[];
}

interface ConfigData {
  settings: SettingEntry[];
  known_models: KnownModels | null;
  default_admins: string[] | null;
  default_admins_note: string | null;
}

interface SecretMeta {
  key: string;
  last_set: string | null;
  last_set_by: string | null;
  ui_updated_at: string | null;
  provisioned: boolean;
}

interface SecretsData {
  secrets: SecretMeta[] | null;
}

interface HealthResult {
  name: string;
  ok: boolean;
  detail: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

const MODEL_KEYS = new Set(["EMBED_MODEL", "LLM_MODEL"]);
const OTHER_SENTINEL = "__other__";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 15, fontWeight: 700 }}>
      {children}
    </h3>
  );
}

function FieldMeta({ entry }: { entry: SettingEntry }) {
  return (
    <span style={{ fontSize: 11, color: BRAND.sub, marginLeft: 8 }}>
      <Badge tone={entry.source === "db" ? "blue" : "gray"}>{entry.source}</Badge>
      {entry.updated_by && (
        <span style={{ marginLeft: 6 }}>
          by {entry.updated_by} · {fmtDate(entry.updated_at)}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ModelField — dropdown + "other…" text override
// ---------------------------------------------------------------------------

function ModelField({
  settingKey,
  entry,
  knownOptions,
  onSave,
  saving,
}: {
  settingKey: string;
  entry: SettingEntry;
  knownOptions: string[];
  onSave: (key: string, value: string) => Promise<void>;
  saving: boolean;
}) {
  const isKnown = knownOptions.includes(entry.value);
  const [selected, setSelected] = useState(isKnown ? entry.value : OTHER_SENTINEL);
  const [otherVal, setOtherVal] = useState(isKnown ? "" : entry.value);
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    const value = selected === OTHER_SENTINEL ? otherVal.trim() : selected;
    if (!value) { setErr("Value required."); return; }
    setPending(true); setErr(null); setOk(false);
    try {
      await onSave(settingKey, value);
      setOk(true);
      setTimeout(() => setOk(false), 3000);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <select
        value={selected}
        onChange={(e) => { setSelected(e.target.value); setOk(false); setErr(null); }}
        style={{ ...inputStyle, minWidth: 220 }}
      >
        {knownOptions.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
        <option value={OTHER_SENTINEL}>other…</option>
      </select>
      {selected === OTHER_SENTINEL && (
        <input
          value={otherVal}
          onChange={(e) => setOtherVal(e.target.value)}
          placeholder="model name"
          style={{ ...inputStyle, minWidth: 200 }}
        />
      )}
      <Button
        onClick={save}
        disabled={pending || saving}
        style={{ padding: "9px 16px", fontSize: 13 }}
      >
        {pending ? "Saving…" : "Save"}
      </Button>
      {ok && <span style={{ fontSize: 12, color: "#1a7f4b" }}>Saved</span>}
      {err && <span style={{ fontSize: 12, color: BRAND.red }}>{err}</span>}
      <span style={{ fontSize: 11, color: BRAND.sub }}>
        Current: <code style={{ background: BRAND.bg, padding: "1px 5px", borderRadius: 4 }}>{entry.value}</code>
        <FieldMeta entry={entry} />
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InlineEditField — plain text edit for non-model keys
// ---------------------------------------------------------------------------

function InlineEditField({
  entry,
  onSave,
  saving,
}: {
  entry: SettingEntry;
  onSave: (key: string, value: string) => Promise<void>;
  saving: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(entry.value);
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Sync if parent data refreshes
  useEffect(() => { if (!editing) setVal(entry.value); }, [entry.value, editing]);

  async function save() {
    setPending(true); setErr(null); setOk(false);
    try {
      await onSave(entry.key, val);
      setOk(true);
      setEditing(false);
      setTimeout(() => setOk(false), 3000);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <code style={{ background: BRAND.bg, padding: "3px 8px", borderRadius: 6, fontSize: 13 }}>
          {entry.value || <em style={{ color: BRAND.sub }}>empty</em>}
        </code>
        <FieldMeta entry={entry} />
        {ok && <span style={{ fontSize: 12, color: "#1a7f4b" }}>Saved</span>}
        <Button
          variant="ghost"
          style={{ padding: "4px 12px", fontSize: 12 }}
          onClick={() => { setEditing(true); setOk(false); }}
        >
          Edit
        </Button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <input
        value={val}
        onChange={(e) => setVal(e.target.value)}
        style={{ ...inputStyle, minWidth: 260 }}
        autoFocus
      />
      <Button
        onClick={save}
        disabled={pending || saving}
        style={{ padding: "9px 14px", fontSize: 13 }}
      >
        {pending ? "Saving…" : "Save"}
      </Button>
      <Button
        variant="ghost"
        onClick={() => { setEditing(false); setVal(entry.value); setErr(null); }}
        style={{ padding: "9px 14px", fontSize: 13 }}
      >
        Cancel
      </Button>
      {err && <span style={{ fontSize: 12, color: BRAND.red }}>{err}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SecretRow — write-only update field; never shows current value
// ---------------------------------------------------------------------------

function SecretRow({
  meta,
  onSave,
}: {
  meta: SecretMeta;
  onSave: (key: string, value: string) => Promise<{ last_set: string | null; last_set_by: string | null }>;
}) {
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState("");
  const [pending, setPending] = useState(false);
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [localMeta, setLocalMeta] = useState(meta);

  async function save() {
    if (!val.trim()) { setErr("Value required."); return; }
    setPending(true); setErr(null);
    try {
      const updated = await onSave(meta.key, val.trim());
      setLocalMeta((m) => ({ ...m, last_set: updated.last_set, last_set_by: updated.last_set_by }));
      setVal("");
      setOpen(false);
      setOk(true);
      setTimeout(() => setOk(false), 4000);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  const notProvisioned = !localMeta.provisioned;

  return (
    <tr style={{ borderBottom: `1px solid ${BRAND.border}`, opacity: notProvisioned ? 0.6 : 1 }}>
      <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 13, color: BRAND.ink, fontWeight: 500 }}>
        {meta.key}
        {notProvisioned && (
          <span style={{ marginLeft: 8, fontSize: 11, color: BRAND.sub, fontFamily: "system-ui", fontWeight: 400 }}>
            (not provisioned)
          </span>
        )}
      </td>
      <td style={{ padding: "10px 12px", fontSize: 13, color: BRAND.sub }}>
        {notProvisioned
          ? <em style={{ color: BRAND.sub }}>not set</em>
          : localMeta.last_set
            ? fmtDate(localMeta.last_set)
            : <em>never set via UI</em>
        }
      </td>
      <td style={{ padding: "10px 12px", fontSize: 13, color: BRAND.sub }}>
        {localMeta.last_set_by || <em>—</em>}
      </td>
      <td style={{ padding: "10px 12px", minWidth: 260 }}>
        {ok && !open && (
          <span style={{ fontSize: 12, color: "#1a7f4b", marginRight: 8 }}>Updated</span>
        )}
        {!open ? (
          <Button
            variant="ghost"
            style={{ padding: "4px 12px", fontSize: 12 }}
            onClick={() => { setOpen(true); setOk(false); }}
          >
            {notProvisioned ? "Set key" : "Update key"}
          </Button>
        ) : (
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="password"
              value={val}
              onChange={(e) => setVal(e.target.value)}
              placeholder="new value (write-only)"
              style={{ ...inputStyle, minWidth: 200 }}
              autoFocus
            />
            <Button
              onClick={save}
              disabled={pending}
              style={{ padding: "9px 13px", fontSize: 13 }}
            >
              {pending ? "Saving…" : "Set"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => { setOpen(false); setVal(""); setErr(null); }}
              style={{ padding: "9px 13px", fontSize: 13 }}
            >
              Cancel
            </Button>
            {err && <span style={{ fontSize: 12, color: BRAND.red }}>{err}</span>}
          </div>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main Settings page
// ---------------------------------------------------------------------------

export function Settings() {
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [secrets, setSecrets] = useState<SecretsData | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [loadingSecrets, setLoadingSecrets] = useState(true);
  const [configErr, setConfigErr] = useState<string | null>(null);
  const [secretsErr, setSecretsErr] = useState<string | null>(null);
  const [globalSaving, setGlobalSaving] = useState(false);

  // Health checks state
  const [healthResults, setHealthResults] = useState<HealthResult[] | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthErr, setHealthErr] = useState<string | null>(null);

  function loadConfig() {
    setLoadingConfig(true);
    setConfigErr(null);
    apiFetch("/config")
      .then((r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); })
      .then((d: ConfigData) => setConfig(d))
      .catch((e: unknown) => setConfigErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingConfig(false));
  }

  function loadSecrets() {
    setLoadingSecrets(true);
    setSecretsErr(null);
    apiFetch("/config/secrets")
      .then((r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); })
      .then((d: SecretsData) => setSecrets(d))
      .catch((e: unknown) => setSecretsErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingSecrets(false));
  }

  function runHealthChecks() {
    setHealthLoading(true);
    setHealthErr(null);
    apiFetch("/config/health-checks")
      .then((r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); })
      .then((d: { results: HealthResult[] }) => setHealthResults(d.results ?? []))
      .catch((e: unknown) => setHealthErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setHealthLoading(false));
  }

  useEffect(() => {
    loadConfig();
    loadSecrets();
  }, []);

  async function saveSetting(key: string, value: string) {
    setGlobalSaving(true);
    try {
      const r = await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ key, value }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string })?.detail ?? `${r.status} ${r.statusText}`);
      }
      // Refresh config data to reflect updated source/updated_by
      loadConfig();
    } finally {
      setGlobalSaving(false);
    }
  }

  async function saveSecret(key: string, value: string) {
    const r = await apiFetch("/config/secrets", {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error((body as { detail?: string })?.detail ?? `${r.status} ${r.statusText}`);
    }
    return r.json() as Promise<{ last_set: string | null; last_set_by: string | null }>;
  }

  // Split settings into model vs regular — defensive: treat missing arrays as empty
  const modelEntries = (config?.settings ?? []).filter((s) => MODEL_KEYS.has(s.key));
  const regularEntries = (config?.settings ?? []).filter((s) => !MODEL_KEYS.has(s.key));

  // Defensive: known_models may be absent from API response
  const knownLlm: string[] = config?.known_models?.llm ?? [];
  const knownEmbed: string[] = config?.known_models?.embed ?? [];

  // Defensive: secrets.secrets may be null if API response is malformed
  const secretsList: SecretMeta[] = secrets?.secrets ?? [];

  return (
    <main style={{ maxWidth: 960 }}>
      <PageTitle>Platform Settings</PageTitle>

      {/* ------------------------------------------------------------------ */}
      {/* Section 1: Editable settings                                        */}
      {/* ------------------------------------------------------------------ */}
      <Card style={{ marginBottom: 24 }}>
        <SectionTitle>Editable Settings</SectionTitle>
        {loadingConfig && <Loading />}
        {configErr && <ErrorMsg>Error loading settings: {configErr}</ErrorMsg>}
        {!loadingConfig && !configErr && config && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "28%" }}>Key</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Value</th>
              </tr>
            </thead>
            <tbody>
              {regularEntries.map((entry) => (
                <tr key={entry.key} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 12px", verticalAlign: "top" }}>
                    <div style={{ fontFamily: "monospace", fontWeight: 600, color: BRAND.ink, fontSize: 13 }}>
                      {entry.key}
                    </div>
                    <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 2 }}>{entry.label}</div>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <InlineEditField entry={entry} onSave={saveSetting} saving={globalSaving} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Section 2: Model dropdowns                                          */}
      {/* ------------------------------------------------------------------ */}
      <Card style={{ marginBottom: 24 }}>
        <SectionTitle>Model Selection</SectionTitle>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: BRAND.sub }}>
          Changes are persisted immediately but take effect on the next service restart
          (the running process reads env at boot).
        </p>
        {loadingConfig && <Loading />}
        {!loadingConfig && !configErr && config && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "22%" }}>Model</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Selection</th>
              </tr>
            </thead>
            <tbody>
              {modelEntries.map((entry) => (
                <tr key={entry.key} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 12px", verticalAlign: "middle" }}>
                    <div style={{ fontFamily: "monospace", fontWeight: 600, color: BRAND.ink, fontSize: 13 }}>
                      {entry.key}
                    </div>
                    <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 2 }}>{entry.label}</div>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <ModelField
                      settingKey={entry.key}
                      entry={entry}
                      knownOptions={entry.key === "LLM_MODEL" ? knownLlm : knownEmbed}
                      onSave={saveSetting}
                      saving={globalSaving}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Section 3: Secrets                                                  */}
      {/* ------------------------------------------------------------------ */}
      <Card style={{ marginBottom: 24, borderTop: `4px solid ${BRAND.navy}` }}>
        <SectionTitle>Secret Manager Keys</SectionTitle>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: BRAND.sub }}>
          Secret values are write-only — they are stored in GCP Secret Manager and never
          returned by this UI. Only metadata (last set time and who) is shown.
          Use "Update key" to add a new secret version. Dimmed rows are not yet provisioned
          (social/IG/TikTok — pending API review).
        </p>
        {loadingSecrets && <Loading />}
        {secretsErr && <ErrorMsg>Error loading secrets: {secretsErr}</ErrorMsg>}
        {!loadingSecrets && !secretsErr && secrets && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "24%" }}>Secret ID</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "20%" }}>Last Set (GCP)</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "16%" }}>Set By</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {secretsList.map((s) => (
                <SecretRow key={s.key} meta={s} onSave={saveSecret} />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Section 4: Connectivity checks                                      */}
      {/* ------------------------------------------------------------------ */}
      <Card style={{ marginBottom: 24, borderTop: `4px solid ${BRAND.navyText}` }}>
        <SectionTitle>Connectivity Tests</SectionTitle>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: BRAND.sub }}>
          Run live checks against each configured integration. Results are not cached —
          each click makes real outbound requests.
        </p>
        <Button
          onClick={runHealthChecks}
          disabled={healthLoading}
          style={{ padding: "9px 20px", fontSize: 14, marginBottom: 16 }}
        >
          {healthLoading ? "Running checks…" : "Test connections"}
        </Button>
        {healthErr && <ErrorMsg>Check failed: {healthErr}</ErrorMsg>}
        {healthResults && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "26%" }}>Integration</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "14%" }}>Status</th>
                <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {healthResults.map((r) => (
                <tr key={r.name} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 12px", fontWeight: 500, color: BRAND.ink }}>{r.name}</td>
                  <td style={{ padding: "10px 12px" }}>
                    <Badge tone={r.ok ? "green" : "amber"}>{r.ok ? "pass" : "fail"}</Badge>
                  </td>
                  <td style={{ padding: "10px 12px", fontSize: 12, color: BRAND.sub, fontFamily: "monospace" }}>
                    {r.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Section 5: Admin / role management note                             */}
      {/* ------------------------------------------------------------------ */}
      <Card style={{ borderTop: `4px solid ${BRAND.red}` }}>
        <SectionTitle>Admin Access</SectionTitle>
        {loadingConfig && <Loading />}
        {!loadingConfig && configErr && (
          <ErrorMsg>Could not load admin config: {configErr}</ErrorMsg>
        )}
        {!loadingConfig && !configErr && config && (
          <>
            <p style={{ margin: "0 0 12px", fontSize: 13, color: BRAND.sub }}>
              {config.default_admins_note ?? ""}
            </p>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
                Default admins (env config allowlist)
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {(config.default_admins ?? []).map((email) => (
                  <span
                    key={email}
                    style={{
                      background: BRAND.bg,
                      border: `1px solid ${BRAND.border}`,
                      borderRadius: 20,
                      padding: "3px 12px",
                      fontSize: 13,
                      color: BRAND.ink,
                      fontFamily: "monospace",
                    }}
                  >
                    {email}
                  </span>
                ))}
              </div>
            </div>
            <a
              href="/users"
              style={{
                display: "inline-block",
                padding: "9px 18px",
                background: BRAND.navy,
                color: "#fff",
                borderRadius: 8,
                fontSize: 14,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Manage user roles on the Users page
            </a>
          </>
        )}
      </Card>
    </main>
  );
}
