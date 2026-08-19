import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { apiFetch, apiFetchMultipart } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge, Spinner } from "../ui";
import { NavContext } from "../App";
import { ClipStudioHelp } from "../components/ClipStudioHelp";
import { errText } from "../lib/errors";
import { seriesTitle } from "../lib/clipTitles";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ArchiveVideo {
  id: string;
  title: string;
  description?: string | null;
  duration: number | null;
  upload_date: string | null;
  archived: boolean;
  youtube_url: string | null;
  clips_generated?: boolean;
  clips_generated_at?: string | null;
}

interface ViralityScore {
  hook_strength: number;
  emotion: number;
  pacing: number;
  value: number;
  total: number;
  rationale: string;
}

interface SuggestedClip {
  start: number;
  end: number;
  title: string;
  caption: string;
  hook: string;
  reason: string;
  summary?: string;
  virality?: ViralityScore;
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

// cleanTitle / seriesTitle live in lib/clipTitles.ts

// ── Virality score badge ──────────────────────────────────────────────────────

function viralityColor(total: number): string {
  if (total >= 80) return "#1a7f4b";   // green — strong
  if (total >= 60) return "#b45309";   // amber — moderate
  if (total >= 40) return "#2563eb";   // blue — fair
  return "#6b7280";                    // gray — weak
}

function ViralityBadge({ virality }: { virality: ViralityScore }) {
  const [tip, setTip] = useState(false);
  const color = viralityColor(virality.total);
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={() => setTip((t) => !t)}
        title="Heuristic score — click for breakdown"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "3px 8px",
          borderRadius: 12,
          border: `1.5px solid ${color}`,
          background: "transparent",
          color,
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        Heuristic score: {virality.total}/100
      </button>
      {tip && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            zIndex: 10,
            minWidth: 240,
            background: "#fff",
            border: `1px solid ${BRAND.border}`,
            borderRadius: 8,
            boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
            padding: "10px 12px",
            fontSize: 12,
            color: BRAND.ink,
            lineHeight: 1.6,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6, color }}>Heuristic score breakdown</div>
          <div>Hook strength: {virality.hook_strength}/25</div>
          <div>Emotion: {virality.emotion}/25</div>
          <div>Pacing: {virality.pacing}/25</div>
          <div>Value: {virality.value}/25</div>
          {virality.rationale && (
            <div style={{ marginTop: 6, color: BRAND.sub, fontStyle: "italic" }}>
              {virality.rationale}
            </div>
          )}
          <div style={{ marginTop: 6, color: BRAND.sub, fontSize: 11 }}>
            LLM heuristic — not trained on engagement data.
          </div>
        </div>
      )}
    </div>
  );
}

// ── Analyzing animation ───────────────────────────────────────────────────────

const ANALYZING_STEPS = [
  "Reading transcript segments…",
  "Identifying high-value moments…",
  "Scoring hooks and CTAs…",
  "Composing clip suggestions…",
];

function AnalyzingDots() {
  const [step, setStep] = useState(0);
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    ref.current = setInterval(() => setStep((s) => (s + 1) % ANALYZING_STEPS.length), 1800);
    return () => { if (ref.current) clearInterval(ref.current); };
  }, []);
  return (
    <span
      style={{
        fontSize: 13,
        color: BRAND.sub,
        fontStyle: "italic",
        transition: "opacity 0.3s",
        minWidth: 260,
        display: "inline-block",
      }}
    >
      {ANALYZING_STEPS[step]}
    </span>
  );
}

// ── Step 1: Video picker ───────────────────────────────────────────────────────

function formatClipDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

interface VideoPickerProps {
  onSelect: (v: ArchiveVideo) => void;
  /** If set, the picker will expose a ref-callback to let the parent auto-select by id. */
  onVideosLoaded?: (videos: ArchiveVideo[]) => void;
}

function VideoPicker({ onSelect, onVideosLoaded }: VideoPickerProps) {
  const [search, setSearch] = useState("");
  const [committedSearch, setCommittedSearch] = useState("");
  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hideWithClips, setHideWithClips] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setCommittedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (committedSearch) qs.set("q", committedSearch);
    apiFetch(`/archive/videos?${qs}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((data: ArchiveVideo[]) => {
        setVideos(data);
        onVideosLoaded?.(data);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [committedSearch]); // eslint-disable-line react-hooks/exhaustive-deps

  const withClipsCount = videos.filter((v) => v.clips_generated).length;
  const displayed = hideWithClips ? videos.filter((v) => !v.clips_generated) : videos;

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
        style={{ ...inputStyle, width: "100%", marginBottom: 10, boxSizing: "border-box" }}
      />

      {/* Hide-with-clips toggle */}
      {!loading && !error && withClipsCount > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <input
            type="checkbox"
            id="hide-with-clips"
            checked={hideWithClips}
            onChange={(e) => setHideWithClips(e.target.checked)}
            style={{ width: 14, height: 14, accentColor: BRAND.red, cursor: "pointer" }}
          />
          <label htmlFor="hide-with-clips" style={{ fontSize: 13, color: BRAND.sub, cursor: "pointer" }}>
            Hide videos with clips already ({withClipsCount})
          </label>
        </div>
      )}

      {loading && <Loading label="Loading videos…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && displayed.length === 0 && (
        <p style={{ color: BRAND.sub, fontSize: 14, margin: 0 }}>
          {hideWithClips && withClipsCount > 0 ? "All videos already have clips." : "No videos found."}
        </p>
      )}

      {!loading && !error && displayed.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 400, overflowY: "auto" }}>
          {displayed.map((v) => (
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
              {v.clips_generated && (
                <span style={{ whiteSpace: "nowrap", flexShrink: 0 }}>
                  <Badge tone="green">
                    Clips {v.clips_generated_at ? formatClipDate(v.clips_generated_at) : "generated"}
                  </Badge>
                </span>
              )}
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

interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

const CLIP_FIT_LABELS: Record<string, string> = {
  instagram: "IG", tiktok: "TikTok", youtube_shorts: "Shorts", facebook: "FB",
};

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
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcriptSegs, setTranscriptSegs] = useState<TranscriptSegment[] | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [fit, setFit] = useState<Record<string, { ok: boolean; failures: string[] }> | null>(null);
  const [scenes, setScenes] = useState<number[] | null>(null);
  const [scenesLoading, setScenesLoading] = useState(false);

  function detectScenes(mode: "speech" | "visual" = "speech") {
    setScenesLoading(true);
    apiFetch(`/clips/scenes?video_id=${encodeURIComponent(videoId)}&start=${clip.start}&end=${clip.end}&mode=${mode}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { boundaries: number[] } | null) => setScenes(d?.boundaries ?? []))
      .catch(() => setScenes([]))
      .finally(() => setScenesLoading(false));
  }

  // Live per-platform spec check via /clips/preflight. Render output is fixed
  // 1080x1920 h264/aac, so duration is the meaningful gate; res/codec always pass.
  useEffect(() => {
    const dur = Number(clip.end) - Number(clip.start);
    if (!(dur > 0)) { setFit(null); return; }
    let cancelled = false;
    apiFetch("/clips/preview/preflight", {
      method: "POST",
      body: JSON.stringify({
        platforms: ["instagram", "tiktok", "youtube_shorts", "facebook"],
        meta: { duration_seconds: dur, width: 1080, height: 1920, size_mb: 50, codec_video: "h264", codec_audio: "aac" },
      }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled) setFit(d?.results ?? null); })
      .catch(() => { if (!cancelled) setFit(null); });
    return () => { cancelled = true; };
  }, [clip.start, clip.end]);

  function update(field: keyof EditableClip, value: string | number | boolean) {
    onChange(index, { ...clip, [field]: value });
  }

  function handleToggleTranscript() {
    if (!transcriptOpen && transcriptSegs === null) {
      setTranscriptLoading(true);
      setTranscriptError(null);
      apiFetch(
        `/clips/transcript?video_id=${encodeURIComponent(videoId)}&start=${clip.start}&end=${clip.end}`
      )
        .then(async (r) => {
          if (!r.ok) throw new Error(await errText(r));
          return r.json();
        })
        .then((data: { segments: TranscriptSegment[] }) => {
          setTranscriptSegs(data.segments ?? []);
        })
        .catch((e: unknown) => {
          setTranscriptError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => setTranscriptLoading(false));
    }
    setTranscriptOpen((o) => !o);
  }

  const previewUrl = `https://youtu.be/${videoId}?t=${Math.floor(clip.start)}`;
  const hasSummary = clip.summary && clip.summary.trim().length > 0;

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
        {clip.virality && clip.virality.total > 0 && (
          <div style={{ flexShrink: 0, marginTop: 2 }}>
            <ViralityBadge virality={clip.virality} />
          </div>
        )}
      </div>

      {/* Hook */}
      <div style={{ marginBottom: 8, padding: "8px 12px", background: BRAND.bg, borderRadius: 8, borderLeft: `3px solid ${BRAND.red}` }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>Hook </span>
        <span style={{ fontSize: 13, color: BRAND.ink }}>{clip.hook || <em style={{ color: BRAND.sub }}>—</em>}</span>
      </div>

      {/* Summary */}
      {hasSummary && (
        <div style={{ marginBottom: 8, fontSize: 13, color: BRAND.ink, lineHeight: 1.5 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4, marginRight: 6 }}>Summary</span>
          {clip.summary}
        </div>
      )}

      {/* Caption */}
      <div style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>Caption </span>
        <span style={{ fontSize: 13, color: BRAND.ink }}>{clip.caption || <em style={{ color: BRAND.sub }}>—</em>}</span>
      </div>

      {/* Per-platform spec fit (duration-driven) */}
      {fit && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.4 }}>Fits</span>
          {Object.entries(fit).map(([p, r]) => (
            <span
              key={p}
              title={r.failures.join("; ") || "meets platform specs"}
              style={{
                fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                background: r.ok ? "#e6f4ea" : "#fdf0e3", color: r.ok ? "#1e7a34" : "#9a6400",
              }}
            >
              {r.ok ? "✓" : "⚠"} {CLIP_FIT_LABELS[p] ?? p}
            </span>
          ))}
        </div>
      )}

      {/* Scene cut points (speech-gap detection) */}
      <div style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => detectScenes("speech")}
          disabled={scenesLoading}
          style={{ fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: `1px solid ${BRAND.border}`, background: "#fff", color: BRAND.sub, cursor: "pointer" }}
        >
          {scenesLoading ? "Detecting…" : "✂ Detect scenes"}
        </button>
        <button
          type="button"
          onClick={() => detectScenes("visual")}
          disabled={scenesLoading}
          title="Analyse the video for visual cuts (camera/B-roll) — slower"
          style={{ fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 6, border: `1px solid ${BRAND.border}`, background: "#fff", color: BRAND.sub, cursor: "pointer" }}
        >
          visual
        </button>
        {scenes && scenes.filter((t) => t > clip.start + 0.5 && t < clip.end - 0.5).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => update("end", Math.round(t * 10) / 10)}
            title="Trim this clip to end at this scene cut"
            style={{ fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 10, border: `1px solid ${BRAND.border}`, background: BRAND.bg, color: BRAND.ink, cursor: "pointer" }}
          >
            cut @ {t.toFixed(1)}s
          </button>
        ))}
        {scenes && scenes.filter((t) => t > clip.start + 0.5 && t < clip.end - 0.5).length === 0 && (
          <span style={{ fontSize: 11, color: BRAND.sub }}>No scene breaks in this range.</span>
        )}
      </div>

      {/* Time range + preview */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="number"
            value={clip.start}
            min={0}
            onChange={(e) => update("start", Number(e.target.value))}
            style={{ ...inputStyle, width: 90, padding: "6px 8px", fontSize: 13 }}
          />
          <span style={{ color: BRAND.sub, fontSize: 14 }}>→</span>
          <input
            type="number"
            value={clip.end}
            min={0}
            onChange={(e) => update("end", Number(e.target.value))}
            style={{ ...inputStyle, width: 90, padding: "6px 8px", fontSize: 13 }}
          />
          <Badge tone="gray">{mmss(clip.start)}–{mmss(clip.end)}</Badge>
        </div>

        <a
          href={previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 13, color: BRAND.red, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
        >
          Preview on YouTube
        </a>
      </div>

      {/* Expandable transcript */}
      <div style={{ marginBottom: 6 }}>
        <button
          onClick={handleToggleTranscript}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 12,
            color: BRAND.sub,
            fontWeight: 600,
            padding: 0,
            textDecoration: "underline",
          }}
        >
          {transcriptOpen ? "Hide transcript" : "Show transcript"}
        </button>
        {transcriptOpen && (
          <div style={{ marginTop: 8, padding: "8px 12px", background: BRAND.bg, borderRadius: 6, fontSize: 13, color: BRAND.ink, lineHeight: 1.6 }}>
            {transcriptLoading && <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: BRAND.sub, fontSize: 13 }}><Spinner small />Loading…</span>}
            {transcriptError && <span style={{ color: BRAND.red }}>Error: {transcriptError}</span>}
            {!transcriptLoading && !transcriptError && transcriptSegs !== null && (
              transcriptSegs.length === 0
                ? <em style={{ color: BRAND.sub }}>No transcript available for this clip.</em>
                : transcriptSegs.map((seg, i) => (
                    <span key={i} style={{ display: "block", marginBottom: 4 }}>
                      <span style={{ fontSize: 11, color: BRAND.sub, marginRight: 6, fontVariantNumeric: "tabular-nums" }}>
                        {mmss(seg.start)}
                      </span>
                      {seg.text}
                    </span>
                  ))
            )}
          </div>
        )}
      </div>

      {/* Reason */}
      {clip.reason && (
        <div style={{ fontSize: 12, color: BRAND.sub, fontStyle: "italic" }}>
          {clip.reason}
        </div>
      )}
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

// ── Reel settings panel ───────────────────────────────────────────────────────

interface BrandVideoUploadProps {
  label: string;
  scene: "intro" | "outro";
  configKey: string;
  currentPath: string;
  onCleared: () => void;
}

function HelpModal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div
      role="dialog"
      aria-label={title}
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000, background: "rgba(16,24,40,0.45)",
        display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "48px 16px",
      }}
    >
      <Card style={{ width: "min(520px, 96vw)" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: BRAND.navyText }}>{title}</h3>
          <Button variant="ghost" onClick={onClose} style={{ padding: "4px 10px", fontSize: 13 }}>Close</Button>
        </div>
        <div style={{ fontSize: 14, color: BRAND.ink, lineHeight: 1.55 }}>{children}</div>
      </Card>
    </div>
  );
}

function HelpIcon({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      style={{
        width: 20, height: 20, borderRadius: "50%", border: `1px solid ${BRAND.border}`,
        background: "#fff", color: BRAND.sub, fontSize: 12, fontWeight: 700, cursor: "pointer",
        lineHeight: "18px", padding: 0,
      }}
    >
      ?
    </button>
  );
}

function BrandVideoUpload({ label, scene, configKey, currentPath, onCleared }: BrandVideoUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [path, setPath] = useState(currentPath);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPath(currentPath);
    if (!currentPath) {
      setPreviewUrl(null);
      return;
    }
    let cancelled = false;
    apiFetch(`/clips/brand-video-url?scene=${scene}`)
      .then(async (r) => (r.ok ? r.json() : null))
      .then((d: { preview_url?: string } | null) => {
        if (!cancelled) setPreviewUrl(d?.preview_url ?? null);
      })
      .catch(() => { if (!cancelled) setPreviewUrl(null); });
    return () => { cancelled = true; };
  }, [currentPath, scene]);

  async function handleFile(file: File) {
    setUploading(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await apiFetchMultipart(`/clips/upload-brand-video?scene=${scene}`, {
        method: "POST",
        body: form,
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const data = await r.json() as { gcs_path: string };
      setPath(data.gcs_path);
      setMsg("Set.");
      const prev = await apiFetch(`/clips/brand-video-url?scene=${scene}`);
      if (prev.ok) {
        const body = await prev.json() as { preview_url?: string };
        setPreviewUrl(body.preview_url ?? null);
      }
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    setMsg(null);
    try {
      const r = await apiFetch("/config", {
        method: "PUT",
        body: JSON.stringify({ key: configKey, value: "" }),
      });
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      setPath("");
      setPreviewUrl(null);
      onCleared();
      setMsg("Cleared.");
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setClearing(false);
    }
  }

  const displayName = path ? path.split("/").pop() ?? path : null;

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: BRAND.ink, marginBottom: 6 }}>{label}</div>
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4"
        style={{ display: "none" }}
        onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
      />
      <button
        type="button"
        disabled={uploading || clearing}
        onClick={() => inputRef.current?.click()}
        style={{
          position: "relative", display: "block", width: "100%", padding: 0,
          border: `1px solid ${BRAND.border}`, borderRadius: 8, overflow: "hidden",
          background: "#111", cursor: uploading ? "wait" : "pointer", aspectRatio: "16 / 9",
        }}
        title={displayName ? "Replace MP4" : "Upload MP4"}
      >
        {previewUrl ? (
          <video
            src={previewUrl}
            muted
            playsInline
            preload="metadata"
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        ) : (
          <span style={{ color: "#9ca3af", fontSize: 13 }}>
            {uploading ? "Uploading…" : "No video — click to upload"}
          </span>
        )}
        <span
          aria-hidden
          style={{
            position: "absolute", right: 10, bottom: 10, width: 32, height: 32, borderRadius: 16,
            background: "rgba(255,255,255,0.92)", color: BRAND.navyText, fontSize: 18,
            display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700,
          }}
        >
          ↑
        </span>
      </button>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, minHeight: 18 }}>
        <span style={{ fontSize: 12, color: displayName ? "#1a7f4b" : BRAND.sub }}>
          {uploading ? "Uploading…" : displayName ? displayName : "Generated title card used until you upload"}
        </span>
        {displayName && (
          <button
            type="button"
            disabled={clearing}
            onClick={handleClear}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: BRAND.sub, padding: 0, textDecoration: "underline" }}
          >
            {clearing ? "Clearing…" : "Clear"}
          </button>
        )}
        {msg && (
          <span style={{ fontSize: 12, color: msg.startsWith("Error") ? BRAND.red : BRAND.sub }}>{msg}</span>
        )}
      </div>
    </div>
  );
}

function ReelSettingsPanel() {
  const [closingText, setClosingText] = useState("");
  const [applyBrandScenes, setApplyBrandScenes] = useState(false);
  const [introVideoPath, setIntroVideoPath] = useState("");
  const [outroVideoPath, setOutroVideoPath] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [help, setHelp] = useState<"intro" | "apply" | null>(null);

  useEffect(() => {
    apiFetch("/config")
      .then((r) => r.ok ? r.json() : null)
      .then((data: { settings?: Array<{ key: string; value: string }> } | null) => {
        if (!data) return;
        const find = (k: string) => (data.settings ?? []).find((s) => s.key === k)?.value ?? "";
        setClosingText(find("REEL_CLOSING_TEXT") || "Perkins Roofing");
        setApplyBrandScenes(find("REEL_APPLY_BRAND_SCENES").toLowerCase() === "true");
        setIntroVideoPath(find("BRAND_INTRO_VIDEO"));
        setOutroVideoPath(find("BRAND_OUTRO_VIDEO"));
        setLoaded(true);
      })
      .catch(() => { setLoaded(true); });
  }, []);

  async function saveKey(key: string, value: string) {
    const r = await apiFetch("/config", {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    });
    if (!r.ok) {
            throw new Error(await errText(r));
    }
  }

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      await saveKey("REEL_CLOSING_TEXT", closingText);
      await saveKey("REEL_APPLY_BRAND_SCENES", applyBrandScenes ? "true" : "false");
      setMsg("Saved.");
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card id="reel-intro-outro" style={{ marginBottom: 24 }}>
      {help === "intro" && (
        <HelpModal title="Intro and outro" onClose={() => setHelp(null)}>
          <p style={{ margin: "0 0 10px" }}>
            Upload an MP4 for the start and end of every rendered reel. The intro is prepended
            and the outro is appended. If either is empty, the render uses a generated title
            card and the closing brand text instead.
          </p>
          <p style={{ margin: 0 }}>
            Changing these files does not recut videos that already rendered. Click
            <strong> Render now</strong> again on a series to apply the new bumpers.
          </p>
        </HelpModal>
      )}
      {help === "apply" && (
        <HelpModal title="Apply All" onClose={() => setHelp(null)}>
          <p style={{ margin: "0 0 10px" }}>
            When this is on and no intro/outro MP4 is set, each <strong>new</strong> render
            gets a generated title card plus the closing brand text.
          </p>
          <p style={{ margin: "0 0 10px" }}>
            It is <strong>not retroactive</strong>. Clips already rendered stay as they are
            until you render that series again.
          </p>
          <p style={{ margin: 0 }}>
            Future renders pick up the current setting. Intro/outro MP4s, when uploaded,
            replace these generated cards.
          </p>
        </HelpModal>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
          Reel Intro / Outro
        </div>
        <HelpIcon label="How intro and outro work" onClick={() => setHelp("intro")} />
      </div>

      {loaded ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 14 }}>
          <BrandVideoUpload
            label="Intro video"
            scene="intro"
            configKey="BRAND_INTRO_VIDEO"
            currentPath={introVideoPath}
            onCleared={() => setIntroVideoPath("")}
          />
          <BrandVideoUpload
            label="Outro video"
            scene="outro"
            configKey="BRAND_OUTRO_VIDEO"
            currentPath={outroVideoPath}
            onCleared={() => setOutroVideoPath("")}
          />
        </div>
      ) : (
        <Spinner small />
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <label style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600, whiteSpace: "nowrap" }}>
          Closing brand text
        </label>
        {!loaded ? (
          <Spinner small />
        ) : (
          <input
            type="text"
            value={closingText}
            disabled={saving}
            onChange={(e) => setClosingText(e.target.value)}
            placeholder="Perkins Roofing"
            style={{ ...inputStyle, width: 240, fontSize: 13 }}
          />
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <input
          type="checkbox"
          id="apply-brand-scenes"
          checked={applyBrandScenes}
          disabled={!loaded || saving}
          onChange={(e) => setApplyBrandScenes(e.target.checked)}
          style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
        />
        <label htmlFor="apply-brand-scenes" style={{ fontSize: 13, color: BRAND.ink, cursor: "pointer" }}>
          Apply All
        </label>
        <HelpIcon label="What Apply All means" onClick={() => setHelp("apply")} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Button
          variant="primary"
          disabled={!loaded || saving}
          onClick={handleSave}
          style={{ padding: "6px 14px", fontSize: 13 }}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        {msg && (
          <span style={{ fontSize: 12, color: msg.startsWith("Error") ? BRAND.red : BRAND.sub }}>
            {msg}
          </span>
        )}
      </div>
    </Card>
  );
}

// ── Render options (Track A spec) ─────────────────────────────────────────────

interface ClipRenderSpec {
  reframe: boolean;
  speaker_tracking: boolean;
  focus_x?: number;
  platforms?: string[];
  captions: { style: string; position: string };
  speech_cleanup: boolean;
  broll: { source: string; query_auto: boolean };
  music: { catalog: string; track_id: string; volume_db: number };
  fx: { transition: string; color_grade: string; title_card: boolean };
  emoji_highlights: boolean;
  aspects: string[];
  audio_enhance: boolean;
  audio_wind: boolean;
}

const DEFAULT_SPEC: ClipRenderSpec = {
  reframe: false,
  speaker_tracking: false,
  focus_x: 0.5,
  platforms: [],
  captions: { style: "default", position: "bottom" },
  speech_cleanup: false,
  broll: { source: "none", query_auto: true },
  music: { catalog: "none", track_id: "", volume_db: -18 },
  fx: { transition: "cut", color_grade: "none", title_card: true },
  emoji_highlights: false,
  aspects: [],
  audio_enhance: false,
  audio_wind: false,
};

function RenderOptionsPanel({
  seriesId,
  onSpecSaved,
}: {
  seriesId: number;
  onSpecSaved?: (spec: ClipRenderSpec) => void;
}) {
  const [open, setOpen] = useState(false);
  const [spec, setSpec] = useState<ClipRenderSpec>(DEFAULT_SPEC);
  const [loading, setLoading] = useState(false);
  // Save is BLOCKED until the GET lands. handleSave PUTs JSON.stringify(spec), and DEFAULT_SPEC
  // does not carry every field the server stores — redact_regions is not even in this file's
  // ClipRenderSpec type; it only exists on the object because loadSpec's response put it there.
  // So a Save inside the fetch window would PUT a spec missing that key and the server would
  // default it back to [], silently deleting an operator's PII regions. Same read-then-echo
  // round-trip that deleted the frozen price build-up in proposals.py today.
  const [specLoaded, setSpecLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function loadSpec() {
    if (loading) return;
    setLoading(true);
    apiFetch(`/clips/${seriesId}/render_spec`)
      .then((r) => r.ok ? r.json() : null)
      .then((data: ClipRenderSpec | null) => { if (data) { setSpec(data); setSpecLoaded(true); } })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  function handleToggle() {
    if (!open) loadSpec();
    setOpen((o) => !o);
    setMsg(null);
  }

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      const r = await apiFetch(`/clips/${seriesId}/render_spec`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(spec),
      });
      if (!r.ok) throw new Error(await errText(r));
      const saved: ClipRenderSpec = await r.json();
      setSpec(saved);
      setMsg("Options saved.");
      onSpecSaved?.(saved);
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap",
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 13, color: BRAND.ink, fontWeight: 600, minWidth: 120,
  };
  const selectStyle: React.CSSProperties = {
    ...inputStyle, fontSize: 13, padding: "4px 8px", minWidth: 130,
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={handleToggle}
        style={{
          background: "none", border: "none", cursor: "pointer",
          fontSize: 12, color: BRAND.sub, padding: 0, fontWeight: 600,
          textDecoration: "underline",
        }}
      >
        {open ? "Hide render options ▲" : "Render options ▼"}
      </button>

      {open && (
        <div
          style={{
            marginTop: 10, padding: "12px 14px",
            background: "#f8f9fb", borderRadius: 8,
            border: `1px solid ${BRAND.border}`,
          }}
        >
          {loading && <Spinner small />}

          {!loading && (
            <>
              {/* Reframe */}
              <div style={rowStyle}>
                <label style={labelStyle}>Reframe 9:16</label>
                <input
                  type="checkbox"
                  checked={spec.reframe}
                  onChange={(e) => setSpec({ ...spec, reframe: e.target.checked })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>Auto-crop to vertical</span>
              </div>

              {/* Speaker tracking */}
              {spec.reframe && (
                <>
                <div style={{ ...rowStyle, paddingLeft: 24 }}>
                  <label style={{ ...labelStyle, color: BRAND.sub }}>Speaker tracking</label>
                  <input
                    type="checkbox"
                    checked={spec.speaker_tracking}
                    onChange={(e) => setSpec({ ...spec, speaker_tracking: e.target.checked })}
                    style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                  />
                  <span style={{ fontSize: 12, color: BRAND.sub }}>
                    Face-centroid tracking crop (requires face detector adapter — falls back to centre-crop when not wired)
                  </span>
                </div>
                {!spec.speaker_tracking && (
                  <div style={{ ...rowStyle, paddingLeft: 24 }}>
                    <label style={{ ...labelStyle, color: BRAND.sub }}>Focal point</label>
                    <input
                      type="range" min="0" max="1" step="0.05"
                      value={spec.focus_x ?? 0.5}
                      onChange={(e) => setSpec({ ...spec, focus_x: Number(e.target.value) })}
                      style={{ flex: 1, maxWidth: 200, cursor: "pointer", accentColor: BRAND.red }}
                    />
                    <span style={{ fontSize: 12, color: BRAND.sub }}>
                      Crop centre {Math.round((spec.focus_x ?? 0.5) * 100)}% — {(spec.focus_x ?? 0.5) < 0.4 ? "left" : (spec.focus_x ?? 0.5) > 0.6 ? "right" : "centre"}
                    </span>
                  </div>
                )}
                </>
              )}

              {/* Speech cleanup */}
              <div style={rowStyle}>
                <label style={labelStyle}>Speech cleanup</label>
                <input
                  type="checkbox"
                  checked={spec.speech_cleanup}
                  onChange={(e) => setSpec({ ...spec, speech_cleanup: e.target.checked })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>Remove filler words / stutters (requires transcript)</span>
              </div>

              {/* Audio enhance */}
              <div style={rowStyle}>
                <label style={labelStyle}>Audio enhance</label>
                <input
                  type="checkbox"
                  checked={spec.audio_enhance}
                  // Clearing audio_wind here is what makes the disabled state below honest.
                  // Without it, tick wind -> untick enhance leaves {audio_wind: true,
                  // audio_enhance: false} in the payload: a flag the render silently ignores,
                  // set from the UI, with the box greyed out so nobody can see or clear it.
                  onChange={(e) => setSpec({
                    ...spec,
                    audio_enhance: e.target.checked,
                    audio_wind: e.target.checked ? spec.audio_wind : false,
                  })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>Denoise + compress + loudnorm (EBU R128, -14 LUFS)</span>
              </div>

              {/* Outdoor / wind. Nested under audio_enhance and disabled when it is off, because
                  the flag only modifies that chain — on its own it does nothing, and a checkbox
                  that silently does nothing is how this repo keeps shipping unreachable config.
                  Ticking enhance does not tick this: the wind profile is measurably better on
                  outdoor footage and measurably pointless indoors, so it stays an operator call. */}
              <div style={{ ...rowStyle, marginLeft: 24, opacity: spec.audio_enhance ? 1 : 0.45 }}>
                <label style={labelStyle}>└ Outdoor / wind</label>
                <input
                  type="checkbox"
                  checked={spec.audio_wind}
                  disabled={!spec.audio_enhance}
                  onChange={(e) => setSpec({ ...spec, audio_wind: e.target.checked })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red,
                           cursor: spec.audio_enhance ? "pointer" : "not-allowed" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>
                  {spec.audio_enhance
                    ? "High-pass wind rumble at 90 Hz and denoise more gently. Measured 2.8 dB better than the default chain on outdoor phone footage — which is worse than doing nothing, because loudnorm boosts the rumble."
                    : "Turn on Audio enhance first — this only modifies that chain."}
                </span>
              </div>

              {/* Publish targets (auto-schedule) */}
              <div style={rowStyle}>
                <label style={labelStyle}>Publish to</label>
                <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
                  {(["instagram", "tiktok"] as const).map((p) => (
                    <label key={p} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: BRAND.ink, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={(spec.platforms ?? []).includes(p)}
                        onChange={(e) => {
                          const cur = spec.platforms ?? [];
                          const next = e.target.checked ? [...cur, p] : cur.filter((x) => x !== p);
                          setSpec({ ...spec, platforms: Array.from(new Set(next)) });
                        }}
                        style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                      />
                      {p === "instagram" ? "Instagram" : "TikTok"}
                    </label>
                  ))}
                  <span style={{ fontSize: 11, color: BRAND.sub }}>None selected = Instagram + TikTok</span>
                </div>
              </div>

              {/* Captions */}
              <div style={rowStyle}>
                <label style={labelStyle}>Captions</label>
                <select
                  value={spec.captions.style}
                  onChange={(e) => setSpec({ ...spec, captions: { ...spec.captions, style: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="default">Off (no burned captions)</option>
                  <option value="bold_yellow">Bold yellow (legacy)</option>
                  <option value="tiktok_pop">TikTok Pop</option>
                  <option value="reels_clean">Reels Clean</option>
                  <option value="shorts_editorial">Shorts Editorial</option>
                </select>
                <select
                  value={spec.captions.position}
                  onChange={(e) => setSpec({ ...spec, captions: { ...spec.captions, position: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="bottom">Bottom</option>
                  <option value="top">Top</option>
                </select>
              </div>

              {/* Emoji highlights */}
              <div style={rowStyle}>
                <label style={labelStyle}>Emoji highlights</label>
                <input
                  type="checkbox"
                  checked={spec.emoji_highlights}
                  onChange={(e) => setSpec({ ...spec, emoji_highlights: e.target.checked })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>
                  Append roofing-domain emoji to matched keywords in captions
                </span>
              </div>

              {/* Aspects */}
              <div style={rowStyle}>
                <label style={labelStyle}>Export aspects</label>
                <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                  <label style={{ fontSize: 13, color: BRAND.ink, display: "flex", alignItems: "center", gap: 6 }}>
                    <input
                      type="checkbox"
                      checked
                      disabled
                      style={{ width: 14, height: 14, accentColor: BRAND.sub }}
                    />
                    9:16 (always)
                  </label>
                  <label style={{ fontSize: 13, color: BRAND.ink, display: "flex", alignItems: "center", gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={(spec.aspects ?? []).includes("square")}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...(spec.aspects ?? []).filter((a) => a !== "square"), "square"]
                          : (spec.aspects ?? []).filter((a) => a !== "square");
                        setSpec({ ...spec, aspects: next });
                      }}
                      style={{ width: 14, height: 14, accentColor: BRAND.red, cursor: "pointer" }}
                    />
                    1:1 square (1080×1080)
                  </label>
                  <label style={{ fontSize: 13, color: BRAND.ink, display: "flex", alignItems: "center", gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={(spec.aspects ?? []).includes("wide")}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...(spec.aspects ?? []).filter((a) => a !== "wide"), "wide"]
                          : (spec.aspects ?? []).filter((a) => a !== "wide");
                        setSpec({ ...spec, aspects: next });
                      }}
                      style={{ width: 14, height: 14, accentColor: BRAND.red, cursor: "pointer" }}
                    />
                    16:9 wide (1920×1080)
                  </label>
                </div>
              </div>

              {/* B-roll */}
              <div style={rowStyle}>
                <label style={labelStyle}>B-roll source</label>
                <select
                  value={spec.broll.source}
                  onChange={(e) => setSpec({ ...spec, broll: { ...spec.broll, source: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="none">None</option>
                  <option value="pexels">Pexels (key required)</option>
                </select>
                {spec.broll.source === "pexels" && (
                  <span style={{ fontSize: 12, color: BRAND.sub }}>PEXELS_API_KEY must be set server-side</span>
                )}
              </div>

              {/* Music */}
              <div style={rowStyle}>
                <label style={labelStyle}>Background music</label>
                <select
                  value={spec.music.catalog}
                  onChange={(e) => setSpec({ ...spec, music: { ...spec.music, catalog: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="none">None</option>
                  <option value="pixabay">Pixabay</option>
                  <option value="fma">FMA</option>
                </select>
                {spec.music.catalog !== "none" && (
                  <input
                    type="text"
                    placeholder="Track ID"
                    value={spec.music.track_id}
                    onChange={(e) => setSpec({ ...spec, music: { ...spec.music, track_id: e.target.value } })}
                    style={{ ...inputStyle, fontSize: 13, width: 120, padding: "4px 8px" }}
                  />
                )}
                {spec.music.catalog !== "none" && (
                  <label style={{ fontSize: 12, color: BRAND.sub }}>
                    Vol&nbsp;
                    <input
                      type="number"
                      min={-60}
                      max={0}
                      step={1}
                      value={spec.music.volume_db}
                      onChange={(e) => setSpec({ ...spec, music: { ...spec.music, volume_db: Number(e.target.value) } })}
                      style={{ ...inputStyle, fontSize: 13, width: 60, padding: "4px 6px" }}
                    />
                    &nbsp;dB
                  </label>
                )}
              </div>

              {/* FX */}
              <div style={rowStyle}>
                <label style={labelStyle}>Transition</label>
                <select
                  value={spec.fx.transition}
                  onChange={(e) => setSpec({ ...spec, fx: { ...spec.fx, transition: e.target.value } })}
                  style={selectStyle}
                >
                  {/* wipe/slide/dissolve removed (#344): those are xfade transitions
                      between two clips (see core/clip_fx.py) — only meaningful at the
                      brand-fuse step (intro+clip+outro), not on a single clip's render.
                      Fade is a genuine single-clip fade-in/out, so it stays. */}
                  <option value="cut">Cut (none)</option>
                  <option value="fade">Fade</option>
                </select>
                <label style={labelStyle}>Color grade</label>
                <select
                  value={spec.fx.color_grade}
                  onChange={(e) => setSpec({ ...spec, fx: { ...spec.fx, color_grade: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="none">None</option>
                  <option value="vivid">Vivid</option>
                  <option value="warm">Warm</option>
                  <option value="cool">Cool</option>
                </select>
              </div>

              {/* Save */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
                <Button
                  variant="ghost"
                  disabled={saving || !specLoaded}
                  onClick={handleSave}
                  style={{ padding: "5px 12px", fontSize: 13 }}
                >
                  {saving ? "Saving…" : !specLoaded ? "Loading…" : "Save options"}
                </Button>
                {msg && (
                  <span style={{ fontSize: 12, color: msg.startsWith("Error") ? BRAND.red : BRAND.sub }}>
                    {msg}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Ready-to-render panel ─────────────────────────────────────────────────────

function RenderableRow({ s }: { s: RenderableSeries }) {
  const partCount = s.parts_count ?? s.parts.length;
  const [triggering, setTriggering] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [status, setStatus] = useState<RenderStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  async function handlePreview() {
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }
    if (previewUrl) {
      setPreviewOpen(true);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const r = await apiFetch(`/clips/${s.id}/preview-url`);
      if (!r.ok) {
                throw new Error(await errText(r));
      }
      const data = await r.json() as { preview_url: string };
      setPreviewUrl(data.preview_url);
      setPreviewOpen(true);
    } catch (e: unknown) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewLoading(false);
    }
  }

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
      if (!r.ok) throw new Error(await errText(r));
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
        padding: "10px 12px",
        background: BRAND.bg,
        borderRadius: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
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

        {isRendered && (
          <Button
            variant="ghost"
            disabled={previewLoading}
            onClick={handlePreview}
            style={{ padding: "5px 12px", fontSize: 13 }}
          >
            {previewLoading ? "Loading…" : previewOpen ? "Hide preview" : "Play preview"}
          </Button>
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

      {previewError && (
        <div style={{ marginTop: 8, fontSize: 12, color: BRAND.red }}>
          Preview error: {previewError}
        </div>
      )}

      {previewOpen && previewUrl && (
        <div style={{ marginTop: 10 }}>
          <video
            src={previewUrl}
            controls
            style={{
              maxWidth: "100%",
              maxHeight: 480,
              borderRadius: 8,
              background: "#000",
              display: "block",
            }}
          />
        </div>
      )}

      {!isRendered && (
        <RenderOptionsPanel seriesId={s.id} />
      )}
    </div>
  );
}

function RenderablePanel() {
  const { navigate } = useContext(NavContext);
  const [series, setSeries] = useState<RenderableSeries[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/clips/renderable")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
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
        <div style={{ fontSize: 13, color: BRAND.ink, lineHeight: 1.55 }}>
          <p style={{ margin: "0 0 8px", color: BRAND.sub }}>No approved series awaiting render.</p>
          <p style={{ margin: "0 0 8px" }}>To put a reel here:</p>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>Pick a source video below (or Edit one that already has clips).</li>
            <li>Suggest clips, then <strong>Save as clip series</strong>.</li>
            <li>
              Open{" "}
              <button
                type="button"
                onClick={() => navigate("video-approval")}
                style={{ background: "none", border: "none", padding: 0, color: BRAND.red, fontWeight: 600, cursor: "pointer", fontSize: 13 }}
              >
                Video Approval
              </button>
              {" "}and Approve the series.
            </li>
            <li>It appears here — set render options, then <strong>Render now</strong>.</li>
          </ol>
        </div>
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

// ── Generated clips list ──────────────────────────────────────────────────────

function ytThumb(id: string): string {
  return `https://i.ytimg.com/vi/${id}/mqdefault.jpg`;
}

function GeneratedClipsList({
  videos,
  onRevisit,
}: {
  videos: ArchiveVideo[];
  onRevisit: (v: ArchiveVideo) => void;
}) {
  const { navigate } = useContext(NavContext);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const withClips = videos.filter((v) => v.clips_generated);
  if (withClips.length === 0) return null;

  function scrollToIntro() {
    document.getElementById("reel-intro-outro")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <Card style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 12, fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
        Videos with generated clips
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {withClips.map((v) => {
          const open = previewId === v.id;
          return (
            <div
              key={v.id}
              style={{
                display: "flex",
                gap: 12,
                padding: 10,
                background: BRAND.bg,
                borderRadius: 10,
                alignItems: "flex-start",
              }}
            >
              <button
                type="button"
                onClick={() => setPreviewId(open ? null : v.id)}
                style={{
                  position: "relative", flex: "0 0 168px", width: 168, height: 94, padding: 0,
                  border: "none", borderRadius: 8, overflow: "hidden", background: "#111", cursor: "pointer",
                }}
                title="Preview"
              >
                <img
                  src={ytThumb(v.id)}
                  alt=""
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                />
                <span
                  style={{
                    position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
                    color: "#fff", fontSize: 22, textShadow: "0 1px 4px rgba(0,0,0,0.6)",
                  }}
                >
                  ▶
                </span>
                {v.duration != null && (
                  <span
                    style={{
                      position: "absolute", right: 6, bottom: 6, background: "rgba(0,0,0,0.8)",
                      color: "#fff", fontSize: 11, padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                    }}
                  >
                    {formatDuration(v.duration)}
                  </span>
                )}
              </button>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: BRAND.ink, fontSize: 14, lineHeight: 1.35 }}>
                  {v.title}
                </div>
                {v.description && (
                  <div
                    style={{
                      marginTop: 4, fontSize: 12, color: BRAND.sub, lineHeight: 1.4,
                      display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                    }}
                  >
                    {v.description}
                  </div>
                )}
                <div style={{ marginTop: 4, fontSize: 12, color: BRAND.sub }}>
                  {v.clips_generated_at ? formatClipDate(v.clips_generated_at) : "Clips generated"}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={() => navigate("video-approval", { series: v.id })}
                    style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 13, color: BRAND.navyText, fontWeight: 600 }}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onRevisit(v)}
                    style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 13, color: BRAND.red, fontWeight: 600 }}
                  >
                    Re-generate →
                  </button>
                  <button
                    type="button"
                    onClick={scrollToIntro}
                    style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 13, color: BRAND.navyText, fontWeight: 600 }}
                  >
                    Intro / Outro
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {previewId && (
        <div style={{ marginTop: 12 }}>
          <iframe
            title="Clip preview"
            src={`https://www.youtube.com/embed/${previewId}?autoplay=1`}
            allow="autoplay; encrypted-media"
            allowFullScreen
            style={{ width: "100%", aspectRatio: "16 / 9", border: 0, borderRadius: 8, background: "#000" }}
          />
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
  const { params, navigate: navNavigate } = useContext(NavContext);
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const [suggesting, setSuggesting] = useState(false);
  const [suggestPlatform, setSuggestPlatform] = useState<string>("");
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // All videos loaded by the picker — used for GeneratedClipsList and preselect.
  const [allVideos, setAllVideos] = useState<ArchiveVideo[]>([]);
  // Track whether we've consumed the incoming nav param.
  const preselectedRef = useRef(false);

  // When videos are loaded by the picker, check if there's a pending preselect param.
  function handleVideosLoaded(videos: ArchiveVideo[]) {
    setAllVideos(videos);
    if (!preselectedRef.current && params.video) {
      const target = videos.find((v) => v.id === params.video);
      if (target) {
        preselectedRef.current = true;
        // Clear the param so a manual "start over" doesn't re-trigger.
        navNavigate("clip-studio", {});
        setStep({ kind: "suggest", video: target });
        setSuggestError(null);
      }
    }
  }

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
        body: JSON.stringify({ video_id: video.id, ...(suggestPlatform ? { platform: suggestPlatform } : {}) }),
      });
      if (!r.ok) {
        const detail = await errText(r);
        if (r.status === 404 && detail.includes("transcript")) {
          throw new Error("This video has no transcript, so clips can't be suggested. Pick a different video.");
        }
        throw new Error(detail ?? `${r.status} ${r.statusText}`);
      }
      // Backend returns { video_id, video_title, suggestions: [...] }
      const data: { video_title: string; suggestions: SuggestedClip[] } = await r.json();
      const editable: EditableClip[] = (data.suggestions ?? []).map((c) => ({ ...c, included: true }));
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
    const title = seriesTitle(step.video.title);
    try {
      const r = await apiFetch("/clips/save", {
        method: "POST",
        body: JSON.stringify({
          video_id: step.video.id,
          title: title,
          parts: selected.map(({ title: partTitle, start, end, hook }) => ({ title: partTitle, start, end, hook: hook ?? "" })),
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      setStep({ kind: "saved", seriesTitle: title });
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const [helpOpen, setHelpOpen] = useState(false);

  return (
    <main style={{ maxWidth: 820 }}>
      {helpOpen && <ClipStudioHelp onClose={() => setHelpOpen(false)} />}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <PageTitle>Clip Studio</PageTitle>
        <Button variant="ghost" style={{ fontSize: 13 }} onClick={() => setHelpOpen(true)}>? Help — features</Button>
      </div>

      {/* Ready-to-render panel — always visible */}
      <RenderablePanel />

      {/* Reel intro/outro settings — always visible */}
      <ReelSettingsPanel />

      {/* Step: saved */}
      {step.kind === "saved" && (
        <>
          <SuccessBanner seriesTitle={step.seriesTitle} />
          <div style={{ marginTop: 16 }}>
            <Button variant="ghost" onClick={() => { preselectedRef.current = false; setStep({ kind: "pick" }); }}>
              Start another
            </Button>
          </div>
        </>
      )}

      {/* Step: pick — show generated list + picker */}
      {step.kind === "pick" && (
        <>
          <GeneratedClipsList
            videos={allVideos}
            onRevisit={(v) => { setStep({ kind: "suggest", video: v }); setSuggestError(null); }}
          />
          <VideoPicker onSelect={handleVideoSelect} onVideosLoaded={handleVideosLoaded} />
        </>
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

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 6 }}>
              Tune suggestions for a platform (optional) — shapes hook, caption style, hashtags &amp; length:
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {([["", "General"], ["instagram", "Instagram"], ["tiktok", "TikTok"], ["youtube_shorts", "YouTube Shorts"], ["facebook", "Facebook"]] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSuggestPlatform(key)}
                  disabled={suggesting}
                  style={{
                    padding: "5px 12px", fontSize: 12, fontWeight: 600, borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${BRAND.border}`,
                    background: suggestPlatform === key ? BRAND.navy : "#fff",
                    color: suggestPlatform === key ? "#fff" : BRAND.sub,
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Button onClick={() => handleSuggest(step.video)} disabled={suggesting}>
              {suggesting ? "Analyzing video… (may take 15–30s)" : "Suggest clips"}
            </Button>
            <Button variant="ghost" onClick={() => setStep({ kind: "pick" })} disabled={suggesting}>
              Back
            </Button>
          </div>

          {suggesting && (
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Spinner />
                <span style={{ fontSize: 14, fontWeight: 600, color: BRAND.navyText }}>Analyzing transcript…</span>
              </div>
              <AnalyzingDots />
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
              Series will be saved as: <strong style={{ color: BRAND.ink }}>{seriesTitle(step.video.title)}</strong>
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
