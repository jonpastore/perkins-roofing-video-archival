import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge } from "../ui";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ArchiveVideo {
  id: string;
  title: string;
  duration: number | null;
  upload_date: string | null;
  archived: boolean;
  youtube_url: string | null;
}

interface SuggestedClip {
  start: number;
  end: number;
  title: string;
  caption: string;
  hook: string;
  reason: string;
}

interface EditableClip extends SuggestedClip {
  included: boolean;
}

interface RenderableSeries {
  id: number;
  video_id: string;
  title: string;
  parts: Array<{ title: string; start: number; end: number }>;
  parts_count?: number;
}

interface RenderStatus {
  rendered: boolean;
  parts_total: number;
  parts_rendered: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function mmss(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ── Step 1: Video picker ───────────────────────────────────────────────────────

function VideoPicker({ onSelect }: { onSelect: (v: ArchiveVideo) => void }) {
  const [search, setSearch] = useState("");
  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    apiFetch(`/archive/videos?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setVideos)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [search]);

  return (
    <Card>
      <div style={{ marginBottom: 14, fontSize: 13, color: BRAND.sub, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4 }}>
        Step 1 — Pick a source video
      </div>
      <input
        type="text"
        placeholder="Search by title…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ ...inputStyle, width: "100%", marginBottom: 14, boxSizing: "border-box" }}
      />

      {loading && <Loading label="Loading videos…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && videos.length === 0 && (
        <p style={{ color: BRAND.sub, fontSize: 14, margin: 0 }}>No videos found.</p>
      )}

      {!loading && !error && videos.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 400, overflowY: "auto" }}>
          {videos.map((v) => (
            <button
              key={v.id}
              onClick={() => onSelect(v)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 12px",
                border: `1px solid ${BRAND.border}`,
                borderRadius: 8,
                background: "#fff",
                cursor: "pointer",
                textAlign: "left",
                gap: 12,
              }}
            >
              <span style={{ fontWeight: 500, color: BRAND.ink, fontSize: 14, flex: 1 }}>{v.title}</span>
              <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                {formatDuration(v.duration)}
              </span>
              {v.upload_date && (
                <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                  {v.upload_date}
                </span>
              )}
              <span style={{ fontSize: 12, color: BRAND.red, fontWeight: 600, whiteSpace: "nowrap" }}>
                Select →
              </span>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Step 2: Clip suggestions ───────────────────────────────────────────────────

function ClipCard({
  clip,
  index,
  videoId,
  onChange,
}: {
  clip: EditableClip;
  index: number;
  videoId: string;
  onChange: (index: number, updated: EditableClip) => void;
}) {
  function update(field: keyof EditableClip, value: string | number | boolean) {
    onChange(index, { ...clip, [field]: value });
  }

  const previewUrl = `https://youtu.be/${videoId}?t=${Math.floor(clip.start)}`;

  return (
    <Card style={{ opacity: clip.included ? 1 : 0.55, transition: "opacity 0.15s" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
        <input
          type="checkbox"
          checked={clip.included}
          onChange={(e) => update("included", e.target.checked)}
          style={{ marginTop: 3, width: 16, height: 16, cursor: "pointer", flexShrink: 0, accentColor: BRAND.red }}
        />
        <div style={{ flex: 1 }}>
          <input
            type="text"
            value={clip.title}
            onChange={(e) => update("title", e.target.value)}
            style={{ ...inputStyle, width: "100%", fontWeight: 700, fontSize: 15, color: BRAND.navyText, boxSizing: "border-box" }}
          />
        </div>
      </div>

      {/* Hook */}
      <div style={{ marginBottom: 8, padding: "8px 12px", background: BRAND.bg, borderRadius: 8, borderLeft: `3px solid ${BRAND.red}` }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>Hook </span>
        <span style={{ fontSize: 13, color: BRAND.ink }}>{clip.hook}</span>
      </div>

      {/* Caption */}
      <div style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>Caption </span>
        <span style={{ fontSize: 13, color: BRAND.ink }}>{clip.caption}</span>
      </div>

      {/* Time range + preview */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}>
            <input
              type="number"
              value={clip.start}
              min={0}
              onChange={(e) => update("start", Number(e.target.value))}
              style={{ ...inputStyle, width: 90, padding: "6px 8px", fontSize: 13 }}
            />
            <span style={{ fontSize: 11, color: BRAND.sub }}>{mmss(clip.start)}</span>
          </div>
          <span style={{ color: BRAND.sub, fontSize: 14 }}>→</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}>
            <input
              type="number"
              value={clip.end}
              min={0}
              onChange={(e) => update("end", Number(e.target.value))}
              style={{ ...inputStyle, width: 90, padding: "6px 8px", fontSize: 13 }}
            />
            <span style={{ fontSize: 11, color: BRAND.sub }}>{mmss(clip.end)}</span>
          </div>
          <Badge tone="gray">{mmss(clip.start)}–{mmss(clip.end)}</Badge>
        </div>

        <a
          href={previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 13, color: BRAND.red, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
        >
          ▶ Preview on YouTube
        </a>
      </div>

      {/* Reason */}
      <div style={{ fontSize: 12, color: BRAND.sub, fontStyle: "italic" }}>
        {clip.reason}
      </div>
    </Card>
  );
}

// ── Step 3 success banner ──────────────────────────────────────────────────────

function SuccessBanner({ seriesTitle }: { seriesTitle: string }) {
  return (
    <Card style={{ background: "#e6f9f0", border: "1px solid #a7e3c1" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <Badge tone="green">Saved</Badge>
        <span style={{ fontWeight: 700, color: "#1a7f4b", fontSize: 15 }}>{seriesTitle}</span>
      </div>
      <p style={{ margin: 0, fontSize: 14, color: "#1a7f4b" }}>
        Clip series saved. Next, approve and schedule it:
      </p>
      <div style={{ marginTop: 10, display: "flex", gap: 10 }}>
        <span style={{ fontSize: 13, color: "#1a7f4b" }}>
          Go to <strong>Video Approval</strong> to review parts, then <strong>Content Scheduling</strong> to publish.
        </span>
      </div>
    </Card>
  );
}

// ── Ready-to-render panel ─────────────────────────────────────────────────────

function RenderableRow({ s }: { s: RenderableSeries }) {
  const partCount = s.parts_count ?? s.parts.length;
  const [triggering, setTriggering] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [status, setStatus] = useState<RenderStatus | null>(null);
  const [polling, setPolling] = useState(false);

  function pollStatus(attempts = 0) {
    if (attempts > 6) { setPolling(false); return; }
    apiFetch(`/clips/${s.id}/render-status`)
      .then((r) => r.ok ? r.json() : null)
      .then((data: RenderStatus | null) => {
        if (!data) return;
        setStatus(data);
        if (!data.rendered) {
          setTimeout(() => pollStatus(attempts + 1), 4000);
        } else {
          setPolling(false);
        }
      })
      .catch(() => setPolling(false));
  }

  async function handleRender() {
    setTriggering(true);
    setMsg(null);
    try {
      const r = await apiFetch(`/clips/${s.id}/render`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setMsg("Rendering started…");
      setPolling(true);
      setTimeout(() => pollStatus(0), 5000);
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTriggering(false);
    }
  }

  const isRendered = status?.rendered ?? false;
  const partsRendered = status?.parts_rendered ?? 0;
  const partsTotal = status?.parts_total ?? partCount;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 12px",
        background: BRAND.bg,
        borderRadius: 8,
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <span style={{ fontWeight: 500, color: BRAND.ink, fontSize: 14, flex: 1 }}>{s.title}</span>

      {isRendered ? (
        <Badge tone="green">Rendered</Badge>
      ) : polling ? (
        <Badge tone="amber">Rendering {partsRendered}/{partsTotal}…</Badge>
      ) : (
        <Badge tone="blue">{partCount} part{partCount !== 1 ? "s" : ""}</Badge>
      )}

      {msg && !isRendered && (
        <span style={{ fontSize: 12, color: msg.startsWith("Error") ? BRAND.red : BRAND.sub }}>
          {msg}
        </span>
      )}

      {!isRendered && (
        <Button
          variant="primary"
          disabled={triggering || polling}
          onClick={handleRender}
          style={{ padding: "6px 14px", fontSize: 13 }}
        >
          {triggering ? "Starting…" : "Render now"}
        </Button>
      )}
    </div>
  );
}

function RenderablePanel() {
  const [series, setSeries] = useState<RenderableSeries[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/clips/renderable")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setSeries)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12, fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
        Ready to Render
      </div>

      {loading && <Loading label="Checking render queue…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && series.length === 0 && (
        <p style={{ margin: 0, color: BRAND.sub, fontSize: 13 }}>No approved series awaiting render.</p>
      )}

      {!loading && !error && series.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {series.map((s) => (
            <RenderableRow key={s.id} s={s} />
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Step =
  | { kind: "pick" }
  | { kind: "suggest"; video: ArchiveVideo }
  | { kind: "clips"; video: ArchiveVideo; clips: EditableClip[] }
  | { kind: "saved"; seriesTitle: string };

export function ClipStudio() {
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Step 1 → 2: video selected
  function handleVideoSelect(video: ArchiveVideo) {
    setStep({ kind: "suggest", video });
    setSuggestError(null);
  }

  // Step 2: run AI suggestion
  async function handleSuggest(video: ArchiveVideo) {
    setSuggesting(true);
    setSuggestError(null);
    try {
      const r = await apiFetch("/clips/suggest", {
        method: "POST",
        body: JSON.stringify({ video_id: video.id }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data: { video_title: string; clips: SuggestedClip[] } = await r.json();
      const editable: EditableClip[] = data.clips.map((c) => ({ ...c, included: true }));
      setStep({ kind: "clips", video, clips: editable });
    } catch (e: unknown) {
      setSuggestError(e instanceof Error ? e.message : String(e));
    } finally {
      setSuggesting(false);
    }
  }

  // Clip editing
  function handleClipChange(index: number, updated: EditableClip) {
    if (step.kind !== "clips") return;
    const clips = step.clips.map((c, i) => (i === index ? updated : c));
    setStep({ ...step, clips });
  }

  // Step 3: save curated clips
  async function handleSave() {
    if (step.kind !== "clips") return;
    const selected = step.clips.filter((c) => c.included);
    if (selected.length === 0) {
      setSaveError("Select at least one clip to save.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    const seriesTitle = `${step.video.title} — Clips`;
    try {
      const r = await apiFetch("/clips/save", {
        method: "POST",
        body: JSON.stringify({
          video_id: step.video.id,
          title: seriesTitle,
          parts: selected.map(({ title, start, end }) => ({ title, start, end })),
        }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setStep({ kind: "saved", seriesTitle });
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <main style={{ maxWidth: 820 }}>
      <PageTitle>Clip Studio</PageTitle>

      {/* Ready-to-render panel — always visible */}
      <RenderablePanel />

      {/* Step: saved */}
      {step.kind === "saved" && (
        <>
          <SuccessBanner seriesTitle={step.seriesTitle} />
          <div style={{ marginTop: 16 }}>
            <Button variant="ghost" onClick={() => setStep({ kind: "pick" })}>
              Start another
            </Button>
          </div>
        </>
      )}

      {/* Step: pick */}
      {step.kind === "pick" && (
        <VideoPicker onSelect={handleVideoSelect} />
      )}

      {/* Step: suggest (video selected, not yet fetched) */}
      {step.kind === "suggest" && (
        <Card>
          <div style={{ marginBottom: 6, fontSize: 13, color: BRAND.sub, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4 }}>
            Step 2 — AI clip suggestions
          </div>
          <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontWeight: 600, color: BRAND.navyText, fontSize: 15 }}>
              {step.video.title}
            </span>
            {step.video.duration != null && (
              <Badge tone="gray">{formatDuration(step.video.duration)}</Badge>
            )}
          </div>

          {suggestError && <ErrorMsg>Error: {suggestError}</ErrorMsg>}

          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Button onClick={() => handleSuggest(step.video)} disabled={suggesting}>
              {suggesting ? "Analyzing video… (may take 15–30s)" : "Suggest clips"}
            </Button>
            <Button variant="ghost" onClick={() => setStep({ kind: "pick" })} disabled={suggesting}>
              Back
            </Button>
          </div>

          {suggesting && (
            <div style={{ marginTop: 16 }}>
              <Loading label="AI is identifying the best clip moments… this may take up to 30 seconds." />
            </div>
          )}
        </Card>
      )}

      {/* Step: clips (suggestions returned, user curates) */}
      {step.kind === "clips" && (
        <>
          <div style={{ marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
            <div>
              <div style={{ fontSize: 13, color: BRAND.sub, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
                Step 2 — Review suggested clips
              </div>
              <span style={{ fontWeight: 600, color: BRAND.navyText, fontSize: 15 }}>
                {step.video.title}
              </span>
              {step.video.youtube_url && (
                <a
                  href={step.video.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ marginLeft: 12, fontSize: 13, color: BRAND.red, fontWeight: 600, textDecoration: "none" }}
                >
                  ▶ Watch full video
                </a>
              )}
            </div>
            <Button variant="ghost" onClick={() => setStep({ kind: "suggest", video: step.video })}>
              Re-suggest
            </Button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
            {step.clips.map((clip, i) => (
              <ClipCard
                key={i}
                clip={clip}
                index={i}
                videoId={step.video.id}
                onChange={handleClipChange}
              />
            ))}
          </div>

          {/* Step 3 action bar */}
          <Card style={{ background: BRAND.bg }}>
            <div style={{ fontSize: 13, color: BRAND.sub, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
              Step 3 — Save as clip series
            </div>
            <div style={{ fontSize: 13, color: BRAND.sub, marginBottom: 12 }}>
              {step.clips.filter((c) => c.included).length} of {step.clips.length} clips selected.
              Series will be saved as: <strong style={{ color: BRAND.ink }}>{step.video.title} — Clips</strong>
            </div>

            {saveError && <ErrorMsg>Error: {saveError}</ErrorMsg>}

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "Saving…" : "Save as clip series"}
              </Button>
              <Button variant="ghost" onClick={() => setStep({ kind: "pick" })} disabled={saving}>
                Start over
              </Button>
            </div>
          </Card>
        </>
      )}
    </main>
  );
}
