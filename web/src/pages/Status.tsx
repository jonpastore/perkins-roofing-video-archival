import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, PageTitle, Card, Button, Badge, Loading, ErrorMsg } from "../ui";

interface FailedStage {
  video_id: string;
  stage: string;
  error: string;
}

interface StatusData {
  videos: number;
  videos_embedded: number;
  videos_archived: number;
  transcripts_done: number;
  articles: number;
  scheduled_content: number;
  failed_stages: FailedStage[];
}

interface KpiCard {
  label: string;
  value: number;
  color?: string;
}

export function Status() {
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    fetchStatus();
  }, []);

  const kpis: KpiCard[] = data
    ? [
        { label: "Total Videos", value: data.videos, color: BRAND.navyText },
        { label: "Embedded", value: data.videos_embedded, color: BRAND.navyText },
        { label: "Archived", value: data.videos_archived, color: BRAND.navyText },
        { label: "Transcripts Done", value: data.transcripts_done, color: BRAND.navyText },
        { label: "Articles", value: data.articles, color: BRAND.navyText },
        { label: "Scheduled Content", value: data.scheduled_content, color: BRAND.navyText },
      ]
    : [];

  return (
    <main style={{ padding: "0 4px" }}>
      <PageTitle right={<Button onClick={fetchStatus} disabled={loading}>Refresh</Button>}>
        Platform Status
      </PageTitle>

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
                style={{ flex: "1 1 140px", minWidth: 140, textAlign: "center" }}
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
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Video ID</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Stage</th>
                    <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {data.failed_stages.map((f, i) => (
                    <tr
                      key={`${f.video_id}-${f.stage}-${i}`}
                      style={{ borderBottom: `1px solid ${BRAND.border}` }}
                    >
                      <td style={{ padding: "10px 16px" }}>
                        <a
                          href={`https://youtu.be/${f.video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: BRAND.navyText, fontWeight: 500, textDecoration: "none" }}
                        >
                          {f.video_id}
                        </a>
                      </td>
                      <td style={{ padding: "10px 16px" }}>
                        <Badge tone="amber">{f.stage}</Badge>
                      </td>
                      <td style={{ padding: "10px 16px", color: BRAND.red, fontSize: 13 }}>
                        {f.error}
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
