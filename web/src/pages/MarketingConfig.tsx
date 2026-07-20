import { useEffect, useState, useCallback, useRef } from "react";
import {
  BRAND,
  FONT,
  Card,
  Button,
  Loading,
  ErrorMsg,
  Badge,
  inputStyle,
} from "../ui";
import {
  apiFetch,
  getMarketingSettings,
  putMarketingSettings,
  getBrandUploadUrl,
  getBrandViewUrl,
  listConnections,
  startOAuth,
  type BrandKit,
  type Connection,
  type MarketingSettings,
} from "../api";
import { errText } from "../lib/errors";

// ── Types ─────────────────────────────────────────────────────────────────────

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

function canManage(role: Role): boolean {
  return role === "admin" || role === "web_admin" || role === "platform_admin";
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: BRAND.sub,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        margin: "20px 0 8px",
      }}
    >
      {children}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label
      style={{
        display: "block",
        fontSize: 11,
        fontWeight: 600,
        color: BRAND.sub,
        marginBottom: 3,
        textTransform: "uppercase",
        letterSpacing: 0.3,
      }}
    >
      {children}
    </label>
  );
}

function HelpText({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <p style={{ margin: "3px 0 0", fontSize: 11, color: BRAND.sub, lineHeight: 1.4, ...style }}>
      {children}
    </p>
  );
}

// Color swatch + hex input pair
function ColorField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <FieldLabel>{label}</FieldLabel>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="color"
          value={value || "#000000"}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          style={{
            width: 36,
            height: 36,
            border: `1px solid ${BRAND.border}`,
            borderRadius: 6,
            padding: 2,
            cursor: disabled ? "not-allowed" : "pointer",
            background: "none",
          }}
        />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder="#000000"
          style={{
            ...inputStyle,
            padding: "7px 10px",
            fontSize: 13,
            width: 110,
            fontFamily: "monospace",
            background: disabled ? BRAND.bg : "#fff",
          }}
        />
      </div>
    </div>
  );
}

// GCS URI field with optional file upload button
function GcsUriField({
  label,
  value,
  onChange,
  onUpload,
  disabled,
  accept,
  helpText,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onUpload: (file: File) => Promise<string>;
  disabled: boolean;
  accept: string;
  helpText?: string;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);  // just-uploaded local blob
  const [remoteUrl, setRemoteUrl] = useState<string | null>(null);    // signed GET for a saved gs:// asset
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  // A fresh local blob always wins; otherwise fetch a signed GET URL for the saved asset.
  useEffect(() => {
    if (previewUrl) return;              // just uploaded — the blob is already showing
    if (!value.startsWith("gs://")) { setRemoteUrl(null); return; }
    let cancelled = false;
    getBrandViewUrl(value).then((u) => { if (!cancelled) setRemoteUrl(u); }).catch(() => { if (!cancelled) setRemoteUrl(null); });
    return () => { cancelled = true; };
  }, [value, previewUrl]);

  const shownPreview = previewUrl ?? remoteUrl;
  const previewKind = accept.includes("video") ? "video" : accept.includes("audio") ? "audio" : "image";

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const gcsPath = await onUpload(file);
      onChange(gcsPath);
      setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(file); });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <FieldLabel>{label}</FieldLabel>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder="gs://bucket/tenants/1/brand/…"
          style={{
            ...inputStyle,
            padding: "7px 10px",
            fontSize: 12,
            flex: 1,
            fontFamily: "monospace",
            background: disabled ? BRAND.bg : "#fff",
          }}
        />
        {!disabled && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept={accept}
              onChange={handleFile}
              style={{ display: "none" }}
            />
            <Button
              variant="ghost"
              style={{ fontSize: 12, padding: "7px 14px", whiteSpace: "nowrap" }}
              disabled={uploading}
              onClick={() => fileRef.current?.click()}
            >
              {uploading ? "Uploading…" : "Upload"}
            </Button>
          </>
        )}
      </div>
      {helpText && <HelpText>{helpText}</HelpText>}
      {uploadError && <ErrorMsg>{uploadError}</ErrorMsg>}
      {shownPreview && (
        <div style={{ marginTop: 8 }}>
          {previewKind === "image" && (
            <img src={shownPreview} alt="preview" style={{ maxHeight: 80, maxWidth: 200, borderRadius: 6, border: `1px solid ${BRAND.border}` }} />
          )}
          {previewKind === "video" && (
            <video src={shownPreview} controls style={{ maxHeight: 120, maxWidth: 240, borderRadius: 6, border: `1px solid ${BRAND.border}` }} />
          )}
          {previewKind === "audio" && <audio src={shownPreview} controls style={{ width: "100%", maxWidth: 260 }} />}
        </div>
      )}
    </div>
  );
}

// Social account row driven by GET /connections. The OAuth capture flow for all
// platforms exists on the backend (api/routes/connections.py); a platform is only
// clickable once its client credentials are in place (oauth_configured), so we
// never fire a redirect that would 503 — we show "Setup pending" instead.
const PLATFORM_LABEL: Record<string, string> = {
  youtube: "YouTube",
  facebook: "Facebook",
  instagram: "Instagram",
  tiktok: "TikTok",
};

function SocialAccountRow({
  platform,
  conn,
  onConnect,
  connecting,
  manage,
}: {
  platform: string;
  conn: Connection | undefined;
  onConnect: (platform: string) => void;
  connecting: boolean;
  manage: boolean;
}) {
  const connected = conn?.status === "ok";
  const configured = conn?.oauth_configured ?? false;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        borderRadius: 8,
        border: `1px solid ${BRAND.border}`,
        marginBottom: 6,
        background: "#fff",
      }}
    >
      <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>
        {PLATFORM_LABEL[platform] ?? platform}
      </span>

      {connected ? (
        <Badge tone="green">Connected</Badge>
      ) : configured ? (
        <>
          <Badge tone="amber">Not connected</Badge>
          {manage && (
            <Button variant="ghost" style={{ fontSize: 12, padding: "5px 12px" }} disabled={connecting} onClick={() => onConnect(platform)}>
              {connecting ? "Connecting…" : "Connect"}
            </Button>
          )}
        </>
      ) : (
        <>
          <Badge tone="gray">Setup pending</Badge>
          <span style={{ fontSize: 11, color: BRAND.sub }}>needs {PLATFORM_LABEL[platform] ?? platform} app credentials</span>
        </>
      )}
    </div>
  );
}

// YouTube row — unlike the other platforms this one is click-to-authenticate:
// reflects whether the token can ACTUALLY post (via /comments/reply-config) and
// offers a Connect/Reconnect button using the same pattern as Comments.tsx.
interface ReplyConfig {
  oauth_configured: boolean;
  can_post: boolean;
  channel_title: string;
  reason: string;
  can_reconnect: boolean;
  connect_path: string | null;
}

function YouTubeConnectRow({
  replyCfg,
  onConnect,
  error,
}: {
  replyCfg: ReplyConfig | null;
  onConnect: () => void;
  error: string | null;
}) {
  const connected = replyCfg?.can_post ?? false;

  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 8,
        border: `1px solid ${BRAND.border}`,
        marginBottom: 6,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>YouTube</span>

        {!replyCfg ? (
          <Badge tone="gray">Loading…</Badge>
        ) : connected ? (
          <>
            <Badge tone="green">Connected</Badge>
            <span style={{ fontSize: 11, color: BRAND.sub, fontFamily: "monospace" }}>
              {replyCfg.channel_title}
            </span>
          </>
        ) : (
          <Badge tone="amber">Reconnect needed</Badge>
        )}

        {replyCfg?.can_reconnect && (
          <Button variant="ghost" style={{ fontSize: 12, padding: "4px 10px" }} onClick={onConnect}>
            {connected ? "Switch account" : "Connect YouTube"}
          </Button>
        )}
      </div>
      {error && <ErrorMsg>{error}</ErrorMsg>}
    </div>
  );
}

// Safety-gate denylist editor
function DenylistEditor({
  items,
  onChange,
  disabled,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  disabled: boolean;
}) {
  const [newItem, setNewItem] = useState("");

  function add() {
    const val = newItem.trim();
    if (!val || items.includes(val)) return;
    onChange([...items, val]);
    setNewItem("");
  }

  function remove(i: number) {
    onChange(items.filter((_, idx) => idx !== i));
  }

  return (
    <div>
      <div
        style={{
          border: `1px solid ${BRAND.border}`,
          borderRadius: 8,
          overflow: "hidden",
          marginBottom: 8,
          minHeight: 44,
        }}
      >
        {items.length === 0 ? (
          <div style={{ padding: "10px 14px", fontSize: 13, color: BRAND.sub }}>
            No blocked terms configured.
          </div>
        ) : (
          items.map((item, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 14px",
                borderBottom: i < items.length - 1 ? `1px solid ${BRAND.border}` : "none",
                background: "#fff",
              }}
            >
              <span
                style={{
                  flex: 1,
                  fontSize: 13,
                  fontFamily: "monospace",
                  color: BRAND.ink,
                }}
              >
                {item}
              </span>
              {!disabled && (
                <button
                  onClick={() => remove(i)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: BRAND.red,
                    fontSize: 16,
                    lineHeight: 1,
                    padding: "0 4px",
                  }}
                  title="Remove"
                >
                  &times;
                </button>
              )}
            </div>
          ))
        )}
      </div>
      {!disabled && (
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Add term…"
            style={{
              ...inputStyle,
              padding: "7px 10px",
              fontSize: 13,
              flex: 1,
            }}
          />
          <Button
            variant="ghost"
            style={{ fontSize: 13, padding: "7px 14px" }}
            onClick={add}
            disabled={!newItem.trim()}
          >
            Add
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface MarketingConfigProps {
  role: Role;
}

const FONT_HEADING_OPTIONS = [
  "Montserrat",
  "Roboto",
  "Open Sans",
  "Lato",
  "Poppins",
  "Inter",
  "Oswald",
  "Raleway",
];

const FONT_BODY_OPTIONS = [
  "Open Sans",
  "Roboto",
  "Lato",
  "Inter",
  "Source Sans Pro",
  "Nunito",
  "Merriweather",
];

const CAPTION_PROMPT_VERSIONS = ["v3", "v4", "v5"] as const;
const MUSIC_CATALOGS = ["pixabay", "ytaudio", "fma"] as const;
const SOCIAL_PLATFORMS = ["youtube", "facebook", "instagram", "tiktok"] as const;

export function MarketingConfig({ role }: MarketingConfigProps) {
  const manage = canManage(role);

  const [settings, setSettings] = useState<MarketingSettings | null>(null);
  const [draft, setDraft] = useState<MarketingSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [replyCfg, setReplyCfg] = useState<ReplyConfig | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connections, setConnections] = useState<Record<string, Connection>>({});
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/comments/reply-config")
      .then((r) => (r.ok ? r.json() : null))
      .then(setReplyCfg)
      .catch(() => undefined);
    listConnections()
      .then((rows) => setConnections(Object.fromEntries(rows.map((r) => [r.integration, r]))))
      .catch(() => undefined);
  }, []);

  async function handleConnectYouTube() {
    if (!replyCfg?.connect_path) return;
    setConnectError(null);
    try {
      const r = await apiFetch(replyCfg.connect_path);
      if (!r.ok) throw new Error(await errText(r));
      const d = await r.json();
      if (d.auth_url) window.location.href = d.auth_url as string;
      else setConnectError("Could not start the YouTube connect flow.");
    } catch (e: unknown) {
      setConnectError(e instanceof Error ? e.message : "Could not start the YouTube connect flow.");
    }
  }

  async function handleConnectSocial(platform: string) {
    setConnectingPlatform(platform);
    setConnectError(null);
    try {
      window.location.href = await startOAuth(platform);
    } catch (e: unknown) {
      setConnectError(e instanceof Error ? e.message : `Could not start the ${platform} connect flow.`);
      setConnectingPlatform(null);
    }
  }

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    getMarketingSettings()
      .then((s: MarketingSettings) => {
        setSettings(s);
        setDraft(JSON.parse(JSON.stringify(s)));
        setIsDirty(false);
        setSaveSuccess(false);
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function update<K extends keyof MarketingSettings>(key: K, value: MarketingSettings[K]) {
    setDraft((prev: MarketingSettings | null) => {
      if (!prev) return prev;
      return { ...prev, [key]: value };
    });
    setIsDirty(true);
    setSaveSuccess(false);
  }

  function updateBrand<K extends keyof BrandKit>(key: K, value: BrandKit[K]) {
    setDraft((prev: MarketingSettings | null) => {
      if (!prev) return prev;
      return { ...prev, brand: { ...prev.brand, [key]: value } };
    });
    setIsDirty(true);
    setSaveSuccess(false);
  }

  async function handleUpload(assetKey: keyof BrandKit, file: File): Promise<string> {
    const ext = file.name.split(".").pop() ?? "bin";
    const { url, gcs_path } = await getBrandUploadUrl(assetKey, ext);
    await fetch(url, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    });
    return gcs_path;
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const saved = await putMarketingSettings(draft);
      setSettings(saved);
      setDraft(JSON.parse(JSON.stringify(saved)));
      setIsDirty(false);
      setSaveSuccess(true);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleDiscard() {
    if (!settings) return;
    setDraft(JSON.parse(JSON.stringify(settings)));
    setIsDirty(false);
    setSaveSuccess(false);
    setSaveError(null);
  }

  if (loading) {
    return (
      <Card style={{ marginTop: 8 }}>
        <Loading label="Loading marketing settings…" />
      </Card>
    );
  }

  if (loadError) {
    return (
      <Card style={{ marginTop: 8 }}>
        <ErrorMsg>Failed to load: {loadError}</ErrorMsg>
        <Button variant="ghost" style={{ fontSize: 13, marginTop: 8 }} onClick={load}>
          Retry
        </Button>
      </Card>
    );
  }

  if (!draft) return null;

  const brand = draft.brand ?? {};

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 4,
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText }}>
            Marketing Config
          </span>
          {isDirty && <Badge tone="amber">Unsaved changes</Badge>}
          {!manage && <Badge tone="gray">Read-only</Badge>}
        </div>
        {manage && (
          <div style={{ display: "flex", gap: 8 }}>
            {isDirty && (
              <Button
                variant="ghost"
                style={{ fontSize: 13 }}
                onClick={handleDiscard}
                disabled={saving}
              >
                Discard
              </Button>
            )}
            <Button
              style={{ fontSize: 13 }}
              onClick={handleSave}
              disabled={saving || !isDirty}
            >
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        )}
      </div>

      {saveError && <ErrorMsg>Save error: {saveError}</ErrorMsg>}
      {saveSuccess && (
        <div
          style={{
            fontSize: 13,
            color: "#1a7f4b",
            background: "#e6f9f0",
            padding: "8px 12px",
            borderRadius: 6,
            marginBottom: 12,
          }}
        >
          Settings saved.
        </div>
      )}

      {/* Brand Kit */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Brand Kit
        </div>
        <HelpText>
          Assets are stored in GCS under tenants/&#123;id&#125;/brand/. Upload files directly — they are
          sent to GCS via a pre-signed URL and never routed through the API server.
        </HelpText>

        <SectionLabel>Logo</SectionLabel>
        <GcsUriField
          label="Logo (PNG/SVG)"
          value={brand.logo_gcs_uri ?? ""}
          onChange={(v) => updateBrand("logo_gcs_uri", v)}
          onUpload={(f) => handleUpload("logo_gcs_uri", f)}
          disabled={!manage}
          accept=".png,.svg,.jpg,.jpeg,.webp"
          helpText="Displayed in the Knowledge Base chat widget and video title cards."
        />

        {brand.logo_gcs_uri && (
          <div style={{ marginBottom: 12 }}>
            <div
              style={{
                display: "inline-block",
                border: `1px solid ${BRAND.border}`,
                borderRadius: 8,
                padding: 8,
                background: BRAND.bg,
              }}
            >
              <span style={{ fontSize: 11, color: BRAND.sub, fontFamily: "monospace" }}>
                {brand.logo_gcs_uri}
              </span>
            </div>
          </div>
        )}

        <SectionLabel>Colors</SectionLabel>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 4 }}>
          <ColorField
            label="Primary color"
            value={brand.primary_color ?? "#1a3c5e"}
            onChange={(v) => updateBrand("primary_color", v)}
            disabled={!manage}
          />
          <ColorField
            label="Accent color"
            value={brand.accent_color ?? "#f4a226"}
            onChange={(v) => updateBrand("accent_color", v)}
            disabled={!manage}
          />
        </div>

        <SectionLabel>Typography</SectionLabel>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <FieldLabel>Heading font</FieldLabel>
            <select
              value={brand.font_heading ?? "Montserrat"}
              onChange={(e) => updateBrand("font_heading", e.target.value)}
              disabled={!manage}
              style={{
                ...inputStyle,
                padding: "7px 10px",
                fontSize: 13,
                width: "100%",
                background: !manage ? BRAND.bg : "#fff",
              }}
            >
              {FONT_HEADING_OPTIONS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel>Body font</FieldLabel>
            <select
              value={brand.font_body ?? "Open Sans"}
              onChange={(e) => updateBrand("font_body", e.target.value)}
              disabled={!manage}
              style={{
                ...inputStyle,
                padding: "7px 10px",
                fontSize: 13,
                width: "100%",
                background: !manage ? BRAND.bg : "#fff",
              }}
            >
              {FONT_BODY_OPTIONS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        </div>

        <SectionLabel>Video bookends</SectionLabel>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <GcsUriField
            label="Intro clip (MP4)"
            value={brand.intro_gcs_uri ?? ""}
            onChange={(v) => updateBrand("intro_gcs_uri", v)}
            onUpload={(f) => handleUpload("intro_gcs_uri", f)}
            disabled={!manage}
            accept="video/*"
            helpText="Prepended to every rendered clip. Falls back to platform default."
          />
          <GcsUriField
            label="Outro clip (MP4)"
            value={brand.outro_gcs_uri ?? ""}
            onChange={(v) => updateBrand("outro_gcs_uri", v)}
            onUpload={(f) => handleUpload("outro_gcs_uri", f)}
            disabled={!manage}
            accept="video/*"
            helpText="Appended to every rendered clip. Falls back to platform default."
          />
        </div>

        <SectionLabel>Voice sample</SectionLabel>
        <GcsUriField
          label="Voice sample (WAV/MP3)"
          value={brand.voice_sample_gcs_uri ?? ""}
          onChange={(v) => updateBrand("voice_sample_gcs_uri", v)}
          onUpload={(f) => handleUpload("voice_sample_gcs_uri", f)}
          disabled={!manage}
          accept="audio/*"
          helpText="Used by the avatar TTS engine to clone the host voice."
        />
      </Card>

      {/* Caption prompt */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Caption Prompt
        </div>
        <HelpText>Controls the AI caption generation engine version for all distributed clips.</HelpText>

        <SectionLabel>Prompt version</SectionLabel>
        <div style={{ display: "flex", gap: 6 }}>
          {CAPTION_PROMPT_VERSIONS.map((v) => {
            const active = (draft.caption_prompt_version ?? "v5") === v;
            return (
              <button
                key={v}
                onClick={() => manage && update("caption_prompt_version", v)}
                disabled={!manage}
                style={{
                  padding: "7px 18px",
                  fontSize: 13,
                  fontWeight: 600,
                  border: `1px solid ${active ? BRAND.navy : BRAND.border}`,
                  borderRadius: 6,
                  cursor: manage ? "pointer" : "default",
                  background: active ? BRAND.navy : "#fff",
                  color: active ? "#fff" : BRAND.sub,
                  fontFamily: FONT,
                  transition: "background 0.1s, color 0.1s",
                }}
              >
                {v}
              </button>
            );
          })}
        </div>
        <HelpText style={{ marginTop: 6 }}>
          v5 is the current recommended version with richer hashtag context and engagement hooks.
        </HelpText>
      </Card>

      {/* Publish cadence */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Publish Cadence
        </div>
        <HelpText>
          Controls the scheduler for how often content is published and the seed percentage for the
          backlog selection.
        </HelpText>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 16 }}>
          <div>
            <FieldLabel>Cadence (days between posts)</FieldLabel>
            <input
              type="number"
              min={1}
              max={90}
              value={draft.publish_cadence_days ?? 7}
              onChange={(e) =>
                update("publish_cadence_days", Math.max(1, parseInt(e.target.value) || 1))
              }
              disabled={!manage}
              style={{
                ...inputStyle,
                padding: "7px 10px",
                fontSize: 13,
                width: "100%",
                background: !manage ? BRAND.bg : "#fff",
              }}
            />
            <HelpText>Days between scheduled posts (1–90).</HelpText>
          </div>

          <div>
            <FieldLabel>Seed percentage (%)</FieldLabel>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={Math.round((draft.seed_pct ?? 0.2) * 100)}
              onChange={(e) =>
                update("seed_pct", Math.min(100, Math.max(0, parseInt(e.target.value) || 0)) / 100)
              }
              disabled={!manage}
              style={{
                ...inputStyle,
                padding: "7px 10px",
                fontSize: 13,
                width: "100%",
                background: !manage ? BRAND.bg : "#fff",
              }}
            />
            <HelpText>
              Fraction of the backlog that is "seed" content (earliest/evergreen videos, 0–100%).
            </HelpText>
          </div>

          <div>
            <FieldLabel>Background music catalog</FieldLabel>
            <select
              value={draft.royalty_free_music_catalog ?? "pixabay"}
              onChange={(e) =>
                update("royalty_free_music_catalog", e.target.value as typeof MUSIC_CATALOGS[number])
              }
              disabled={!manage}
              style={{
                ...inputStyle,
                padding: "7px 10px",
                fontSize: 13,
                width: "100%",
                background: !manage ? BRAND.bg : "#fff",
              }}
            >
              {MUSIC_CATALOGS.map((c) => (
                <option key={c} value={c}>
                  {c === "pixabay"
                    ? "Pixabay (default, free)"
                    : c === "ytaudio"
                    ? "YouTube Audio Library"
                    : "Free Music Archive"}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {/* Social accounts */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Social Account Status
        </div>
        <HelpText>
          OAuth connection status for each distribution platform. A platform becomes connectable
          once its app credentials are in place; Instagram/TikTok/Facebook live posting also needs
          platform app-review approval.
        </HelpText>
        <div style={{ marginTop: 14 }}>
          {SOCIAL_PLATFORMS.map((p) =>
            p === "youtube" ? (
              <YouTubeConnectRow key={p} replyCfg={replyCfg} onConnect={handleConnectYouTube} error={connectError} />
            ) : (
              <SocialAccountRow
                key={p}
                platform={p}
                conn={connections[p]}
                onConnect={handleConnectSocial}
                connecting={connectingPlatform === p}
                manage={manage}
              />
            )
          )}
        </div>
        {connectError && <div style={{ marginTop: 8 }}><ErrorMsg>{connectError}</ErrorMsg></div>}
      </Card>

      {/* Safety-gate denylist */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Safety-Gate Denylist
        </div>
        <HelpText>
          Terms blocked from appearing in AI-generated captions, titles, and hashtags. Case-insensitive
          exact-match. Matches cause the caption job to retry with an explicit avoidance prompt.
        </HelpText>
        <div style={{ marginTop: 14 }}>
          <DenylistEditor
            items={draft.safety_denylist ?? []}
            onChange={(items) => update("safety_denylist", items)}
            disabled={!manage}
          />
        </div>
      </Card>

      {/* Save footer */}
      {manage && isDirty && (
        <div
          style={{
            marginTop: 20,
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
          }}
        >
          <Button variant="ghost" onClick={handleDiscard} disabled={saving}>
            Discard
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      )}
    </div>
  );
}
