import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Badge, Loading, ErrorMsg } from "../ui";

interface ArchiveVideo {
  id: string;
  title: string;
  duration: number | null;
  upload_date: string | null;
  archived: boolean;
  youtube_url: string | null;
  topic_count: number;
  article_count: number;
  social_post_count: number;
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

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// seconds -> M:SS (copied from SearchAsk.tsx)
function mmss(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
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

function DetailPanel({ videoId }: { videoId: string }) {
  const [state, setState] = useState<DetailState>({ kind: "loading" });

  useEffect(() => {
    apiFetch(`/archive/${videoId}/detail`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: VideoDetail) => setState({ kind: "ok", data }))
      .catch((e) =>
        setState({ kind: "error", msg: e instanceof Error ? e.message : String(e) })
      );
  }, [videoId]);

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
                    ▶ {mmss(t.t)}
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

        {/* TODO (B2): unanswered-comments count column — depends on the comments table built in B2.
            Will show a count badge per video that, when clicked, opens the B2 comment-review queue. */}

      </div>
    </div>
  );
}

export function Archive() {
  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    apiFetch(`/archive/videos?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setVideos)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [search]);

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

  return (
    <main>
      <h2 style={{ marginTop: 0, marginBottom: 20, color: "#1a1a2e" }}>
        Video Archive
      </h2>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, alignItems: "center" }}>
        <input
          type="text"
          placeholder="Search by title..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            padding: "8px 12px",
            border: "1px solid #ddd",
            borderRadius: 6,
            fontSize: 14,
            width: 280,
          }}
        />
      </div>

      {/* States */}
      {loading && <Loading />}
      {error && <p style={{ color: "#e94560", fontSize: 14 }}>Error: {error}</p>}

      {/* Table */}
      {!loading && !error && (
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 14,
          }}
        >
          <thead>
            <tr style={{ borderBottom: "2px solid #eee", textAlign: "left" }}>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Title</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Duration</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Upload Date</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Usage</th>
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Download</th>
            </tr>
          </thead>
          <tbody>
            {videos.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: "24px 12px", color: "#888", textAlign: "center" }}>
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
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {/* Accordion toggle — left of the row */}
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
                      {/* Play button — opens YouTube video */}
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
                      {/* Clickable title — expand detail panel */}
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
                  <td style={{ padding: "10px 12px", color: "#555" }}>
                    {formatDuration(v.duration)}
                  </td>
                  <td style={{ padding: "10px 12px", color: "#555" }}>
                    {v.upload_date ?? "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {v.topic_count > 0 && (
                        <span title="Topics" style={{ fontSize: 11, fontWeight: 600, background: "#eef2ff", color: "#4338ca", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.topic_count} topics
                        </span>
                      )}
                      {v.article_count > 0 && (
                        <span title="Articles referencing this video" style={{ fontSize: 11, fontWeight: 600, background: "#f0fdf4", color: "#166534", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.article_count} {v.article_count === 1 ? "article" : "articles"}
                        </span>
                      )}
                      {v.social_post_count > 0 && (
                        <span title="Social posts" style={{ fontSize: 11, fontWeight: 600, background: "#fff7ed", color: "#c2410c", borderRadius: 4, padding: "2px 6px", whiteSpace: "nowrap" }}>
                          {v.social_post_count} {v.social_post_count === 1 ? "post" : "posts"}
                        </span>
                      )}
                      {v.topic_count === 0 && v.article_count === 0 && v.social_post_count === 0 && (
                        <span style={{ fontSize: 11, color: "#bbb" }}>—</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
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
                  </td>
                </tr>
                {expandedId === v.id && (
                  <tr key={`${v.id}-detail`}>
                    <td colSpan={5} style={{ padding: 0 }}>
                      <DetailPanel videoId={v.id} />
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
