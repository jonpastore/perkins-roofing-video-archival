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

interface FaqItem {
  q: string;
  a: string;
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

// ---------------------------------------------------------------------------
// Lightweight safe markdown renderer — no dangerouslySetInnerHTML with raw
// untrusted input. We escape all text nodes, then apply limited structural
// patterns on escaped output only.
// ---------------------------------------------------------------------------

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(md: string): string {
  if (!md) return "";
  const lines = md.split("\n");
  const out: string[] = [];
  let inList = false;

  const closeList = () => {
    if (inList) { out.push("</ul>"); inList = false; }
  };

  const inlineFormat = (raw: string): string => {
    // raw is already html-escaped — apply only span-level patterns
    return raw
      // **bold**
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      // *italic*
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      // `code`
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // [text](url) — url is already escaped so & → &amp; etc.
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" rel="noopener noreferrer">$1</a>');
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // Blank line
    if (!trimmed) {
      closeList();
      continue;
    }

    // ATX headings
    const h3 = trimmed.match(/^###\s+(.*)/);
    if (h3) { closeList(); out.push(`<h3>${inlineFormat(escapeHtml(h3[1]))}</h3>`); continue; }
    const h2 = trimmed.match(/^##\s+(.*)/);
    if (h2) { closeList(); out.push(`<h2>${inlineFormat(escapeHtml(h2[1]))}</h2>`); continue; }
    const h1 = trimmed.match(/^#\s+(.*)/);
    if (h1) { closeList(); out.push(`<h1>${inlineFormat(escapeHtml(h1[1]))}</h1>`); continue; }

    // Unordered list item
    const li = trimmed.match(/^[-*]\s+(.*)/);
    if (li) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inlineFormat(escapeHtml(li[1]))}</li>`);
      continue;
    }

    // Paragraph
    closeList();
    out.push(`<p>${inlineFormat(escapeHtml(trimmed))}</p>`);
  }
  closeList();
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// Article view modal
// ---------------------------------------------------------------------------

interface ArticleModalProps {
  slug: string;
  onClose: () => void;
  onRefresh: () => void;
}

function ArticleModal({ slug, onClose, onRefresh }: ArticleModalProps) {
  const [article, setArticle] = useState<ArticleFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleSuccess, setScheduleSuccess] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/articles/${slug}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ArticleFull) => setArticle(data))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [slug]);

  async function handlePublish() {
    setPublishing(true);
    setPublishError(null);
    try {
      const r = await apiFetch(`/articles/${slug}/publish`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: ArticleFull = await r.json();
      setArticle(updated);
      onRefresh();
    } catch (e: unknown) {
      setPublishError(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  }

  async function handleSchedule() {
    if (!scheduleAt) {
      setScheduleError("Choose a date and time.");
      return;
    }
    setScheduling(true);
    setScheduleError(null);
    setScheduleSuccess(false);
    try {
      const isoAt = new Date(scheduleAt).toISOString();

      // 1. Create scheduling entry
      const sr = await apiFetch("/scheduling", {
        method: "POST",
        body: JSON.stringify({
          kind: "article",
          ref_id: slug,
          publish_at: isoAt,
          target: "wordpress",
          status: "scheduled",
        }),
      });
      if (!sr.ok) {
        const body = await sr.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${sr.status} ${sr.statusText}`);
      }

      // 2. Update article status + publish_at
      const ar = await apiFetch(`/articles/${slug}`, {
        method: "PUT",
        body: JSON.stringify({ status: "scheduled", publish_at: isoAt }),
      });
      if (!ar.ok) {
        const body = await ar.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${ar.status} ${ar.statusText}`);
      }
      const updated: ArticleFull = await ar.json();
      setArticle(updated);
      setScheduleSuccess(true);
      setScheduleAt("");
      onRefresh();
    } catch (e: unknown) {
      setScheduleError(e instanceof Error ? e.message : String(e));
    } finally {
      setScheduling(false);
    }
  }

  const faqItems = Array.isArray(article?.faq_json)
    ? (article!.faq_json as FaqItem[]).filter((f) => f && typeof f.q === "string")
    : [];

  const renderedHtml = article?.content_md ? renderMarkdown(article.content_md) : "";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 1000,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        overflowY: "auto",
        padding: "40px 16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          width: "100%",
          maxWidth: 780,
          boxShadow: "0 8px 40px rgba(16,24,40,0.18)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "18px 24px",
            borderBottom: `1px solid ${BRAND.border}`,
            background: BRAND.navy,
          }}
        >
          <span style={{ color: "#fff", fontWeight: 700, fontSize: 16 }}>
            {article ? article.title : "Article"}
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "rgba(255,255,255,0.7)",
              cursor: "pointer",
              fontSize: 22,
              lineHeight: 1,
              padding: "0 4px",
            }}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 24 }}>
          {loading && <Loading />}
          {error && <ErrorMsg>Failed to load article: {error}</ErrorMsg>}

          {article && (
            <>
              {/* Meta row */}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
                {statusBadge(article.status)}
                {roleBadge(article.role)}
                {article.publish_at && (
                  <span style={{ fontSize: 13, color: BRAND.sub, alignSelf: "center" }}>
                    {article.status === "published" ? "Published" : "Scheduled"}:{" "}
                    {new Date(article.publish_at).toLocaleString()}
                  </span>
                )}
                {article.wp_post_id && (
                  <span style={{ fontSize: 13, color: BRAND.sub, alignSelf: "center" }}>
                    WP #{article.wp_post_id}
                  </span>
                )}
              </div>

              {/* Meta description */}
              {article.meta && (
                <p style={{ fontSize: 13, color: BRAND.sub, margin: "0 0 16px", fontStyle: "italic" }}>
                  {article.meta}
                </p>
              )}

              {/* Publish / Schedule actions (only when not already published) */}
              {article.status !== "published" && (
                <div
                  style={{
                    display: "flex",
                    gap: 16,
                    flexWrap: "wrap",
                    alignItems: "flex-start",
                    padding: "14px 16px",
                    background: BRAND.bg,
                    borderRadius: 10,
                    marginBottom: 20,
                    border: `1px solid ${BRAND.border}`,
                  }}
                >
                  {/* Publish now */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <Button
                      onClick={handlePublish}
                      disabled={publishing}
                      style={{ whiteSpace: "nowrap" }}
                    >
                      {publishing ? "Publishing…" : "Publish Now"}
                    </Button>
                    {publishError && (
                      <span style={{ fontSize: 12, color: BRAND.red }}>{publishError}</span>
                    )}
                  </div>

                  <div style={{ width: 1, background: BRAND.border, alignSelf: "stretch" }} />

                  {/* Schedule */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        type="datetime-local"
                        value={scheduleAt}
                        onChange={(e) => { setScheduleAt(e.target.value); setScheduleSuccess(false); }}
                        style={{ ...inputStyle, fontSize: 13, padding: "8px 10px" }}
                      />
                      <Button
                        variant="ghost"
                        onClick={handleSchedule}
                        disabled={scheduling || !scheduleAt}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {scheduling ? "Scheduling…" : "Schedule"}
                      </Button>
                    </div>
                    {scheduleError && (
                      <span style={{ fontSize: 12, color: BRAND.red }}>{scheduleError}</span>
                    )}
                    {scheduleSuccess && (
                      <span style={{ fontSize: 12, color: "#1a7f4b" }}>Scheduled successfully.</span>
                    )}
                  </div>
                </div>
              )}

              {/* Article content */}
              {renderedHtml ? (
                <div
                  style={{
                    fontSize: 15,
                    lineHeight: 1.7,
                    color: BRAND.ink,
                    borderTop: `1px solid ${BRAND.border}`,
                    paddingTop: 20,
                    marginTop: 4,
                  }}
                  // Safe: renderedHtml is built from escaped text + limited structural tags only
                  // eslint-disable-next-line react/no-danger
                  dangerouslySetInnerHTML={{ __html: renderedHtml }}
                />
              ) : (
                <p style={{ color: BRAND.sub, fontSize: 14 }}>No content.</p>
              )}

              {/* FAQ */}
              {faqItems.length > 0 && (
                <div style={{ marginTop: 24, borderTop: `1px solid ${BRAND.border}`, paddingTop: 20 }}>
                  <h4 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 14, fontWeight: 700 }}>
                    FAQ
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {faqItems.map((item, i) => (
                      <div key={i} style={{ background: BRAND.bg, borderRadius: 8, padding: "10px 14px" }}>
                        <p style={{ margin: "0 0 4px", fontWeight: 600, fontSize: 14, color: BRAND.navyText }}>
                          {item.q}
                        </p>
                        <p style={{ margin: 0, fontSize: 14, color: BRAND.ink }}>
                          {item.a}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "14px 24px",
            borderTop: `1px solid ${BRAND.border}`,
            display: "flex",
            justifyContent: "flex-end",
          }}
        >
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Articles page
// ---------------------------------------------------------------------------

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
  const [viewingSlug, setViewingSlug] = useState<string | null>(null);

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

      {viewingSlug && (
        <ArticleModal
          slug={viewingSlug}
          onClose={() => setViewingSlug(null)}
          onRefresh={load}
        />
      )}

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
                      <button
                        onClick={() => setViewingSlug(a.slug)}
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          cursor: "pointer",
                          color: BRAND.navyText,
                          fontWeight: 600,
                          fontSize: 14,
                          textAlign: "left",
                          textDecoration: "underline",
                          textDecorationColor: BRAND.border,
                        }}
                      >
                        {a.title}
                      </button>
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
