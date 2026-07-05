import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, inputStyle, Loading, ErrorMsg } from "../ui";

interface ArticleSummary {
  slug: string;
  title: string;
  role: string;
  status: string;
  pillar_slug: string | null;
  wp_post_id: number | null;
  publish_at: string | null;
}

interface ArticleFull extends ArticleSummary {
  meta: string | null;
  content_md: string | null;
  faq_json: unknown;
  jsonld_json: unknown;
}

interface FormState {
  title: string;
  role: string;
  status: string;
  publish_at: string;
  meta: string;
  content_md: string;
}

const emptyForm: FormState = {
  title: "",
  role: "standalone",
  status: "draft",
  publish_at: "",
  meta: "",
  content_md: "",
};

function roleBadge(role: string) {
  if (role === "pillar") return <Badge tone="blue">pillar</Badge>;
  if (role === "cluster") return <Badge tone="amber">cluster</Badge>;
  return <Badge tone="gray">standalone</Badge>;
}

function statusBadge(status: string) {
  if (status === "published") return <Badge tone="green">published</Badge>;
  if (status === "scheduled") return <Badge tone="amber">scheduled</Badge>;
  return <Badge tone="gray">draft</Badge>;
}

export function Articles() {
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch("/articles")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setArticles)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setEditingSlug(null);
    setForm(emptyForm);
    setSaveError(null);
    setShowForm(true);
  }

  function openEdit(a: ArticleSummary) {
    setEditingSlug(a.slug);
    setForm({
      title: a.title,
      role: a.role,
      status: a.status,
      publish_at: a.publish_at ? a.publish_at.slice(0, 16) : "",
      meta: "",
      content_md: "",
    });
    setSaveError(null);
    // Fetch full article to pre-fill meta + content_md
    apiFetch(`/articles/${a.slug}`)
      .then((r) => r.json())
      .then((full: ArticleFull) => {
        setForm((f) => ({
          ...f,
          meta: full.meta ?? "",
          content_md: full.content_md ?? "",
        }));
      })
      .catch(() => {/* non-fatal — form still opens */});
    setShowForm(true);
  }

  function cancelForm() {
    setShowForm(false);
    setEditingSlug(null);
    setForm(emptyForm);
    setSaveError(null);
  }

  async function handleSave() {
    if (!form.title.trim()) {
      setSaveError("Title is required.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const payload: Record<string, unknown> = {
        title: form.title,
        role: form.role,
        status: form.status,
        meta: form.meta || null,
        content_md: form.content_md || null,
        publish_at: form.publish_at ? new Date(form.publish_at).toISOString() : null,
      };
      const r = await apiFetch(
        editingSlug == null ? "/articles" : `/articles/${editingSlug}`,
        {
          method: editingSlug == null ? "POST" : "PUT",
          body: JSON.stringify(payload),
        }
      );
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      cancelForm();
      load();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(a: ArticleSummary) {
    if (!confirm(`Delete article "${a.title}"? This cannot be undone.`)) return;
    setDeletingSlug(a.slug);
    try {
      const r = await apiFetch(`/articles/${a.slug}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      load();
    } catch (e: unknown) {
      alert(`Delete failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeletingSlug(null);
    }
  }

  const labelStyle = {
    display: "block",
    fontSize: 13,
    fontWeight: 600,
    color: BRAND.navyText,
    marginBottom: 4,
  } as const;

  return (
    <main style={{ maxWidth: 1000 }}>
      <PageTitle
        right={!showForm && <Button onClick={openNew}>+ New Article</Button>}
      >
        Articles
      </PageTitle>

      {showForm && (
        <Card style={{ marginBottom: 24, borderTop: `4px solid ${BRAND.red}` }}>
          <h3 style={{ margin: "0 0 16px", color: BRAND.navyText, fontSize: 16 }}>
            {editingSlug == null ? "New Article" : `Edit: ${editingSlug}`}
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={labelStyle}>Title</label>
              <input
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="Article title"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Role</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }}
                >
                  <option value="standalone">standalone</option>
                  <option value="pillar">pillar</option>
                  <option value="cluster">cluster</option>
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Status</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }}
                >
                  <option value="draft">draft</option>
                  <option value="scheduled">scheduled</option>
                  <option value="published">published</option>
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Publish at</label>
                <input
                  type="datetime-local"
                  value={form.publish_at}
                  onChange={(e) => setForm((f) => ({ ...f, publish_at: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }}
                />
              </div>
            </div>
            <div>
              <label style={labelStyle}>Meta description</label>
              <input
                value={form.meta}
                onChange={(e) => setForm((f) => ({ ...f, meta: e.target.value }))}
                placeholder="SEO meta description"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>
            <div>
              <label style={labelStyle}>Content (Markdown)</label>
              <textarea
                value={form.content_md}
                onChange={(e) => setForm((f) => ({ ...f, content_md: e.target.value }))}
                placeholder="Article body in Markdown…"
                rows={10}
                style={{ ...inputStyle, width: "100%", resize: "vertical", fontFamily: "monospace" }}
              />
            </div>
            {saveError && <ErrorMsg>{saveError}</ErrorMsg>}
            <div style={{ display: "flex", gap: 10 }}>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "Saving…" : editingSlug == null ? "Create" : "Save Changes"}
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
          {articles.length === 0 ? (
            <Card>
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
                No articles yet. Click "+ New Article" to create one.
              </p>
            </Card>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Title</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Role</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>WP Post</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Publish at</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {articles.map((a) => (
                  <tr key={a.slug} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 12px", fontWeight: 500, color: BRAND.ink }}>
                      {a.title}
                      {a.pillar_slug && (
                        <span style={{ display: "block", fontSize: 12, color: BRAND.sub, fontWeight: 400 }}>
                          pillar: {a.pillar_slug}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "10px 12px" }}>{roleBadge(a.role)}</td>
                    <td style={{ padding: "10px 12px" }}>{statusBadge(a.status)}</td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub }}>
                      {a.wp_post_id ?? <span style={{ color: BRAND.border }}>—</span>}
                    </td>
                    <td style={{ padding: "10px 12px", color: BRAND.sub, fontSize: 13 }}>
                      {a.publish_at
                        ? new Date(a.publish_at).toLocaleString()
                        : <span style={{ color: BRAND.border }}>—</span>}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", gap: 8 }}>
                        <Button
                          variant="ghost"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          onClick={() => openEdit(a)}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="danger"
                          style={{ padding: "6px 14px", fontSize: 13 }}
                          disabled={deletingSlug === a.slug}
                          onClick={() => handleDelete(a)}
                        >
                          {deletingSlug === a.slug ? "Deleting…" : "Delete"}
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
