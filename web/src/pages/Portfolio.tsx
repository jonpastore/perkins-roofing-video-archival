import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, Loading, ErrorMsg } from "../ui";
import { errText } from "../lib/errors";

interface PublishResult {
  status: string;
  post_id?: number;
}

interface PortfolioItem {
  slug: string;
  name: string;
  city: string | null;
  property_type: string;
  roof_type: string | null;
  companycam_url: string | null;
  youtube_url: string | null;
  permission_property: boolean;
  permission_photos: boolean;
  permission_video: boolean;
  curated_photos?: number;
  curated_videos?: number;
  missing_permissions: string[];
  wp_post_id: number | null;
  wp_status: string | null;
  wp_admin_url: string | null;
  publish_result?: PublishResult;
}

interface MediaPhoto {
  companycam_photo_id: string;
  url: string | null;
  captured_at: string | null;
}

interface MediaVideo {
  companycam_video_id: string;
  url: string | null;
  thumbnail_url: string | null;
  captured_at: string | null;
}

interface Selection {
  kind: "photo" | "video";
  id: string;
  alt?: string;
}

interface ScoreCheck {
  key: string;
  label: string;
  pass: boolean;
  points?: number;
  detail?: string;
  tier?: string;
}

interface ProjectScore {
  score: number;
  max: number;
  pct: number;
  checks: ScoreCheck[];
  aio: ScoreCheck[];
  blocking: string[];
}

interface CurationView {
  slug: string;
  name: string;
  companycam_project_id: string | null;
  companycam_url: string | null;
  youtube_url: string | null;
  permission_property: boolean;
  permission_photos: boolean;
  permission_video: boolean;
  available: { photos: MediaPhoto[]; videos: MediaVideo[] };
  selections: Selection[];
  score: ProjectScore;
}

function gateBadge(item: PortfolioItem) {
  if (item.missing_permissions.length === 0) return <Badge tone="green">permissions confirmed</Badge>;
  return <Badge tone="amber">{item.missing_permissions.length} permission(s) missing</Badge>;
}

function wpBadge(item: PortfolioItem) {
  if (!item.wp_post_id) return <Badge tone="gray">not on WordPress</Badge>;
  if (item.wp_status === "publish") return <Badge tone="green">published</Badge>;
  return <Badge tone="blue">{item.wp_status ?? "draft"}</Badge>;
}

function ScorePanel({ score }: { score: ProjectScore }) {
  const tone = score.pct >= 80 ? "green" : score.pct >= 50 ? "amber" : "red";
  return (
    <div style={{ minWidth: 280 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <strong style={{ color: BRAND.navyText }}>SEO / AIO</strong>
        <Badge tone={tone}>
          {score.score}/{score.max} ({score.pct}%)
        </Badge>
      </div>
      {score.blocking.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          {score.blocking.map((b) => (
            <div key={b} style={{ fontSize: 12, color: BRAND.red }}>
              blocked — {b}
            </div>
          ))}
        </div>
      )}
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12 }}>
        {score.checks.map((c) => (
          <li key={c.key} style={{ padding: "2px 0", color: c.pass ? BRAND.sub : BRAND.navyText }}>
            {c.pass ? "✓" : "✗"} {c.label}
            {c.detail ? <span style={{ color: BRAND.sub }}> — {c.detail}</span> : null}
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8, fontSize: 11, color: BRAND.sub }}>
        Advisory (AI optimization) — never blocks publish:
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12 }}>
        {score.aio.map((c) => (
          <li key={c.key} style={{ padding: "1px 0", color: BRAND.sub }}>
            {c.pass ? "✓" : "○"} {c.label}
            {c.detail ? ` — ${c.detail}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CurationPanel({ slug, onSaved }: { slug: string; onSaved: () => void }) {
  const [view, setView] = useState<CurationView | null>(null);
  const [sel, setSel] = useState<Selection[]>([]);
  const [perms, setPerms] = useState({ property: false, photos: false, video: false });
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function loadView() {
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${slug}/media`);
      if (!r.ok) throw new Error(await errText(r));
      const v: CurationView = await r.json();
      setView(v);
      setSel(v.selections ?? []);
      setPerms({
        property: v.permission_property,
        photos: v.permission_photos,
        video: v.permission_video,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void loadView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  // Permissions gate what the API will even return, so a change has to re-fetch the media
  // list — otherwise the editor sees thumbnails the server would reject on save.
  async function savePerms(next: { property: boolean; photos: boolean; video: boolean }) {
    setPerms(next);
    setSaving(true);
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${slug}/curation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          permission_property: next.property,
          permission_photos: next.photos,
          permission_video: next.video,
          // Drop selections the new permissions would invalidate rather than 422 the editor.
          selections: sel.filter((s) =>
            s.kind === "photo" ? next.photos : next.video,
          ),
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const v: CurationView = await r.json();
      setView(v);
      setSel(v.selections ?? []);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function toggle(kind: "photo" | "video", id: string) {
    setSel((prev) =>
      prev.some((s) => s.kind === kind && s.id === id)
        ? prev.filter((s) => !(s.kind === kind && s.id === id))
        : [...prev, { kind, id, alt: "" }],
    );
  }

  function setAlt(id: string, alt: string) {
    setSel((prev) => prev.map((s) => (s.kind === "photo" && s.id === id ? { ...s, alt } : s)));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${slug}/curation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          permission_property: perms.property,
          permission_photos: perms.photos,
          permission_video: perms.video,
          selections: sel,
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const v: CurationView = await r.json();
      setView(v);
      setSel(v.selections ?? []);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (err && !view) return <ErrorMsg>{err}</ErrorMsg>;
  if (!view) return <Loading label="Loading media…" />;

  const isSelected = (kind: "photo" | "video", id: string) =>
    sel.some((s) => s.kind === kind && s.id === id);
  const altOf = (id: string) => sel.find((s) => s.kind === "photo" && s.id === id)?.alt ?? "";
  const noMedia = view.available.photos.length === 0 && view.available.videos.length === 0;

  return (
    <div style={{ display: "flex", gap: 24, padding: "12px 14px", background: BRAND.bg }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
          {([
            ["property", "Name the property"],
            ["photos", "Use photos"],
            ["video", "Use video"],
          ] as const).map(([key, label]) => (
            <label key={key} style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}>
              <input
                type="checkbox"
                checked={perms[key]}
                disabled={saving}
                onChange={(e) => void savePerms({ ...perms, [key]: e.target.checked })}
              />
              Client permission: {label}
            </label>
          ))}
        </div>

        {noMedia && (
          <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 8 }}>
            {!view.companycam_project_id
              ? "No CompanyCam project linked for this candidate."
              : !perms.photos && !perms.video
                ? "Media is hidden until a client permission is recorded above."
                : "No mirrored media yet — companycam-sync runs 06:00 ET."}
          </div>
        )}

        {view.available.photos.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {view.available.photos.map((p) => {
              const on = isSelected("photo", p.companycam_photo_id);
              return (
                <div key={p.companycam_photo_id} style={{ width: 150 }}>
                  <button
                    type="button"
                    onClick={() => toggle("photo", p.companycam_photo_id)}
                    style={{
                      padding: 0,
                      border: `2px solid ${on ? BRAND.red : BRAND.border}`,
                      borderRadius: 4,
                      cursor: "pointer",
                      background: "none",
                      display: "block",
                      width: "100%",
                    }}
                  >
                    <img
                      src={p.url ?? ""}
                      alt=""
                      style={{ width: "100%", height: 100, objectFit: "cover", display: "block" }}
                    />
                  </button>
                  {on && (
                    <input
                      value={altOf(p.companycam_photo_id)}
                      onChange={(e) => setAlt(p.companycam_photo_id, e.target.value)}
                      placeholder="alt text (must be unique)"
                      style={{ width: "100%", fontSize: 11, marginTop: 3, padding: "2px 4px" }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {view.available.videos.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
            {view.available.videos.map((v) => {
              const on = isSelected("video", v.companycam_video_id);
              return (
                <button
                  key={v.companycam_video_id}
                  type="button"
                  onClick={() => toggle("video", v.companycam_video_id)}
                  style={{
                    padding: 0,
                    border: `2px solid ${on ? BRAND.red : BRAND.border}`,
                    borderRadius: 4,
                    cursor: "pointer",
                    background: "none",
                    width: 150,
                    position: "relative",
                  }}
                >
                  <img
                    src={v.thumbnail_url ?? ""}
                    alt=""
                    style={{ width: "100%", height: 100, objectFit: "cover", display: "block" }}
                  />
                  <span style={{ position: "absolute", bottom: 4, right: 6, color: "#fff", fontSize: 11 }}>
                    ▶ video
                  </span>
                </button>
              );
            })}
          </div>
        )}

        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10 }}>
          <Button onClick={() => void save()} disabled={saving}>
            {saving ? "Saving…" : "Save selection"}
          </Button>
          <span style={{ fontSize: 12, color: BRAND.sub }}>
            {sel.filter((s) => s.kind === "photo").length} photos,{" "}
            {sel.filter((s) => s.kind === "video").length} videos selected
          </span>
        </div>
        {err && <ErrorMsg>{err}</ErrorMsg>}
      </div>

      <ScorePanel score={view.score} />
    </div>
  );
}

export function Portfolio() {
  const [items, setItems] = useState<PortfolioItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [publishingSlug, setPublishingSlug] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [openSlug, setOpenSlug] = useState<string | null>(null);

  async function load() {
    setLoadError(null);
    try {
      const r = await apiFetch("/portfolio");
      if (!r.ok) throw new Error(await errText(r));
      setItems(await r.json());
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handlePublish(item: PortfolioItem) {
    if (!window.confirm(`Publish "${item.name}" as an Avada Portfolio draft on WordPress?`)) return;
    setPublishingSlug(item.slug);
    setRowError((prev) => ({ ...prev, [item.slug]: "" }));
    try {
      const r = await apiFetch(`/portfolio/${item.slug}/publish`, { method: "POST" });
      if (!r.ok) throw new Error(await errText(r));
      const updated: PortfolioItem = await r.json();
      setItems((prev) => prev && prev.map((i) => (i.slug === updated.slug ? updated : i)));
    } catch (e) {
      setRowError((prev) => ({ ...prev, [item.slug]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setPublishingSlug(null);
    }
  }

  if (loadError) return <ErrorMsg>{loadError}</ErrorMsg>;
  if (!items) return <Loading label="Loading portfolio projects…" />;

  return (
    <div>
      <PageTitle>Portfolio</PageTitle>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: BRAND.bg, textAlign: "left" }}>
                {["Project", "City", "Property Type", "Roof System", "Media", "Permissions", "WordPress", "", ""].map((h) => (
                  <th key={h} style={{ padding: "10px 14px", fontSize: 11, textTransform: "uppercase", color: BRAND.sub, letterSpacing: 0.3 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.flatMap((item) => [
                <tr key={item.slug} style={{ borderTop: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 14px", fontWeight: 600, color: BRAND.navyText }}>{item.name}</td>
                  <td style={{ padding: "10px 14px" }}>{item.city || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{item.property_type}</td>
                  <td style={{ padding: "10px 14px" }}>{item.roof_type || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    {(item.curated_photos ?? 0) + (item.curated_videos ?? 0) > 0 ? (
                      <Badge tone="green">
                        {item.curated_photos ?? 0}p / {item.curated_videos ?? 0}v
                      </Badge>
                    ) : (
                      <Badge tone="gray">none curated</Badge>
                    )}
                  </td>
                  <td style={{ padding: "10px 14px" }}>{gateBadge(item)}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {wpBadge(item)}
                      {item.wp_admin_url && (
                        <a href={item.wp_admin_url} target="_blank" rel="noopener noreferrer" style={{ color: BRAND.red, fontSize: 12 }}>
                          Edit in WordPress
                        </a>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <Button
                      variant="ghost"
                      onClick={() => setOpenSlug(openSlug === item.slug ? null : item.slug)}
                    >
                      {openSlug === item.slug ? "Close" : "Curate"}
                    </Button>
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <Button
                      variant="ghost"
                      disabled={publishingSlug === item.slug || item.missing_permissions.length > 0}
                      title={item.missing_permissions.length > 0 ? `Blocked: ${item.missing_permissions.join(", ")}` : undefined}
                      onClick={() => void handlePublish(item)}
                    >
                      {publishingSlug === item.slug ? "Publishing…" : "Publish"}
                    </Button>
                    {rowError[item.slug] && <ErrorMsg>{rowError[item.slug]}</ErrorMsg>}
                  </td>
                </tr>,
                openSlug === item.slug ? (
                  <tr key={`${item.slug}-curate`}>
                    <td colSpan={9} style={{ padding: 0, borderTop: `1px solid ${BRAND.border}` }}>
                      <CurationPanel slug={item.slug} onSaved={() => void load()} />
                    </td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
