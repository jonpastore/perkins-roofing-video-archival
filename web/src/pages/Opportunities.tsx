import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../api";
import { hms, BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";

interface ArticleTopic {
  label: string;
  num_videos: number;
  total_content_length: number;
  count: number;
  sample: { video_id: string; t: number };
}

interface Reel {
  series_id: number;
  video_id: string;
  title: string;
  parts_count: number;
}

interface FaqItem {
  question: string;
  video_id: string;
  title: string;
  t: number;
}

interface UnusedVideo {
  video_id: string;
  title: string;
}

interface Suggestions {
  article_topics: ArticleTopic[];
  article_topics_total: number;
  reels: Reel[];
  faqs: FaqItem[];
  faqs_total: number;
  unused_videos: UnusedVideo[];
  unused_videos_total: number;
}

interface TopicItem {
  label: string;
  count: number;
  num_videos: number;
  total_content_length: number;
  sample: { video_id: string; t: number };
}

interface TopicVideo {
  video_id: string;
  title: string;
  duration: number;
  start: number;
}

const PAGE_SIZE = 15;
const TOPIC_PAGE_SIZE = 24;
const FETCH_LIMIT = 200;

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

function TopicVideoModal({
  label,
  onClose,
}: {
  label: string;
  onClose: () => void;
}) {
  const [videos, setVideos] = useState<TopicVideo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/topics/videos?label=${encodeURIComponent(label)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: TopicVideo[]) => setVideos(data))
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, [label]);

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
          background: "#fff", borderRadius: 14, width: "min(600px, 94vw)",
          maxHeight: "80vh", display: "flex", flexDirection: "column",
          boxShadow: "0 8px 32px rgba(16,24,40,0.18)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "18px 24px 12px" }}>
          <h3 style={{ margin: 0, fontSize: 16, color: BRAND.navyText, fontWeight: 700 }}>{label}</h3>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: BRAND.sub, lineHeight: 1 }}
          >
            ×
          </button>
        </div>
        <div style={{ overflowY: "auto", flex: 1, padding: "0 24px 20px" }}>
          {!videos && !err && <Loading label="Loading videos…" />}
          {err && <ErrorMsg>Could not load videos: {err}</ErrorMsg>}
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

export function Opportunities() {
  const [data, setData] = useState<Suggestions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [genMsg, setGenMsg] = useState<Record<string, string>>({});

  // Server-paginated topics section
  const [topicSort, setTopicSort] = useState<"length" | "videos" | "alpha">("length");
  const [topicOffset, setTopicOffset] = useState(0);
  const [topicItems, setTopicItems] = useState<TopicItem[]>([]);
  const [topicTotal, setTopicTotal] = useState(0);
  const [topicLoading, setTopicLoading] = useState(true);
  const [topicError, setTopicError] = useState<string | null>(null);
  const [videoModalLabel, setVideoModalLabel] = useState<string | null>(null);

  // Pagination state for other buckets (0-indexed page)
  const [faqPage, setFaqPage] = useState(0);
  const [unusedPage, setUnusedPage] = useState(0);

  const fetchTopics = useCallback((sort: "length" | "videos" | "alpha", offset: number) => {
    setTopicLoading(true);
    setTopicError(null);
    apiFetch(`/topics?sort=${sort}&limit=${TOPIC_PAGE_SIZE}&offset=${offset}`)
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
    fetchTopics(topicSort, topicOffset);
  }, [fetchTopics, topicSort, topicOffset]);

  function handleTopicSortChange(s: "length" | "videos" | "alpha") {
    setTopicSort(s);
    setTopicOffset(0);
  }

  function fetchSuggestions() {
    setLoading(true);
    setError(null);
    apiFetch(`/suggestions?limit=${FETCH_LIMIT}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: Suggestions) => {
        setData(d);
        setFaqPage(0);
        setUnusedPage(0);
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e))
      )
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchSuggestions();
  }, []);

  function generateArticle(topic: string) {
    setGenerating(topic);
    apiFetch("/topics/generate-article", {
      method: "POST",
      body: JSON.stringify({ topic }),
    })
      .then((r) => r.json())
      .then((d: { slug: string; status: string }) => {
        setGenMsg((prev) => ({
          ...prev,
          [topic]: `Draft created: ${d.slug} (${d.status})`,
        }));
      })
      .catch((e: unknown) => {
        setGenMsg((prev) => ({
          ...prev,
          [topic]: `Error: ${e instanceof Error ? e.message : String(e)}`,
        }));
      })
      .finally(() => setGenerating(null));
  }

  function generateUnusedArticle(video: UnusedVideo) {
    const key = video.video_id;
    setGenerating(key);
    apiFetch("/topics/generate-article", {
      method: "POST",
      body: JSON.stringify({ topic: video.title }),
    })
      .then((r) => r.json())
      .then((d: { slug: string; status: string }) => {
        setGenMsg((prev) => ({
          ...prev,
          [key]: `Draft created: ${d.slug} (${d.status})`,
        }));
      })
      .catch((e: unknown) => {
        setGenMsg((prev) => ({
          ...prev,
          [key]: `Error: ${e instanceof Error ? e.message : String(e)}`,
        }));
      })
      .finally(() => setGenerating(null));
  }

  // Compute paged slices for other buckets
  const faqs = data?.faqs ?? [];
  const faqsTotal = data?.faqs_total ?? 0;
  const faqTotalPages = Math.max(1, Math.ceil(faqs.length / PAGE_SIZE));
  const faqSlice = faqs.slice(faqPage * PAGE_SIZE, (faqPage + 1) * PAGE_SIZE);

  const unused = data?.unused_videos ?? [];
  const unusedTotal = data?.unused_videos_total ?? 0;
  const unusedTotalPages = Math.max(1, Math.ceil(unused.length / PAGE_SIZE));
  const unusedSlice = unused.slice(unusedPage * PAGE_SIZE, (unusedPage + 1) * PAGE_SIZE);

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle
        right={
          <Button onClick={() => { fetchSuggestions(); fetchTopics(topicSort, topicOffset); }} disabled={loading}>
            Refresh
          </Button>
        }
      >
        Content Opportunities
      </PageTitle>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {/* Article Topics — server-paginated from /topics */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "28px 0 4px" }}>
        <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
          Suggested article topics to cover ({topicTotal > 0 ? topicTotal : "…"})
        </h3>
        <div style={{ display: "flex", gap: 4, alignItems: "center", marginLeft: "auto" }}>
          <span style={{ fontSize: 12, color: BRAND.sub }}>Sort:</span>
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
      {!topicLoading && !topicError && topicItems.length === 0 && (
        <EmptyState label="All topics covered" />
      )}
      {!topicLoading && !topicError && topicItems.length > 0 && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {topicItems.map((t) => (
              <Card key={t.label} style={{ flex: "1 1 220px", minWidth: 220 }}>
                <div style={{ fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                  {t.label}
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
                </div>
                {genMsg[t.label] ? (
                  <div style={{ fontSize: 12, color: BRAND.sub, fontStyle: "italic" }}>
                    {genMsg[t.label]}
                  </div>
                ) : (
                  <Button
                    variant="primary"
                    style={{ fontSize: 13, padding: "6px 14px" }}
                    disabled={generating === t.label}
                    onClick={() => generateArticle(t.label)}
                  >
                    {generating === t.label ? "Generating…" : "Generate cluster article"}
                  </Button>
                )}
              </Card>
            ))}
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

      {!loading && !error && data && (
        <>
          {/* Reels */}
          <SectionHeader>
            Reels ready to schedule ({data.reels.length})
          </SectionHeader>
          <ActionNote>
            These approved clips are ready to post — schedule them in{" "}
            <strong>Clip Studio</strong> or submit via <strong>Video Approval</strong>.
          </ActionNote>
          {data.reels.length === 0 ? (
            <EmptyState label="No reels pending" />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {data.reels.map((r) => (
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

          {/* FAQs */}
          <SectionHeader>
            FAQ candidates ({faqs.length}
            {faqsTotal > faqs.length ? ` of ${faqsTotal}` : ""})
          </SectionHeader>
          <ActionNote>
            These are candidate questions from your video content. Use the{" "}
            <strong>FAQ tab</strong> to mine and generate answers — the full FAQ builder
            (mine + batch answer) lives there.
          </ActionNote>
          {faqs.length === 0 ? (
            <EmptyState label="No FAQ gaps found" />
          ) : (
            <>
              <Card style={{ padding: 0, overflow: "hidden" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 14,
                  }}
                >
                  <thead>
                    <tr
                      style={{
                        borderBottom: `2px solid ${BRAND.border}`,
                        textAlign: "left",
                      }}
                    >
                      <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>
                        Question
                      </th>
                      <th
                        style={{
                          padding: "10px 16px",
                          color: BRAND.sub,
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                        }}
                      >
                        Source clip
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {faqSlice.map((f, i) => (
                      <tr
                        key={`${f.video_id}-${f.t}-${i}`}
                        style={{ borderBottom: `1px solid ${BRAND.border}` }}
                      >
                        <td style={{ padding: "10px 16px" }}>{f.question}</td>
                        <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                          <a
                            href={`https://youtu.be/${f.video_id}?t=${f.t}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: BRAND.navyText, fontWeight: 500, textDecoration: "none" }}
                          >
                            {f.title} @{hms(f.t)}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Paginator
                page={faqPage}
                totalPages={faqTotalPages}
                onPrev={() => setFaqPage((p) => Math.max(0, p - 1))}
                onNext={() => setFaqPage((p) => Math.min(faqTotalPages - 1, p + 1))}
              />
              <p style={{ fontSize: 12, color: BRAND.sub, margin: "8px 0 0", fontStyle: "italic" }}>
                Open the <strong>FAQ tab</strong> to mine questions and generate answers in bulk.
              </p>
            </>
          )}

          {/* Unused Videos */}
          <SectionHeader>
            Unused videos ({unused.length}
            {unusedTotal > unused.length ? ` of ${unusedTotal}` : ""})
          </SectionHeader>
          <p style={{ fontSize: 13, color: BRAND.sub, margin: "-6px 0 14px" }}>
            A video is "used" when it is referenced in a published or draft article, or included in a
            video mini-series. These videos have transcript or topic data but are not yet used anywhere.
          </p>
          {unused.length === 0 ? (
            <EmptyState label="All videos used" />
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {unusedSlice.map((v) => (
                  <Card
                    key={v.video_id}
                    style={{ flex: "1 1 260px", minWidth: 260 }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        color: BRAND.navyText,
                        marginBottom: 4,
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
                    <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                      {genMsg[v.video_id] ? (
                        <div style={{ fontSize: 12, color: BRAND.sub, fontStyle: "italic" }}>
                          {genMsg[v.video_id]}
                        </div>
                      ) : (
                        <Button
                          variant="primary"
                          style={{ fontSize: 12, padding: "5px 12px" }}
                          disabled={generating === v.video_id}
                          onClick={() => generateUnusedArticle(v)}
                        >
                          {generating === v.video_id ? "Generating…" : "Generate cluster article"}
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
        </>
      )}
    </main>
  );
}
