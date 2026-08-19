import { useEffect, useState, useCallback, useContext } from "react";
import { apiFetch } from "../api";
import { hms, ytLink, BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";
import { NavContext } from "../App";
import { errText } from "../lib/errors";

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
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: TopicVideo[]) => setVideos(data))
      .catch((e: unknown) => setVideoErr(e instanceof Error ? e.message : String(e)));
  }, [label]);

  useEffect(() => {
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
                        href={ytLink(v.video_id, v.start)}
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

interface GraphSubject {
  label: string;
  slug: string;
  n_videos: number;
  yt_views: number;
  yt_comments: number;
  grounding_seconds: number;
  opportunity: number;
  aio: number;
  covered: boolean;
}
interface GraphGenre {
  id: string;
  label: string;
  publishable: boolean;
  density: string;
  color: string;
  n_unpublished: number;
  subjects: GraphSubject[];
}
interface GraphPayload {
  genres: GraphGenre[];
  diversity: { shannon: number; concentrated: boolean; flags: { genre: string; flag: string }[] };
}

const INBOX_LIMIT = 12;

function inboxFromGraph(g: GraphPayload | null): Array<GraphSubject & { genre: string; genreId: string; density: string }> {
  if (!g) return [];
  const rows: Array<GraphSubject & { genre: string; genreId: string; density: string }> = [];
  for (const genre of g.genres) {
    if (!genre.publishable || genre.id === "internal") continue;
    for (const s of genre.subjects) {
      if (s.covered) continue;
      rows.push({ ...s, genre: genre.label, genreId: genre.id, density: genre.density });
    }
  }
  rows.sort((a, b) => b.opportunity - a.opportunity || b.yt_comments - a.yt_comments);
  return rows.slice(0, INBOX_LIMIT);
}

export function Opportunities() {
  const { navigate } = useContext(NavContext);

  const [topicStates, setTopicStates] = useState<Record<string, { state: "generating" | "done"; result?: GenerateResult }>>({});
  const [genMsg, setGenMsg] = useState<Record<string, string>>({});
  const [clusterModal, setClusterModal] = useState<{ topic: string; result: GenerateResult } | null>(null);
  const [videoModalLabel, setVideoModalLabel] = useState<string | null>(null);

  const [articleGraph, setArticleGraph] = useState<GraphPayload | null>(null);
  const [faqGraph, setFaqGraph] = useState<GraphPayload | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState<string | null>(null);

  const [reels, setReels] = useState<Reel[]>([]);
  const [reelsLoading, setReelsLoading] = useState(true);
  const [reelsError, setReelsError] = useState<string | null>(null);

  const [unused, setUnused] = useState<UnusedVideo[]>([]);
  const [unusedTotal, setUnusedTotal] = useState(0);
  const [unusedPage, setUnusedPage] = useState(0);
  const [unusedLoading, setUnusedLoading] = useState(true);
  const [unusedError, setUnusedError] = useState<string | null>(null);

  const fetchGraph = useCallback(() => {
    setGraphLoading(true);
    setGraphError(null);
    Promise.all([
      apiFetch("/topic-graph?kind=articles&published=no").then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      }),
      apiFetch("/topic-graph?kind=faqs&published=no").then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      }),
    ])
      .then(([arts, faqs]: [GraphPayload, GraphPayload]) => {
        setArticleGraph(arts);
        setFaqGraph(faqs);
      })
      .catch((e: unknown) => setGraphError(e instanceof Error ? e.message : String(e)))
      .finally(() => setGraphLoading(false));
  }, []);

  const fetchReels = useCallback(() => {
    setReelsLoading(true);
    setReelsError(null);
    apiFetch(`/suggestions?limit=200&bucket=reels`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
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
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((d: UnusedBucket) => {
        setUnused(d.unused_videos ?? []);
        setUnusedTotal(d.unused_videos_total ?? 0);
      })
      .catch((e: unknown) => setUnusedError(e instanceof Error ? e.message : String(e)))
      .finally(() => setUnusedLoading(false));
  }, []);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);
  useEffect(() => { fetchReels(); }, [fetchReels]);
  useEffect(() => { fetchUnused(unusedPage); }, [fetchUnused, unusedPage]);

  function refreshAll() {
    fetchGraph();
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
      fetchGraph();
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

  const articleInbox = inboxFromGraph(articleGraph);
  const faqInbox = inboxFromGraph(faqGraph);
  const underServed = new Set(
    (articleGraph?.diversity.flags ?? [])
      .filter((f) => f.flag === "under_served" || f.flag === "empty")
      .map((f) => f.genre),
  );
  const unusedTotalPages = Math.max(1, Math.ceil(unusedTotal / BUCKET_PAGE_SIZE));
  const anyLoading = reelsLoading || unusedLoading || graphLoading;

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

      {/* Scored article inbox — from topic-graph, not the 8k variant list */}
      <SectionHeader>This week — articles to write ({articleInbox.length})</SectionHeader>
      <ActionNote>
        Ranked by opportunity (YouTube engagement, grounding, named-entity AIO, genre diversity).
        Internal topics never appear. Open the Topic Graph on Articles for the full map.
      </ActionNote>
      {graphLoading && <Loading label="Scoring topics…" />}
      {graphError && <ErrorMsg>Could not load topic graph: {graphError}</ErrorMsg>}
      {!graphLoading && !graphError && articleInbox.length === 0 && (
        <EmptyState label="No uncovered article subjects in the queue" />
      )}
      {!graphLoading && !graphError && articleInbox.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {articleInbox.map((t) => {
            const ts = topicStates[t.label];
            return (
              <Card key={t.slug} style={{ padding: 14 }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <div style={{ fontWeight: 600, color: BRAND.navyText }}>{t.label}</div>
                    <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 4 }}>
                      {t.genre}
                      {" · "}{t.n_videos} video{t.n_videos !== 1 ? "s" : ""}
                      {" · "}{Math.round(t.grounding_seconds / 60)} min
                      {" · "}{t.yt_comments} comments
                      {" · opp "}{t.opportunity.toFixed(2)}
                      {t.aio ? " · AIO entity" : ""}
                      {t.density === "under_served" || t.density === "empty" ? " · under-served genre" : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <Button variant="ghost" style={{ fontSize: 12, padding: "5px 10px" }} onClick={() => setVideoModalLabel(t.label)}>
                      Videos
                    </Button>
                    <Button variant="ghost" style={{ fontSize: 12, padding: "5px 10px" }} onClick={() => navigate("articles")}>
                      Graph
                    </Button>
                    <Button
                      style={{ fontSize: 12, padding: "5px 12px" }}
                      disabled={ts?.state === "generating"}
                      onClick={() => generateArticle(t.label)}
                    >
                      {ts?.state === "generating" ? "Generating…" : "Generate cluster"}
                    </Button>
                  </div>
                </div>
                {genMsg[t.label] && (
                  <div style={{ fontSize: 12, color: BRAND.red, marginTop: 6 }}>{genMsg[t.label]}</div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      <SectionHeader>FAQs to answer ({faqInbox.length})</SectionHeader>
      <ActionNote>Unanswered questions, same score as the FAQ graph. Full map is on FAQ Builder.</ActionNote>
      {!graphLoading && faqInbox.length === 0 && <EmptyState label="No FAQ gaps in the queue" />}
      {faqInbox.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {faqInbox.map((t) => (
            <Card key={t.slug} style={{ padding: "10px 14px" }}>
              <div style={{ fontWeight: 600, color: BRAND.navyText }}>{t.label}</div>
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 3 }}>
                {t.genre} · {t.yt_comments} comments · opp {t.opportunity.toFixed(2)}
              </div>
              <button
                type="button"
                onClick={() => navigate("faq")}
                style={{ marginTop: 6, background: "none", border: "none", padding: 0, color: BRAND.red, fontWeight: 600, fontSize: 12, cursor: "pointer" }}
              >
                Open FAQ Builder →
              </button>
            </Card>
          ))}
        </div>
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
                <button
                  type="button"
                  onClick={() => navigate("clip-studio", { video: r.video_id })}
                  style={{ fontSize: 12, color: BRAND.navyText, textDecoration: "underline", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                >
                  Open in Clip Studio
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Unused Videos */}
      <SectionHeader>
        Unused footage ({unusedTotal > 0 ? unusedTotal : unusedLoading ? "…" : unused.length})
        {underServed.size > 0 ? ` — under-served: ${[...underServed].slice(0, 3).join(", ")}` : ""}
      </SectionHeader>
      <p style={{ fontSize: 13, color: BRAND.sub, margin: "-6px 0 14px" }}>
        Footage not yet in an article or reel. Use it to ground an under-served genre — do not
        generate an article from the video title.
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
                  <Button
                    variant="ghost"
                    style={{ fontSize: 12, padding: "5px 12px" }}
                    onClick={() => navigate("clip-studio", { video: v.video_id })}
                  >
                    Open in Clip Studio
                  </Button>
                  <Button
                    variant="ghost"
                    style={{ fontSize: 12, padding: "5px 12px" }}
                    onClick={() => navigate("articles")}
                  >
                    Topic Graph
                  </Button>
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
