import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";

interface ArticleTopic {
  label: string;
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

interface FaqAnswer {
  answer: string;
  citations: { url: string; title?: string }[];
}

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

function TotalNote({ shown, total, onShowMore }: { shown: number; total: number; onShowMore?: () => void }) {
  if (total <= shown) return null;
  return (
    <p style={{ fontSize: 12, color: BRAND.sub, margin: "6px 0 0" }}>
      Showing {shown} of {total}.{" "}
      {onShowMore && (
        <button
          onClick={onShowMore}
          style={{ background: "none", border: "none", color: BRAND.navyText, cursor: "pointer", fontWeight: 600, padding: 0, fontSize: 12 }}
        >
          Show more
        </button>
      )}
    </p>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <Badge tone="green">{label}</Badge>
    </div>
  );
}

export function Opportunities() {
  const [data, setData] = useState<Suggestions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [genMsg, setGenMsg] = useState<Record<string, string>>({});
  const [limit, setLimit] = useState(25);

  // FAQ answer state: key = `${video_id}-${t}`, value = answer payload or "loading"/"error"
  const [faqAnswers, setFaqAnswers] = useState<Record<string, FaqAnswer | "loading" | string>>({});

  function fetchSuggestions(fetchLimit = limit) {
    setLoading(true);
    setError(null);
    apiFetch(`/suggestions?limit=${fetchLimit}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: Suggestions) => setData(d))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e))
      )
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchSuggestions();
  }, []);

  function handleShowMore() {
    const next = limit + 25;
    setLimit(next);
    fetchSuggestions(next);
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

  function buildFaqAnswer(faq: FaqItem) {
    const key = `${faq.video_id}-${faq.t}`;
    setFaqAnswers((prev) => ({ ...prev, [key]: "loading" }));
    apiFetch("/faq/build", {
      method: "POST",
      body: JSON.stringify({ questions: [faq.question] }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: { faq: { question: string; answer: string; citations: { url: string; title?: string }[] }[] }) => {
        const item = d.faq[0];
        setFaqAnswers((prev) => ({
          ...prev,
          [key]: { answer: item?.answer ?? "", citations: item?.citations ?? [] },
        }));
      })
      .catch((e: unknown) => {
        setFaqAnswers((prev) => ({
          ...prev,
          [key]: `Error: ${e instanceof Error ? e.message : String(e)}`,
        }));
      });
  }

  function toggleFaqAnswer(faq: FaqItem) {
    const key = `${faq.video_id}-${faq.t}`;
    const existing = faqAnswers[key];
    if (existing === undefined) {
      // Not yet fetched — build it
      buildFaqAnswer(faq);
    } else if (existing === "loading") {
      // Already in flight, do nothing
    } else {
      // Already have it (or errored) — toggle off by removing
      setFaqAnswers((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  }

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle
        right={
          <Button onClick={() => fetchSuggestions(limit)} disabled={loading}>
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
          <SectionHeader>
            Article topics to cover ({data.article_topics.length}
            {data.article_topics_total > data.article_topics.length
              ? ` of ${data.article_topics_total}`
              : ""}
            ) — ranked by how many videos cover the topic
          </SectionHeader>
          {data.article_topics.length === 0 ? (
            <EmptyState label="All topics covered" />
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {data.article_topics.map((t) => (
                  <Card
                    key={t.label}
                    style={{ flex: "1 1 220px", minWidth: 220 }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        color: BRAND.navyText,
                        marginBottom: 4,
                      }}
                    >
                      {t.label}
                    </div>
                    <div
                      style={{
                        fontSize: 13,
                        color: BRAND.sub,
                        marginBottom: 10,
                      }}
                    >
                      {t.count} video{t.count !== 1 ? "s" : ""}
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
                      <div
                        style={{
                          fontSize: 12,
                          color: BRAND.sub,
                          fontStyle: "italic",
                        }}
                      >
                        {genMsg[t.label]}
                      </div>
                    ) : (
                      <Button
                        variant="primary"
                        style={{ fontSize: 13, padding: "6px 14px" }}
                        disabled={generating === t.label}
                        onClick={() => generateArticle(t.label)}
                      >
                        {generating === t.label
                          ? "Generating…"
                          : "Generate cluster article"}
                      </Button>
                    )}
                  </Card>
                ))}
              </div>
              <TotalNote
                shown={data.article_topics.length}
                total={data.article_topics_total}
                onShowMore={handleShowMore}
              />
            </>
          )}

          {/* Reels */}
          <SectionHeader>
            Reels ready to schedule ({data.reels.length})
          </SectionHeader>
          {data.reels.length === 0 ? (
            <EmptyState label="No reels pending" />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {data.reels.map((r) => (
                <Card
                  key={r.series_id}
                  style={{ flex: "1 1 220px", minWidth: 220 }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      color: BRAND.navyText,
                      marginBottom: 4,
                    }}
                  >
                    {r.title}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: BRAND.sub,
                      marginBottom: 10,
                    }}
                  >
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
                  <Badge tone="blue">Approved</Badge>
                </Card>
              ))}
            </div>
          )}

          {/* FAQs */}
          <SectionHeader>
            FAQs to build ({data.faqs.length}
            {data.faqs_total > data.faqs.length ? ` of ${data.faqs_total}` : ""})
          </SectionHeader>
          {data.faqs.length === 0 ? (
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
                      <th
                        style={{
                          padding: "10px 16px",
                          color: BRAND.sub,
                          fontWeight: 600,
                        }}
                      >
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
                        Source
                      </th>
                      <th
                        style={{
                          padding: "10px 16px",
                          color: BRAND.sub,
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                        }}
                      >
                        Answer
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.faqs.map((f, i) => {
                      const key = `${f.video_id}-${f.t}`;
                      const answerState = faqAnswers[key];
                      const isLoading = answerState === "loading";
                      const isOpen = answerState !== undefined;
                      const isError = typeof answerState === "string" && answerState !== "loading";
                      const answerData = typeof answerState === "object" ? answerState : null;
                      return (
                        <>
                          <tr
                            key={`${key}-${i}-row`}
                            style={{ borderBottom: isOpen ? "none" : `1px solid ${BRAND.border}` }}
                          >
                            <td style={{ padding: "10px 16px" }}>{f.question}</td>
                            <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                              <a
                                href={`https://youtu.be/${f.video_id}?t=${f.t}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{
                                  color: BRAND.navyText,
                                  fontWeight: 500,
                                  textDecoration: "none",
                                }}
                              >
                                {f.title} @{f.t}s
                              </a>
                            </td>
                            <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                              <Button
                                variant="ghost"
                                style={{ fontSize: 12, padding: "4px 10px" }}
                                disabled={isLoading}
                                onClick={() => toggleFaqAnswer(f)}
                              >
                                {isLoading
                                  ? "Building…"
                                  : isOpen
                                  ? "Hide answer"
                                  : "Show answer / Build"}
                              </Button>
                            </td>
                          </tr>
                          {isOpen && (
                            <tr
                              key={`${key}-${i}-answer`}
                              style={{ borderBottom: `1px solid ${BRAND.border}`, background: BRAND.bg }}
                            >
                              <td colSpan={3} style={{ padding: "12px 16px" }}>
                                {isError && (
                                  <p style={{ color: BRAND.red, fontSize: 13, margin: 0 }}>{answerState}</p>
                                )}
                                {answerData && (
                                  <>
                                    <p style={{ margin: "0 0 8px", fontSize: 14, color: BRAND.ink, lineHeight: 1.55 }}>
                                      {answerData.answer}
                                    </p>
                                    {answerData.citations.length > 0 && (
                                      <div style={{ fontSize: 12, color: BRAND.sub }}>
                                        <strong>Sources:</strong>{" "}
                                        {answerData.citations.map((c, ci) => (
                                          <span key={ci}>
                                            {ci > 0 && " · "}
                                            <a
                                              href={c.url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              style={{ color: BRAND.navyText }}
                                            >
                                              {c.title || c.url}
                                            </a>
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </>
                                )}
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
              <TotalNote
                shown={data.faqs.length}
                total={data.faqs_total}
                onShowMore={handleShowMore}
              />
            </>
          )}

          {/* Unused Videos */}
          <SectionHeader>
            Unused videos ({data.unused_videos.length}
            {data.unused_videos_total > data.unused_videos.length
              ? ` of ${data.unused_videos_total}`
              : ""})
          </SectionHeader>
          <p style={{ fontSize: 13, color: BRAND.sub, margin: "-6px 0 14px" }}>
            A video is "used" when it is referenced in a published or draft article, or included in a
            video mini-series. These videos have transcript or topic data but are not yet used anywhere.
          </p>
          {data.unused_videos.length === 0 ? (
            <EmptyState label="All videos used" />
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {data.unused_videos.map((v) => (
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
              <TotalNote
                shown={data.unused_videos.length}
                total={data.unused_videos_total}
                onShowMore={handleShowMore}
              />
            </>
          )}
        </>
      )}
    </main>
  );
}
