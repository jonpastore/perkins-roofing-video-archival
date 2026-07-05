import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

interface EmailTemplate {
  id: number;
  name: string;
  subject: string;
  body: string;
  created_by: string;
}

interface FormState {
  name: string;
  subject: string;
  body: string;
}

const emptyForm: FormState = { name: "", subject: "", body: "" };

export function Templates() {
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null); // null = new
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch("/email/templates")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setTemplates)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setEditingId(null);
    setForm(emptyForm);
    setSaveError(null);
    setShowForm(true);
  }

  function openEdit(t: EmailTemplate) {
    setEditingId(t.id);
    setForm({ name: t.name, subject: t.subject, body: t.body });
    setSaveError(null);
    setShowForm(true);
  }

  function cancelForm() {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
    setSaveError(null);
  }

  async function handleSave() {
    if (!form.name.trim() || !form.subject.trim() || !form.body.trim()) {
      setSaveError("Name, subject, and body are required.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const r = await apiFetch(
        editingId == null ? "/email/templates" : `/email/templates/${editingId}`,
        {
          method: editingId == null ? "POST" : "PUT",
          body: JSON.stringify({ name: form.name, subject: form.subject, body: form.body }),
        }
      );
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      cancelForm();
      load();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(t: EmailTemplate) {
    if (!confirm(`Delete template "${t.name}"? This cannot be undone.`)) return;
    setDeletingId(t.id);
    try {
      const r = await apiFetch(`/email/templates/${t.id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      load();
    } catch (e: unknown) {
      alert(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle
        right={
          !showForm && (
            <Button onClick={openNew}>+ New Template</Button>
          )
        }
      >
        Email Templates
      </PageTitle>

      {/* Inline form */}
      {showForm && (
        <Card style={{ marginBottom: 24, borderTop: `4px solid ${BRAND.red}` }}>
          <h3 style={{ margin: "0 0 16px", color: BRAND.navyText, fontSize: 16 }}>
            {editingId == null ? "New Template" : "Edit Template"}
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                Name
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Welcome email"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                Subject
              </label>
              <input
                value={form.subject}
                onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
                placeholder="Email subject line"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                Body
              </label>
              <textarea
                value={form.body}
                onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
                placeholder="Email body text…"
                rows={8}
                style={{ ...inputStyle, width: "100%", resize: "vertical", fontFamily: "inherit" }}
              />
            </div>
            {saveError && <ErrorMsg>{saveError}</ErrorMsg>}
            <div style={{ display: "flex", gap: 10 }}>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "Saving…" : editingId == null ? "Create" : "Save Changes"}
              </Button>
              <Button variant="ghost" onClick={cancelForm} disabled={saving}>
                Cancel
              </Button>
            </div>
          </div>
        </Card>
      )}

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && (
        <>
          {templates.length === 0 ? (
            <Card>
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
                No templates yet. Click "New Template" to create one.
              </p>
            </Card>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Name</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Subject</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Created by</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.id} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 12px", fontWeight: 500, color: BRAND.ink }}>{t.name}</td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub }}>{t.subject}</td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub }}>{t.created_by}</td>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", gap: 8 }}>
                        <Button
                          variant="ghost"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          onClick={() => openEdit(t)}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="danger"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          disabled={deletingId === t.id}
                          onClick={() => handleDelete(t)}
                        >
                          {deletingId === t.id ? "Deleting…" : "Delete"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </main>
  );
}
