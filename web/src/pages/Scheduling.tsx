import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, inputStyle, Loading, ErrorMsg } from "../ui";

interface ScheduledItem {
  id: number;
  kind: string;
  ref_id: string;
  display_name: string;
  publish_at: string;
  status: string;
  target: string | null;
}

interface FormState {
  kind: string;
  ref_id: string;
  publish_at: string;
  target: string;
}

interface ArticleOption {
  slug: string;
  title: string;
}

interface SeriesOption {
  id: number;
  title: string;
  label: string;
}

const emptyForm: FormState = {
  kind: "article",
  ref_id: "",
  publish_at: "",
  target: "wordpress",
};

const KIND_DISPLAY: Record<string, string> = {
  article: "Article",
  reel: "Social media",
};

function kindBadge(kind: string) {
  return kind === "reel" ? (
    <Badge tone="blue">Social media</Badge>
  ) : (
    <Badge tone="gray">Article</Badge>
  );
}

function statusBadge(status: string) {
  if (status === "published") return <Badge tone="green">published</Badge>;
  if (status === "error") return <Badge tone="amber">error</Badge>;
  return <Badge tone="blue">scheduled</Badge>;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function Scheduling() {
  const [items, setItems] = useState<ScheduledItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const [articles, setArticles] = useState<ArticleOption[]>([]);
  const [seriesList, setSeriesList] = useState<SeriesOption[]>([]);
  const [dropdownsLoading, setDropdownsLoading] = useState(false);

  function load(filter?: string) {
    setLoading(true);
    setError(null);
    const qs = (filter ?? statusFilter) ? `?status=${filter ?? statusFilter}` : "";
    apiFetch(`/scheduling${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  function loadDropdowns() {
    setDropdownsLoading(true);
    Promise.all([
      apiFetch("/articles").then((r) => (r.ok ? r.json() : [])),
      apiFetch("/video/series").then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([arts, series]) => {
        setArticles(arts as ArticleOption[]);
        setSeriesList(
          (series as Array<{ id: number; title: string; label: string }>).map((s) => ({
            id: s.id,
            title: s.title,
            label: s.label ?? s.title,
          }))
        );
      })
      .catch(() => {})
      .finally(() => setDropdownsLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  function handleFilterChange(v: string) {
    setStatusFilter(v);
    load(v);
  }

  function openNew() {
    setEditingId(null);
    setForm(emptyForm);
    setSaveError(null);
    setShowForm(true);
    loadDropdowns();
  }

  function openEdit(item: ScheduledItem) {
    setEditingId(item.id);
    const dtLocal = item.publish_at ? item.publish_at.slice(0, 16) : "";
    setForm({
      kind: item.kind,
      ref_id: item.ref_id,
      publish_at: dtLocal,
      target: item.target ?? "",
    });
    setSaveError(null);
    setShowForm(true);
    loadDropdowns();
  }

  function cancelForm() {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
    setSaveError(null);
  }

  function handleKindChange(newKind: string) {
    setForm((f) => ({
      ...f,
      kind: newKind,
      ref_id: "",
      target: newKind === "article" ? "wordpress" : "",
    }));
  }

  async function handleSave() {
    if (!form.ref_id || !form.publish_at) {
      setSaveError("Content and publish date are required.");
      return;
    }
    if (form.kind === "reel" && !form.target) {
      setSaveError("Platform is required for Social media.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      let r: Response;
      if (editingId == null) {
        r = await apiFetch("/scheduling", {
          method: "POST",
          body: JSON.stringify({
            kind: form.kind,
            ref_id: form.ref_id,
            publish_at: form.publish_at,
            target: form.target || null,
          }),
        });
      } else {
        r = await apiFetch(`/scheduling/${editingId}`, {
          method: "PUT",
          body: JSON.stringify({
            publish_at: form.publish_at,
            target: form.target || null,
          }),
        });
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      cancelForm();
      load();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item: ScheduledItem) {
    if (!confirm(`Cancel scheduled item "${item.display_name}"? This cannot be undone.`)) return;
    setDeletingId(item.id);
    try {
      const r = await apiFetch(`/scheduling/${item.id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      load();
    } catch (e: unknown) {
      alert(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeletingId(null);
    }
  }

  const labelStyle = {
    display: "block" as const,
    fontSize: 13,
    fontWeight: 600,
    color: BRAND.navyText,
    marginBottom: 4,
  };

  const hintStyle = {
    fontSize: 11,
    color: BRAND.sub,
    marginTop: 3,
  };

  return (
    <main style={{ maxWidth: 960 }}>
      <PageTitle
        right={
          !showForm && (
            <Button onClick={openNew}>+ New</Button>
          )
        }
      >
        Content Scheduling
      </PageTitle>

      {/* Inline form */}
      {showForm && (
        <Card style={{ marginBottom: 24, borderTop: `4px solid ${BRAND.red}` }}>
          <h3 style={{ margin: "0 0 16px", color: BRAND.navyText, fontSize: 16 }}>
            {editingId == null ? "Schedule Content" : "Edit Scheduled Item"}
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {editingId == null && (
              <>
                {/* Kind dropdown */}
                <div>
                  <label style={labelStyle}>Kind</label>
                  <select
                    value={form.kind}
                    onChange={(e) => handleKindChange(e.target.value)}
                    style={{ ...inputStyle, width: "100%" }}
                  >
                    {Object.entries(KIND_DISPLAY).map(([val, label]) => (
                      <option key={val} value={val}>{label}</option>
                    ))}
                  </select>
                </div>

                {/* Ref ID — dropdown based on kind */}
                <div>
                  <label style={labelStyle}>
                    {form.kind === "article" ? "Article" : "Video Series"}
                  </label>
                  {dropdownsLoading ? (
                    <p style={{ color: BRAND.sub, fontSize: 13, margin: 0 }}>Loading…</p>
                  ) : form.kind === "article" ? (
                    <select
                      value={form.ref_id}
                      onChange={(e) => setForm((f) => ({ ...f, ref_id: e.target.value }))}
                      style={{ ...inputStyle, width: "100%" }}
                    >
                      <option value="">— select an article —</option>
                      {articles.map((a) => (
                        <option key={a.slug} value={a.slug}>{a.title}</option>
                      ))}
                    </select>
                  ) : (
                    <select
                      value={form.ref_id}
                      onChange={(e) => setForm((f) => ({ ...f, ref_id: e.target.value }))}
                      style={{ ...inputStyle, width: "100%" }}
                    >
                      <option value="">— select a video series —</option>
                      {seriesList.map((s) => (
                        <option key={s.id} value={String(s.id)}>{s.label}</option>
                      ))}
                    </select>
                  )}
                  <p style={hintStyle}>
                    The article or video series this schedule entry publishes
                  </p>
                </div>
              </>
            )}

            {/* Publish At */}
            <div>
              <label style={labelStyle}>Publish At</label>
              <input
                type="datetime-local"
                value={form.publish_at}
                onChange={(e) => setForm((f) => ({ ...f, publish_at: e.target.value }))}
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>

            {/* Target — read-only for article, platform dropdown for reel */}
            <div>
              <label style={labelStyle}>Target</label>
              {form.kind === "article" ? (
                <div
                  style={{
                    ...inputStyle,
                    width: "100%",
                    background: BRAND.bg,
                    color: BRAND.sub,
                    cursor: "default",
                  }}
                >
                  wordpress
                </div>
              ) : (
                <select
                  value={form.target}
                  onChange={(e) => setForm((f) => ({ ...f, target: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }}
                >
                  <option value="">— select platform —</option>
                  <option value="instagram">Instagram</option>
                  <option value="tiktok">TikTok</option>
                </select>
              )}
            </div>

          </div>

          {saveError && <ErrorMsg>{saveError}</ErrorMsg>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : editingId == null ? "Create" : "Save Changes"}
            </Button>
            <Button variant="ghost" onClick={cancelForm} disabled={saving}>
              Cancel
            </Button>
          </div>
        </Card>
      )}

      {/* Status filter */}
      {!showForm && (
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>Filter:</label>
          <select
            value={statusFilter}
            onChange={(e) => handleFilterChange(e.target.value)}
            style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
          >
            <option value="">All statuses</option>
            <option value="scheduled">scheduled</option>
            <option value="published">published</option>
            <option value="error">error</option>
          </select>
        </div>
      )}

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && (
        <>
          {items.length === 0 ? (
            <Card>
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
                No scheduled items. Click "+ New" to create one.
              </p>
            </Card>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Kind</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Content</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Publish At</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Target</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 12px" }}>{kindBadge(item.kind)}</td>
                    <td style={{ padding: "10px 12px", fontWeight: 500, color: BRAND.ink }}>{item.display_name}</td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub }}>{fmtDate(item.publish_at)}</td>
                    <td style={{ padding: "10px 12px" }}>{statusBadge(item.status)}</td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub }}>{item.target ?? "—"}</td>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", gap: 8 }}>
                        <Button
                          variant="ghost"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          onClick={() => openEdit(item)}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="danger"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          disabled={deletingId === item.id}
                          onClick={() => handleDelete(item)}
                        >
                          {deletingId === item.id ? "Cancelling…" : "Cancel"}
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
