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
  t: number;
}

interface UnusedVideo {
  video_id: string;
  title: string;
}

interface Suggestions {
  article_topics: ArticleTopic[];
  reels: Reel[];
  faqs: FaqItem[];
  unused_videos: UnusedVideo[];
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

  function fetchSuggestions() {
    setLoading(true);
    setError(null);
    apiFetch("/suggestions")
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

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle
        right={
          <Button onClick={fetchSuggestions} disabled={loading}>
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
            Article topics to cover ({data.article_topics.length})
          </SectionHeader>
          {data.article_topics.length === 0 ? (
            <EmptyState label="All topics covered" />
          ) : (
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
                      ▶ sample
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
                      ▶ source video
                    </a>
                  </div>
                  <Badge tone="blue">Approved</Badge>
                </Card>
              ))}
            </div>
          )}

          {/* FAQs */}
          <SectionHeader>
            FAQs to build ({data.faqs.length})
          </SectionHeader>
          {data.faqs.length === 0 ? (
            <EmptyState label="No FAQ gaps found" />
          ) : (
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
                  </tr>
                </thead>
                <tbody>
                  {data.faqs.map((f, i) => (
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
                          style={{
                            color: BRAND.navyText,
                            fontWeight: 500,
                            textDecoration: "none",
                          }}
                        >
                          ▶ {f.video_id} @{f.t}s
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {/* Unused Videos */}
          <SectionHeader>
            Unused videos ({data.unused_videos.length})
          </SectionHeader>
          {data.unused_videos.length === 0 ? (
            <EmptyState label="All videos used" />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {data.unused_videos.map((v) => (
                <Card
                  key={v.video_id}
                  style={{ flex: "1 1 220px", minWidth: 220 }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      color: BRAND.navyText,
                      marginBottom: 6,
                      fontSize: 14,
                    }}
                  >
                    {v.title || v.video_id}
                  </div>
                  <a
                    href={`https://youtu.be/${v.video_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: 13,
                      color: BRAND.navyText,
                      textDecoration: "none",
                    }}
                  >
                    ▶ {v.video_id}
                  </a>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
