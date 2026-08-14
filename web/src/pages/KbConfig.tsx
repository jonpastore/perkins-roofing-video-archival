import { useEffect, useState, useCallback } from "react";
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
import { getKbSettings, putKbSettings, type KbSettings } from "../api";

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

function HelpText({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <p style={{ margin: "3px 0 0", fontSize: 11, color: BRAND.sub, lineHeight: 1.4, ...style }}>
      {children}
    </p>
  );
}

// Channel source list editor
function ChannelSourcesEditor({
  channels,
  onChange,
  disabled,
}: {
  channels: string[];
  onChange: (channels: string[]) => void;
  disabled: boolean;
}) {
  const [newChannel, setNewChannel] = useState("");

  function add() {
    const val = newChannel.trim();
    if (!val || channels.includes(val)) return;
    onChange([...channels, val]);
    setNewChannel("");
  }

  function remove(i: number) {
    onChange(channels.filter((_, idx) => idx !== i));
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
        {channels.length === 0 ? (
          <div style={{ padding: "10px 14px", fontSize: 13, color: BRAND.sub }}>
            No channel sources configured.
          </div>
        ) : (
          channels.map((ch, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 14px",
                borderBottom: i < channels.length - 1 ? `1px solid ${BRAND.border}` : "none",
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
                {ch}
              </span>
              <a
                href={`https://www.youtube.com/channel/${ch}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 11, color: BRAND.navyText, textDecoration: "none" }}
              >
                View
              </a>
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
            value={newChannel}
            onChange={(e) => setNewChannel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="UCxxxxxxxxxxxxxxxxxxxxxxxx"
            style={{
              ...inputStyle,
              padding: "7px 10px",
              fontSize: 13,
              fontFamily: "monospace",
              flex: 1,
            }}
          />
          <Button
            variant="ghost"
            style={{ fontSize: 13, padding: "7px 14px" }}
            onClick={add}
            disabled={!newChannel.trim()}
          >
            Add
          </Button>
        </div>
      )}
      <HelpText>
        YouTube channel IDs starting with "UC". The ingest job enumerates videos from these channels
        on each scheduled run.
      </HelpText>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface KbConfigProps {
  role: Role;
}

export function KbConfig({ role }: KbConfigProps) {
  const manage = canManage(role);

  const [settings, setSettings] = useState<KbSettings | null>(null);
  const [draft, setDraft] = useState<KbSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    getKbSettings()
      .then((s: KbSettings) => {
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

  function update<K extends keyof KbSettings>(key: K, value: KbSettings[K]) {
    setDraft((prev: KbSettings | null) => {
      if (!prev) return prev;
      return { ...prev, [key]: value };
    });
    setIsDirty(true);
    setSaveSuccess(false);
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const saved = await putKbSettings(draft);
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
        <Loading label="Loading KB settings…" />
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
            Knowledge Base Config
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

      {/* Ingest controls */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText, marginBottom: 2 }}>
          Ingest Controls
        </div>
        <HelpText>
          Controls whether the nightly ingest job fetches new videos from the configured channel
          sources and adds them to the video archive.
        </HelpText>

        <SectionLabel>Ingest enabled</SectionLabel>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "12px 16px",
            border: `1px solid ${BRAND.border}`,
            borderRadius: 8,
            background: "#fff",
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>
              {draft.ingest_enabled ? "Ingest is active" : "Ingest is paused"}
            </div>
            <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
              {draft.ingest_enabled
                ? "New videos are fetched and embedded on the nightly schedule."
                : "No new videos will be fetched until re-enabled."}
            </div>
          </div>
          <button
            onClick={() => manage && update("ingest_enabled", !draft.ingest_enabled)}
            disabled={!manage}
            style={{
              width: 44,
              height: 24,
              borderRadius: 12,
              border: "none",
              cursor: manage ? "pointer" : "not-allowed",
              background: draft.ingest_enabled ? BRAND.navy : BRAND.border,
              position: "relative",
              transition: "background 0.15s",
              flexShrink: 0,
            }}
          >
            <span
              style={{
                position: "absolute",
                top: 3,
                left: draft.ingest_enabled ? 23 : 3,
                width: 18,
                height: 18,
                borderRadius: "50%",
                background: "#fff",
                transition: "left 0.15s",
                boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
              }}
            />
          </button>
        </div>

        <SectionLabel>Channel sources</SectionLabel>
        <ChannelSourcesEditor
          channels={draft.channel_sources ?? []}
          onChange={(ch) => update("channel_sources", ch)}
          disabled={!manage}
        />
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
