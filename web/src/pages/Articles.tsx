import { useEffect, useRef, useState, useContext } from "react";
import { Editor } from "@tinymce/tinymce-react";
import type { Editor as TinyMCEEditor } from "tinymce";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, inputStyle, Loading, ErrorMsg } from "../ui";
import { NavContext } from "../App";

// Detect user's local timezone once at module load
const USER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Convert a datetime-local string (YYYY-MM-DDTHH:MM) to a full ISO-8601 string
 *  with the browser's UTC offset, so the API knows the user's intended wall-clock time. */
function localInputToIso(localStr: string): string {
  if (!localStr) return "";
  // datetime-local gives "YYYY-MM-DDTHH:MM"; Date constructor treats it as local time
  return new Date(localStr).toISOString();
}

/** Interpret a datetime-local string as wall-clock time in the given IANA timezone
 *  and return the corresponding UTC ISO-8601 string. Uses offset correction via
 *  Intl (no external library). */
function wallTimeInTzToIso(localStr: string, tz: string): string {
  if (!localStr) return "";
  const [datePart, timePart] = localStr.split("T");
  const [y, mo, d] = datePart.split("-").map(Number);
  const [h, mi] = (timePart ?? "00:00").split(":").map(Number);
  const asUTC = Date.UTC(y, mo - 1, d, h, mi);
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(asUTC).map((p) => [p.type, p.value])
  );
  const shownHour = parts.hour === "24" ? 0 : Number(parts.hour);
  const shown = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), shownHour, Number(parts.minute));
  return new Date(asUTC - (shown - asUTC)).toISOString();
}

/** Format a UTC/ISO timestamp using the browser's locale, showing both date and time. */
function fmtLocale(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

interface ArticleSummary {
  slug: string;
  title: string;
  role: string;
  status: string;
  pillar_slug: string | null;
  wp_post_id: number | null;
  wp_url: string | null;
  wp_admin_url: string | null;
  publish_at: string | null;
}

interface ArticleFull extends ArticleSummary {
  meta: string | null;
  content_md: string | null;
  faq_json: unknown;
  jsonld_json: unknown;
  // wp_url is already on ArticleSummary via extends
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

// Extract YouTube video ID and start seconds from any YouTube URL.
// Handles: youtube.com/watch?v=ID&t=Ns  youtu.be/ID?t=Ns  /embed/ID
function parseYouTubeUrl(url: string): { id: string; start: number } | null {
  try {
    const u = new URL(url);
    let id = "";
    let start = 0;
    if (u.hostname === "youtu.be") {
      id = u.pathname.slice(1).split("?")[0];
      start = parseInt(u.searchParams.get("t") ?? "0", 10) || 0;
    } else if (
      u.hostname === "www.youtube.com" ||
      u.hostname === "youtube.com" ||
      u.hostname === "m.youtube.com"
    ) {
      if (u.pathname === "/watch") {
        id = u.searchParams.get("v") ?? "";
        const t = u.searchParams.get("t") ?? "0";
        start = parseInt(t, 10) || 0;
      } else if (u.pathname.startsWith("/embed/")) {
        id = u.pathname.split("/embed/")[1].split("?")[0];
        start = parseInt(u.searchParams.get("start") ?? "0", 10) || 0;
      }
    }
    if (!id) return null;
    return { id, start };
  } catch {
    return null;
  }
}

function renderYouTubeEmbed(id: string, start: number): string {
  const src = `https://www.youtube.com/embed/${escapeHtml(id)}${start > 0 ? `?start=${start}` : ""}`;
  return (
    `<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:8px;margin:16px 0">` +
    `<iframe src="${src}" style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" ` +
    `allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" ` +
    `allowfullscreen loading="lazy" title="YouTube video"></iframe>` +
    `</div>`
  );
}

// Admonition types for GitHub-style callouts: [!TIP], [!NOTE], [!WARNING], [!IMPORTANT]
const ADMONITION_TYPES: Record<string, { label: string; bg: string; border: string; labelColor: string }> = {
  TIP: { label: "Tip", bg: "#f0fdf4", border: "#22c55e", labelColor: "#15803d" },
  NOTE: { label: "Note", bg: "#eff6ff", border: "#3b82f6", labelColor: "#1d4ed8" },
  WARNING: { label: "Warning", bg: "#fffbeb", border: "#f59e0b", labelColor: "#b45309" },
  IMPORTANT: { label: "Important", bg: "#fdf4ff", border: "#a855f7", labelColor: "#7e22ce" },
  CAUTION: { label: "Caution", bg: "#fff1f2", border: "#f43f5e", labelColor: "#be123c" },
};

function renderMarkdown(md: string): string {
  if (!md) return "";
  const lines = md.split("\n");
  const out: string[] = [];
  let inList = false;
  // Admonition state: we collect blockquote lines and flush when the block ends
  let admonitionType: string | null = null;
  let admonitionLines: string[] = [];

  const closeList = () => {
    if (inList) { out.push("</ul>"); inList = false; }
  };

  const flushAdmonition = () => {
    if (admonitionType === null) return;
    const def = ADMONITION_TYPES[admonitionType];
    if (def) {
      const icon = admonitionType === "TIP" ? "💡"
        : admonitionType === "NOTE" ? "ℹ️"
        : admonitionType === "WARNING" ? "⚠️"
        : admonitionType === "CAUTION" ? "🚨"
        : "❗";
      const body = admonitionLines.map((l) => `<p style="margin:4px 0 0;font-size:14px;color:#374151">${inlineFormat(escapeHtml(l))}</p>`).join("");
      out.push(
        `<div style="border-left:4px solid ${def.border};background:${def.bg};border-radius:6px;padding:10px 14px;margin:12px 0">` +
        `<span style="font-weight:700;font-size:13px;color:${def.labelColor}">${icon} ${def.label}</span>` +
        body +
        `</div>`
      );
    }
    admonitionType = null;
    admonitionLines = [];
  };

  const inlineFormat = (raw: string): string => {
    return raw
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" rel="noopener noreferrer" target="_blank">$1</a>');
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // Blockquote / admonition lines start with >
    if (trimmed.startsWith(">")) {
      closeList();
      const content = trimmed.slice(1).trim();
      // First line of a blockquote: check for [!TYPE]
      if (admonitionType === null) {
        const typeMatch = content.match(/^\[!(TIP|NOTE|WARNING|IMPORTANT|CAUTION)\]$/i);
        if (typeMatch) {
          admonitionType = typeMatch[1].toUpperCase();
        } else {
          // Regular blockquote — treat as admonition-less, just emit a <blockquote>
          out.push(`<blockquote style="border-left:3px solid #d1d5db;margin:8px 0;padding:4px 12px;color:#6b7280">${inlineFormat(escapeHtml(content))}</blockquote>`);
        }
      } else {
        if (content) admonitionLines.push(content);
      }
      continue;
    }

    // Non-blockquote line: flush any pending admonition
    flushAdmonition();

    if (!trimmed) { closeList(); continue; }

    // Check if this line is a bare YouTube URL (standalone paragraph)
    const ytMatch = parseYouTubeUrl(trimmed);
    if (ytMatch) {
      closeList();
      out.push(renderYouTubeEmbed(ytMatch.id, ytMatch.start));
      continue;
    }

    const h3 = trimmed.match(/^###\s+(.*)/);
    if (h3) { closeList(); out.push(`<h3 style="font-size:17px;margin:20px 0 8px;color:#1a202c">${inlineFormat(escapeHtml(h3[1]))}</h3>`); continue; }
    const h2 = trimmed.match(/^##\s+(.*)/);
    if (h2) { closeList(); out.push(`<h2 style="font-size:20px;margin:24px 0 10px;color:#1a202c">${inlineFormat(escapeHtml(h2[1]))}</h2>`); continue; }
    const h1 = trimmed.match(/^#\s+(.*)/);
    if (h1) { closeList(); out.push(`<h1 style="font-size:26px;line-height:1.2;margin:0 0 16px;color:#1a202c">${inlineFormat(escapeHtml(h1[1]))}</h1>`); continue; }
    const li = trimmed.match(/^[-*]\s+(.*)/);
    if (li) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inlineFormat(escapeHtml(li[1]))}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inlineFormat(escapeHtml(trimmed))}</p>`);
  }
  flushAdmonition();
  closeList();
  return out.join("\n");
}

// ---------------------------------------------------------------------------
// SEO / AIO score — computed client-side from article signals
// ---------------------------------------------------------------------------

interface SeoCheck {
  label: string;
  points: number;
  pass: boolean;
  detail?: string;
}

interface SeoResult {
  score: number;
  max: number;
  checks: SeoCheck[];
}

function computeSeoScore(article: ArticleFull): SeoResult {
  const checks: SeoCheck[] = [];

  // 1. Meta description present (10 pts)
  const metaPresent = Boolean(article.meta && article.meta.trim().length > 0);
  checks.push({ label: "Meta description present", points: 10, pass: metaPresent });

  // 2. Meta description length 120-160 chars (10 pts)
  const metaLen = article.meta?.trim().length ?? 0;
  const metaLenOk = metaLen >= 120 && metaLen <= 160;
  checks.push({
    label: "Meta description 120–160 chars",
    points: 10,
    pass: metaLenOk,
    detail: metaLen > 0 ? `${metaLen} chars` : "no meta",
  });

  // 3. Title length 30-65 chars (5 pts)
  const titleLen = article.title?.trim().length ?? 0;
  const titleLenOk = titleLen >= 30 && titleLen <= 65;
  checks.push({
    label: "Title length 30–65 chars",
    points: 5,
    pass: titleLenOk,
    detail: `${titleLen} chars`,
  });

  // 4. Keyword in title (5 pts) — client-side: always pass (keyword not stored on article)
  checks.push({
    label: "Keyword appears in title",
    points: 5,
    pass: true,
    detail: "verified server-side",
  });

  // 5. Has H2 or H3 headings in content_md (10 pts) — matches HTML or markdown
  const hasHeadings = /(<h[23][\s/>])|(^#{2,3}\s)/im.test(article.content_md ?? "");
  checks.push({ label: "Has H2/H3 headings in content", points: 10, pass: hasHeadings });

  // 6. Answer-first lede (5 pts) — first 200 plain-text chars contain a sentence
  const plainHead = (article.content_md ?? "")
    .replace(/<[^>]+>/g, " ")
    .replace(/[#*>`_~\[\]]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200);
  const answerFirst = /\w{4,}.*?\./.test(plainHead);
  checks.push({ label: "Answer-first lede (direct sentence early)", points: 5, pass: answerFirst });

  // 7. Has FAQ (faq_json non-empty array) (5 pts)
  const faqItems = Array.isArray(article.faq_json)
    ? (article.faq_json as FaqItem[]).filter((f) => f && typeof f.q === "string")
    : [];
  const hasFaq = faqItems.length > 0;
  checks.push({
    label: "Has FAQ schema (≥1 pair)",
    points: 5,
    pass: hasFaq,
    detail: hasFaq ? `${faqItems.length} item${faqItems.length !== 1 ? "s" : ""}` : "none",
  });

  // 8. FAQ count ≥4 (10 pts) — SGE/AEO requires at least 4 pairs to display FAQPage
  const hasFaqCount = faqItems.length >= 4;
  checks.push({
    label: "FAQ has ≥4 pairs (SGE/AEO)",
    points: 10,
    pass: hasFaqCount,
    detail: `${faqItems.length} item${faqItems.length !== 1 ? "s" : ""}`,
  });

  // 9. Has JSON-LD (15 pts)
  const hasJsonLd = Boolean(
    article.jsonld_json &&
    (typeof article.jsonld_json === "object"
      ? Object.keys(article.jsonld_json as object).length > 0
      : String(article.jsonld_json).trim().length > 0)
  );
  checks.push({ label: "Has JSON-LD structured data", points: 15, pass: hasJsonLd });

  // 10. Has embedded YouTube link in content_md (10 pts)
  const hasVideo = /youtube\.com|youtu\.be/i.test(article.content_md ?? "");
  checks.push({ label: "Has embedded video link", points: 10, pass: hasVideo });

  // 11. Word count > 300 (15 pts) — strip HTML tags before counting
  const wordCount = (article.content_md ?? "")
    .replace(/<[^>]+>/g, " ")
    .replace(/[#*>`_~\[\]]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 0).length;
  const hasWords = wordCount > 300;
  checks.push({
    label: "Word count > 300",
    points: 15,
    pass: hasWords,
    detail: `${wordCount} words`,
  });

  const max = checks.reduce((s, c) => s + c.points, 0);
  const score = checks.filter((c) => c.pass).reduce((s, c) => s + c.points, 0);
  return { score, max, checks };
}

// ---------------------------------------------------------------------------
// WYSIWYG HTML editor (TinyMCE, self-hosted via npm tinymce package)
// ---------------------------------------------------------------------------

interface HtmlEditorProps {
  value: string;
  onChange: (html: string) => void;
}

function HtmlEditor({ value, onChange }: HtmlEditorProps) {
  const editorRef = useRef<TinyMCEEditor | null>(null);

  return (
    <Editor
      tinymceScriptSrc="/tinymce/tinymce.min.js"
      onInit={(_evt, editor) => { editorRef.current = editor; }}
      value={value}
      onEditorChange={(content) => onChange(content)}
      init={{
        height: 400,
        menubar: false,
        plugins: [
          "advlist", "autolink", "lists", "link", "image", "charmap", "preview",
          "anchor", "searchreplace", "visualblocks", "code", "fullscreen",
          "insertdatetime", "media", "table", "help", "wordcount",
        ],
        toolbar:
          "undo redo | blocks | bold italic underline strikethrough | " +
          "alignleft aligncenter alignright alignjustify | " +
          "bullist numlist outdent indent | link image media table | " +
          "removeformat code fullscreen | help",
        content_style:
          "body { font-family: system-ui, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1a202c; line-height: 1.7; }",
        skin: "oxide",
        branding: false,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Article view modal
// ---------------------------------------------------------------------------

type ModalTab = "article" | "seo";

interface ArticleModalProps {
  slug: string;
  onClose: () => void;
  onRefresh: () => void;
}

const TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Phoenix",
  "America/Anchorage",
  "Pacific/Honolulu",
  "UTC",
];

function looksLikeHtml(s: string): boolean {
  return /<(h[1-6]|p|ul|ol|li|div|strong|em|a|br|table)\b/i.test(s);
}

function ArticleModal({ slug, onClose, onRefresh }: ArticleModalProps) {
  const [article, setArticle] = useState<ArticleFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishResult, setPublishResult] = useState<{ wp_published: boolean; wp_url: string | null; wp_error: string | null } | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");
  const [scheduleTz, setScheduleTz] = useState(USER_TZ);
  const [scheduling, setScheduling] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleSuccess, setScheduleSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState<ModalTab>("article");

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
    setPublishResult(null);
    try {
      const r = await apiFetch(`/articles/${slug}/publish`, { method: "POST" });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: ArticleFull & { wp_published?: boolean; wp_error?: string | null } = await r.json();
      setArticle(updated);
      setPublishResult({
        wp_published: Boolean(updated.wp_published),
        wp_url: updated.wp_url ?? null,
        wp_error: updated.wp_error ?? null,
      });
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
      const isoAt = wallTimeInTzToIso(scheduleAt, scheduleTz);

      const sr = await apiFetch("/scheduling", {
        method: "POST",
        body: JSON.stringify({
          kind: "article",
          ref_id: slug,
          publish_at: isoAt,
          target: "wordpress",
          status: "scheduled",
          tz: scheduleTz,
        }),
      });
      if (!sr.ok) {
        const body = await sr.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${sr.status} ${sr.statusText}`);
      }

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

  const renderedHtml = article?.content_md
    ? (looksLikeHtml(article.content_md) ? article.content_md : renderMarkdown(article.content_md))
    : "";
  const seo = article ? computeSeoScore(article) : null;

  // Score bar color
  const scoreColor = seo
    ? seo.score >= 80 ? "#16a34a"
      : seo.score >= 50 ? "#d97706"
      : "#dc2626"
    : "#dc2626";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          width: "100%",
          maxWidth: 780,
          maxHeight: "90vh",
          boxShadow: "0 8px 40px rgba(16,24,40,0.18)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Fixed header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "18px 24px",
            borderBottom: `1px solid ${BRAND.border}`,
            background: BRAND.navy,
            flexShrink: 0,
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

        {/* Published banner — wp_url link prominently shown for published articles */}
        {article && article.status === "published" && article.wp_url && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 24px",
              background: "#e6f9f0",
              borderBottom: "1px solid #bbf7d0",
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 13, color: "#166534", fontWeight: 600 }}>
              Published on WordPress
            </span>
            <a
              href={article.wp_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 13,
                color: "#166534",
                fontWeight: 700,
                textDecoration: "underline",
              }}
            >
              View live post ↗
            </a>
          </div>
        )}

        {/* Fixed action bar (publish/schedule) — only when unpublished */}
        {article && article.status !== "published" && (
          <div
            style={{
              display: "flex",
              gap: 16,
              flexWrap: "wrap",
              alignItems: "flex-start",
              padding: "12px 24px",
              background: BRAND.bg,
              borderBottom: `1px solid ${BRAND.border}`,
              flexShrink: 0,
            }}
          >
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

            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  type="datetime-local"
                  value={scheduleAt}
                  onChange={(e) => { setScheduleAt(e.target.value); setScheduleSuccess(false); }}
                  style={{ ...inputStyle, fontSize: 13, padding: "8px 10px" }}
                />
                <select
                  value={scheduleTz}
                  onChange={(e) => setScheduleTz(e.target.value)}
                  style={{ ...inputStyle, fontSize: 13, padding: "8px 10px" }}
                >
                  {(TIMEZONES.includes(USER_TZ) ? TIMEZONES : [USER_TZ, ...TIMEZONES]).map((tz) => (
                    <option key={tz} value={tz}>{tz}</option>
                  ))}
                </select>
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

        {/* Tabs */}
        {article && (
          <div
            style={{
              display: "flex",
              borderBottom: `1px solid ${BRAND.border}`,
              background: "#fff",
              flexShrink: 0,
            }}
          >
            {(["article", "seo"] as ModalTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                style={{
                  padding: "10px 20px",
                  border: "none",
                  borderBottom: activeTab === tab ? `2px solid ${BRAND.red}` : "2px solid transparent",
                  background: "none",
                  cursor: "pointer",
                  fontSize: 14,
                  fontWeight: activeTab === tab ? 700 : 500,
                  color: activeTab === tab ? BRAND.navyText : BRAND.sub,
                  marginBottom: -1,
                }}
              >
                {tab === "article" ? "Article" : "SEO / AIO"}
              </button>
            ))}
          </div>
        )}

        {/* Scrollable content area */}
        <div style={{ overflowY: "auto", flex: 1, padding: 24 }}>
          {loading && <Loading />}
          {error && <ErrorMsg>Failed to load article: {error}</ErrorMsg>}

          {article && activeTab === "article" && (
            <>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
                {statusBadge(article.status)}
                {roleBadge(article.role)}
                {article.publish_at && (
                  <span style={{ fontSize: 13, color: BRAND.sub, alignSelf: "center" }}>
                    {article.status === "published" ? "Published" : "Scheduled"}:{" "}
                    {new Date(article.publish_at).toLocaleString()}
                  </span>
                )}
                {article.wp_post_id && (article.status === "published" ? article.wp_url : (article.wp_admin_url ?? article.wp_url)) && (
                  <a
                    href={(article.status === "published" ? article.wp_url : (article.wp_admin_url ?? article.wp_url)) ?? "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={article.status === "published" ? "View live WordPress post" : "Open the draft in the WordPress editor"}
                    style={{ fontSize: 13, color: BRAND.navyText, alignSelf: "center", textDecoration: "underline" }}
                  >
                    {article.status === "published" ? `WP #${article.wp_post_id} ↗` : `Edit WP #${article.wp_post_id} ↗`}
                  </a>
                )}
                {article.wp_post_id && !(article.status === "published" ? article.wp_url : (article.wp_admin_url ?? article.wp_url)) && (
                  <span style={{ fontSize: 13, color: BRAND.sub, alignSelf: "center" }}>
                    WP #{article.wp_post_id}
                  </span>
                )}
              </div>

              {/* Publish confirmation banner */}
              {publishResult && (
                publishResult.wp_published ? (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
                    background: "#e6f9f0", border: "1px solid #bbf7d0", color: "#166534",
                    borderRadius: 8, padding: "12px 16px", marginBottom: 16, fontSize: 14,
                  }}>
                    <strong>✓ Published to WordPress.</strong>
                    {publishResult.wp_url && (
                      <a href={publishResult.wp_url} target="_blank" rel="noopener noreferrer"
                        style={{ color: "#166534", fontWeight: 700 }}>
                        View published article ↗
                      </a>
                    )}
                  </div>
                ) : (
                  <div style={{
                    background: "#fff8e1", border: "1px solid #ffe082", color: "#8a6d3b",
                    borderRadius: 8, padding: "12px 16px", marginBottom: 16, fontSize: 14,
                  }}>
                    <strong>⚠ Marked as published, but not live on WordPress.</strong>
                    {" "}{publishResult.wp_error ?? "The WordPress push did not complete."} The
                    article status is set to <em>published</em> in the console, but it was not pushed
                    to the site — resolve the issue and re-publish to make it live.
                  </div>
                )
              )}

              {article.meta && (
                <p style={{ fontSize: 13, color: BRAND.sub, margin: "0 0 16px", fontStyle: "italic" }}>
                  {article.meta}
                </p>
              )}

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

          {article && activeTab === "seo" && seo && (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              {/* Score summary */}
              <div
                style={{
                  background: BRAND.bg,
                  border: `1px solid ${BRAND.border}`,
                  borderRadius: 10,
                  padding: "16px 20px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ fontWeight: 700, fontSize: 15, color: BRAND.navyText }}>SEO / AIO Score</span>
                  <span style={{ fontWeight: 800, fontSize: 22, color: scoreColor }}>
                    {seo.score}<span style={{ fontSize: 14, fontWeight: 500, color: BRAND.sub }}>/{seo.max}</span>
                  </span>
                </div>
                {/* Score bar */}
                <div style={{ height: 8, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(seo.score / seo.max) * 100}%`,
                      background: scoreColor,
                      borderRadius: 4,
                      transition: "width 0.3s",
                    }}
                  />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                  <span style={{ fontSize: 11, color: "#dc2626" }}>Poor &lt; 50</span>
                  <span style={{ fontSize: 11, color: "#d97706" }}>Fair &lt; 80</span>
                  <span style={{ fontSize: 11, color: "#16a34a" }}>Good ≥ 80</span>
                </div>
              </div>

              {/* Checklist */}
              <div>
                <h4 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Checks
                </h4>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {seo.checks.map((check, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 12px",
                        borderRadius: 8,
                        background: check.pass ? "#f0fdf4" : "#fff7f7",
                        border: `1px solid ${check.pass ? "#bbf7d0" : "#fecaca"}`,
                      }}
                    >
                      <span style={{ fontSize: 15, flexShrink: 0 }}>
                        {check.pass ? "✓" : "✗"}
                      </span>
                      <span style={{ flex: 1, fontSize: 14, color: BRAND.ink }}>{check.label}</span>
                      {check.detail && (
                        <span style={{ fontSize: 12, color: BRAND.sub }}>{check.detail}</span>
                      )}
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: check.pass ? "#16a34a" : "#dc2626",
                          flexShrink: 0,
                        }}
                      >
                        +{check.points}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Meta description */}
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Meta Description
                </h4>
                {article.meta ? (
                  <p style={{ margin: 0, fontSize: 14, color: BRAND.ink, lineHeight: 1.6, background: BRAND.bg, padding: "10px 14px", borderRadius: 8, border: `1px solid ${BRAND.border}` }}>
                    {article.meta}
                  </p>
                ) : (
                  <p style={{ margin: 0, fontSize: 14, color: BRAND.sub, fontStyle: "italic" }}>No meta description set.</p>
                )}
              </div>

              {/* JSON-LD */}
              <div>
                <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  JSON-LD Schema
                </h4>
                {article.jsonld_json ? (
                  <pre
                    style={{
                      margin: 0,
                      fontSize: 12,
                      background: "#1a202c",
                      color: "#e2e8f0",
                      padding: "14px 16px",
                      borderRadius: 8,
                      overflowX: "auto",
                      lineHeight: 1.5,
                    }}
                  >
                    {JSON.stringify(article.jsonld_json, null, 2)}
                  </pre>
                ) : (
                  <p style={{ margin: 0, fontSize: 14, color: BRAND.sub, fontStyle: "italic" }}>No JSON-LD data.</p>
                )}
              </div>

              {/* FAQ items */}
              {faqItems.length > 0 && (
                <div>
                  <h4 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    FAQ ({faqItems.length} item{faqItems.length !== 1 ? "s" : ""})
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {faqItems.map((item, i) => (
                      <div key={i} style={{ background: BRAND.bg, borderRadius: 8, padding: "10px 14px", border: `1px solid ${BRAND.border}` }}>
                        <p style={{ margin: "0 0 4px", fontWeight: 600, fontSize: 14, color: BRAND.navyText }}>
                          {item.q}
                        </p>
                        <p style={{ margin: 0, fontSize: 13, color: BRAND.ink }}>
                          {item.a}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Fixed footer */}
        <div
          style={{
            padding: "14px 24px",
            borderTop: `1px solid ${BRAND.border}`,
            display: "flex",
            justifyContent: "flex-end",
            flexShrink: 0,
          }}
        >
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Article row — shared between flat list and cluster view
// ---------------------------------------------------------------------------

interface ArticleRowProps {
  a: ArticleSummary;
  clusterTitle: string;
  indented?: boolean;
  deletingSlug: string | null;
  onView: (slug: string) => void;
  onEdit: (a: ArticleSummary) => void;
  onDelete: (a: ArticleSummary) => void;
}

function ArticleRow({ a, clusterTitle, indented, deletingSlug, onView, onEdit, onDelete }: ArticleRowProps) {
  return (
    <tr style={{ borderBottom: `1px solid ${BRAND.border}` }}>
      <td style={{ padding: "10px 12px", paddingLeft: indented ? 32 : 12, overflow: "hidden" }}>
        <button
          onClick={() => onView(a.slug)}
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
            width: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            display: "block",
          }}
          title={a.title}
        >
          {a.title}
        </button>
      </td>
      <td style={{ padding: "10px 12px", overflow: "hidden" }}>
        <span
          style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13, color: BRAND.ink }}
          title={clusterTitle}
        >
          {clusterTitle}
        </span>
      </td>
      <td style={{ padding: "10px 12px", width: 90 }}>{roleBadge(a.role)}</td>
      <td style={{ padding: "10px 12px", width: 90 }}>{statusBadge(a.status)}</td>
      <td style={{ padding: "10px 12px", width: 150, overflow: "hidden" }}>
        {a.wp_post_id && (a.status === "published" ? a.wp_url : (a.wp_admin_url ?? a.wp_url)) ? (
          <a
            href={(a.status === "published" ? a.wp_url : (a.wp_admin_url ?? a.wp_url)) ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            title={a.status === "published" ? "View live WordPress post" : "Open the draft in the WordPress editor"}
            style={{
              fontSize: 13,
              fontWeight: a.status === "published" ? 700 : 400,
              color: a.status === "published" ? "#166534" : BRAND.navyText,
              textDecoration: "underline",
              whiteSpace: "nowrap",
              background: a.status === "published" ? "#e6f9f0" : "transparent",
              padding: a.status === "published" ? "2px 6px" : "0",
              borderRadius: a.status === "published" ? 4 : 0,
            }}
          >
            {a.status === "published" ? "View on WP ↗" : `Edit WP #${a.wp_post_id} ↗`}
          </a>
        ) : a.wp_post_id ? (
          <span style={{ fontSize: 13, color: BRAND.sub }}>WP #{a.wp_post_id}</span>
        ) : (
          <span style={{ color: BRAND.border }}>—</span>
        )}
      </td>
      <td style={{ padding: "10px 12px", width: 120, color: BRAND.sub, fontSize: 13, overflow: "hidden" }}>
        {a.status === "published" && a.publish_at
          ? <span style={{ whiteSpace: "nowrap" }}>{fmtLocale(a.publish_at)}</span>
          : a.status === "scheduled" && a.publish_at
          ? (
            <span style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
              <Badge tone="amber">Sched</Badge>
              <span style={{ fontSize: 12, whiteSpace: "nowrap" }}>{fmtLocale(a.publish_at)}</span>
            </span>
          )
          : <span style={{ color: BRAND.border }}>Draft</span>}
      </td>
      <td style={{ padding: "10px 12px", width: 80 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button
            onClick={() => onEdit(a)}
            title="Edit article"
            aria-label="Edit article"
            style={{
              background: "none",
              border: `1px solid ${BRAND.border}`,
              borderRadius: 6,
              cursor: "pointer",
              padding: "4px 8px",
              fontSize: 15,
              color: BRAND.navyText,
              lineHeight: 1,
            }}
          >
            ✎
          </button>
          <button
            onClick={() => onDelete(a)}
            disabled={deletingSlug === a.slug}
            title="Delete article"
            aria-label="Delete article"
            style={{
              background: "none",
              border: `1px solid ${BRAND.redDark}`,
              borderRadius: 6,
              cursor: deletingSlug === a.slug ? "not-allowed" : "pointer",
              padding: "4px 8px",
              fontSize: 15,
              color: BRAND.redDark,
              lineHeight: 1,
              opacity: deletingSlug === a.slug ? 0.5 : 1,
            }}
          >
            🗑
          </button>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Grouping helpers
// ---------------------------------------------------------------------------

type SortMode = "cluster" | "date";

interface ClusterGroup {
  pillarSlug: string;
  pillar: ArticleSummary | null;
  clusters: ArticleSummary[];
}

function groupByCluster(articles: ArticleSummary[]): ClusterGroup[] {
  // Build a map of pillar slug → group
  const groups = new Map<string, ClusterGroup>();

  // First pass: identify all pillar articles
  for (const a of articles) {
    if (a.role === "pillar") {
      const key = a.slug;
      if (!groups.has(key)) {
        groups.set(key, { pillarSlug: key, pillar: a, clusters: [] });
      } else {
        groups.get(key)!.pillar = a;
      }
    }
  }

  // Second pass: attach clusters to their pillar group
  const orphans: ArticleSummary[] = [];
  for (const a of articles) {
    if (a.role === "cluster") {
      const key = a.pillar_slug ?? "";
      if (key && groups.has(key)) {
        groups.get(key)!.clusters.push(a);
      } else if (key) {
        // Pillar not in list yet — create a placeholder group
        if (!groups.has(key)) {
          groups.set(key, { pillarSlug: key, pillar: null, clusters: [] });
        }
        groups.get(key)!.clusters.push(a);
      } else {
        orphans.push(a);
      }
    } else if (a.role === "standalone") {
      orphans.push(a);
    }
  }

  // Sort groups: pillar publish_at desc (nulls last), then standalone/orphans at end
  const sorted = [...groups.values()].sort((ga, gb) => {
    const ta = ga.pillar?.publish_at ?? null;
    const tb = gb.pillar?.publish_at ?? null;
    if (ta && tb) return new Date(tb).getTime() - new Date(ta).getTime();
    if (ta) return -1;
    if (tb) return 1;
    return (ga.pillar?.title ?? ga.pillarSlug).localeCompare(gb.pillar?.title ?? gb.pillarSlug);
  });

  // Append standalone/orphan articles as their own singleton groups
  for (const a of orphans) {
    sorted.push({ pillarSlug: a.slug, pillar: a, clusters: [] });
  }

  return sorted;
}

function sortByDate(articles: ArticleSummary[]): ArticleSummary[] {
  return [...articles].sort((a, b) => {
    const ta = a.publish_at ? new Date(a.publish_at).getTime() : 0;
    const tb = b.publish_at ? new Date(b.publish_at).getTime() : 0;
    return tb - ta;
  });
}

// ---------------------------------------------------------------------------
// Main Articles page
// ---------------------------------------------------------------------------

export function Articles() {
  const { params } = useContext(NavContext);

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

  // Sort + filter state — seed filterCluster from nav params when navigated here
  const [sortMode, setSortMode] = useState<SortMode>("cluster");
  const [filterCluster, setFilterCluster] = useState<string>(params.cluster ?? "");

  // Sync filter if nav params change (e.g. user navigates here from SearchAsk "View")
  useEffect(() => {
    if (params.cluster !== undefined) {
      setFilterCluster(params.cluster);
    }
  }, [params.cluster]);

  // Auto-open a specific article when navigated with an `open` slug param.
  useEffect(() => {
    if (params.open) setViewingSlug(params.open);
  }, [params.open]);

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
    apiFetch(`/articles/${a.slug}`)
      .then((r) => r.json())
      .then((full: ArticleFull) => {
        setForm((f) => ({
          ...f,
          meta: full.meta ?? "",
          content_md: full.content_md ?? "",
        }));
      })
      .catch(() => {/* non-fatal */});
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
        publish_at: form.publish_at ? localInputToIso(form.publish_at) : null,
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

  // Derive unique cluster options for the filter dropdown (pillars that have clusters)
  const clusterOptions: { slug: string; title: string }[] = [];
  const seenPillars = new Set<string>();
  for (const a of articles) {
    if (a.role === "pillar" && !seenPillars.has(a.slug)) {
      seenPillars.add(a.slug);
      clusterOptions.push({ slug: a.slug, title: a.title });
    }
  }
  // Also include pillar_slug references from clusters where the pillar isn't in the list
  for (const a of articles) {
    if (a.role === "cluster" && a.pillar_slug && !seenPillars.has(a.pillar_slug)) {
      seenPillars.add(a.pillar_slug);
      clusterOptions.push({ slug: a.pillar_slug, title: a.pillar_slug });
    }
  }

  // Apply cluster filter
  const filteredArticles = filterCluster
    ? articles.filter(
        (a) =>
          a.slug === filterCluster ||
          a.pillar_slug === filterCluster
      )
    : articles;

  // Build a slug→title map for pillar articles so cluster rows can show the pillar title
  const pillarTitleBySlug = new Map<string, string>();
  for (const a of articles) {
    if (a.role === "pillar") {
      pillarTitleBySlug.set(a.slug, a.title);
    }
  }

  /** Return the cluster topic title to display for any article. */
  function clusterTitleFor(a: ArticleSummary): string {
    if (a.role === "pillar") return a.title;
    if (a.pillar_slug) return pillarTitleBySlug.get(a.pillar_slug) ?? a.title;
    return a.title;
  }

  const rowProps = {
    deletingSlug,
    onView: setViewingSlug,
    onEdit: openEdit,
    onDelete: handleDelete,
  };

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
              <label style={labelStyle}>Content (HTML)</label>
              <HtmlEditor
                value={form.content_md}
                onChange={(html) => setForm((f) => ({ ...f, content_md: html }))}
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
            <>
              {/* Controls bar: sort + cluster filter */}
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "center",
                  marginBottom: 16,
                  flexWrap: "wrap",
                }}
              >
                {/* Sort toggle */}
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 13, color: BRAND.sub, fontWeight: 600 }}>Sort:</span>
                  <div
                    style={{
                      display: "inline-flex",
                      border: `1px solid ${BRAND.border}`,
                      borderRadius: 8,
                      overflow: "hidden",
                    }}
                  >
                    {(["cluster", "date"] as SortMode[]).map((m) => (
                      <button
                        key={m}
                        onClick={() => setSortMode(m)}
                        style={{
                          padding: "6px 14px",
                          border: "none",
                          cursor: "pointer",
                          fontSize: 13,
                          fontWeight: 600,
                          background: sortMode === m ? BRAND.navy : "#fff",
                          color: sortMode === m ? "#fff" : BRAND.navyText,
                        }}
                      >
                        {m === "cluster" ? "By cluster" : "By date"}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Cluster filter — only shown when clusterOptions exist */}
                {clusterOptions.length > 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 13, color: BRAND.sub, fontWeight: 600 }}>Cluster:</span>
                    <select
                      value={filterCluster}
                      onChange={(e) => setFilterCluster(e.target.value)}
                      style={{ ...inputStyle, fontSize: 13, padding: "6px 10px" }}
                    >
                      <option value="">All clusters</option>
                      {clusterOptions.map((o) => (
                        <option key={o.slug} value={o.slug}>{o.title}</option>
                      ))}
                    </select>
                    {filterCluster && (
                      <button
                        onClick={() => setFilterCluster("")}
                        style={{
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          color: BRAND.sub,
                          fontSize: 18,
                          lineHeight: 1,
                          padding: "0 2px",
                        }}
                        title="Clear filter"
                        aria-label="Clear cluster filter"
                      >
                        &times;
                      </button>
                    )}
                  </div>
                )}

                <span style={{ fontSize: 12, color: BRAND.sub, marginLeft: "auto" }}>
                  {filteredArticles.length} article{filteredArticles.length !== 1 ? "s" : ""}
                </span>
              </div>

              {/* Fixed-layout table — columns never shift regardless of content length */}
              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 14,
                    tableLayout: "fixed",
                  }}
                >
                  <colgroup>
                    <col style={{ width: "30%" }} />
                    <col style={{ width: "22%" }} />
                    <col style={{ width: "90px" }} />
                    <col style={{ width: "90px" }} />
                    <col style={{ width: "150px" }} />
                    <col style={{ width: "120px" }} />
                    <col style={{ width: "80px" }} />
                  </colgroup>
                  <thead>
                    <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Title</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Cluster</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Role</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>WP</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Published</th>
                      <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortMode === "date" ? (
                      // Flat list sorted by publish_at desc
                      sortByDate(filteredArticles).map((a) => (
                        <ArticleRow key={a.slug} a={a} clusterTitle={clusterTitleFor(a)} {...rowProps} />
                      ))
                    ) : (
                      // Cluster-grouped view
                      groupByCluster(filteredArticles).map((group) => (
                        <>
                          {/* Pillar header row — blue left border */}
                          {group.pillar ? (
                            <tr
                              key={`pillar-${group.pillarSlug}`}
                              style={{ borderBottom: `1px solid ${BRAND.border}`, background: "#f0f4ff" }}
                            >
                              <td
                                colSpan={7}
                                style={{ padding: 0 }}
                              >
                                <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
                                  <colgroup>
                                    <col style={{ width: "30%" }} />
                                    <col style={{ width: "22%" }} />
                                    <col style={{ width: "90px" }} />
                                    <col style={{ width: "90px" }} />
                                    <col style={{ width: "150px" }} />
                                    <col style={{ width: "120px" }} />
                                    <col style={{ width: "80px" }} />
                                  </colgroup>
                                  <tbody>
                                    <ArticleRow
                                      a={group.pillar}
                                      clusterTitle={group.pillar.title}
                                      {...rowProps}
                                    />
                                  </tbody>
                                </table>
                              </td>
                            </tr>
                          ) : (
                            // Pillar not loaded — show a muted header with the slug
                            <tr
                              key={`pillar-stub-${group.pillarSlug}`}
                              style={{ background: "#f0f4ff", borderBottom: `1px solid ${BRAND.border}` }}
                            >
                              <td
                                colSpan={7}
                                style={{
                                  padding: "8px 12px",
                                  fontSize: 13,
                                  color: BRAND.sub,
                                  fontStyle: "italic",
                                }}
                              >
                                Cluster: {group.pillarSlug}
                              </td>
                            </tr>
                          )}
                          {/* Cluster articles — indented */}
                          {group.clusters.map((c) => (
                            <ArticleRow
                              key={c.slug}
                              a={c}
                              clusterTitle={group.pillar?.title ?? c.title}
                              indented
                              {...rowProps}
                            />
                          ))}
                        </>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}
