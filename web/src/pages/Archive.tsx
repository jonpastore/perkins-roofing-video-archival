import { useEffect, useState } from "react";
import { apiFetch } from "../api";

interface ArchiveVideo {
  id: string;
  title: string;
  duration: number | null;
  upload_date: string | null;
  archived: boolean;
  youtube_url: string | null;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function Archive() {
  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [search, setSearch] = useState("");
  const [archivedOnly, setArchivedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (archivedOnly) params.set("archived_only", "true");
    apiFetch(`/archive/videos?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setVideos)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [search, archivedOnly]);

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
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, color: "#444" }}>
          <input
            type="checkbox"
            checked={archivedOnly}
            onChange={(e) => setArchivedOnly(e.target.checked)}
          />
          Archived only
        </label>
      </div>

      {/* States */}
      {loading && <p style={{ color: "#666", fontSize: 14 }}>Loading...</p>}
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
              <th style={{ padding: "8px 12px", color: "#666", fontWeight: 600 }}>Status</th>
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
              <tr
                key={v.id}
                style={{ borderBottom: "1px solid #f0f0f0" }}
              >
                <td style={{ padding: "10px 12px" }}>
                  {v.youtube_url ? (
                    <a
                      href={v.youtube_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "#1a1a2e", textDecoration: "none", fontWeight: 500 }}
                    >
                      {v.title}
                    </a>
                  ) : (
                    <span style={{ fontWeight: 500 }}>{v.title}</span>
                  )}
                </td>
                <td style={{ padding: "10px 12px", color: "#555" }}>
                  {formatDuration(v.duration)}
                </td>
                <td style={{ padding: "10px 12px", color: "#555" }}>
                  {v.upload_date ?? "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {v.archived ? (
                    <span
                      style={{
                        background: "#e6f9f0",
                        color: "#1a7f4b",
                        padding: "2px 10px",
                        borderRadius: 20,
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      Archived
                    </span>
                  ) : (
                    <span
                      style={{
                        background: "#fff3e0",
                        color: "#b45309",
                        padding: "2px 10px",
                        borderRadius: 20,
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      Pending
                    </span>
                  )}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {v.archived ? (
                    <button
                      onClick={() => handleDownload(v)}
                      disabled={downloading === v.id}
                      style={{
                        padding: "6px 14px",
                        background: downloading === v.id ? "#ccc" : "#1a1a2e",
                        color: "#fff",
                        border: "none",
                        borderRadius: 6,
                        cursor: downloading === v.id ? "not-allowed" : "pointer",
                        fontSize: 13,
                        fontWeight: 500,
                      }}
                    >
                      {downloading === v.id ? "..." : "Download"}
                    </button>
                  ) : (
                    <span style={{ color: "#bbb", fontSize: 13 }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
