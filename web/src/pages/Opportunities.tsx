import { useEffect, useState, useCallback, useContext } from "react";
import { apiFetch } from "../api";
import { hms, BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";
import { NavContext } from "../App";

interface Reel {
  series_id: number;
  video_id: string;
  title: string;
  parts_count: number;
}

interface UnusedVideo {
  video_id: string;
  title: string;
  duration: number;
}

interface ReelsBucket {
  reels: Reel[];
}

interface UnusedBucket {
  unused_videos: UnusedVideo[];
  unused_videos_total: number;
}

interface TopicItem {
  label: string;
  count: number;
  num_videos: number;
  total_content_length: number;
  sample: { video_id: string; t: number };
  generated: boolean;
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
}

interface GenerateResult {
  pillar_slug: string;
  pillar: { slug: string; title: string };
  clusters: { slug: string; title: string }[];
  count: number;
}

// Matches server _slugify: lowercase, non-alphanumerics→"-", trim, slice(0,80)
function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

const TOPIC_PAGE_SIZE = 24;
const BUCKET_PAGE_SIZE = 50;

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        margin: "28px 0 12px",
        color: BRAND.navyText,
        fontSize: 16,
        fontWeight: 600,
      }}
    >
      {children}
    </h3>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <Badge tone="green">{label}</Badge>
    </div>
  );
}

function ActionNote({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: 12, color: BRAND.sub, margin: "2px 0 8px", fontStyle: "italic" }}>
      {children}
    </p>
  );
}

type ModalTab = "videos" | "articles";

function TopicVideoModal({
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
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: TopicVideo[]) => setVideos(data))
      .catch((e: unknown) => setVideoErr(e instanceof Error ? e.message : String(e)));
  }, [label]);

  useEffect(() => {
    apiFetch("/articles")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: TopicArticle[]) => {
        const related = data.filter(
          (a) => a.slug === pillarSlug || a.pillar_slug === pillarSlug
        );
        setArticles(related);
      })
      .catch((e: unknown) => setArticleErr(e instanceof Error ? e.message : String(e)));
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
          <h3 style={{ margin: 0, fontSize: 16, color: BRAND.navyText, fontWeight: 700 }}>{label}</h3>
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
                      <span style={{ flex: 1, fontSize: 13.5, color: BRAND.ink, fontWeight: 500 }}>{v.title}</span>
                      <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>{hms(v.duration)}</span>
                      <a
                        href={`https://youtu.be/${v.video_id}?t=${Math.floor(v.start)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: BRAND.red, fontWeight: 700, fontSize: 13, textDecoration: "none", whiteSpace: "nowrap" }}
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
                  No articles generated for this topic yet. Use "Generate cluster articles" to create them.
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

function ClusterResultModal({
  topic,
  result,
  onClose,
}: {
  topic: string;
  result: GenerateResult;
  onClose: () => void;
}) {
  const { navigate } = useContext(NavContext);
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 14, width: "min(600px, 94vw)",
          maxHeight: "80vh", display: "flex", flexDirection: "column",
          boxShadow: "0 8px 32px rgba(16,24,40,0.18)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", padding: "18px 24px 12px" }}>
          <div>
            <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 4, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Cluster created
            </div>
            <h3 style={{ margin: 0, fontSize: 16, color: BRAND.navyText, fontWeight: 700 }}>{topic}</h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1, marginTop: 2 }}
          >
            ×
          </button>
        </div>

        <div style={{ overflowY: "auto", flex: 1, padding: "0 24px 20px" }}>
          {/* Pillar article */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>
              Pillar article
            </div>
            <div
              style={{
                padding: "10px 14px", border: `2px solid ${BRAND.navyText}`,
                borderRadius: 8, background: "#f0f4ff",
                display: "flex", alignItems: "center", gap: 10,
              }}
            >
              <span style={{ flex: 1, fontSize: 14, color: BRAND.navyText, fontWeight: 600 }}>
                {result.pillar.title}
              </span>
              <button
                onClick={() => { navigate("articles", { open: result.pillar.slug, cluster: result.pillar_slug }); onClose(); }}
                style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0, whiteSpace: "nowrap" }}
              >
                Open →
              </button>
            </div>
          </div>

          {/* Cluster articles */}
          {result.clusters.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>
                Cluster articles ({result.clusters.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {result.clusters.map((c) => (
                  <div
                    key={c.slug}
                    style={{
                      padding: "9px 14px", border: `1px solid ${BRAND.border}`,
                      borderRadius: 8, background: BRAND.bg,
                      display: "flex", alignItems: "center", gap: 10,
                    }}
                  >
                    <span style={{ flex: 1, fontSize: 13.5, color: BRAND.ink, fontWeight: 500 }}>
                      {c.title}
                    </span>
                    <button
                      onClick={() => { navigate("articles", { open: c.slug, cluster: result.pillar_slug }); onClose(); }}
                      style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0, whiteSpace: "nowrap" }}
                    >
                      Open →
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "12px 24px 16px", borderTop: `1px solid ${BRAND.border}`, display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button
            variant="primary"
            onClick={() => { navigate("articles", { cluster: result.pillar_slug }); onClose(); }}
          >
            View all in Articles
          </Button>
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}

function Paginator({
  page,
  totalPages,
  onPrev,
  onNext,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "10px 0 4px", fontSize: 13 }}>
      <button
        onClick={onPrev}
        disabled={page === 0}
        style={{
          background: "none",
          border: `1px solid ${BRAND.border}`,
          borderRadius: 6,
          padding: "3px 12px",
          cursor: page === 0 ? "not-allowed" : "pointer",
          color: page === 0 ? BRAND.sub : BRAND.navyText,
          fontWeight: 600,
        }}
      >
        Prev
      </button>
      <span style={{ color: BRAND.sub }}>
        Page {page + 1} of {totalPages}
      </span>
      <button
        onClick={onNext}
        disabled={page >= totalPages - 1}
        style={{
          background: "none",
          border: `1px solid ${BRAND.border}`,
          borderRadius: 6,
          padding: "3px 12px",
          cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
          color: page >= totalPages - 1 ? BRAND.sub : BRAND.navyText,
          fontWeight: 600,
        }}
      >
        Next
      </button>
    </div>
  );
}

type TopicFilter = "all" | "not_generated" | "generated";

export function Opportunities() {
  const { navigate } = useContext(NavContext);

  // Per-topic state: label -> { state: "generating"|"done", result?: GenerateResult }
  const [topicStates, setTopicStates] = useState<Record<string, { state: "generating" | "done"; result?: GenerateResult }>>({});
  const [genMsg, setGenMsg] = useState<Record<string, string>>({});
  // Modal for post-generation cluster result
  const [clusterModal, setClusterModal] = useState<{ topic: string; result: GenerateResult } | null>(null);

  // Server-paginated topics section
  const [topicSort, setTopicSort] = useState<"length" | "videos" | "alpha">("length");
  const [topicFilter, setTopicFilter] = useState<TopicFilter>("all");
  const [topicOffset, setTopicOffset] = useState(0);
  const [topicItems, setTopicItems] = useState<TopicItem[]>([]);
  const [topicTotal, setTopicTotal] = useState(0);
  const [topicLoading, setTopicLoading] = useState(true);
  const [topicError, setTopicError] = useState<string | null>(null);
  const [videoModalLabel, setVideoModalLabel] = useState<string | null>(null);

  // Reels — fetched once
  const [reels, setReels] = useState<Reel[]>([]);
  const [reelsLoading, setReelsLoading] = useState(true);
  const [reelsError, setReelsError] = useState<string | null>(null);

  // Unused videos — server-paginated
  const [unused, setUnused] = useState<UnusedVideo[]>([]);
  const [unusedTotal, setUnusedTotal] = useState(0);
  const [unusedPage, setUnusedPage] = useState(0);
  const [unusedLoading, setUnusedLoading] = useState(true);
  const [unusedError, setUnusedError] = useState<string | null>(null);

  const fetchTopics = useCallback((sort: "length" | "videos" | "alpha", filter: TopicFilter, offset: number) => {
    setTopicLoading(true);
    setTopicError(null);
    const generatedParam = filter === "not_generated" ? "no" : filter === "generated" ? "yes" : "all";
    apiFetch(`/topics?sort=${sort}&limit=${TOPIC_PAGE_SIZE}&offset=${offset}&generated=${generatedParam}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: { total: number; items: TopicItem[] }) => {
        setTopicItems(d.items);
        setTopicTotal(d.total);
      })
      .catch((e: unknown) => setTopicError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTopicLoading(false));
  }, []);

  useEffect(() => {
    fetchTopics(topicSort, topicFilter, topicOffset);
  }, [fetchTopics, topicSort, topicFilter, topicOffset]);

  function handleTopicSortChange(s: "length" | "videos" | "alpha") {
    setTopicSort(s);
    setTopicOffset(0);
  }

  function handleTopicFilterChange(f: TopicFilter) {
    setTopicFilter(f);
    setTopicOffset(0);
  }

  const fetchReels = useCallback(() => {
    setReelsLoading(true);
    setReelsError(null);
    apiFetch(`/suggestions?limit=200&bucket=reels`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: ReelsBucket) => setReels(d.reels ?? []))
      .catch((e: unknown) => setReelsError(e instanceof Error ? e.message : String(e)))
      .finally(() => setReelsLoading(false));
  }, []);

  const fetchUnused = useCallback((page: number) => {
    setUnusedLoading(true);
    setUnusedError(null);
    const offset = page * BUCKET_PAGE_SIZE;
    apiFetch(`/suggestions?limit=${BUCKET_PAGE_SIZE}&offset=${offset}&bucket=unused`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: UnusedBucket) => {
        setUnused(d.unused_videos ?? []);
        setUnusedTotal(d.unused_videos_total ?? 0);
      })
      .catch((e: unknown) => setUnusedError(e instanceof Error ? e.message : String(e)))
      .finally(() => setUnusedLoading(false));
  }, []);

  useEffect(() => { fetchReels(); }, [fetchReels]);
  useEffect(() => { fetchUnused(unusedPage); }, [fetchUnused, unusedPage]);

  function refreshAll() {
    fetchTopics(topicSort, topicFilter, topicOffset);
    fetchReels();
    fetchUnused(unusedPage);
  }

  async function generateArticle(topic: string) {
    setTopicStates((s) => ({ ...s, [topic]: { state: "generating" } }));
    try {
      const r = await apiFetch("/topics/generate-article", {
        method: "POST",
        body: JSON.stringify({ topic }),
      });
      if (!r.ok) {
        const txt = await r.text().catch(() => r.statusText);
        throw new Error(`${r.status}: ${txt}`);
      }
      const d = await r.json() as GenerateResult;
      setTopicStates((s) => ({ ...s, [topic]: { state: "done", result: d } }));
      setClusterModal({ topic, result: d });
      // Refresh topics so the generated flag updates
      fetchTopics(topicSort, topicFilter, topicOffset);
    } catch (e: unknown) {
      setTopicStates((s) => {
        const next = { ...s };
        delete next[topic];
        return next;
      });
      setGenMsg((prev) => ({
        ...prev,
        [topic]: `Error: ${e instanceof Error ? e.message : String(e)}`,
      }));
    }
  }

  async function generateUnusedArticle(video: UnusedVideo) {
    const key = video.video_id;
    setTopicStates((s) => ({ ...s, [key]: { state: "generating" } }));
    try {
      const r = await apiFetch("/topics/generate-article", {
        method: "POST",
        body: JSON.stringify({ topic: video.title }),
      });
      if (!r.ok) {
        const txt = await r.text().catch(() => r.statusText);
        throw new Error(`${r.status}: ${txt}`);
      }
      const d = await r.json() as GenerateResult;
      setTopicStates((s) => ({ ...s, [key]: { state: "done", result: d } }));
      setClusterModal({ topic: video.title, result: d });
    } catch (e: unknown) {
      setTopicStates((s) => {
        const next = { ...s };
        delete next[key];
        return next;
      });
      setGenMsg((prev) => ({
        ...prev,
        [key]: `Error: ${e instanceof Error ? e.message : String(e)}`,
      }));
    }
  }

  // Server handles filter + generated-to-back ordering across all pages.
  const filteredTopicItems: TopicItem[] = topicItems;

  const unusedTotalPages = Math.max(1, Math.ceil(unusedTotal / BUCKET_PAGE_SIZE));

  const anyLoading = reelsLoading || unusedLoading || topicLoading;

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle
        right={
          <Button onClick={refreshAll} disabled={anyLoading}>
            Refresh
          </Button>
        }
      >
        Content Opportunities
      </PageTitle>

      {/* Cluster result modal */}
      {clusterModal && (
        <ClusterResultModal
          topic={clusterModal.topic}
          result={clusterModal.result}
          onClose={() => setClusterModal(null)}
        />
      )}

      {/* Article Topics — server-paginated from /topics */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "28px 0 4px", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
          Suggested article topics to cover ({topicTotal > 0 ? topicTotal : "…"})
        </h3>
        <div style={{ display: "flex", gap: 4, alignItems: "center", marginLeft: "auto", flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, color: BRAND.sub }}>Filter:</span>
          {([["all", "All"], ["not_generated", "Not generated"], ["generated", "Generated"]] as [TopicFilter, string][]).map(([f, label]) => (
            <button
              key={f}
              onClick={() => handleTopicFilterChange(f)}
              style={{
                fontSize: 12, padding: "3px 10px", borderRadius: 6,
                border: `1px solid ${topicFilter === f ? BRAND.navyText : BRAND.border}`,
                background: topicFilter === f ? BRAND.navyText : "#fff",
                color: topicFilter === f ? "#fff" : BRAND.sub,
                cursor: "pointer", fontWeight: topicFilter === f ? 600 : 400,
              }}
            >
              {label}
            </button>
          ))}
          <span style={{ fontSize: 12, color: BRAND.sub, marginLeft: 8 }}>Sort:</span>
          {(["length", "videos", "alpha"] as const).map((s) => {
            const label = s === "length" ? "Total content length" : s === "videos" ? "Number of videos" : "A–Z";
            return (
              <button
                key={s}
                onClick={() => handleTopicSortChange(s)}
                style={{
                  fontSize: 12, padding: "3px 10px", borderRadius: 6,
                  border: `1px solid ${topicSort === s ? BRAND.navyText : BRAND.border}`,
                  background: topicSort === s ? BRAND.navyText : "#fff",
                  color: topicSort === s ? "#fff" : BRAND.sub,
                  cursor: "pointer", fontWeight: topicSort === s ? 600 : 400,
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
      <ActionNote>
        Generating an article creates a cluster draft — see the Articles tab to review and publish.
      </ActionNote>
      {topicLoading && <Loading label="Loading topics…" />}
      {topicError && <ErrorMsg>Could not load topics: {topicError}</ErrorMsg>}
      {!topicLoading && !topicError && filteredTopicItems.length === 0 && (
        <EmptyState label={topicFilter === "generated" ? "No generated topics" : topicFilter === "not_generated" ? "All topics have been generated" : "All topics covered"} />
      )}
      {!topicLoading && !topicError && filteredTopicItems.length > 0 && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {filteredTopicItems.map((t) => {
              const ts = topicStates[t.label];
              const isGenerated = t.generated || ts?.state === "done";
              const genResult = ts?.result;
              const pillarSlug = genResult?.pillar_slug ?? slugify(t.label);
              return (
                <Card
                  key={t.label}
                  style={{
                    flex: "1 1 220px", minWidth: 220,
                    opacity: isGenerated && topicFilter !== "generated" ? 0.75 : 1,
                    borderColor: isGenerated ? BRAND.border : undefined,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 4 }}>
                    <div style={{ fontWeight: 600, color: isGenerated ? BRAND.sub : BRAND.navyText, flex: 1 }}>
                      {t.label}
                    </div>
                    {isGenerated && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: "2px 7px", borderRadius: 10,
                        background: "#e6f9f0", color: "#1a7f4b", whiteSpace: "nowrap",
                      }}>
                        Generated
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 6 }}>
                    {t.num_videos} video{t.num_videos !== 1 ? "s" : ""}
                    {" · "}
                    {hms(t.total_content_length)}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
                    <button
                      onClick={() => setVideoModalLabel(t.label)}
                      style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                    >
                      View videos
                    </button>
                    <a
                      href={`https://youtu.be/${t.sample.video_id}?t=${t.sample.t}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline" }}
                    >
                      sample clip
                    </a>
                    {isGenerated && (
                      <button
                        onClick={() => navigate("articles", { cluster: pillarSlug })}
                        style={{ fontSize: 12, color: "#1a7f4b", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                      >
                        View cluster →
                      </button>
                    )}
                  </div>
                  {genMsg[t.label] && ts?.state !== "done" && (
                    <div style={{ fontSize: 12, color: genMsg[t.label].startsWith("Error") ? BRAND.red : BRAND.sub, fontStyle: "italic", marginBottom: 6 }}>
                      {genMsg[t.label]}
                    </div>
                  )}
                  {!isGenerated && (
                    <Button
                      variant="primary"
                      style={{ fontSize: 13, padding: "6px 14px" }}
                      disabled={ts?.state === "generating"}
                      onClick={() => generateArticle(t.label)}
                    >
                      {ts?.state === "generating" ? "Rendering…" : "Generate cluster articles"}
                    </Button>
                  )}
                </Card>
              );
            })}
          </div>
          {/* Server pagination for topics */}
          {topicTotal > TOPIC_PAGE_SIZE && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "10px 0 4px", fontSize: 13 }}>
              <button
                onClick={() => setTopicOffset((o) => Math.max(0, o - TOPIC_PAGE_SIZE))}
                disabled={topicOffset === 0}
                style={{
                  background: "none", border: `1px solid ${BRAND.border}`, borderRadius: 6,
                  padding: "3px 12px", cursor: topicOffset === 0 ? "not-allowed" : "pointer",
                  color: topicOffset === 0 ? BRAND.sub : BRAND.navyText, fontWeight: 600,
                }}
              >
                Prev
              </button>
              <span style={{ color: BRAND.sub }}>
                Page {Math.floor(topicOffset / TOPIC_PAGE_SIZE) + 1} of {Math.ceil(topicTotal / TOPIC_PAGE_SIZE)} · {topicTotal} topics
              </span>
              <button
                onClick={() => setTopicOffset((o) => o + TOPIC_PAGE_SIZE)}
                disabled={topicOffset + TOPIC_PAGE_SIZE >= topicTotal}
                style={{
                  background: "none", border: `1px solid ${BRAND.border}`, borderRadius: 6,
                  padding: "3px 12px", cursor: topicOffset + TOPIC_PAGE_SIZE >= topicTotal ? "not-allowed" : "pointer",
                  color: topicOffset + TOPIC_PAGE_SIZE >= topicTotal ? BRAND.sub : BRAND.navyText, fontWeight: 600,
                }}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      {videoModalLabel && (
        <TopicVideoModal label={videoModalLabel} onClose={() => setVideoModalLabel(null)} />
      )}

      {/* Reels */}
      <SectionHeader>
        Reels ready to schedule ({reels.length})
      </SectionHeader>
      <ActionNote>
        These approved clips are ready to post — schedule them in{" "}
        <strong>Clip Studio</strong> or submit via <strong>Video Approval</strong>.
      </ActionNote>
      {reelsLoading && <Loading label="Loading reels…" />}
      {reelsError && <ErrorMsg>Could not load reels: {reelsError}</ErrorMsg>}
      {!reelsLoading && !reelsError && reels.length === 0 && (
        <EmptyState label="No reels pending" />
      )}
      {!reelsLoading && !reelsError && reels.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {reels.map((r) => (
            <Card
              key={r.series_id}
              style={{ flex: "1 1 220px", minWidth: 220 }}
            >
              <div style={{ fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                {r.title}
              </div>
              <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 10 }}>
                {r.parts_count} part{r.parts_count !== 1 ? "s" : ""}
                {" · "}
                <a
                  href={`https://youtu.be/${r.video_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: BRAND.navyText }}
                >
                  source video
                </a>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Badge tone="blue">Approved</Badge>
                <a
                  href="#"
                  onClick={(e) => { e.preventDefault(); }}
                  style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", cursor: "pointer" }}
                >
                  Open in Clip Studio
                </a>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Unused Videos */}
      <SectionHeader>
        Unused videos ({unusedTotal > 0 ? unusedTotal : unusedLoading ? "…" : unused.length})
      </SectionHeader>
      <p style={{ fontSize: 13, color: BRAND.sub, margin: "-6px 0 14px" }}>
        A video is "used" when it is referenced in a published or draft article, or included in a
        video mini-series. These videos have transcript or topic data but are not yet used anywhere.
      </p>
      {unusedLoading && <Loading label="Loading unused videos…" />}
      {unusedError && <ErrorMsg>Could not load unused videos: {unusedError}</ErrorMsg>}
      {!unusedLoading && !unusedError && unused.length === 0 && (
        <EmptyState label="All videos used" />
      )}
      {!unusedLoading && !unusedError && unused.length > 0 && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {unused.map((v) => (
              <Card
                key={v.video_id}
                style={{ flex: "1 1 260px", minWidth: 260 }}
              >
                <div
                  style={{
                    fontWeight: 600,
                    color: BRAND.navyText,
                    marginBottom: 2,
                    fontSize: 14,
                  }}
                >
                  <a
                    href={`https://youtu.be/${v.video_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: BRAND.navyText, textDecoration: "none" }}
                  >
                    {v.title}
                  </a>
                </div>
                {v.duration > 0 && (
                  <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 8 }}>
                    {hms(v.duration)}
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
                  {genMsg[v.video_id] && topicStates[v.video_id]?.state !== "done" && (
                    <div style={{ fontSize: 12, color: genMsg[v.video_id].startsWith("Error") ? BRAND.red : BRAND.sub, fontStyle: "italic", width: "100%" }}>
                      {genMsg[v.video_id]}
                    </div>
                  )}
                  {topicStates[v.video_id]?.state === "done" ? (
                    <Button
                      variant="primary"
                      style={{ fontSize: 12, padding: "5px 12px" }}
                      onClick={() => navigate("articles", { cluster: topicStates[v.video_id].result?.pillar_slug ?? slugify(v.title) })}
                    >
                      View
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      style={{ fontSize: 12, padding: "5px 12px" }}
                      disabled={topicStates[v.video_id]?.state === "generating"}
                      onClick={() => generateUnusedArticle(v)}
                    >
                      {topicStates[v.video_id]?.state === "generating" ? "Rendering…" : "Generate cluster articles"}
                    </Button>
                  )}
                  <a
                    href={`/video/proposals?video_id=${v.video_id}`}
                    style={{
                      fontSize: 12,
                      padding: "5px 12px",
                      borderRadius: 8,
                      border: `1px solid ${BRAND.border}`,
                      color: BRAND.navyText,
                      textDecoration: "none",
                      fontWeight: 600,
                      display: "inline-block",
                    }}
                  >
                    Propose mini-series
                  </a>
                </div>
              </Card>
            ))}
          </div>
          <Paginator
            page={unusedPage}
            totalPages={unusedTotalPages}
            onPrev={() => setUnusedPage((p) => Math.max(0, p - 1))}
            onNext={() => setUnusedPage((p) => Math.min(unusedTotalPages - 1, p + 1))}
          />
        </>
      )}
    </main>
  );
}
