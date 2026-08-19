import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Badge, Loading, ErrorMsg } from "../ui";
import { errText } from "../lib/errors";


/**
 * Portfolio admin. Three tabs per project, because the three jobs are genuinely different:
 *   Project   — what the job WAS (full CRUD on the record)
 *   Media     — which photos/videos publish, in what order, with what alt text
 *   SEO / AIO — the score, the publish gate, and the adversarial review
 *
 * The gate is the load-bearing part: publish REFUSES on a blocker (privacy or client
 * permission) or a major (a page not worth having), so the button is disabled with the reasons
 * listed rather than failing after a click.
 */

interface PublishResult {
  status: string;
  post_id?: number;
  jsonld_stored?: boolean;
}

interface GateCriterion {
  key: string;
  label: string;
  ok: boolean;
  severity: "blocker" | "major" | "minor";
  detail?: string;
  evidence?: string[];
}

interface Gate {
  publishable: boolean;
  blockers: GateCriterion[];
  failing: GateCriterion[];
  criteria: GateCriterion[];
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
  gate?: Gate;
  // Persisted verdict from the last gate run on a write (migration 0051). null = never gated,
  // [] = gated and clean — the list must not render those the same way.
  gate_failures?: GateCriterion[] | null;
  gate_checked_at?: string | null;
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
  preview_html: string;
  scope_lines: string[];
  gate: Gate;
}

interface ProjectForm {
  name: string;
  city: string;
  section: string;
  companycam_url: string;
  youtube_url: string;
  date_start: string;
  date_end: string;
  notes: string;
  search_terms: string;
}

interface Finding {
  severity: string;
  issue: string;
  fix?: string;
  lens?: string;
}

const EMPTY_FORM: ProjectForm = {
  name: "", city: "", section: "commercial", companycam_url: "", youtube_url: "",
  date_start: "", date_end: "", notes: "", search_terms: "",
};

const TABS = ["Project", "Media", "SEO / AIO"] as const;
type Tab = (typeof TABS)[number];

const inputStyle: React.CSSProperties = {
  width: "100%", fontSize: 12, padding: "4px 6px", border: `1px solid ${BRAND.border}`,
  borderRadius: 3,
};
const labelStyle: React.CSSProperties = {
  fontSize: 11, color: BRAND.sub, display: "block", marginBottom: 2,
};

function sevTone(sev: string): "red" | "amber" | "gray" {
  return sev === "blocker" ? "red" : sev === "major" ? "amber" : "gray";
}

function gateBadge(item: PortfolioItem) {
  if (item.gate) {
    if (item.gate.publishable) return <Badge tone="green">ready to publish</Badge>;
    const blocked = item.gate.blockers.length;
    return (
      <Badge tone={blocked > 0 ? "red" : "amber"}>
        {blocked > 0 ? `${blocked} blocker(s)` : `${item.gate.failing.length} to fix`}
      </Badge>
    );
  }
  // Fall back to the LAST RECORDED verdict, so the list answers "why is this stuck?" without
  // re-running the gate for all 13 projects on every render.
  if (item.gate_failures && item.gate_failures.length > 0) {
    const blockers = item.gate_failures.filter((f) => f.severity === "blocker").length;
    return (
      <Badge tone={blockers > 0 ? "red" : "amber"}>
        {blockers > 0 ? `${blockers} blocker(s)` : `${item.gate_failures.length} to fix`}
      </Badge>
    );
  }
  if (item.gate_failures && item.gate_failures.length === 0) {
    return <Badge tone="green">gate passed</Badge>;
  }
  if (item.missing_permissions.length === 0) return <Badge tone="green">permissions confirmed</Badge>;
  return <Badge tone="amber">{item.missing_permissions.length} permission(s) missing</Badge>;
}

function gateReasonLine(item: PortfolioItem) {
  const failures = item.gate_failures;
  if (!failures || failures.length === 0) return null;
  return (
    <div style={{ fontSize: "0.8rem", opacity: 0.75, marginTop: "0.2rem" }}>
      {failures.slice(0, 3).map((f) => f.label + (f.detail ? ` (${f.detail})` : "")).join(" · ")}
      {failures.length > 3 ? ` · +${failures.length - 3} more` : ""}
    </div>
  );
}

function wpBadge(item: PortfolioItem) {
  if (!item.wp_post_id) return <Badge tone="gray">not on WordPress</Badge>;
  if (item.wp_status === "publish") return <Badge tone="green">published</Badge>;
  return <Badge tone="blue">{item.wp_status ?? "draft"}</Badge>;
}

/** The publish gate: blockers first, with the evidence that produced them. */
function GatePanel({ gate }: { gate: Gate }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <strong style={{ color: BRAND.navyText }}>Publish gate</strong>
        <Badge tone={gate.publishable ? "green" : "red"}>
          {gate.publishable ? "may publish" : "refused"}
        </Badge>
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12 }}>
        {gate.criteria.map((c) => (
          <li key={c.key} style={{ padding: "2px 0" }}>
            <span style={{ color: c.ok ? BRAND.sub : c.severity === "blocker" ? BRAND.red : BRAND.navyText }}>
              {c.ok ? "✓" : c.severity === "minor" ? "○" : "✗"} {c.label}
              {c.detail ? ` — ${c.detail}` : ""}
            </span>
            {!c.ok && c.evidence && c.evidence.length > 0 && (
              <ul style={{ margin: "2px 0 4px 16px", padding: 0, color: BRAND.red, fontSize: 11 }}>
                {c.evidence.map((e) => <li key={e}>{e}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScorePanel({ score }: { score: ProjectScore }) {
  const tone = score.pct >= 80 ? "green" : score.pct >= 50 ? "amber" : "red";
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <strong style={{ color: BRAND.navyText }}>SEO / AIO score</strong>
        <Badge tone={tone}>{score.score}/{score.max} ({score.pct}%)</Badge>
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12 }}>
        {score.checks.map((c) => (
          <li key={c.key} style={{ padding: "1px 0", color: c.pass ? BRAND.sub : BRAND.navyText }}>
            {c.pass ? "✓" : "✗"} {c.label}{c.detail ? ` — ${c.detail}` : ""}
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 6, fontSize: 11, color: BRAND.sub }}>
        Advisory (AI optimization) — never blocks:
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 12, color: BRAND.sub }}>
        {score.aio.map((c) => (
          <li key={c.key}>{c.pass ? "✓" : "○"} {c.label}{c.detail ? ` — ${c.detail}` : ""}</li>
        ))}
      </ul>
    </div>
  );
}

function ProjectTab({ item, onSaved }: { item: PortfolioItem; onSaved: () => void }) {
  const [form, setForm] = useState<ProjectForm | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setForm({
      ...EMPTY_FORM,
      name: item.name,
      city: item.city ?? "",
      companycam_url: item.companycam_url ?? "",
      youtube_url: item.youtube_url ?? "",
      section: item.property_type?.toLowerCase() === "residential" ? "residential" : "commercial",
    });
  }, [item]);

  async function save() {
    if (!form) return;
    setBusy(true);
    setErr(null);
    setProblems([]);
    try {
      const r = await apiFetch(`/portfolio/${item.slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          search_terms: form.search_terms.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      if (r.status === 422) {
        const body = await r.json();
        setProblems(body?.detail?.problems ?? ["invalid"]);
        return;
      }
      if (!r.ok) throw new Error(await errText(r));
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!window.confirm(`Archive "${item.name}"? It stays findable and can be restored.`)) return;
    setBusy(true);
    try {
      const r = await apiFetch(`/portfolio/${item.slug}`, { method: "DELETE" });
      if (!r.ok) throw new Error(await errText(r));
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!form) return <Loading label="Loading project…" />;
  const set =
    (k: keyof ProjectForm) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm({ ...form, [k]: e.target.value });

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 10 }}>
      <div>
        <label style={labelStyle}>Project name (never a customer&apos;s name)</label>
        <input style={inputStyle} value={form.name} onChange={set("name")} />
      </div>
      <div>
        <label style={labelStyle}>City or neighbourhood</label>
        <input style={inputStyle} value={form.city} onChange={set("city")} />
      </div>
      <div>
        <label style={labelStyle}>Section</label>
        <select style={inputStyle} value={form.section} onChange={set("section")}>
          <option value="commercial">commercial</option>
          <option value="residential">residential</option>
          <option value="construction">construction</option>
        </select>
      </div>
      <div>
        <label style={labelStyle}>CompanyCam project URL</label>
        <input style={inputStyle} value={form.companycam_url} onChange={set("companycam_url")}
               placeholder="https://app.companycam.com/projects/…" />
      </div>
      <div>
        <label style={labelStyle}>YouTube URL (only if it is THIS property)</label>
        <input style={inputStyle} value={form.youtube_url} onChange={set("youtube_url")} />
      </div>
      <div>
        <label style={labelStyle}>Start (as written)</label>
        <input style={inputStyle} value={form.date_start} onChange={set("date_start")}
               placeholder="20 Feb 2024" />
      </div>
      <div>
        <label style={labelStyle}>End (as written)</label>
        <input style={inputStyle} value={form.date_end} onChange={set("date_end")} />
      </div>
      <div>
        <label style={labelStyle}>Knowify search terms (comma separated)</label>
        <input style={inputStyle} value={form.search_terms} onChange={set("search_terms")} />
      </div>
      <div style={{ gridColumn: "1 / -1" }}>
        <label style={labelStyle}>Notes — no addresses, unit numbers or names</label>
        <textarea style={{ ...inputStyle, minHeight: 54 }} value={form.notes} onChange={set("notes")} />
      </div>
      <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8, alignItems: "center" }}>
        <Button onClick={() => void save()} disabled={busy}>
          {busy ? "Saving…" : "Save project"}
        </Button>
        <Button variant="ghost" onClick={() => void archive()} disabled={busy}>Archive</Button>
      </div>
      {problems.length > 0 && (
        <div style={{ gridColumn: "1 / -1" }}>
          {problems.map((p) => (
            <div key={p} style={{ color: BRAND.red, fontSize: 12 }}>{p}</div>
          ))}
        </div>
      )}
      {err && <div style={{ gridColumn: "1 / -1" }}><ErrorMsg>{err}</ErrorMsg></div>}
    </div>
  );
}

function MediaTab({ view, onChanged }: { view: CurationView; onChanged: (v: CurationView) => void }) {
  const [sel, setSel] = useState<Selection[]>(view.selections ?? []);
  const [perms, setPerms] = useState({
    property: view.permission_property,
    photos: view.permission_photos,
    video: view.permission_video,
  });
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function put(next = sel, p = perms) {
    setSaving(true);
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${view.slug}/curation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          permission_property: p.property,
          permission_photos: p.photos,
          permission_video: p.video,
          selections: next.filter((s) => (s.kind === "photo" ? p.photos : p.video)),
        }),
      });
      if (!r.ok) throw new Error(await errText(r));
      const v: CurationView = await r.json();
      setSel(v.selections ?? []);
      onChanged(v);
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

  function move(from: number, to: number) {
    if (from === to || to < 0 || to >= sel.length) return;
    setSel((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  const isSel = (kind: "photo" | "video", id: string) =>
    sel.some((s) => s.kind === kind && s.id === id);
  const altOf = (id: string) => sel.find((s) => s.kind === "photo" && s.id === id)?.alt ?? "";
  const thumb = (s: Selection) =>
    s.kind === "photo"
      ? view.available.photos.find((p) => p.companycam_photo_id === s.id)?.url
      : view.available.videos.find((v) => v.companycam_video_id === s.id)?.thumbnail_url;
  const noMedia = view.available.photos.length === 0 && view.available.videos.length === 0;

  return (
    <div>
      <div style={{ display: "flex", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
        {([["property", "Name the property"], ["photos", "Use photos"], ["video", "Use video"]] as const)
          .map(([k, text]) => (
            <label key={k} style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}>
              <input
                type="checkbox"
                checked={perms[k]}
                disabled={saving}
                onChange={(e) => {
                  const next = { ...perms, [k]: e.target.checked };
                  setPerms(next);
                  void put(sel, next);
                }}
              />
              Client permission: {text}
            </label>
          ))}
      </div>

      {noMedia && (
        <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 8 }}>
          {!view.companycam_project_id
            ? "No CompanyCam project linked — add its URL on the Project tab."
            : !perms.photos && !perms.video
              ? "Media stays hidden until a client permission is recorded above."
              : "No mirrored media yet — companycam-sync runs 06:00 ET."}
        </div>
      )}

      {view.available.photos.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {view.available.photos.map((p) => {
            const on = isSel("photo", p.companycam_photo_id);
            return (
              <div key={p.companycam_photo_id} style={{ width: 148 }}>
                <button
                  type="button"
                  onClick={() => toggle("photo", p.companycam_photo_id)}
                  style={{
                    padding: 0, border: `2px solid ${on ? BRAND.red : BRAND.border}`,
                    borderRadius: 4, cursor: "pointer", background: "none",
                    display: "block", width: "100%",
                  }}
                >
                  <img src={p.url ?? ""} alt=""
                       style={{ width: "100%", height: 96, objectFit: "cover", display: "block" }} />
                </button>
                {on && (
                  <input
                    value={altOf(p.companycam_photo_id)}
                    onChange={(e) =>
                      setSel((prev) => prev.map((s) =>
                        s.kind === "photo" && s.id === p.companycam_photo_id
                          ? { ...s, alt: e.target.value } : s))}
                    placeholder="alt text — must be unique"
                    style={{ ...inputStyle, fontSize: 11, marginTop: 3 }}
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
            const on = isSel("video", v.companycam_video_id);
            return (
              <button
                key={v.companycam_video_id}
                type="button"
                onClick={() => toggle("video", v.companycam_video_id)}
                style={{
                  padding: 0, border: `2px solid ${on ? BRAND.red : BRAND.border}`,
                  borderRadius: 4, cursor: "pointer", background: "none",
                  width: 148, position: "relative",
                }}
              >
                <img src={v.thumbnail_url ?? ""} alt=""
                     style={{ width: "100%", height: 96, objectFit: "cover", display: "block" }} />
                <span style={{ position: "absolute", bottom: 4, right: 6, color: "#fff", fontSize: 11 }}>
                  ▶ video
                </span>
              </button>
            );
          })}
        </div>
      )}

      {sel.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 4 }}>
            Publish order — drag to reorder. The first image is the one search engines and AI
            treat as representing the page.
          </div>
          <ol
            style={{ display: "flex", flexWrap: "wrap", gap: 6, listStyle: "none", padding: 0, margin: 0 }}
            onDragOver={(e) => e.preventDefault()}
          >
            {sel.map((s, i) => (
              <li
                key={`${s.kind}:${s.id}`}
                draggable
                onDragStart={(e) => e.dataTransfer.setData("text/plain", String(i))}
                onDrop={(e) => {
                  e.preventDefault();
                  move(Number(e.dataTransfer.getData("text/plain")), i);
                }}
                title={s.alt || s.kind}
                style={{
                  width: 74, cursor: "grab", border: `1px solid ${BRAND.border}`,
                  borderRadius: 4, padding: 2, background: "#fff", position: "relative",
                }}
              >
                <img src={thumb(s) ?? ""} alt=""
                     style={{ width: "100%", height: 48, objectFit: "cover", display: "block" }} />
                <span style={{ position: "absolute", top: 2, left: 4, fontSize: 10, color: "#fff",
                               textShadow: "0 0 3px #000" }}>
                  {i + 1}{s.kind === "video" ? " ▶" : ""}
                </span>
                <span style={{ display: "flex", justifyContent: "space-between", padding: "0 2px" }}>
                  <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0}
                          style={{ border: "none", background: "none", cursor: "pointer", fontSize: 11 }}>
                    ←
                  </button>
                  <button type="button" onClick={() => move(i, i + 1)} disabled={i === sel.length - 1}
                          style={{ border: "none", background: "none", cursor: "pointer", fontSize: 11 }}>
                    →
                  </button>
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10 }}>
        <Button onClick={() => void put()} disabled={saving}>
          {saving ? "Saving…" : "Save selection"}
        </Button>
        <span style={{ fontSize: 12, color: BRAND.sub }}>
          {sel.filter((s) => s.kind === "photo").length} photos,{" "}
          {sel.filter((s) => s.kind === "video").length} videos selected
        </span>
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
    </div>
  );
}

function SeoTab({ view, item, onPublished }: {
  view: CurationView;
  item: PortfolioItem;
  onPublished: () => void;
}) {
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [gateErr, setGateErr] = useState<Gate | null>(null);
  const [result, setResult] = useState<PublishResult | null>(item.publish_result ?? null);

  async function review() {
    setReviewing(true);
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${view.slug}/review`, { method: "POST" });
      if (!r.ok) throw new Error(await errText(r));
      const body = await r.json();
      setFindings(body.critique ?? []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setReviewing(false);
    }
  }

  async function publish() {
    if (!window.confirm(`Publish "${view.name}" to WordPress?`)) return;
    setPublishing(true);
    setErr(null);
    setGateErr(null);
    try {
      const r = await apiFetch(`/portfolio/${view.slug}/publish`, { method: "POST" });
      if (r.status === 422) {
        const body = await r.json();
        setGateErr(body?.detail ?? null);
        return;
      }
      if (!r.ok) throw new Error(await errText(r));
      const body = await r.json();
      setResult(body.publish_result ?? null);
      onPublished();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPublishing(false);
    }
  }

  const gate = gateErr ?? view.gate;
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
      <div style={{ minWidth: 300, flex: 1 }}><GatePanel gate={gate} /></div>
      <div style={{ minWidth: 300, flex: 1 }}><ScorePanel score={view.score} /></div>
      <div style={{ minWidth: 280, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <strong style={{ color: BRAND.navyText }}>Adversarial review</strong>
          <Button variant="ghost" onClick={() => void review()} disabled={reviewing}>
            {reviewing ? "Reviewing…" : "Run review"}
          </Button>
        </div>
        <div style={{ fontSize: 11, color: BRAND.sub, marginBottom: 6 }}>
          Three critics — privacy, grounding, reader — read the page that would publish.
          Advisory: the gate on the left is what refuses.
        </div>
        {findings && findings.length === 0 && (
          <div style={{ fontSize: 12, color: BRAND.sub }}>No findings.</div>
        )}
        {findings?.map((f, i) => (
          <div key={`${f.lens}-${i}`} style={{ marginBottom: 6, fontSize: 12 }}>
            <Badge tone={sevTone(f.severity)}>{f.severity}</Badge>{" "}
            <span style={{ color: BRAND.sub }}>{f.lens}</span>
            <div style={{ color: BRAND.navyText }}>{f.issue}</div>
            {f.fix && <div style={{ color: BRAND.sub, fontSize: 11 }}>fix: {f.fix}</div>}
          </div>
        ))}

        <div style={{ marginTop: 12, borderTop: `1px solid ${BRAND.border}`, paddingTop: 10 }}>
          <Button
            onClick={() => void publish()}
            disabled={publishing || !gate.publishable}
            title={gate.publishable ? undefined
              : `Blocked: ${gate.failing.map((c) => c.label).join(", ")}`}
          >
            {publishing ? "Publishing…" : item.wp_post_id ? "Update on WordPress" : "Publish to WordPress"}
          </Button>
          {!gate.publishable && (
            <div style={{ fontSize: 11, color: BRAND.red, marginTop: 4 }}>
              Publish is refused until the gate passes.
            </div>
          )}
          {result?.jsonld_stored === false && (
            <div style={{ fontSize: 11, color: BRAND.red, marginTop: 4 }}>
              Published, but WordPress dropped the JSON-LD — the perkins-jsonld mu-plugin needs
              updating for portfolio/page types.
            </div>
          )}
        </div>
        {err && <ErrorMsg>{err}</ErrorMsg>}
      </div>

      <div style={{ width: "100%" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
          Preview of the WordPress page
          {view.scope_lines.length > 0 && ` · ${view.scope_lines.length} scope lines from the contract`}
        </div>
        <div
          style={{
            border: `1px solid ${BRAND.border}`, borderRadius: 4, padding: 8, marginTop: 6,
            maxHeight: 340, overflowY: "auto", background: "#fff", fontSize: 12,
          }}
          dangerouslySetInnerHTML={{ __html: view.preview_html }}
        />
      </div>
    </div>
  );
}

function ProjectPanel({ item, onChanged }: { item: PortfolioItem; onChanged: () => void }) {
  const [tab, setTab] = useState<Tab>("Project");
  const [view, setView] = useState<CurationView | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const r = await apiFetch(`/portfolio/${item.slug}/media`);
      if (!r.ok) throw new Error(await errText(r));
      setView(await r.json());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.slug]);

  return (
    <div style={{ background: BRAND.bg, padding: "10px 14px" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              fontSize: 12, padding: "4px 10px", cursor: "pointer",
              border: `1px solid ${BRAND.border}`, borderRadius: 3,
              background: tab === t ? "#fff" : "transparent",
              fontWeight: tab === t ? 600 : 400,
              color: tab === t ? BRAND.navyText : BRAND.sub,
            }}
          >
            {t}
          </button>
        ))}
      </div>
      {err && <ErrorMsg>{err}</ErrorMsg>}
      {tab === "Project" && <ProjectTab item={item} onSaved={onChanged} />}
      {tab !== "Project" && !view && <Loading label="Loading…" />}
      {tab === "Media" && view && (
        <MediaTab view={view} onChanged={(v) => { setView(v); onChanged(); }} />
      )}
      {tab === "SEO / AIO" && view && (
        <SeoTab view={view} item={item} onPublished={() => { void load(); onChanged(); }} />
      )}
    </div>
  );
}

function NewProject({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    setProblems([]);
    try {
      const r = await apiFetch("/portfolio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          search_terms: form.search_terms.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      if (r.status === 422) {
        const body = await r.json();
        setProblems(body?.detail?.problems ?? ["invalid"]);
        return;
      }
      if (!r.ok) throw new Error(await errText(r));
      setForm(EMPTY_FORM);
      setOpen(false);
      onCreated();
    } catch (e) {
      setProblems([e instanceof Error ? e.message : String(e)]);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div style={{ marginBottom: 10 }}>
        <Button onClick={() => setOpen(true)}>New project</Button>
      </div>
    );
  }
  const set =
    (k: keyof ProjectForm) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm({ ...form, [k]: e.target.value });

  return (
    <Card style={{ marginBottom: 10, padding: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 10 }}>
        <div>
          <label style={labelStyle}>Project name *</label>
          <input style={inputStyle} value={form.name} onChange={set("name")} autoFocus />
        </div>
        <div>
          <label style={labelStyle}>City or neighbourhood</label>
          <input style={inputStyle} value={form.city} onChange={set("city")} />
        </div>
        <div>
          <label style={labelStyle}>Section</label>
          <select style={inputStyle} value={form.section} onChange={set("section")}>
            <option value="commercial">commercial</option>
            <option value="residential">residential</option>
            <option value="construction">construction</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>CompanyCam project URL</label>
          <input style={inputStyle} value={form.companycam_url} onChange={set("companycam_url")} />
        </div>
        <div>
          <label style={labelStyle}>Knowify search terms (comma separated)</label>
          <input style={inputStyle} value={form.search_terms} onChange={set("search_terms")} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Button onClick={() => void create()} disabled={busy || !form.name.trim()}>
          {busy ? "Creating…" : "Create"}
        </Button>
        <Button variant="ghost" onClick={() => { setOpen(false); setProblems([]); }}>Cancel</Button>
      </div>
      {problems.map((p) => (
        <div key={p} style={{ color: BRAND.red, fontSize: 12 }}>{p}</div>
      ))}
    </Card>
  );
}

export function Portfolio() {
  const [items, setItems] = useState<PortfolioItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ name: string; html: string; scope: number } | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);

  async function previewItem(item: PortfolioItem) {
    setPreviewing(item.slug);
    setPreviewErr(null);
    try {
      const r = await apiFetch(`/portfolio/${item.slug}/media`);
      if (!r.ok) throw new Error(await errText(r));
      const view: CurationView = await r.json();
      setPreview({
        name: view.name,
        html: view.preview_html,
        scope: view.scope_lines.length,
      });
    } catch (e) {
      setPreviewErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewing(null);
    }
  }

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

  useEffect(() => { void load(); }, []);

  if (loadError) return <ErrorMsg>{loadError}</ErrorMsg>;
  if (!items) return <Loading label="Loading portfolio projects…" />;

  const head = ["Project", "City", "Type", "Roof System", "Media", "Gate", "WordPress", ""];
  return (
    <div>
      <PageTitle>Portfolio</PageTitle>
      <NewProject onCreated={() => void load()} />
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: BRAND.bg, textAlign: "left" }}>
                {head.map((h) => (
                  <th key={h} style={{ padding: "10px 14px", fontSize: 11, textTransform: "uppercase",
                                       color: BRAND.sub, letterSpacing: 0.3 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.flatMap((item) => [
                <tr key={item.slug} style={{ borderTop: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 14px", fontWeight: 600, color: BRAND.navyText }}>
                    {item.name}
                  </td>
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
                  <td style={{ padding: "10px 14px" }}>{gateBadge(item)}{gateReasonLine(item)}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {wpBadge(item)}
                      {item.wp_admin_url && (
                        <a href={item.wp_admin_url} target="_blank" rel="noopener noreferrer"
                           style={{ color: BRAND.red, fontSize: 12 }}>
                          Edit in WordPress
                        </a>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="ghost"
                              onClick={() => void previewItem(item)}
                              disabled={previewing === item.slug}>
                        {previewing === item.slug ? "Loading…" : "Preview"}
                      </Button>
                      <Button variant="ghost"
                              onClick={() => setOpenSlug(openSlug === item.slug ? null : item.slug)}>
                        {openSlug === item.slug ? "Close" : "Manage"}
                      </Button>
                    </div>
                  </td>
                </tr>,
                openSlug === item.slug ? (
                  <tr key={`${item.slug}-panel`}>
                    <td colSpan={head.length} style={{ padding: 0, borderTop: `1px solid ${BRAND.border}` }}>
                      <ProjectPanel item={item} onChanged={() => void load()} />
                    </td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          </table>
        </div>
      </Card>
      {previewErr && <ErrorMsg>{previewErr}</ErrorMsg>}
      {preview && createPortal(
        <div
          role="dialog"
          aria-label="Portfolio preview"
          onClick={() => setPreview(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)",
            zIndex: 80, display: "flex", justifyContent: "center", alignItems: "flex-start",
            padding: "24px 16px", overflow: "auto",
          }}
        >
          <Card
            style={{
              width: "min(800px, calc(100vw - 32px))",
              maxHeight: "calc(100vh - 48px)",
              overflow: "auto",
              padding: 20,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 16, lineHeight: 1.3 }}>
                  Preview: {preview.name}
                </h3>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: BRAND.sub }}>
                  This is the HTML that Publish to WordPress will push
                  {preview.scope > 0 ? ` · ${preview.scope} scope lines from the contract` : ""}.
                </p>
              </div>
              <Button variant="ghost" onClick={() => setPreview(null)}>Close</Button>
            </div>
            <div
              className="portfolio-preview-html"
              style={{
                border: `1px solid ${BRAND.border}`, borderRadius: 8, padding: "20px 24px",
                background: "#fff", fontSize: 15, lineHeight: 1.55, color: BRAND.ink,
                overflowWrap: "anywhere",
              }}
              dangerouslySetInnerHTML={{ __html: preview.html }}
            />
          </Card>
        </div>,
        document.body,
      )}
    </div>
  );
}
