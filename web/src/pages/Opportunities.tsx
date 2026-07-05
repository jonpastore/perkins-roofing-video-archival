import { useEffect, useState } from "react";
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

const PAGE_SIZE = 15;
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

function formatContentLength(chars: number): string {
  if (chars === 0) return "no transcript";
  const minutes = Math.round(chars / 900); // ~900 chars/min spoken word
  if (minutes < 1) return `~${chars} chars`;
  return `~${minutes} min`;
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
  const [topicSort, setTopicSort] = useState<"length" | "videos">("length");

  // Pagination state per bucket (0-indexed page)
  const [topicPage, setTopicPage] = useState(0);
  const [faqPage, setFaqPage] = useState(0);
  const [unusedPage, setUnusedPage] = useState(0);

  function fetchSuggestions(fetchSort = topicSort) {
    setLoading(true);
    setError(null);
    apiFetch(`/suggestions?limit=${FETCH_LIMIT}&sort=${fetchSort}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: Suggestions) => {
        setData(d);
        setTopicPage(0);
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

  function handleSortChange(s: "length" | "videos") {
    setTopicSort(s);
    fetchSuggestions(s);
  }

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

  // Compute paged slices
  const topics = data?.article_topics ?? [];
  const topicsTotal = data?.article_topics_total ?? 0;
  const topicTotalPages = Math.max(1, Math.ceil(topics.length / PAGE_SIZE));
  const topicSlice = topics.slice(topicPage * PAGE_SIZE, (topicPage + 1) * PAGE_SIZE);

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
          <Button onClick={() => fetchSuggestions(topicSort)} disabled={loading}>
            Refresh
          </Button>
        }
      >
        Content Opportunities
      </PageTitle>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && data && (
        <>
          {/* Article Topics */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "28px 0 4px" }}>
            <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
              Suggested article topics to cover ({topics.length}
              {topicsTotal > topics.length ? ` of ${topicsTotal}` : ""})
            </h3>
            <div style={{ display: "flex", gap: 4, alignItems: "center", marginLeft: "auto" }}>
              <span style={{ fontSize: 12, color: BRAND.sub }}>Sort:</span>
              <button
                onClick={() => handleSortChange("length")}
                style={{
                  fontSize: 12,
                  padding: "3px 10px",
                  borderRadius: 6,
                  border: `1px solid ${topicSort === "length" ? BRAND.navyText : BRAND.border}`,
                  background: topicSort === "length" ? BRAND.navyText : "#fff",
                  color: topicSort === "length" ? "#fff" : BRAND.sub,
                  cursor: "pointer",
                  fontWeight: topicSort === "length" ? 600 : 400,
                }}
              >
                Total content length
              </button>
              <button
                onClick={() => handleSortChange("videos")}
                style={{
                  fontSize: 12,
                  padding: "3px 10px",
                  borderRadius: 6,
                  border: `1px solid ${topicSort === "videos" ? BRAND.navyText : BRAND.border}`,
                  background: topicSort === "videos" ? BRAND.navyText : "#fff",
                  color: topicSort === "videos" ? "#fff" : BRAND.sub,
                  cursor: "pointer",
                  fontWeight: topicSort === "videos" ? 600 : 400,
                }}
              >
                Number of videos
              </button>
            </div>
          </div>
          <ActionNote>
            Generating an article creates a cluster draft — see the Articles tab to review and publish.
          </ActionNote>
          {topics.length === 0 ? (
            <EmptyState label="All topics covered" />
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {topicSlice.map((t) => (
                  <Card
                    key={t.label}
                    style={{ flex: "1 1 220px", minWidth: 220 }}
                  >
                    <div style={{ fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
                      {t.label}
                    </div>
                    <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 10 }}>
                      {t.num_videos} video{t.num_videos !== 1 ? "s" : ""}
                      {" · "}
                      {formatContentLength(t.total_content_length)}
                      {" · "}
                      <a
                        href={`https://youtu.be/${t.sample.video_id}?t=${t.sample.t}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: BRAND.navyText }}
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
              <Paginator
                page={topicPage}
                totalPages={topicTotalPages}
                onPrev={() => setTopicPage((p) => Math.max(0, p - 1))}
                onNext={() => setTopicPage((p) => Math.min(topicTotalPages - 1, p + 1))}
              />
            </>
          )}

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
