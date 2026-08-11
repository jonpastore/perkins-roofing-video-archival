import { useContext, useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge, hms, ytLink } from "../ui";
import { NavContext } from "../App";
import { errText } from "../lib/errors";

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
  // Persisted on the source video. Present on load so a description generated yesterday is
  // visible today — otherwise the card offers "Generate" again and the reviewer silently
  // regenerates over one that already existed.
  description?: string | null;
  description_generated_at?: string | null;
  description_model?: string | null;
}

// ytLink is imported from ui — guards NaN/null and omits ?t= when start is not finite.

// Seconds -> "hh:mm:ss" (zero-padded).
function fmtHMS(secs: number): string {
  const s = Math.max(0, Math.floor(secs || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(sec)}`;
}

// Lenient "hh:mm:ss" / "mm:ss" / "ss" -> seconds. Returns null if any part is non-numeric.
function parseHMS(str: string): number | null {
  const parts = str.split(":").map((p) => p.trim());
  if (parts.some((p) => p !== "" && Number.isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p || 0), 0);
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
  // Raw text while editing an hh:mm:ss field (keeps typing fluid); cleared on blur.
  const [timeEdits, setTimeEdits] = useState<Record<string, string>>({});
  // Which source video is currently minting a download URL (null = none in flight).
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadErr, setDownloadErr] = useState<string | null>(null);
  const [describing, setDescribing] = useState(false);
  const [savingDesc, setSavingDesc] = useState(false);
  // `description` is what the server has; `draft` is what is in the textarea. They diverge only
  // while an edit is unsaved, which is exactly the state the reload guard below watches for.
  const [description, setDescription] = useState<string | null>(proposal.description ?? null);
  const [draft, setDraft] = useState<string>(proposal.description ?? "");
  const [descModel, setDescModel] = useState<string | null>(proposal.description_model ?? null);
  const [descMeta, setDescMeta] = useState<string | null>(
    proposal.description
      ? [proposal.description_model, proposal.description_generated_at
          ? new Date(proposal.description_generated_at).toLocaleString()
          : null].filter(Boolean).join(" · ") || null
      : null
  );
  const [descErr, setDescErr] = useState<string | null>(null);
  // What the post-generation pass changed, and what it could not fix. The API has returned
  // these since the pass shipped and nothing rendered them — so a caption the model padded to
  // eight hashtags, or one that opened "Here is your caption", reached the reviewer with no
  // indication either had happened.
  const [descFixes, setDescFixes] = useState<string[]>([]);
  const [descProblems, setDescProblems] = useState<string[]>([]);

  const dirty = description !== null && draft !== description;

  // An unsaved caption is typed work, and the browser is the only thing that can stop a reload
  // from discarding it.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Generate a description from the transcript via the backend (Vertex) and persist it on the
  // video. The text shown here is what was STORED, not a preview — regenerating overwrites, so
  // an unsaved edit or a previously hand-written caption gets a confirm first.
  async function describe() {
    if (dirty && !window.confirm("Regenerate will discard your unsaved edits. Continue?")) return;
    if (!dirty && descModel === "edited" &&
        !window.confirm("This caption was written by hand. Regenerating overwrites it. Continue?")) return;
    setDescribing(true);
    setDescErr(null);
    try {
      const r = await apiFetch(`/video/${proposal.video_id}/description`, { method: "POST" });
      if (!r.ok) throw new Error(await errText(r));
      const d = await r.json();
      setDescription(d.description);
      setDraft(d.description);
      setDescModel(d.model);
      setDescMeta(
        `${d.model} · ${d.transcript_chars.toLocaleString()} transcript chars` +
        (d.truncated ? " (truncated)" : "")
      );
      setDescFixes(d.fixes ?? []);
      setDescProblems(d.problems ?? []);
    } catch (e: unknown) {
      setDescErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDescribing(false);
    }
  }

  // Persist a hand-edited caption. The server flags it `description_model = "edited"` so a later
  // "regenerate everything model X wrote" sweep leaves human text alone.
  async function saveDescription() {
    setSavingDesc(true);
    setDescErr(null);
    try {
      const r = await apiFetch(`/video/${proposal.video_id}/description`, {
        method: "PATCH",
        body: JSON.stringify({ description: draft }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const d = await r.json();
      setDescription(d.description);
      setDraft(d.description);
      setDescModel(d.model);
      setDescMeta(`${d.model} · ${new Date(d.generated_at).toLocaleString()}`);
      // The human just rewrote it; notes about the generated version no longer apply.
      setDescFixes([]);
      setDescProblems([]);
    } catch (e: unknown) {
      setDescErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingDesc(false);
    }
  }

  // Download the SOURCE video behind a proposal. The signed URL is minted per click rather than
  // rendered into an href: it is short-lived, so a link built at page load is already stale by the
  // time a reviewer works down the queue. Same endpoint and flow the Archive page uses.
  async function download(videoId: string) {
    setDownloading(videoId);
    setDownloadErr(null);
    try {
      const r = await apiFetch(`/archive/${videoId}/download`);
      if (!r.ok) throw new Error(await errText(r));
      const { download_url } = await r.json();
      window.open(download_url, "_blank", "noopener,noreferrer");
    } catch (e: unknown) {
      setDownloadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(null);
    }
  }

  function updatePart(index: number, field: keyof Part, value: string | number) {
    setParts((prev) =>
      prev.map((p, i) => (i === index ? { ...p, [field]: value } : p))
    );
  }

  function timeValue(i: number, field: "start" | "end"): string {
    return timeEdits[`${i}-${field}`] ?? fmtHMS(parts[i][field]);
  }
  function onTimeChange(i: number, field: "start" | "end", raw: string) {
    setTimeEdits((prev) => ({ ...prev, [`${i}-${field}`]: raw }));
    const parsed = parseHMS(raw);
    if (parsed !== null) updatePart(i, field, parsed);
  }
  function onTimeBlur(i: number, field: "start" | "end") {
    setTimeEdits((prev) => {
      const n = { ...prev };
      delete n[`${i}-${field}`];
      return n;
    });
  }

  async function handleApprove() {
    setApproving(true);
    setError(null);
    try {
      const r = await apiFetch(`/video/${proposal.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ parts }),
      });
      if (!r.ok) throw new Error(await errText(r));
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
      if (!r.ok) throw new Error(await errText(r));
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
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <a
              href={ytLink(proposal.video_id, 0)}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: 13, color: BRAND.red, textDecoration: "none", fontWeight: 600 }}
            >
              ▶ Watch source video on YouTube
            </a>
            <button
              type="button"
              onClick={() => download(proposal.video_id)}
              disabled={downloading === proposal.video_id}
              title="Download the archived source MP4"
              style={{
                background: "none",
                border: "none",
                padding: 0,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: "inherit",
                color: downloading === proposal.video_id ? BRAND.sub : BRAND.navyText,
                cursor: downloading === proposal.video_id ? "wait" : "pointer",
              }}
            >
              {downloading === proposal.video_id ? "⬇ Preparing…" : "⬇ Download source video"}
            </button>
            <button
              type="button"
              onClick={describe}
              disabled={describing}
              title="Generate a description from the transcript and save it to this video"
              style={{
                background: "none",
                border: "none",
                padding: 0,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: "inherit",
                color: describing ? BRAND.sub : BRAND.navyText,
                cursor: describing ? "wait" : "pointer",
              }}
            >
              {describing ? "✎ Generating…" : description ? "✎ Regenerate description" : "✎ Generate description"}
            </button>
          </div>
          {downloadErr && (
            <div style={{ fontSize: 12, color: BRAND.red, marginTop: 4 }}>{downloadErr}</div>
          )}
          {descErr && <div style={{ fontSize: 12, color: BRAND.red, marginTop: 4 }}>{descErr}</div>}
          {description !== null && (
            <div style={{ marginTop: 10, maxWidth: 720 }}>
              <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 3 }}>
                {dirty ? "Unsaved edits" : "Saved description"}{descMeta ? ` — ${descMeta}` : ""}
              </div>
              {descProblems.length > 0 && (
                <div style={{ fontSize: 12, color: BRAND.red, marginBottom: 4 }}>
                  ⚠ {descProblems.join("; ")} — check before posting.
                </div>
              )}
              {descFixes.length > 0 && (
                <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 4 }}>
                  Auto-corrected: {descFixes.join("; ")}.
                </div>
              )}
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={8}
                spellCheck
                style={{
                  ...inputStyle,
                  width: "100%",
                  boxSizing: "border-box",
                  fontSize: 13,
                  lineHeight: 1.5,
                  fontFamily: "inherit",
                  resize: "vertical",
                  background: BRAND.bg,
                }}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                <Button onClick={saveDescription} disabled={!dirty || savingDesc}>
                  {savingDesc ? "Saving…" : "Save description"}
                </Button>
                {dirty && !savingDesc && (
                  <button
                    type="button"
                    onClick={() => setDraft(description)}
                    style={{
                      background: "none", border: "none", padding: 0, fontSize: 13,
                      fontWeight: 600, fontFamily: "inherit", color: BRAND.sub, cursor: "pointer",
                    }}
                  >
                    Discard edits
                  </button>
                )}
              </div>
            </div>
          )}
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
          <span style={hdrStyle}>Start (hh:mm:ss)</span>
          <span style={hdrStyle}>End (hh:mm:ss)</span>
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
                  {/* Topic-driven series pull parts from OTHER videos, and the header button only
                      downloads the proposal's own source — without this those files are
                      unreachable from this page. */}
                  <button
                    type="button"
                    onClick={() => download(part.video_id as string)}
                    disabled={downloading === part.video_id}
                    title="Download this part's archived source MP4"
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      marginLeft: 8,
                      fontSize: 11,
                      fontWeight: 600,
                      fontFamily: "inherit",
                      color: downloading === part.video_id ? BRAND.sub : BRAND.navyText,
                      cursor: downloading === part.video_id ? "wait" : "pointer",
                    }}
                  >
                    {downloading === part.video_id ? "⬇ …" : "⬇ Download"}
                  </button>
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
                type="text"
                inputMode="numeric"
                value={timeValue(i, "start")}
                placeholder="hh:mm:ss"
                onChange={(e) => onTimeChange(i, "start", e.target.value)}
                onBlur={() => onTimeBlur(i, "start")}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, fontVariantNumeric: "tabular-nums" }}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                type="text"
                inputMode="numeric"
                value={timeValue(i, "end")}
                placeholder="hh:mm:ss"
                onChange={(e) => onTimeChange(i, "end", e.target.value)}
                onBlur={() => onTimeBlur(i, "end")}
                style={{ ...inputStyle, padding: "7px 10px", fontSize: 13, fontVariantNumeric: "tabular-nums" }}
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
  const { params, navigate } = useContext(NavContext);
  const targetSeries = params.series ?? null;

  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch("/video/proposals")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
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

  // When navigated here with a series param, show only the matching proposal (by
  // video_id matching the ref_id passed from Scheduling). Fall back to full list
  // if no match is found so the user is never stranded on an empty page.
  const filtered = targetSeries
    ? proposals.filter((p) => String(p.id) === targetSeries || p.video_id === targetSeries)
    : proposals;
  const displayProposals = filtered.length > 0 ? filtered : proposals;
  const isFiltered = targetSeries !== null && filtered.length > 0 && filtered.length < proposals.length;

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>Video Approval</PageTitle>

      <Card style={{ marginBottom: 16, background: "#eef2ff", borderLeft: `4px solid ${BRAND.navy}` }}>
        <p style={{ margin: 0, fontSize: 13, color: BRAND.navyText, lineHeight: 1.6 }}>
          These are <strong>proposed short-form reels</strong> the system generated from your source
          videos — each is a set of clip segments (title → parts → closing) picked from the transcript.
          Review the parts and adjust the <strong>start/end times</strong> (hh:mm:ss) if a moment needs
          trimming, then <strong>Approve</strong> to lock the cut. Approving marks the reel ready to
          render and move into Content Scheduling / social posting. Use <strong>Re-propose</strong> to
          regenerate the parts from scratch.
        </p>
      </Card>

      {loading && <Loading label="Loading proposals…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {isFiltered && (
        <p style={{ fontSize: 13, color: BRAND.sub, marginBottom: 12 }}>
          Showing proposal for series <strong>{targetSeries}</strong>.{" "}
          <button
            onClick={() => navigate("video-approval")}
            style={{ background: "none", border: "none", color: BRAND.navy, cursor: "pointer", fontSize: 13, padding: 0, textDecoration: "underline" }}
          >
            Show all
          </button>
        </p>
      )}

      {!loading && !error && displayProposals.length === 0 && (
        <Card>
          <p style={{ margin: 0, color: BRAND.sub, fontSize: 14, textAlign: "center" }}>
            No proposals awaiting approval.
          </p>
        </Card>
      )}

      {!loading &&
        !error &&
        displayProposals.map((p) => (
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
