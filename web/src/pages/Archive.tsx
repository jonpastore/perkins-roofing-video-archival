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
  unavailable_since: string | null;
  hidden_at: string | null;
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
  const { navigate } = useContext(NavContext);
  const [state, setState] = useState<DetailState>({ kind: "loading" });
  const [showTopicsModal, setShowTopicsModal] = useState(false);

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
  const inlineTopics = topics.slice(0, 8);

  function searchTopic(label: string) {
    setShowTopicsModal(false);
    navigate("search-ask", { mode: "search", topic: label });
  }

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        {[
          ["Topics", topics.length],
          ["Articles", articles.length],
          ["Social posts", social_posts.length],
        ].map(([label, value]) => (
          <div key={label} style={{ padding: "7px 10px", border: `1px solid ${BRAND.border}`, borderRadius: 8, background: "#fff" }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: BRAND.navyText, lineHeight: 1 }}>{Number(value).toLocaleString()}</div>
            <div style={{ marginTop: 2, fontSize: 10, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>

        {/* Topics */}
        <div style={{ minWidth: 220, flex: "1 1 220px" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Topics ({topics.length.toLocaleString()})
          </div>
          {topics.length === 0 ? (
            <span style={{ fontSize: 13, color: BRAND.sub }}>No topics mined.</span>
          ) : (
            <>
              <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 5 }}>
                {inlineTopics.map((t) => (
                  <li key={t.url} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 13 }}>
                    <a
                      href={t.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
                    >
                      ▶ {hms(t.t)}
                    </a>
                    <button
                      onClick={() => searchTopic(t.label)}
                      style={{ border: "none", background: "none", padding: 0, color: BRAND.ink, cursor: "pointer", textAlign: "left", textDecoration: "underline", textUnderlineOffset: 2 }}
                      title="Find all videos for this topic"
                    >
                      {t.label}
                    </button>
                  </li>
                ))}
              </ul>
              {topics.length > inlineTopics.length && (
                <Button variant="ghost" onClick={() => setShowTopicsModal(true)} style={{ marginTop: 10, fontSize: 12, padding: "5px 10px" }}>
                  View all {topics.length.toLocaleString()} topics
                </Button>
              )}
            </>
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

      {showTopicsModal && (
        <div style={{
          position: "fixed",
          inset: 0,
          zIndex: 1200,
          background: "rgba(16,24,40,0.24)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
        }}>
          <div style={{
            width: "min(820px, 96vw)",
            maxHeight: "86vh",
            overflow: "auto",
            background: "#fff",
            border: `1px solid ${BRAND.border}`,
            borderRadius: 12,
            boxShadow: "0 16px 48px rgba(16,24,40,0.18)",
            fontFamily: "inherit",
          }}>
            <div style={{ padding: "18px 22px", borderBottom: `1px solid ${BRAND.border}`, display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText }}>
                  All Topics — {video.title}
                </div>
                <div style={{ marginTop: 3, color: BRAND.sub, fontSize: 12 }}>
                  {topics.length.toLocaleString()} mined topic{topics.length === 1 ? "" : "s"}. Click a topic to search all videos for it.
                </div>
              </div>
              <button
                onClick={() => setShowTopicsModal(false)}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1 }}
                aria-label="Close topics modal"
              >
                ×
              </button>
            </div>
            <div style={{ padding: 22 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
                {topics.map((t) => (
                  <div key={t.url} style={{ border: `1px solid ${BRAND.border}`, borderRadius: 8, padding: 10, background: BRAND.bg }}>
                    <a
                      href={t.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ display: "inline-block", color: BRAND.red, fontWeight: 700, textDecoration: "none", fontSize: 12, marginBottom: 6 }}
                    >
                      ▶ {hms(t.t)}
                    </a>
                    <button
                      onClick={() => searchTopic(t.label)}
                      style={{ display: "block", border: "none", background: "none", padding: 0, color: BRAND.navyText, cursor: "pointer", textAlign: "left", fontWeight: 600, fontSize: 13, lineHeight: 1.35 }}
                      title="Find all videos for this topic"
                    >
                      {t.label}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
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

  // Show-hidden toggle — when true the API is called with include_hidden=true
  const [includeHidden, setIncludeHidden] = useState(false);
  const [hiddenCount, setHiddenCount] = useState(0);
  const [hidingId, setHidingId] = useState<string | null>(null);

  async function handleHide(video: ArchiveVideo) {
    setHidingId(video.id);
    try {
      const r = await apiFetch(`/archive/${video.id}/hide`, { method: "POST" });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? r.statusText); }
      fetchVideos(committed, includeHidden);
    } catch (e) {
      alert(`Hide failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setHidingId(null);
    }
  }

  async function handleUnhide(video: ArchiveVideo) {
    setHidingId(video.id);
    try {
      const r = await apiFetch(`/archive/${video.id}/unhide`, { method: "POST" });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? r.statusText); }
      fetchVideos(committed, includeHidden);
    } catch (e) {
      alert(`Unhide failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setHidingId(null);
    }
  }

  // Inline video rename + name-suggestion state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [nameBusy, setNameBusy] = useState<"save" | "yt" | "suggest" | null>(null);
  const [nameMsg, setNameMsg] = useState<string | null>(null);

  function startRename(v: ArchiveVideo) {
    setEditingId(v.id);
    setEditTitle(v.title ?? "");
    setNameMsg(null);
  }
  function cancelRename() {
    setEditingId(null);
    setEditTitle("");
    setNameMsg(null);
  }
  async function saveRename(v: ArchiveVideo) {
    const t = editTitle.trim();
    if (!t) { setNameMsg("Title can't be empty."); return; }
    setNameBusy("save");
    setNameMsg(null);
    try {
      const r = await apiFetch(`/archive/${v.id}/rename`, { method: "POST", body: JSON.stringify({ title: t }) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? r.statusText); }
      const upd = await r.json();
      setVideos((prev) => prev.map((x) => (x.id === v.id ? { ...x, title: upd.title } : x)));
      cancelRename();
    } catch (e) { setNameMsg(e instanceof Error ? e.message : String(e)); }
    finally { setNameBusy(null); }
  }
  async function fetchNameFrom(v: ArchiveVideo, kind: "yt" | "suggest") {
    setNameBusy(kind);
    setNameMsg(null);
    try {
      const path = kind === "yt" ? `/archive/${v.id}/youtube-name` : `/archive/${v.id}/suggest-name`;
      const r = await apiFetch(path, { method: kind === "yt" ? "GET" : "POST" });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? r.statusText); }
      const d = await r.json();
      setEditTitle(kind === "yt" ? (d.youtube_title ?? "") : (d.suggested_title ?? ""));
    } catch (e) { setNameMsg(e instanceof Error ? e.message : String(e)); }
    finally { setNameBusy(null); }
  }

  // Debounce timer for text/number/date inputs
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchVideos = useCallback((f: Filters, withHidden?: boolean) => {
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
    if (withHidden) params.set("include_hidden", "true");
    apiFetch(`/archive/videos?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ArchiveVideo[]) => {
        setVideos(data);
        setHiddenCount(data.filter((v) => v.hidden_at !== null).length);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Initial load (and re-load when filters or includeHidden changes)
  useEffect(() => {
    fetchVideos(committed, includeHidden);
  }, [committed, includeHidden, fetchVideos]);

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
      fetchVideos(committed, includeHidden);
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
      fetchVideos(committed, includeHidden);
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

        <div style={{ width: 1, height: 24, background: BRAND.border }} />

        {/* Show hidden toggle */}
        <button
          onClick={() => setIncludeHidden((prev) => !prev)}
          style={{
            padding: "5px 12px",
            fontSize: 12,
            fontWeight: 600,
            borderRadius: 20,
            border: `1px solid ${includeHidden ? BRAND.navy : BRAND.border}`,
            cursor: "pointer",
            background: includeHidden ? BRAND.navy : "#fff",
            color: includeHidden ? "#fff" : BRAND.sub,
            transition: "background 0.1s, color 0.1s",
            whiteSpace: "nowrap",
          }}
          title={includeHidden ? "Click to hide the hidden videos again" : "Click to show videos you have hidden"}
        >
          {includeHidden
            ? `Showing hidden (${hiddenCount})`
            : "Show hidden"}
        </button>
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
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, width: "34%" }}>Title</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, textAlign: "right", whiteSpace: "nowrap" }}>Duration</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, whiteSpace: "nowrap" }}>Upload Date</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, minWidth: 140 }}>Usage</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, whiteSpace: "nowrap", minWidth: 210 }} title="YouTube views, likes, and comments">KPIs</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600, whiteSpace: "nowrap" }}>Actions</th>
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
                  <td style={{ padding: "10px 12px", maxWidth: 340 }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
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
                      {v.unavailable_since ? (
                        <span
                          title="Deleted or made private on YouTube — your archived copy is retained."
                          style={{
                            fontSize: 15,
                            lineHeight: 1,
                            flexShrink: 0,
                            color: "#bbb",
                            cursor: "default",
                          }}
                        >
                          ▶
                        </span>
                      ) : (
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
                      )}
                      {editingId === v.id ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
                          <input
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            autoFocus
                            style={{ ...inputStyle, fontSize: 13, padding: "6px 8px", width: "100%", boxSizing: "border-box" }}
                          />
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button onClick={() => saveRename(v)} disabled={nameBusy !== null}
                              style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "none", cursor: "pointer", background: BRAND.navy, color: "#fff" }}>
                              {nameBusy === "save" ? "Saving…" : "Save"}
                            </button>
                            <button onClick={cancelRename} disabled={nameBusy !== null}
                              style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5, border: `1px solid ${BRAND.border}`, cursor: "pointer", background: "#fff", color: "#666" }}>
                              Cancel
                            </button>
                            <button onClick={() => fetchNameFrom(v, "yt")} disabled={nameBusy !== null} title="Fetch the current title from YouTube"
                              style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5, border: `1px solid ${BRAND.border}`, cursor: "pointer", background: "#fff", color: BRAND.navy }}>
                              {nameBusy === "yt" ? "…" : "From YouTube"}
                            </button>
                            <button onClick={() => fetchNameFrom(v, "suggest")} disabled={nameBusy !== null} title="Suggest a title from the transcript"
                              style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5, border: `1px solid ${BRAND.border}`, cursor: "pointer", background: "#fff", color: BRAND.navy }}>
                              {nameBusy === "suggest" ? "…" : "Suggest from transcript"}
                            </button>
                          </div>
                          {nameMsg && <span style={{ fontSize: 11, color: BRAND.red }}>{nameMsg}</span>}
                        </div>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1, minWidth: 0 }}>
                          <span
                            style={{
                              fontWeight: 500,
                              color: "#1a1a2e",
                              whiteSpace: "normal",
                              overflowWrap: "anywhere",
                            }}
                          >
                            <span onClick={() => toggleExpand(v.id)} style={{ cursor: "pointer", textDecoration: expandedId === v.id ? "underline" : "none", textUnderlineOffset: 2 }} title="Click to expand topics and usage">
                              {v.title}
                            </span>
                            <button onClick={(e) => { e.stopPropagation(); startRename(v); }} title="Rename this video"
                              style={{ background: "none", border: "none", cursor: "pointer", marginLeft: 6, color: BRAND.sub, fontSize: 12, padding: 0 }}>
                              ✏
                            </button>
                          </span>
                          {v.unavailable_since && (
                            <span
                              title="Deleted or made private on YouTube — your archived copy is retained."
                              style={{
                                alignSelf: "flex-start",
                                fontSize: 10,
                                fontWeight: 700,
                                background: "#fffbeb",
                                color: "#92400e",
                                border: "1px solid #fcd34d",
                                borderRadius: 4,
                                padding: "2px 6px",
                                whiteSpace: "nowrap",
                              }}
                            >
                              Unavailable on YouTube
                            </span>
                          )}
                          {v.clips_generated && (
                            <button onClick={() => navigate("video-approval", { series: v.id })} title="Review the generated reel for approval"
                              style={{ alignSelf: "flex-start", background: "none", border: "none", padding: 0, cursor: "pointer", color: BRAND.red, fontSize: 11, fontWeight: 600 }}>
                              🎬 Review reel →
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </td>

                  {/* Duration */}
                  <td style={{ padding: "10px 12px", color: "#555", whiteSpace: "nowrap", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
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

                  {/* KPIs inline (single row, hover explains each) */}
                  <td style={{ padding: "10px 12px", fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                    <div style={{ display: "flex", flexDirection: "row", gap: 14, alignItems: "center" }}>
                      <span title="Total lifetime views on YouTube" style={{ cursor: "help" }}>👁 {v.views?.toLocaleString() ?? "—"}</span>
                      <span title="Total likes on YouTube" style={{ cursor: "help" }}>♥ {v.likes?.toLocaleString() ?? "—"}</span>
                      <span title="Total comments on YouTube" style={{ cursor: "help" }}>💬 {v.comment_count?.toLocaleString() ?? "—"}</span>
                    </div>
                  </td>

                  {/* Clip Studio (edit) + Download + Hide/Unhide */}
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
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
                      <button
                        onClick={() => handleDownload(v)}
                        disabled={downloading === v.id}
                        title="Download archived copy"
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
                      {v.hidden_at ? (
                        <button
                          onClick={() => handleUnhide(v)}
                          disabled={hidingId === v.id}
                          title="Unhide — restore to default list"
                          aria-label="Unhide"
                          style={{
                            background: "none",
                            border: `1px solid ${BRAND.border}`,
                            borderRadius: 5,
                            cursor: hidingId === v.id ? "not-allowed" : "pointer",
                            padding: "3px 8px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: hidingId === v.id ? "#bbb" : BRAND.navy,
                          }}
                        >
                          {hidingId === v.id ? "…" : "Unhide"}
                        </button>
                      ) : (
                        <button
                          onClick={() => handleHide(v)}
                          disabled={hidingId === v.id}
                          title="Hide — remove from default list (archive copy retained)"
                          aria-label="Hide"
                          style={{
                            background: "none",
                            border: `1px solid ${BRAND.border}`,
                            borderRadius: 5,
                            cursor: hidingId === v.id ? "not-allowed" : "pointer",
                            padding: "3px 8px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: hidingId === v.id ? "#bbb" : BRAND.sub,
                          }}
                        >
                          {hidingId === v.id ? "…" : "Hide"}
                        </button>
                      )}
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
