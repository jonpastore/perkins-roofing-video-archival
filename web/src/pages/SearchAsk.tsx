import { useState, useEffect, useContext, type ReactNode } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, inputStyle, Loading, ErrorMsg, hms, ytLink } from "../ui";
import { ComposeEmailModal } from "../components/ComposeEmailModal";
import { NavContext } from "../App";
import { errText } from "../lib/errors";

// ---- types matching the live API ----
interface Source {
  url: string;
  video_id: string;
  t: number;
  title: string;
  snippet: string;
}
interface AskResult {
  answer: string;
  abstained: boolean;
  confidence: number;
  citations: string[]; // bare links (widget back-compat)
  sources: Source[]; // descriptive: video title + snippet + timestamp
  cached?: boolean;   // true when served from ask_cache
}
interface CachedSuggestion {
  question: string;
  answer: { answer: string; abstained: boolean; confidence: number; citations: string[]; sources: Source[] };
  similarity: number;
}
interface SearchRow {
  score: number;
  link: string;
  video_id: string;
  text: string;
}
interface TopicVideo {
  video_id: string;
  title: string;
  duration: number;
  start: number;
}
interface TopicArticle {
  slug: string;
  title: string;
  status: string;
  role: string;
  pillar_slug: string | null;
  wp_url?: string | null;
  wp_post_id?: number | null;
}

// Slugify matching the server _slugify so we can filter articles by pillar_slug
function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

const SUGGESTIONS = [
  "How do I know if my roof needs to be replaced?",
  "What should I look for after a storm?",
  "Do I need a permit to replace my roof?",
  "How long does a roof replacement take?",
];

// Pull {videoId, t} out of a youtu.be/watch deep link.
function parseLink(url: string): { videoId: string; t: number } | null {
  const t = Number(/[?&]t=(\d+)/.exec(url)?.[1] ?? NaN);
  const id =
    /youtu\.be\/([\w-]{6,})/.exec(url)?.[1] ??
    /[?&]v=([\w-]{6,})/.exec(url)?.[1] ??
    null;
  if (!id) return null;
  return { videoId: id, t: Number.isFinite(t) ? t : 0 };
}

function TimestampLink({ url, label }: { url: string; label?: string }) {
  const p = parseLink(url);
  const text = label ?? (p ? `▶ ${hms(p.t)}` : "▶ watch");
  return (
    <a href={url} target="_blank" rel="noopener noreferrer"
      style={{ color: BRAND.red, textDecoration: "none", fontWeight: 600, whiteSpace: "nowrap" }}>
      {text}
    </a>
  );
}

// Render the LLM answer with **bold**, [label](url) and bare youtu.be links as clickable
// timestamp links. Tokenized into React nodes (no innerHTML → no XSS from model output).
function renderRich(text: string): ReactNode[] {
  const pattern =
    /(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?:\/\/[^)]+\))|(https?:\/\/(?:youtu\.be|www\.youtube\.com)\/[^\s).,;]+)/g;
  const out: ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = pattern.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      out.push(<strong key={i++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("[")) {
      const lm = /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/.exec(tok)!;
      out.push(<TimestampLink key={i++} url={lm[2]} label={lm[1]} />);
    } else {
      out.push(<TimestampLink key={i++} url={tok} />);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ---- Topic videos + articles modal (tabbed) ----
type ModalTab = "videos" | "articles";

function TopicVideosModal({
  label,
  onClose,
}: {
  label: string;
  onClose: () => void;
}) {
  const { navigate } = useContext(NavContext);
  const [activeTab, setActiveTab] = useState<ModalTab>("videos");
  const [videos, setVideos] = useState<TopicVideo[] | null>(null);
  const [videoErr, setVideoErr] = useState<string | null>(null);
  const [articles, setArticles] = useState<TopicArticle[] | null>(null);
  const [articleErr, setArticleErr] = useState<string | null>(null);

  const pillarSlug = slugify(label);

  useEffect(() => {
    apiFetch(`/topics/videos?label=${encodeURIComponent(label)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: TopicVideo[]) => setVideos(data))
      .catch((e) => setVideoErr(e instanceof Error ? e.message : String(e)));
  }, [label]);

  useEffect(() => {
    // Load articles for this topic's cluster (filter by pillar_slug client-side)
    apiFetch("/articles")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: TopicArticle[]) => {
        const related = data.filter(
          (a) => a.slug === pillarSlug || a.pillar_slug === pillarSlug
        );
        setArticles(related);
      })
      .catch((e) => setArticleErr(e instanceof Error ? e.message : String(e)));
  }, [pillarSlug]);

  const tabStyle = (t: ModalTab): React.CSSProperties => ({
    padding: "8px 18px",
    border: "none",
    borderBottom: activeTab === t ? `2px solid ${BRAND.red}` : "2px solid transparent",
    background: "none",
    cursor: "pointer",
    fontSize: 14,
    fontWeight: activeTab === t ? 700 : 500,
    color: activeTab === t ? BRAND.navyText : BRAND.sub,
    marginBottom: -1,
  });

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 14, width: "min(640px, 94vw)",
          maxHeight: "80vh", display: "flex", flexDirection: "column",
          boxShadow: "0 8px 32px rgba(16,24,40,0.18)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "18px 24px 0" }}>
          <h3 style={{ margin: 0, fontSize: 16, color: BRAND.navyText, fontWeight: 700 }}>
            {label}
          </h3>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: `1px solid ${BRAND.border}`, padding: "0 24px", marginTop: 8 }}>
          <button style={tabStyle("videos")} onClick={() => setActiveTab("videos")}>Videos</button>
          <button style={tabStyle("articles")} onClick={() => setActiveTab("articles")}>
            Articles{articles && articles.length > 0 ? ` (${articles.length})` : ""}
          </button>
        </div>

        {/* Content */}
        <div style={{ overflowY: "auto", flex: 1, padding: "16px 24px 20px" }}>
          {activeTab === "videos" && (
            <>
              {!videos && !videoErr && <Loading label="Loading videos…" />}
              {videoErr && <ErrorMsg>Could not load videos: {videoErr}</ErrorMsg>}
              {videos && videos.length === 0 && (
                <p style={{ color: BRAND.sub, fontSize: 14 }}>No videos found for this topic.</p>
              )}
              {videos && videos.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {videos.map((v) => (
                    <div
                      key={v.video_id}
                      style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "10px 12px", border: `1px solid ${BRAND.border}`,
                        borderRadius: 8, background: BRAND.bg,
                      }}
                    >
                      <span style={{ flex: 1, fontSize: 13.5, color: BRAND.ink, fontWeight: 500 }}>
                        {v.title}
                      </span>
                      <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                        {hms(v.duration)}
                      </span>
                      <a
                        href={ytLink(v.video_id, v.start)}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          color: BRAND.red, fontWeight: 700, fontSize: 13,
                          textDecoration: "none", whiteSpace: "nowrap",
                        }}
                      >
                        ▶ play
                      </a>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {activeTab === "articles" && (
            <>
              {!articles && !articleErr && <Loading label="Loading articles…" />}
              {articleErr && <ErrorMsg>Could not load articles: {articleErr}</ErrorMsg>}
              {articles && articles.length === 0 && (
                <p style={{ color: BRAND.sub, fontSize: 14 }}>
                  No articles for this topic yet. Open Opportunities if it scores as a gap.
                </p>
              )}
              {articles && articles.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {articles.map((a) => (
                    <div
                      key={a.slug}
                      style={{
                        padding: "10px 12px", border: `1px solid ${BRAND.border}`,
                        borderRadius: 8, background: BRAND.bg,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ flex: 1, fontSize: 13.5, color: BRAND.ink, fontWeight: 500 }}>
                          {a.title}
                        </span>
                        <span style={{
                          fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
                          background: a.role === "pillar" ? "#e8eefc" : "#fff3e0",
                          color: a.role === "pillar" ? BRAND.navyText : "#b45309",
                          whiteSpace: "nowrap",
                        }}>
                          {a.role}
                        </span>
                        <span style={{
                          fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
                          background: a.status === "published" ? "#e6f9f0" : "#eef1f5",
                          color: a.status === "published" ? "#1a7f4b" : BRAND.sub,
                          whiteSpace: "nowrap",
                        }}>
                          {a.status}
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: 14, marginTop: 6 }}>
                        <button
                          onClick={() => { navigate("articles", { open: a.slug, cluster: a.pillar_slug ?? a.slug }); onClose(); }}
                          style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                        >
                          Open article
                        </button>
                        <button
                          onClick={() => { navigate("scheduling"); onClose(); }}
                          style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                        >
                          Queue
                        </button>
                        {a.status === "published" && a.wp_url && (
                          <a
                            href={a.wp_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline" }}
                          >
                            WordPress ↗
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function SearchAsk() {
  const { params } = useContext(NavContext);

  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ans, setAns] = useState<AskResult | null>(null);
  const [rows, setRows] = useState<SearchRow[] | null>(null);

  // Ask-cache typeahead suggestions
  const [suggestions, setSuggestions] = useState<CachedSuggestion[]>([]);
  const [suggestTimer, setSuggestTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  // Email compose state
  const [checkedUrls, setCheckedUrls] = useState<Set<string>>(new Set());
  const [emailModalBody, setEmailModalBody] = useState<string | null>(null);

  // Pre-mined topics state
  const [genres, setGenres] = useState<Array<{ id: string; label: string; publishable: boolean }>>([]);
  const [drillLabel, setDrillLabel] = useState<string | null>(null);
  useEffect(() => {
    apiFetch("/topic-graph/genres")
      .then(async (r) => (r.ok ? r.json() : []))
      .then((rows: Array<{ id: string; label: string; publishable: boolean }>) => {
        setGenres((rows ?? []).filter((g) => g.publishable && g.id !== "other"));
      })
      .catch(() => setGenres([]));
  }, []);

  // Debounced typeahead: fire /ask/suggest after 400 ms when >=8 chars typed in ask mode
  function handleQueryChange(val: string) {
    setQuery(val);
    if (mode !== "ask") return;
    if (suggestTimer) clearTimeout(suggestTimer);
    if (val.trim().length < 8) {
      setSuggestions([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await apiFetch(`/ask/suggest?q=${encodeURIComponent(val.trim())}`);
        if (!r.ok) return;
        const data: CachedSuggestion[] = await r.json();
        setSuggestions(data);
      } catch {
        // suggest is best-effort — silently ignore network errors
      }
    }, 400);
    setSuggestTimer(t);
  }

  function handleSuggestionClick(s: CachedSuggestion) {
    setSuggestions([]);
    setQuery(s.question);
    setAns({ ...s.answer, cached: true });
    setRows(null);
    setError(null);
    setCheckedUrls(new Set());
  }

  async function run(q: string, runMode: "ask" | "search" = mode) {
    const question = q.trim();
    if (!question) return;
    setSuggestions([]);
    setLoading(true); setError(null); setAns(null); setRows(null); setCheckedUrls(new Set());
    try {
      const r = await apiFetch(runMode === "ask" ? "/ask" : "/search", {
        method: "POST",
        body: JSON.stringify({ query: question, k: 8 }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const data = await r.json();
      if (runMode === "ask") setAns(data); else setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const topic = params.topic?.trim();
    if (!topic) return;
    setMode("search");
    setQuery(topic);
    setDrillLabel(null);
    run(topic, "search");
    // params is intentionally the trigger: Archive passes a topic when navigating here.
    // Run a video-content search only; do not open the topic drilldown modal here.
  }, [params.topic]); // eslint-disable-line react-hooks/exhaustive-deps

  function searchGenre(label: string) {
    setMode("search");
    setQuery(label);
    run(label, "search");
  }

  // group the descriptive sources by video so each clip is labeled with its video + topic
  const grouped = ans && !ans.abstained
    ? Object.values(
        (ans.sources ?? []).reduce((acc, s) => {
          (acc[s.video_id] ??= { video_id: s.video_id, title: s.title, clips: [] as Source[] }).clips.push(s);
          return acc;
        }, {} as Record<string, { video_id: string; title: string; clips: Source[] }>)
      )
    : [];

  // All source URLs from the current answer (for toggle-all logic)
  const allSourceUrls = grouped.flatMap((g) => g.clips.map((c) => c.url));
  const allChecked = allSourceUrls.length > 0 && allSourceUrls.every((u) => checkedUrls.has(u));
  const someChecked = allSourceUrls.some((u) => checkedUrls.has(u));

  function toggleAll() {
    if (allChecked) {
      setCheckedUrls(new Set());
    } else {
      setCheckedUrls(new Set(allSourceUrls));
    }
  }

  function toggleUrl(url: string) {
    setCheckedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url); else next.add(url);
      return next;
    });
  }

  function buildEmailBody(): string {
    // Emit HTML (not markdown/plain text) so links are real clickable anchors — this flows into
    // the WYSIWYG editor and the html send path directly.
    const esc = (s: string) =>
      (s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    const clips: { title: string; snippet: string; url: string }[] = [];
    for (const g of grouped) {
      for (const c of g.clips) {
        if (checkedUrls.has(c.url)) {
          clips.push({ title: g.title, snippet: c.snippet, url: c.url });
        }
      }
    }
    const items = clips
      .map(
        (c) =>
          `<li style="margin-bottom:12px;"><strong>${esc(c.title)}</strong><br>` +
          `${esc(c.snippet)}<br>` +
          `<a href="${esc(c.url)}">▶ Watch the clip</a></li>`
      )
      .join("\n");
    return [
      "<p>Hi,</p>",
      "<p>I wanted to share some relevant clips from Tim Perkins' roofing knowledge base that may be helpful:</p>",
      `<ul>${items}</ul>`,
      "<p>Let me know if you have any questions!</p>",
      "<p>Best,<br>Tim Perkins Roofing</p>",
    ].join("\n");
  }

  function handleIncludeInEmail() {
    setEmailModalBody(buildEmailBody());
  }

  return (
    <main style={{ maxWidth: 860 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ margin: 0, color: BRAND.navyText, fontSize: 22 }}>Ask Perkins Knowledge Base</h2>
        <div style={{ display: "inline-flex", border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
          {(["ask", "search"] as const).map((mo) => (
            <button key={mo} onClick={() => { setMode(mo); }}
              style={{
                padding: "7px 16px", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600,
                background: mode === mo ? BRAND.navy : "#fff",
                color: mode === mo ? "#fff" : BRAND.navyText,
              }}>
              {mo === "ask" ? "Ask a question" : "Search"}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
        <input
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") run(query); }}
          placeholder={mode === "ask" ? "Ask anything about the roofing content…" : "Search Tim's videos…"}
          style={{ ...inputStyle, flex: 1 }}
        />
        <Button onClick={() => run(query)} disabled={loading || !query.trim()}>
          {loading ? "…" : mode === "ask" ? "Ask" : "Search"}
        </Button>
      </div>
      {mode === "search" && genres.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
          {genres.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => searchGenre(g.label)}
              style={{
                padding: "5px 10px", borderRadius: 16, cursor: "pointer", fontSize: 12,
                border: `1px solid ${BRAND.border}`, background: query === g.label ? BRAND.navy : "#fff",
                color: query === g.label ? "#fff" : BRAND.navyText, fontWeight: 600,
              }}
            >
              {g.label}
            </button>
          ))}
        </div>
      )}

      {/* ask-cache typeahead chips — up to 3 "Asked before" suggestions */}
      {mode === "ask" && suggestions.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <span style={{ fontSize: 11, color: BRAND.sub, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4, marginRight: 8 }}>
            Asked before:
          </span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {suggestions.map((s) => (
              <button
                key={s.question}
                onClick={() => handleSuggestionClick(s)}
                style={{
                  padding: "5px 12px", background: "#f0f4ff", color: BRAND.navyText,
                  border: `1px solid ${BRAND.border}`, borderRadius: 20,
                  fontSize: 12.5, cursor: "pointer", textAlign: "left",
                }}
              >
                {s.question}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* static suggestion chips — ask mode only, hidden once cache suggestions appear */}
      {mode === "ask" && suggestions.length === 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 22 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => { setQuery(s); run(s); }}
              style={{
                padding: "6px 12px", background: "#eef1f6", color: BRAND.navyText, border: "none",
                borderRadius: 20, fontSize: 12.5, cursor: "pointer",
              }}>
              {s}
            </button>
          ))}
        </div>
      )}

      {loading && <Loading label={mode === "ask" ? "Searching Tim's videos…" : "Searching videos…"} />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {/* ---- ASK result (only in ask mode — switching to Search must hide it) ---- */}
      {mode === "ask" && ans && (
        <Card style={{ borderTop: `4px solid ${ans.abstained ? BRAND.sub : BRAND.red}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5 }}>
              {ans.abstained ? "No confident answer" : "Answer"}
            </span>
            <span style={{ fontSize: 12, color: BRAND.sub }}>confidence {Math.round(ans.confidence * 100)}%</span>
          </div>
          <div style={{ fontSize: 15, lineHeight: 1.6, color: BRAND.ink, whiteSpace: "pre-wrap" }}>
            {renderRich(ans.answer)}
          </div>
          {grouped.length > 0 && (
            <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${BRAND.border}` }}>
              {/* Sources header row: label + toggle-all + Include in email button */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", userSelect: "none" }}>
                  <input
                    type="checkbox"
                    checked={allChecked}
                    ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked; }}
                    onChange={toggleAll}
                    style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                  />
                  <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5 }}>
                    SOURCES — {grouped.length} video{grouped.length > 1 ? "s" : ""}
                  </span>
                </label>
                {someChecked && (
                  <Button
                    style={{ fontSize: 12, padding: "5px 12px", marginLeft: "auto" }}
                    onClick={handleIncludeInEmail}
                  >
                    Include in email ({checkedUrls.size})
                  </Button>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {grouped.map((g) => (
                  <div key={g.video_id}>
                    <a href={`https://youtu.be/${g.video_id}`} target="_blank" rel="noopener noreferrer"
                      style={{ color: BRAND.navyText, fontWeight: 600, fontSize: 13.5, textDecoration: "none" }}>
                      {g.title}
                    </a>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4, paddingLeft: 2 }}>
                      {g.clips.map((c) => (
                        <label key={c.url} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 13, cursor: "pointer", userSelect: "none" }}>
                          <input
                            type="checkbox"
                            checked={checkedUrls.has(c.url)}
                            onChange={() => toggleUrl(c.url)}
                            style={{ width: 14, height: 14, accentColor: BRAND.red, cursor: "pointer", flexShrink: 0, marginTop: 2 }}
                          />
                          <TimestampLink url={c.url} />
                          <span style={{ color: BRAND.sub }}>{c.snippet}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* ---- SEARCH results (free-text /search hits) ---- */}
      {rows && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
          {rows.length === 0 && <p style={{ color: BRAND.sub }}>No matching topics found.</p>}
          {rows.map((r, i) => (
            <Card key={i} style={{ padding: 14, display: "flex", gap: 14, alignItems: "center" }}>
              <TimestampLink url={r.link} />
              <span style={{ flex: 1, fontSize: 14, color: BRAND.ink }}>{r.text}</span>
              <span style={{ fontSize: 12, color: BRAND.sub }}>{Math.round(r.score * 100)}%</span>
            </Card>
          ))}
        </div>
      )}

      {/* ---- Compose Email Modal ---- */}
      {emailModalBody !== null && (
        <ComposeEmailModal
          initialBody={emailModalBody}
          onClose={() => setEmailModalBody(null)}
        />
      )}

      {drillLabel && (
        <TopicVideosModal label={drillLabel} onClose={() => setDrillLabel(null)} />
      )}
    </main>
  );
}
