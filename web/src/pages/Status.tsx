import { useContext, useEffect, useState } from "react";
import { apiFetch } from "../api";
import { NavContext } from "../App";
import { BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";

type ToastTone = "green" | "red";
interface Toast { message: string; tone: ToastTone; }

interface FailedStage {
  video_id: string;
  stage: string;
  error: string;
  title?: string | null;
  youtube_url?: string;
}

interface QueueItem {
  video_id: string;
  title?: string | null;
  stage: string;
  status: string;
}

interface ScheduledBucket {
  count: number;
  next_up: string | null; // ISO datetime
}

interface ScheduledBreakdown {
  articles: ScheduledBucket;
  social: Record<string, ScheduledBucket>;
}

interface StatusData {
  videos: number;
  videos_embedded: number;
  videos_archived: number;
  transcripts_done: number;
  articles: number;
  faq_count: number;
  scheduled_content: number;
  // Extended counters — added by backend; optional so page still works before backend lands.
  scheduled_breakdown?: ScheduledBreakdown;
  content_opportunities?: number;
  comments_to_answer?: number;
  videos_to_approve?: number;
  failed_stages: FailedStage[];
  queue: QueueItem[];
}

interface KpiCard {
  label: string;
  value: number;
  color?: string;
  navTarget?: string;
}

export function Status() {
  const { navigate } = useContext(NavContext);
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null); // "video_id:stage" key
  const [toast, setToast] = useState<Toast | null>(null);

  function showToast(message: string, tone: ToastTone) {
    setToast({ message, tone });
    setTimeout(() => setToast(null), 4000);
  }

  function fetchStatus() {
    setLoading(true);
    setError(null);
    apiFetch("/status")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: StatusData) => setData(d))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  function retryStage(video_id: string, stage: string) {
    const key = `${video_id}:${stage}`;
    setRetrying(key);
    apiFetch("/status/retry", {
      method: "POST",
      body: JSON.stringify({ video_id, stage }),
    })
      .then((r) => {
        if (!r.ok) return r.json().then((d: { detail?: string }) => { throw new Error(d.detail ?? `${r.status}`); });
        return r.json();
      })
      .then((d: { reset: number }) => {
        showToast(`Re-queued ${d.reset} run(s) for next ingest. Refresh to confirm.`, "green");
        fetchStatus();
      })
      .catch((e: unknown) => showToast(`Retry failed: ${e instanceof Error ? e.message : String(e)}`, "red"))
      .finally(() => setRetrying(null));
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  const kpis: KpiCard[] = data
    ? [
        { label: "Total Videos", value: data.videos, color: BRAND.navyText, navTarget: "archive" },
        { label: "Embedded", value: data.videos_embedded, color: BRAND.navyText, navTarget: "archive" },
        { label: "Archived", value: data.videos_archived, color: BRAND.navyText, navTarget: "archive" },
        { label: "Transcripts Done", value: data.transcripts_done, color: BRAND.navyText, navTarget: "archive" },
        { label: "Articles", value: data.articles, color: BRAND.navyText, navTarget: "articles" },
        { label: "FAQ Entries", value: data.faq_count, color: BRAND.navyText, navTarget: "faq" },
        { label: "Scheduled Content", value: data.scheduled_content, color: BRAND.navyText, navTarget: "scheduling" },
        ...(data.content_opportunities != null
          ? [{ label: "Content Opportunities", value: data.content_opportunities, color: data.content_opportunities > 0 ? "#b45309" : BRAND.navyText, navTarget: "search-ask" }]
          : []),
        ...(data.comments_to_answer != null
          ? [{ label: "Comments to Answer", value: data.comments_to_answer, color: data.comments_to_answer > 0 ? "#b45309" : BRAND.navyText, navTarget: "comments" }]
          : []),
        ...(data.videos_to_approve != null
          ? [{ label: "Videos to Approve", value: data.videos_to_approve, color: data.videos_to_approve > 0 ? "#b45309" : BRAND.navyText, navTarget: "scheduling" }]
          : []),
        { label: "Failed Stages", value: data.failed_stages.length, color: data.failed_stages.length > 0 ? BRAND.red : BRAND.navyText },
        { label: "In Queue", value: data.queue.length, color: data.queue.length > 0 ? "#b45309" : BRAND.navyText },
      ]
    : [];

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle right={<Button onClick={fetchStatus} disabled={loading}>Refresh</Button>}>
        Platform Status
      </PageTitle>

      {toast && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 16px",
            borderRadius: 8,
            background: toast.tone === "green" ? "#e6f9f0" : "#fdecea",
            color: toast.tone === "green" ? "#1a7f4b" : BRAND.red,
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          {toast.message}
        </div>
      )}

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && data && (
        <>
          {/* KPI grid */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 16,
              marginBottom: 32,
            }}
          >
            {kpis.map((kpi) => (
              <Card
                key={kpi.label}
                onClick={kpi.navTarget ? () => navigate(kpi.navTarget!) : undefined}
                style={{
                  flex: "1 1 140px",
                  minWidth: 140,
                  textAlign: "center",
                  cursor: kpi.navTarget ? "pointer" : "default",
                  transition: "box-shadow 0.15s",
                }}
                onMouseEnter={kpi.navTarget ? (e) => { (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(0,0,0,0.10)"; } : undefined}
                onMouseLeave={kpi.navTarget ? (e) => { (e.currentTarget as HTMLElement).style.boxShadow = ""; } : undefined}
              >
                <div
                  style={{
                    fontSize: 36,
                    fontWeight: 700,
                    color: kpi.color ?? BRAND.navyText,
                    lineHeight: 1.1,
                    marginBottom: 6,
                  }}
                >
                  {kpi.value.toLocaleString()}
                </div>
                <div style={{ fontSize: 13, color: BRAND.sub, fontWeight: 500 }}>
                  {kpi.label}
                </div>
              </Card>
            ))}
          </div>

          {/* Scheduled content breakdown */}
          {data.scheduled_breakdown && (
            <>
              <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
                Scheduled Content Breakdown
              </h3>
              <Card style={{ marginBottom: 32, padding: "16px 20px" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                      Articles
                    </div>
                    <div style={{ fontSize: 28, fontWeight: 700, color: BRAND.navyText }}>
                      {data.scheduled_breakdown.articles.count}
                    </div>
                    {data.scheduled_breakdown.articles.next_up && (
                      <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                        Next: {new Date(data.scheduled_breakdown.articles.next_up).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                  <div style={{ width: 1, background: BRAND.border, alignSelf: "stretch" }} />
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                      Social Posts
                    </div>
                    <div style={{ display: "flex", gap: 16, alignItems: "baseline", flexWrap: "wrap" }}>
                      {Object.entries(data.scheduled_breakdown.social)
                        .filter(([, b]) => b.count > 0)
                        .map(([platform, b]) => (
                          <span key={platform}>
                            <span style={{ fontSize: 22, fontWeight: 700, color: BRAND.navyText }}>{b.count}</span>
                            <span style={{ fontSize: 12, color: BRAND.sub, marginLeft: 4, textTransform: "capitalize" }}>{platform}</span>
                            {b.next_up && (
                              <span style={{ fontSize: 11, color: BRAND.sub, marginLeft: 4 }}>
                                (next {new Date(b.next_up).toLocaleDateString()})
                              </span>
                            )}
                          </span>
                        ))}
                      {Object.values(data.scheduled_breakdown.social).every((b) => b.count === 0) && (
                        <span style={{ fontSize: 14, color: BRAND.sub }}>None scheduled</span>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            </>
          )}

          {/* Failed stages */}
          <h3 style={{ margin: "0 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
            Failed Stages
          </h3>

          {data.failed_stages.length === 0 ? (
            <div style={{ marginBottom: 8 }}>
              <Badge tone="green">No failed stages</Badge>
            </div>
          ) : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Video</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Stage</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Error</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.failed_stages.map((f, i) => {
                    const key = `${f.video_id}:${f.stage}`;
                    const busy = retrying === key;
                    return (
                      <tr
                        key={`${f.video_id}-${f.stage}-${i}`}
                        style={{ borderBottom: `1px solid ${BRAND.border}` }}
                      >
                        <td style={{ padding: "10px 16px" }}>
                          <a
                            href={f.youtube_url ?? `https://youtu.be/${f.video_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none" }}
                          >
                            {f.title ?? "▶ watch on YouTube"}
                          </a>
                        </td>
                        <td style={{ padding: "10px 16px" }}>
                          <Badge tone="amber">{f.stage}</Badge>
                        </td>
                        <td style={{ padding: "10px 16px", color: BRAND.red, fontSize: 13 }}>
                          {f.error}
                        </td>
                        <td style={{ padding: "10px 16px" }}>
                          <Button
                            variant="ghost"
                            disabled={busy}
                            style={{ padding: "5px 12px", fontSize: 13 }}
                            onClick={() => retryStage(f.video_id, f.stage)}
                            title="Re-queues this stage for the next ingest run"
                          >
                            {busy ? "Queuing…" : "Retry"}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          )}

          {/* Processing / Queue */}
          <h3 style={{ margin: "32px 0 14px", color: BRAND.navyText, fontSize: 16, fontWeight: 600 }}>
            Processing / Queue
          </h3>

          {data.queue.length === 0 ? (
            <div style={{ marginBottom: 8 }}>
              <Badge tone="green">Queue empty</Badge>
            </div>
          ) : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Video</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Stage</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.queue.map((q, i) => (
                    <tr
                      key={`${q.video_id}-${q.stage}-${i}`}
                      style={{ borderBottom: `1px solid ${BRAND.border}` }}
                    >
                      <td style={{ padding: "10px 16px" }}>
                        <a
                          href={`https://youtu.be/${q.video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: BRAND.navyText, fontWeight: 600, textDecoration: "none" }}
                        >
                          {q.title ?? q.video_id}
                        </a>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <Badge tone="amber">{q.stage}</Badge>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <Badge tone={q.status === "running" ? "green" : "amber"}>{q.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
