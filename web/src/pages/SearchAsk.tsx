import { useState, type ReactNode } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, inputStyle, Loading, ErrorMsg } from "../ui";

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

export function SearchAsk() {
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ans, setAns] = useState<AskResult | null>(null);
  const [rows, setRows] = useState<SearchRow[] | null>(null);

  async function run(q: string) {
    const question = q.trim();
    if (!question) return;
    setLoading(true); setError(null); setAns(null); setRows(null);
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

  // group the descriptive sources by video so each clip is labeled with its video + topic
  const grouped = ans && !ans.abstained
    ? Object.values(
        (ans.sources ?? []).reduce((acc, s) => {
          (acc[s.video_id] ??= { video_id: s.video_id, title: s.title, clips: [] as Source[] }).clips.push(s);
          return acc;
        }, {} as Record<string, { video_id: string; title: string; clips: Source[] }>)
      )
    : [];

  return (
    <main style={{ maxWidth: 860 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ margin: 0, color: BRAND.navyText, fontSize: 22 }}>Ask Tim’s Videos</h2>
        <div style={{ display: "inline-flex", border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden" }}>
          {(["ask", "search"] as const).map((mo) => (
            <button key={mo} onClick={() => setMode(mo)}
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
          placeholder={mode === "ask" ? "Ask anything about the roofing content…" : "Search for a topic across all videos…"}
          style={{ ...inputStyle, flex: 1 }}
        />
        <Button onClick={() => run(query)} disabled={loading || !query.trim()}>
          {loading ? "…" : mode === "ask" ? "Ask" : "Search"}
        </Button>
      </div>

      {/* suggestion chips */}
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

      {loading && <Loading label={mode === "ask" ? "Searching Tim’s videos…" : "Searching topics…"} />}
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
              <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, marginBottom: 10 }}>
                SOURCES — {grouped.length} video{grouped.length > 1 ? "s" : ""}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {grouped.map((g) => (
                  <div key={g.video_id}>
                    <a href={`https://youtu.be/${g.video_id}`} target="_blank" rel="noopener noreferrer"
                      style={{ color: BRAND.navyText, fontWeight: 600, fontSize: 13.5, textDecoration: "none" }}>
                      {g.title}
                    </a>
                    <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 4, paddingLeft: 2 }}>
                      {g.clips.map((c) => (
                        <div key={c.url} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 13 }}>
                          <TimestampLink url={c.url} />
                          <span style={{ color: BRAND.sub }}>{c.snippet}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* ---- SEARCH results ---- */}
      {rows && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
    </main>
  );
}
