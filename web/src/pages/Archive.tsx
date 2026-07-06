import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { NavContext } from "../App";
import { BRAND, Badge, Button, Loading, ErrorMsg, Spinner, hms, inputStyle } from "../ui";

interface ArchiveVideo {
  id: string;
  title: string;
  duration: number | null;
  content_length: number | null;
  upload_date: string | null;
  archived: boolean;
  youtube_url: string | null;
  topic_count: number;
  article_count: number;
  social_post_count: number;
  clips_generated: boolean;
  articles_generated: boolean;
  social_generated: boolean;
  clips_generated_at: string | null;
  views: number | null;
  likes: number | null;
  comment_count: number | null;
  last_comment_at: string | null;
  kpis_polled_at: string | null;
  last_pulled_at: string | null;
}

interface Topic {
  label: string;
  t: number;
  url: string;
}

interface ArticleUsage {
  slug: string;
  title: string;
  status: string;
}

interface SocialPostUsage {
  platform: string;
  status: string;
  url: string | null;
}

interface VideoDetail {
  topics: Topic[];
  articles: ArticleUsage[];
  social_posts: SocialPostUsage[];
}

type DetailState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; msg: string }
  | { kind: "ok"; data: VideoDetail };

type TriState = "all" | "yes" | "no";

interface Filters {
  q: string;
  min_length: string;
  max_length: string;
  uploaded_after: string;
  uploaded_before: string;
  clips: TriState;
  articles: TriState;
  social: TriState;
}

const DEFAULT_FILTERS: Filters = {
  q: "",
  min_length: "",
  max_length: "",
  uploaded_after: "",
  uploaded_before: "",
  clips: "all",
  articles: "all",
  social: "all",
};

function hasActiveFilters(f: Filters): boolean {
  return (
    f.q !== "" ||
    f.min_length !== "" ||
    f.max_length !== "" ||
    f.uploaded_after !== "" ||
    f.uploaded_before !== "" ||
    f.clips !== "all" ||
    f.articles !== "all" ||
    f.social !== "all"
  );
}

function statusTone(status: string): "green" | "amber" | "blue" | "gray" {
  if (status === "published") return "green";
  if (status === "scheduled") return "blue";
  if (status === "draft") return "amber";
  return "gray";
}

function platformTone(platform: string): "green" | "amber" | "blue" | "gray" {
  if (platform === "instagram") return "amber";
  if (platform === "tiktok") return "blue";
  return "gray";
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

function TriToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: TriState;
  onChange: (v: TriState) => void;
}) {
  const options: TriState[] = ["all", "yes", "no"];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </span>
      <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            style={{
              flex: 1,
              padding: "5px 10px",
              fontSize: 12,
              fontWeight: 600,
              border: "none",
              borderRight: opt !== "no" ? `1px solid ${BRAND.border}` : "none",
              cursor: "pointer",
              background: value === opt ? (opt === "yes" ? "#e6f9f0" : opt === "no" ? "#fff0f0" : BRAND.navy) : "#fff",
              color: value === opt ? (opt === "yes" ? "#1a7f4b" : opt === "no" ? BRAND.red : "#fff") : BRAND.sub,
              transition: "background 0.1s, color 0.1s",
            }}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

function DetailPanel({ video }: { video: ArchiveVideo }) {
  const [state, setState] = useState<DetailState>({ kind: "loading" });

  useEffect(() => {
    apiFetch(`/archive/${video.id}/detail`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: VideoDetail) => setState({ kind: "ok", data }))
      .catch((e) =>
        setState({ kind: "error", msg: e instanceof Error ? e.message : String(e) })
      );
  }, [video.id]);

  const panelStyle = {
    padding: "14px 16px",
    background: BRAND.bg,
    borderTop: `1px solid ${BRAND.border}`,
    borderBottom: `1px solid ${BRAND.border}`,
  };

  if (state.kind === "loading") return <div style={panelStyle}><Loading label="Loading detail…" /></div>;
  if (state.kind === "error") return <div style={panelStyle}><ErrorMsg>Error: {state.msg}</ErrorMsg></div>;
  if (state.kind !== "ok") return null;

  const { topics, articles, social_posts } = state.data;

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>

        {/* Topics */}
        <div style={{ minWidth: 220, flex: "1 1 220px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Topics
          </div>
          {topics.length === 0 ? (
            <span style={{ fontSize: 13, color: BRAND.sub }}>No topics mined.</span>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 5 }}>
              {topics.map((t) => (
                <li key={t.url} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 13 }}>
                  <a
                    href={t.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
                  >
                    ▶ {hms(t.t)}
                  </a>
                  <span style={{ color: BRAND.ink }}>{t.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Used in Articles */}
        <div style={{ minWidth: 200, flex: "1 1 200px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Used in Articles
          </div>
          {articles.length === 0 ? (
            <span style={{ fontSize: 13, color: BRAND.sub }}>Not used in any articles.</span>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {articles.map((a) => (
                <li key={a.slug} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                  <Badge tone={statusTone(a.status)}>{a.status}</Badge>
                  <span style={{ color: BRAND.ink }}>{a.title}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Used in Social Posts */}
        <div style={{ minWidth: 200, flex: "1 1 200px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Used in Social Posts
          </div>
          {social_posts.length === 0 ? (
            <span style={{ fontSize: 13, color: BRAND.sub }}>No social posts.</span>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {social_posts.map((p, i) => (
                <li key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                  <Badge tone={platformTone(p.platform)}>{p.platform}</Badge>
                  <Badge tone={statusTone(p.status)}>{p.status}</Badge>
                  {p.url && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none", fontSize: 12 }}
                    >
                      view ↗
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* KPIs */}
        <div style={{ minWidth: 200, flex: "1 1 200px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            KPIs
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 13 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={{ color: BRAND.sub, minWidth: 90 }}>Views</span>
              <span style={{ color: BRAND.ink, fontWeight: 600 }}>{video.views?.toLocaleString() ?? "—"}</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={{ color: BRAND.sub, minWidth: 90 }}>Likes</span>
              <span style={{ color: BRAND.ink, fontWeight: 600 }}>{video.likes?.toLocaleString() ?? "—"}</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={{ color: BRAND.sub, minWidth: 90 }}>Comments</span>
              <span style={{ color: BRAND.ink, fontWeight: 600 }}>{video.comment_count?.toLocaleString() ?? "—"}</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={{ color: BRAND.sub, minWidth: 90 }}>Last comment</span>
              <span style={{ color: BRAND.ink }}>{fmtDateShort(video.last_comment_at)}</span>
            </div>
            <div style={{ marginTop: 6, fontSize: 11, color: BRAND.sub }}>
              KPIs polled: {fmtDate(video.kpis_polled_at)}
            </div>
            <div style={{ fontSize: 11, color: BRAND.sub }}>
              Last pulled: {fmtDate(video.last_pulled_at)}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

type ActionState = "idle" | "loading" | "done";

export function Archive() {
  const { navigate } = useContext(NavContext);

  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  // Committed filters — what was last sent to the API (debounced text/number inputs)
  const [committed, setCommitted] = useState<Filters>(DEFAULT_FILTERS);

  // Action bar state
  const [checkState, setCheckState] = useState<ActionState>("idle");
  const [checkResult, setCheckResult] = useState<{ new_count: number; last_pulled_at: string | null } | null>(null);
  const [backfillState, setBackfillState] = useState<ActionState>("idle");
  const [backfillResult, setBackfillResult] = useState<{ added: number } | null>(null);
  const [kpiState, setKpiState] = useState<ActionState>("idle");
  const [kpiResult, setKpiResult] = useState<{ polled: number } | null>(null);

  // Debounce timer for text/number/date inputs
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchVideos = useCallback((f: Filters) => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (f.q) params.set("q", f.q);
    if (f.min_length) params.set("min_length", f.min_length);
    if (f.max_length) params.set("max_length", f.max_length);
    if (f.uploaded_after) params.set("uploaded_after", f.uploaded_after);
    if (f.uploaded_before) params.set("uploaded_before", f.uploaded_before);
    if (f.clips !== "all") params.set("clips", f.clips);
    if (f.articles !== "all") params.set("articles", f.articles);
    if (f.social !== "all") params.set("social", f.social);
    apiFetch(`/archive/videos?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setVideos)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Initial load
  useEffect(() => {
    fetchVideos(committed);
  }, [committed, fetchVideos]);

  // Patch a filter field; for toggle (TriState) fields commit immediately
  function patchFilter<K extends keyof Filters>(key: K, value: Filters[K], immediate = false) {
    const next = { ...filters, [key]: value };
    setFilters(next);
    if (immediate) {
      setCommitted(next);
    } else {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => setCommitted(next), 400);
    }
  }

  async function handleDownload(video: ArchiveVideo) {
    setDownloading(video.id);
    try {
      const r = await apiFetch(`/archive/${video.id}/download`);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const { download_url } = await r.json();
      window.open(download_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      alert(`Download failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDownloading(null);
    }
  }

  function toggleExpand(videoId: string) {
    setExpandedId((prev) => (prev === videoId ? null : videoId));
  }

  async function handleCheckNew() {
    setCheckState("loading");
    setCheckResult(null);
    try {
      const r = await apiFetch("/archive/check-new");
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      setCheckResult(data);
      setCheckState("done");
    } catch (e) {
      alert(`Check failed: ${e instanceof Error ? e.message : String(e)}`);
      setCheckState("idle");
    }
  }

  async function handleBackfill() {
    setBackfillState("loading");
    setBackfillResult(null);
    try {
      const r = await apiFetch("/archive/backfill", { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      setBackfillResult(data);
      setBackfillState("done");
      // Refresh list after backfill
      fetchVideos(committed);
    } catch (e) {
      alert(`Backfill failed: ${e instanceof Error ? e.message : String(e)}`);
      setBackfillState("idle");
    }
  }

  async function handlePollKpis() {
    setKpiState("loading");
    setKpiResult(null);
    try {
      const r = await apiFetch("/archive/poll-kpis", { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      setKpiResult(data);
      setKpiState("done");
      // Refresh list to show updated KPI timestamps
      fetchVideos(committed);
    } catch (e) {
      alert(`KPI poll failed: ${e instanceof Error ? e.message : String(e)}`);
      setKpiState("idle");
    }
  }

  const active = hasActiveFilters(committed);

  const labelStyle = {
    fontSize: 11,
    fontWeight: 700 as const,
    color: BRAND.sub,
    textTransform: "uppercase" as const,
    letterSpacing: 0.5,
    marginBottom: 4,
    display: "block",
  };

  const numInputStyle = {
    ...inputStyle,
    width: 90,
    padding: "5px 8px",
    fontSize: 13,
  };

  return (
    <main>
      <h2 style={{ marginTop: 0, marginBottom: 16, color: "#1a1a2e" }}>
        Video Archive
        {active && (
          <span style={{ marginLeft: 12, fontSize: 12, fontWeight: 600, color: BRAND.red, verticalAlign: "middle" }}>
            Filtered
          </span>
        )}
      </h2>

      {/* Actions bar */}
      <div style={{
        display: "flex",
        gap: 10,
        alignItems: "center",
        flexWrap: "wrap",
        marginBottom: 16,
        padding: "10px 14px",
        background: BRAND.bg,
        border: `1px solid ${BRAND.border}`,
        borderRadius: 8,
      }}>
        {/* Check for new */}
        <Button
          variant="ghost"
          onClick={handleCheckNew}
          disabled={checkState === "loading"}
          style={{ padding: "7px 14px", fontSize: 13 }}
        >
          {checkState === "loading" ? <><Spinner small /> Checking…</> : "Check for new videos"}
        </Button>
        {checkState === "done" && checkResult && (
          <span style={{ fontSize: 12, color: BRAND.sub }}>
            <strong style={{ color: BRAND.ink }}>{checkResult.new_count} new</strong>
            {checkResult.last_pulled_at ? ` since ${fmtDate(checkResult.last_pulled_at)}` : ""}
          </span>
        )}

        <div style={{ width: 1, height: 24, background: BRAND.border }} />

        {/* Backfill missing */}
        <Button
          variant="ghost"
          onClick={handleBackfill}
          disabled={backfillState === "loading"}
          style={{ padding: "7px 14px", fontSize: 13 }}
        >
          {backfillState === "loading" ? <><Spinner small /> Backfilling…</> : "Backfill missing"}
        </Button>
        {backfillState === "done" && backfillResult && (
          <span style={{ fontSize: 12, color: BRAND.sub }}>
            <strong style={{ color: BRAND.ink }}>{backfillResult.added} added</strong>
          </span>
        )}

        <div style={{ width: 1, height: 24, background: BRAND.border }} />

        {/* Refresh KPIs */}
        <Button
          variant="ghost"
          onClick={handlePollKpis}
          disabled={kpiState === "loading"}
          style={{ padding: "7px 14px", fontSize: 13 }}
        >
          {kpiState === "loading" ? <><Spinner small /> Polling KPIs…</> : "Refresh KPIs"}
        </Button>
        {kpiState === "done" && kpiResult && (
          <span style={{ fontSize: 12, color: BRAND.sub }}>
            <strong style={{ color: BRAND.ink }}>{kpiResult.polled} polled</strong>
          </span>
        )}
      </div>

      {/* Filter bar */}
      <div style={{
        display: "flex",
        gap: 16,
        marginBottom: 20,
        flexWrap: "wrap",
        alignItems: "flex-end",
        padding: "12px 14px",
        background: active ? "#fef9f0" : BRAND.bg,
        border: `1px solid ${active ? "#f5c97a" : BRAND.border}`,
        borderRadius: 8,
        transition: "background 0.15s, border-color 0.15s",
      }}>
        {/* Search */}
        <div>
          <label style={labelStyle}>Search</label>
          <input
            type="text"
            placeholder="Title…"
            value={filters.q}
            onChange={(e) => patchFilter("q", e.target.value)}
            style={{ ...inputStyle, width: 220, padding: "5px 10px", fontSize: 13 }}
          />
        </div>

        {/* Min / max content length */}
        <div>
          <label style={labelStyle}>Min length <span style={{ fontWeight: 400, textTransform: "none" }}>(secs, e.g. 300 = 5:00)</span></label>
          <input
            type="number"
            placeholder="0"
            min={0}
            value={filters.min_length}
            onChange={(e) => patchFilter("min_length", e.target.value)}
            style={numInputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Max length <span style={{ fontWeight: 400, textTransform: "none" }}>(secs)</span></label>
          <input
            type="number"
            placeholder="∞"
            min={0}
            value={filters.max_length}
            onChange={(e) => patchFilter("max_length", e.target.value)}
            style={numInputStyle}
          />
        </div>

        {/* Date range */}
        <div>
          <label style={labelStyle}>Uploaded after</label>
          <input
            type="date"
            value={filters.uploaded_after}
            onChange={(e) => patchFilter("uploaded_after", e.target.value)}
            style={{ ...inputStyle, padding: "5px 8px", fontSize: 13 }}
          />
        </div>
        <div>
          <label style={labelStyle}>Uploaded before</label>
          <input
            type="date"
            value={filters.uploaded_before}
            onChange={(e) => patchFilter("uploaded_before", e.target.value)}
            style={{ ...inputStyle, padding: "5px 8px", fontSize: 13 }}
          />
        </div>

        {/* TriState toggles */}
        <TriToggle label="Clips generated" value={filters.clips} onChange={(v) => patchFilter("clips", v, true)} />
        <TriToggle label="Articles generated" value={filters.articles} onChange={(v) => patchFilter("articles", v, true)} />
        <TriToggle label="Social generated" value={filters.social} onChange={(v) => patchFilter("social", v, true)} />

        {/* Clear button */}
        {active && (
          <button
            onClick={() => { setFilters(DEFAULT_FILTERS); setCommitted(DEFAULT_FILTERS); }}
            style={{
              alignSelf: "flex-end",
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              color: BRAND.red,
              fontWeight: 700,
              padding: "6px 4px",
              textDecoration: "underline",
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* States */}
      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {/* Table */}
      {!loading && !error && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Title</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Duration</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Upload Date</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Usage</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>KPIs</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {videos.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: "24px 12px", color: "#888", textAlign: "center" }}>
                  No videos found.
                </td>
              </tr>
            )}
            {videos.map((v) => (
              <>
                <tr
                  key={v.id}
                  style={{ borderBottom: expandedId === v.id ? "none" : "1px solid #f0f0f0" }}
                >
                  {/* Title cell */}
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <button
                        onClick={() => toggleExpand(v.id)}
                        aria-label={expandedId === v.id ? "Collapse" : "Expand"}
                        style={{
                          fontFamily: "monospace",
                          fontSize: 13,
                          fontWeight: 700,
                          color: BRAND.red,
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          padding: "0 2px",
                          lineHeight: 1,
                          flexShrink: 0,
                          userSelect: "none",
                        }}
                      >
                        {expandedId === v.id ? "[-]" : "[+]"}
                      </button>
                      <a
                        href={`https://youtu.be/${v.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Play on YouTube"
                        style={{
                          color: BRAND.red,
                          fontSize: 15,
                          lineHeight: 1,
                          textDecoration: "none",
                          flexShrink: 0,
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        ▶
                      </a>
                      <span
                        onClick={() => toggleExpand(v.id)}
                        style={{
                          fontWeight: 500,
                          color: "#1a1a2e",
                          cursor: "pointer",
                          textDecoration: expandedId === v.id ? "underline" : "none",
                          textUnderlineOffset: 2,
                        }}
                        title="Click to expand topics and usage"
                      >
                        {v.title}
                      </span>
                    </div>
                  </td>

                  {/* Duration */}
                  <td style={{ padding: "10px 12px", color: "#555", whiteSpace: "nowrap" }}>
                    {hms(v.content_length ?? v.duration)}
                  </td>

                  {/* Upload date */}
                  <td style={{ padding: "10px 12px", color: "#555", whiteSpace: "nowrap" }}>
                    {v.upload_date ?? "—"}
                  </td>

                  {/* Usage badges */}
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {v.topic_count > 0 && (
                        <span style={{ fontSize: 11, fontWeight: 600, background: "#eef2ff", color: "#4338ca", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.topic_count} topics
                        </span>
                      )}
                      {v.article_count > 0 && (
                        <span style={{ fontSize: 11, fontWeight: 600, background: "#f0fdf4", color: "#166534", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.article_count} {v.article_count === 1 ? "article" : "articles"}
                        </span>
                      )}
                      {v.social_post_count > 0 && (
                        <span style={{ fontSize: 11, fontWeight: 600, background: "#fff7ed", color: "#c2410c", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.social_post_count} {v.social_post_count === 1 ? "post" : "posts"}
                        </span>
                      )}
                      {v.topic_count === 0 && v.article_count === 0 && v.social_post_count === 0 && (
                        <span style={{ fontSize: 11, color: "#bbb" }}>—</span>
                      )}
                    </div>
                  </td>

                  {/* KPIs inline */}
                  <td style={{ padding: "10px 12px", fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span title="Views">👁 {v.views?.toLocaleString() ?? "—"}</span>
                      <span title="Likes">♥ {v.likes?.toLocaleString() ?? "—"}</span>
                      <span title="Comments">💬 {v.comment_count?.toLocaleString() ?? "—"}</span>
                    </div>
                  </td>

                  {/* Download + Clip Studio */}
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                      <button
                        onClick={() => handleDownload(v)}
                        disabled={downloading === v.id}
                        title="Download"
                        aria-label="Download"
                        style={{
                          background: "none",
                          border: "none",
                          cursor: downloading === v.id ? "not-allowed" : "pointer",
                          padding: "4px 6px",
                          fontSize: 18,
                          lineHeight: 1,
                          color: downloading === v.id ? "#bbb" : BRAND.navy,
                          display: "flex",
                          alignItems: "center",
                        }}
                      >
                        {downloading === v.id ? "…" : "⬇"}
                      </button>
                      <button
                        onClick={() => navigate("clip-studio", { video: v.id })}
                        title="Open in Clip Studio"
                        aria-label="Open in Clip Studio"
                        style={{
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          padding: "4px 6px",
                          fontSize: 16,
                          lineHeight: 1,
                          color: BRAND.navy,
                          display: "flex",
                          alignItems: "center",
                        }}
                      >
                        ✎
                      </button>
                    </div>
                  </td>
                </tr>

                {expandedId === v.id && (
                  <tr key={`${v.id}-detail`}>
                    <td colSpan={6} style={{ padding: 0 }}>
                      <DetailPanel video={v} />
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
