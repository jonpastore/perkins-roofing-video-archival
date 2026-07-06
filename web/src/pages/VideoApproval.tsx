import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge, hms } from "../ui";

interface Part {
  title: string;
  start: number;
  end: number;
  // Topic-driven multi-source series carry a per-part source video.
  video_id?: string | null;
  video_title?: string | null;
}

interface Proposal {
  id: number;
  video_id: string;
  title: string;
  parts: Part[];
  approved: number;
  duration: number | null;
}

// youtu.be link jumped to a specific second offset.
function ytLink(videoId: string, start: number): string {
  return `https://youtu.be/${videoId}?t=${Math.max(0, Math.floor(start))}`;
}

function ProposalCard({
  proposal,
  onApproved,
  onReproposed,
}: {
  proposal: Proposal;
  onApproved: (id: number) => void;
  onReproposed: (p: Proposal) => void;
}) {
  const [parts, setParts] = useState<Part[]>(proposal.parts.map((p) => ({ ...p })));
  const [approving, setApproving] = useState(false);
  const [reproposing, setReproposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  function updatePart(index: number, field: keyof Part, value: string | number) {
    setParts((prev) =>
      prev.map((p, i) => (i === index ? { ...p, [field]: value } : p))
    );
  }

  async function handleApprove() {
    setApproving(true);
    setError(null);
    try {
      const r = await apiFetch(`/video/${proposal.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ parts }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setApproved(true);
      setTimeout(() => onApproved(proposal.id), 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  }

  async function handleRepropose() {
    setReproposing(true);
    setError(null);
    try {
      const r = await apiFetch(`/video/${proposal.id}/repropose`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const fresh: Proposal = await r.json();
      setParts(fresh.parts.map((p) => ({ ...p })));
      onReproposed(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReproposing(false);
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, fontWeight: 700 }}>
            {proposal.title}
            <span style={{ marginLeft: 10, fontSize: 13, fontWeight: 600, color: BRAND.sub }}>
              {hms(proposal.duration)}
            </span>
          </h3>
          <a
            href={ytLink(proposal.video_id, 0)}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13, color: BRAND.red, textDecoration: "none", fontWeight: 600 }}
          >
            ▶ Watch source video on YouTube
          </a>
        </div>
        {approved && <Badge tone="green">Approved</Badge>}
      </div>

      {/* Parts table */}
      <div style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 150px 120px 120px",
            gap: "6px 10px",
            alignItems: "center",
            marginBottom: 6,
          }}
        >
          <span style={hdrStyle}>Part Title</span>
          <span style={hdrStyle}>Time Range</span>
          <span style={hdrStyle}>Start (s)</span>
          <span style={hdrStyle}>End (s)</span>
        </div>

        {parts.map((part, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 150px 120px 120px",
              gap: "6px 10px",
              alignItems: "center",
              marginBottom: 8,
              paddingBottom: 8,
              borderBottom: i < parts.length - 1 ? `1px solid ${BRAND.border}` : "none",
            }}
          >
            <div>
              <input
                type="text"
                value={part.title}
                onChange={(e) => updatePart(i, "title", e.target.value)}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, width: "100%", boxSizing: "border-box" }}
              />
              {part.video_id && part.video_id !== proposal.video_id && (
                <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 3 }}>
                  Source: {part.video_title || part.video_id}
                </div>
              )}
            </div>
            <a
              href={ytLink(part.video_id || proposal.video_id, part.start)}
              target="_blank"
              rel="noopener noreferrer"
              title="Play this part on YouTube at its start time"
              style={{ fontSize: 13, color: BRAND.red, textDecoration: "none", fontWeight: 600, whiteSpace: "nowrap" }}
            >
              ▶ {hms(part.start)}–{hms(part.end)}
            </a>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                type="number"
                value={part.start}
                min={0}
                onChange={(e) => updatePart(i, "start", Number(e.target.value))}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                type="number"
                value={part.end}
                min={0}
                onChange={(e) => updatePart(i, "end", Number(e.target.value))}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
              />
            </div>
          </div>
        ))}
      </div>

      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
        <Button variant="ghost" onClick={handleRepropose} disabled={reproposing || approving || approved}>
          {reproposing ? "Re-proposing…" : "Re-propose"}
        </Button>
        <Button onClick={handleApprove} disabled={approving || reproposing || approved}>
          {approving ? "Approving…" : "Approve"}
        </Button>
      </div>
    </Card>
  );
}

const hdrStyle = {
  fontSize: 12,
  fontWeight: 700,
  color: BRAND.sub,
  textTransform: "uppercase" as const,
  letterSpacing: 0.4,
};

export function VideoApproval() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch("/video/proposals")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setProposals)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  function handleApproved(id: number) {
    setProposals((prev) => prev.filter((p) => p.id !== id));
  }

  function handleReproposed(fresh: Proposal) {
    setProposals((prev) => prev.map((p) => (p.id === fresh.id ? fresh : p)));
  }

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>Video Approval</PageTitle>

      {loading && <Loading label="Loading proposals…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && proposals.length === 0 && (
        <Card>
          <p style={{ margin: 0, color: BRAND.sub, fontSize: 14, textAlign: "center" }}>
            No proposals awaiting approval.
          </p>
        </Card>
      )}

      {!loading &&
        !error &&
        proposals.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            onApproved={handleApproved}
            onReproposed={handleReproposed}
          />
        ))}
    </main>
  );
}
