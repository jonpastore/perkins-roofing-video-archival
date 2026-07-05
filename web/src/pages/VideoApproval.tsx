import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge } from "../ui";

interface Part {
  title: string;
  start: number;
  end: number;
}

interface Proposal {
  id: number;
  video_id: string;
  title: string;
  parts: Part[];
  approved: number;
}

// seconds -> M:SS
function mmss(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function ProposalCard({
  proposal,
  onApproved,
}: {
  proposal: Proposal;
  onApproved: (id: number) => void;
}) {
  const [parts, setParts] = useState<Part[]>(proposal.parts.map((p) => ({ ...p })));
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  function updatePart(index: number, field: keyof Part, value: string | number) {
    setParts((prev) =>
      prev.map((p, i) =>
        i === index ? { ...p, [field]: typeof value === "number" ? value : value } : p
      )
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

  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, fontWeight: 700 }}>
            {proposal.title}
          </h3>
          <a
            href={`https://youtu.be/${proposal.video_id}`}
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
            gridTemplateColumns: "1fr 120px 120px",
            gap: "6px 10px",
            alignItems: "center",
            marginBottom: 6,
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
            Part Title
          </span>
          <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
            Start (s)
          </span>
          <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>
            End (s)
          </span>
        </div>

        {parts.map((part, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 120px 120px",
              gap: "6px 10px",
              alignItems: "center",
              marginBottom: 8,
              paddingBottom: 8,
              borderBottom: i < parts.length - 1 ? `1px solid ${BRAND.border}` : "none",
            }}
          >
            <input
              type="text"
              value={part.title}
              onChange={(e) => updatePart(i, "title", e.target.value)}
              style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                type="number"
                value={part.start}
                min={0}
                onChange={(e) => updatePart(i, "start", Number(e.target.value))}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
              />
              <span style={{ fontSize: 11, color: BRAND.sub, textAlign: "center" }}>
                {mmss(part.start)}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                type="number"
                value={part.end}
                min={0}
                onChange={(e) => updatePart(i, "end", Number(e.target.value))}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13 }}
              />
              <span style={{ fontSize: 11, color: BRAND.sub, textAlign: "center" }}>
                {mmss(part.end)}
              </span>
            </div>
          </div>
        ))}
      </div>

      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button onClick={handleApprove} disabled={approving || approved}>
          {approving ? "Approving…" : "Approve"}
        </Button>
      </div>
    </Card>
  );
}

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

  return (
    <main style={{ maxWidth: 820 }}>
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

      {!loading && !error && proposals.map((p) => (
        <ProposalCard key={p.id} proposal={p} onApproved={handleApproved} />
      ))}
    </main>
  );
}
