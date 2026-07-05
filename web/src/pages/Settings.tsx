import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

interface ConfigData {
  settings: Record<string, string>;
  runtime: Record<string, string | string[]>;
}

export function Settings() {
  const [data, setData] = useState<ConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editKey, setEditKey] = useState("");
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch("/config")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: ConfigData) => setData(d))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave() {
    if (!editKey.trim()) {
      setSaveError("Key is required.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveOk(null);
    try {
      const r = await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ key: editKey.trim(), value: editValue }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setSaveOk(`Saved "${editKey.trim()}".`);
      setEditKey("");
      setEditValue("");
      load();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function renderRuntimeValue(v: string | string[]): string {
    if (Array.isArray(v)) return v.join(", ");
    return String(v);
  }

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>Platform Settings</PageTitle>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && data && (
        <>
          {/* Read-only runtime info */}
          <Card style={{ marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 15 }}>
              Runtime Info (read-only)
            </h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "35%" }}>Key</th>
                  <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Value</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.runtime).map(([k, v]) => (
                  <tr key={k} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "8px 12px", fontWeight: 500, color: BRAND.ink, fontFamily: "monospace" }}>{k}</td>
                    <td style={{ padding: "8px 12px", color: BRAND.sub }}>{renderRuntimeValue(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* Editable settings */}
          <Card style={{ marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 15 }}>
              Editable Settings
            </h3>
            {Object.keys(data.settings).length === 0 ? (
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0 }}>
                No settings configured yet. Use the form below to add one.
              </p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, marginBottom: 0 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: "35%" }}>Key</th>
                    <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600 }}>Value</th>
                    <th style={{ padding: "6px 12px", color: BRAND.sub, fontWeight: 600, width: 80 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.settings).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                      <td style={{ padding: "8px 12px", fontWeight: 500, color: BRAND.ink, fontFamily: "monospace" }}>{k}</td>
                      <td style={{ padding: "8px 12px", color: BRAND.sub }}>{v}</td>
                      <td style={{ padding: "8px 12px" }}>
                        <Button
                          variant="ghost"
                          style={{ padding: "4px 12px", fontSize: 12 }}
                          onClick={() => { setEditKey(k); setEditValue(v); setSaveError(null); setSaveOk(null); }}
                        >
                          Edit
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {/* Add / edit form */}
          <Card style={{ borderTop: `4px solid ${BRAND.red}` }}>
            <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 15 }}>
              {editKey && data.settings[editKey] !== undefined ? `Edit "${editKey}"` : "Add / Update Setting"}
            </h3>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div style={{ flex: "1 1 200px" }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                  Key
                </label>
                <input
                  value={editKey}
                  onChange={(e) => setEditKey(e.target.value)}
                  placeholder="e.g. wp_url"
                  style={{ ...inputStyle, width: "100%" }}
                />
              </div>
              <div style={{ flex: "2 1 300px" }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                  Value
                </label>
                <input
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder="value"
                  style={{ ...inputStyle, width: "100%" }}
                />
              </div>
              <Button onClick={handleSave} disabled={saving} style={{ alignSelf: "flex-end", marginBottom: 1 }}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
            {saveError && <ErrorMsg>{saveError}</ErrorMsg>}
            {saveOk && <p style={{ color: "#1a7f4b", fontSize: 13, margin: "8px 0 0" }}>{saveOk}</p>}
          </Card>
        </>
      )}
    </main>
  );
}
