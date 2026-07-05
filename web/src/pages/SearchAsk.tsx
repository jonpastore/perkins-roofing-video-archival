import { useState, useEffect, type ReactNode } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, inputStyle, Loading, ErrorMsg } from "../ui";
import { ComposeEmailModal } from "../components/ComposeEmailModal";

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
}
interface SearchRow {
  score: number;
  link: string;
  video_id: string;
  text: string;
}
interface TopicItem {
  label: string;
  count: number;
  sample: { video_id: string; t: number };
}

const SUGGESTIONS = [
  "How do I know if my roof needs to be replaced?",
  "What should I look for after a storm?",
  "Do I need a permit to replace my roof?",
  "How long does a roof replacement take?",
];

// seconds -> M:SS
function mmss(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

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
  const text = label ?? (p ? `▶ ${mmss(p.t)}` : "▶ watch");
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
    /(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?:\/\/[^)]+\))|(https?:\/\/(?:youtu\.be|www\.youtube\.com)\/[^\s)]+)/g;
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

// ---- Topic chip / row component ----
function TopicRow({
  topic,
  onGenerate,
}: {
  topic: TopicItem;
  onGenerate: (label: string) => void;
}) {
  const sampleUrl = `https://youtu.be/${topic.sample.video_id}?t=${topic.sample.t}`;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        background: "#fff",
        border: `1px solid ${BRAND.border}`,
        borderRadius: 10,
        boxShadow: "0 1px 2px rgba(16,24,40,0.04)",
      }}
    >
      <span style={{ flex: 1, fontSize: 14, color: BRAND.ink, fontWeight: 500 }}>
        {topic.label}
      </span>
      <span
        style={{
          fontSize: 12,
          color: BRAND.sub,
          whiteSpace: "nowrap",
          minWidth: 64,
          textAlign: "right",
        }}
      >
        {topic.count} video{topic.count !== 1 ? "s" : ""}
      </span>
      <a
        href={sampleUrl}
        target="_blank"
        rel="noopener noreferrer"
        title={`Jump to sample timecode (${mmss(topic.sample.t)})`}
        style={{
          color: BRAND.red,
          fontWeight: 600,
          fontSize: 12,
          textDecoration: "none",
          whiteSpace: "nowrap",
        }}
      >
        ▶ {mmss(topic.sample.t)}
      </a>
      <Button
        variant="ghost"
        style={{ fontSize: 12, padding: "5px 10px", whiteSpace: "nowrap" }}
        onClick={() => onGenerate(topic.label)}
      >
        Generate cluster article
      </Button>
    </div>
  );
}

export function SearchAsk() {
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ans, setAns] = useState<AskResult | null>(null);
  const [rows, setRows] = useState<SearchRow[] | null>(null);

  // Email compose state
  const [checkedUrls, setCheckedUrls] = useState<Set<string>>(new Set());
  const [emailModalBody, setEmailModalBody] = useState<string | null>(null);

  // Pre-mined topics state
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [topicsError, setTopicsError] = useState<string | null>(null);
  const [generateMsg, setGenerateMsg] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null); // label being generated

  // Fetch mined topics when entering "search" mode
  useEffect(() => {
    if (mode !== "search") return;
    // Only fetch if we don't have them yet
    if (topics.length > 0) return;
    setTopicsLoading(true);
    setTopicsError(null);
    apiFetch("/topics")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: TopicItem[]) => setTopics(data))
      .catch((e) => setTopicsError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTopicsLoading(false));
  }, [mode]);

  async function run(q: string) {
    const question = q.trim();
    if (!question) return;
    setLoading(true); setError(null); setAns(null); setRows(null); setCheckedUrls(new Set());
    try {
      const r = await apiFetch(mode === "ask" ? "/ask" : "/search", {
        method: "POST",
        body: JSON.stringify({ query: question, k: 8 }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      if (mode === "ask") setAns(data); else setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateArticle(label: string) {
    setGenerating(label);
    setGenerateMsg(null);
    try {
      const r = await apiFetch("/topics/generate-article", {
        method: "POST",
        body: JSON.stringify({ topic: label }),
      });
      if (!r.ok) {
        const txt = await r.text().catch(() => r.statusText);
        throw new Error(`${r.status}: ${txt}`);
      }
      const data = await r.json();
      setGenerateMsg(`Draft created — see Articles (${data.slug})`);
    } catch (e) {
      setGenerateMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGenerating(null);
    }
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
    const lines: string[] = [];
    for (const g of grouped) {
      for (const c of g.clips) {
        if (checkedUrls.has(c.url)) {
          lines.push(`• ${g.title} — ${c.snippet} — watch: ${c.url}`);
        }
      }
    }
    return lines.join("\n");
  }

  function handleIncludeInEmail() {
    setEmailModalBody(buildEmailBody());
  }

  // Filtered topic list: if user typed a query, filter by it; otherwise show all
  const filteredTopics = query.trim()
    ? topics.filter((t) => t.label.toLowerCase().includes(query.toLowerCase()))
    : topics;

  return (
    <main style={{ maxWidth: 860 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ margin: 0, color: BRAND.navyText, fontSize: 22 }}>Ask Perkins Knowledge Base</h2>
        <div style={{ display: "inline-flex", border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
          {(["ask", "search"] as const).map((mo) => (
            <button key={mo} onClick={() => { setMode(mo); setGenerateMsg(null); }}
              style={{
                padding: "7px 16px", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600,
                background: mode === mo ? BRAND.navy : "#fff",
                color: mode === mo ? "#fff" : BRAND.navyText,
              }}>
              {mo === "ask" ? "Ask a question" : "Search topics"}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") run(query); }}
          placeholder={mode === "ask" ? "Ask anything about the roofing content…" : "Filter topics, or type to search all videos…"}
          style={{ ...inputStyle, flex: 1 }}
        />
        <Button onClick={() => run(query)} disabled={loading || !query.trim()}>
          {loading ? "…" : mode === "ask" ? "Ask" : "Search"}
        </Button>
      </div>

      {/* suggestion chips — ask mode only */}
      {mode === "ask" && (
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

      {loading && <Loading label={mode === "ask" ? "Searching Tim's videos…" : "Searching topics…"} />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {/* ---- ASK result ---- */}
      {ans && (
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

      {/* ---- SEARCH mode: pre-mined topic list ---- */}
      {mode === "search" && (
        <div>
          {/* Generate-article confirmation / error banner */}
          {generateMsg && (
            <div
              style={{
                marginBottom: 12,
                padding: "10px 14px",
                borderRadius: 8,
                background: generateMsg.startsWith("Error") ? "#fff0f0" : "#e6f9f0",
                color: generateMsg.startsWith("Error") ? BRAND.red : "#1a7f4b",
                fontSize: 13,
                fontWeight: 500,
                border: `1px solid ${generateMsg.startsWith("Error") ? "#fecaca" : "#bbf7d0"}`,
              }}
            >
              {generateMsg}
            </div>
          )}

          {topicsLoading && <Loading label="Loading mined topics…" />}
          {topicsError && <ErrorMsg>Could not load topics: {topicsError}</ErrorMsg>}

          {!topicsLoading && !topicsError && topics.length > 0 && (
            <>
              <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 10 }}>
                {filteredTopics.length} topic{filteredTopics.length !== 1 ? "s" : ""}
                {query.trim() ? ` matching "${query}"` : " extracted from Tim's videos"}
                {" — click ▶ to jump to the timecode, or generate a cluster article draft"}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {filteredTopics.map((t) => (
                  <TopicRow
                    key={t.label}
                    topic={t}
                    onGenerate={generating ? () => {} : handleGenerateArticle}
                  />
                ))}
                {filteredTopics.length === 0 && query.trim() && (
                  <p style={{ color: BRAND.sub, fontSize: 14 }}>
                    No mined topics match "{query}". Try the Search button above to search across all video content.
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </main>
  );
}
