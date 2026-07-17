import { useContext, useEffect, useRef, useState } from "react";
import { apiFetch, apiFetchMultipart } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, Badge, Spinner } from "../ui";
import { NavContext } from "../App";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ArchiveVideo {
  id: string;
  title: string;
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

/** Mirror of core.miniseries.clean_title: strip emojis, hashtags, leading junk. */
function cleanTitle(text: string): string {
  // Remove emoji ranges
  let s = text.replace(/[☀-➿ἰ0-ᾯF︀-️←-⇿⬀-⯿]/gu, "");
  // Remove hashtag tokens
  s = s.replace(/(?:^|\s)#\w+/g, " ");
  // Strip leading/trailing junk
  s = s.replace(/^[\s#@*•\-–—|]+/, "").replace(/[\s#@*•\-–—|]+$/, "");
  // Collapse whitespace
  return s.replace(/\s+/g, " ").trim();
}

/** Produce a concise clip-series title: clean + truncate at word boundary ≤50 chars. */
function seriesTitle(videoTitle: string): string {
  const cleaned = cleanTitle(videoTitle);
  if (!cleaned) return "Clips";
  const MAX = 50;
  const truncated = cleaned.length > MAX
    ? cleaned.slice(0, MAX).replace(/\s+\S*$/, "").trim()
    : cleaned;
  return `${truncated} — Clips`;
}

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
  const [videos, setVideos] = useState<ArchiveVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hideWithClips, setHideWithClips] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (search) qs.set("q", search);
    apiFetch(`/archive/videos?${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ArchiveVideo[]) => {
        setVideos(data);
        onVideosLoaded?.(data);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

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
        .then((r) => {
          if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
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

function BrandVideoUpload({ label, scene, configKey, currentPath, onCleared }: BrandVideoUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [path, setPath] = useState(currentPath);
  const inputRef = useRef<HTMLInputElement>(null);

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
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status}`);
      }
      const data = await r.json() as { gcs_path: string };
      setPath(data.gcs_path);
      setMsg("Set.");
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
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status}`);
      }
      setPath("");
      onCleared();
      setMsg("Cleared.");
    } catch (e: unknown) {
      setMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setClearing(false);
    }
  }

  // Derive a short display name from the gs:// path (last segment).
  const displayName = path ? path.split("/").pop() ?? path : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: BRAND.ink }}>{label}</span>
      {displayName ? (
        <span style={{ fontSize: 11, color: "#1a7f4b", fontFamily: "monospace", wordBreak: "break-all" }}>
          ✓ {displayName}
        </span>
      ) : (
        <span style={{ fontSize: 11, color: BRAND.sub, fontStyle: "italic" }}>
          Not set — generated card used as fallback
        </span>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          ref={inputRef}
          type="file"
          accept="video/mp4"
          style={{ display: "none" }}
          onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
        />
        <Button
          variant="ghost"
          disabled={uploading || clearing}
          onClick={() => inputRef.current?.click()}
          style={{ padding: "4px 12px", fontSize: 12 }}
        >
          {uploading ? "Uploading…" : (displayName ? "Replace" : "Upload MP4")}
        </Button>
        {displayName && (
          <button
            disabled={clearing}
            onClick={handleClear}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              color: BRAND.sub,
              padding: 0,
              textDecoration: "underline",
            }}
          >
            {clearing ? "Clearing…" : "Clear"}
          </button>
        )}
        {msg && (
          <span style={{ fontSize: 12, color: msg.startsWith("Error") ? BRAND.red : BRAND.sub }}>
            {msg}
          </span>
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
      const body = await r.json().catch(() => ({}));
      throw new Error((body as { detail?: string }).detail ?? `${r.status}`);
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
    <Card style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 10, fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
        Reel Intro / Outro
      </div>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: BRAND.sub, lineHeight: 1.5 }}>
        Upload an <strong>intro video</strong> and <strong>outro video</strong> (MP4) to be
        concatenated with every rendered reel. When set, these videos are merged directly
        into each clip — the intro is prepended and the outro is appended. Falls back to
        auto-generated title and closing cards when no videos are set.
      </p>

      {/* Brand video uploads */}
      {loaded && (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 14 }}>
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
      )}
      {!loaded && <Spinner small />}

      {/* Closing brand text */}
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

      {/* Apply checkbox */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <input
          type="checkbox"
          id="apply-brand-scenes"
          checked={applyBrandScenes}
          disabled={!loaded || saving}
          onChange={(e) => setApplyBrandScenes(e.target.checked)}
          style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
        />
        <label
          htmlFor="apply-brand-scenes"
          style={{ fontSize: 13, color: BRAND.ink, cursor: "pointer" }}
        >
          Apply brand scenes to every render (used when no intro/outro videos are set)
        </label>
      </div>

      {/* Save */}
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
  captions: { style: string; position: string };
  speech_cleanup: boolean;
  broll: { source: string; query_auto: boolean };
  music: { catalog: string; track_id: string; volume_db: number };
  fx: { transition: string; color_grade: string; title_card: boolean };
  emoji_highlights: boolean;
  aspects: string[];
  audio_enhance: boolean;
}

const DEFAULT_SPEC: ClipRenderSpec = {
  reframe: false,
  speaker_tracking: false,
  captions: { style: "default", position: "bottom" },
  speech_cleanup: false,
  broll: { source: "none", query_auto: true },
  music: { catalog: "none", track_id: "", volume_db: -18 },
  fx: { transition: "cut", color_grade: "none", title_card: true },
  emoji_highlights: false,
  aspects: [],
  audio_enhance: false,
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
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function loadSpec() {
    if (loading) return;
    setLoading(true);
    apiFetch(`/clips/${seriesId}/render_spec`)
      .then((r) => r.ok ? r.json() : null)
      .then((data: ClipRenderSpec | null) => { if (data) setSpec(data); })
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
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
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
                  onChange={(e) => setSpec({ ...spec, audio_enhance: e.target.checked })}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 12, color: BRAND.sub }}>Denoise + compress + loudnorm (EBU R128, -14 LUFS)</span>
              </div>

              {/* Captions */}
              <div style={rowStyle}>
                <label style={labelStyle}>Captions</label>
                <select
                  value={spec.captions.style}
                  onChange={(e) => setSpec({ ...spec, captions: { ...spec.captions, style: e.target.value } })}
                  style={selectStyle}
                >
                  <option value="default">Default</option>
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
                  <option value="cut">Cut (none)</option>
                  <option value="fade">Fade</option>
                  <option value="wipe">Wipe</option>
                  <option value="slide">Slide</option>
                  <option value="dissolve">Dissolve</option>
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
                  disabled={saving}
                  onClick={handleSave}
                  style={{ padding: "5px 12px", fontSize: 13 }}
                >
                  {saving ? "Saving…" : "Save options"}
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
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `${r.status}`);
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

// ── Generated clips list ──────────────────────────────────────────────────────

function GeneratedClipsList({
  videos,
  onRevisit,
}: {
  videos: ArchiveVideo[];
  onRevisit: (v: ArchiveVideo) => void;
}) {
  const withClips = videos.filter((v) => v.clips_generated);
  if (withClips.length === 0) return null;
  return (
    <Card style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 10, fontSize: 13, fontWeight: 700, color: BRAND.navyText, textTransform: "uppercase", letterSpacing: 0.4 }}>
        Videos with generated clips
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {withClips.map((v) => (
          <div
            key={v.id}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 12px",
              background: BRAND.bg,
              borderRadius: 8,
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <span style={{ fontWeight: 500, color: BRAND.ink, fontSize: 14, flex: 1 }}>{v.title}</span>
            {v.clips_generated_at && (
              <span style={{ fontSize: 12, color: BRAND.sub, whiteSpace: "nowrap" }}>
                {formatClipDate(v.clips_generated_at)}
              </span>
            )}
            <button
              onClick={() => onRevisit(v)}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: 13,
                color: BRAND.red,
                fontWeight: 600,
                padding: 0,
                whiteSpace: "nowrap",
              }}
            >
              Re-generate →
            </button>
          </div>
        ))}
      </div>
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
        body: JSON.stringify({ video_id: video.id }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        const detail = (body as { detail?: string }).detail;
        if (r.status === 404 && detail?.includes("transcript")) {
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
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setStep({ kind: "saved", seriesTitle: title });
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
