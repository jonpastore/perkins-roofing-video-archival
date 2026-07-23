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
  missing_permissions: string[];
  wp_post_id: number | null;
  wp_status: string | null;
  wp_admin_url: string | null;
  publish_result?: PublishResult;
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

export function Portfolio() {
  const [items, setItems] = useState<PortfolioItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [publishingSlug, setPublishingSlug] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

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
                {["Project", "City", "Property Type", "Roof System", "Permissions", "WordPress", ""].map((h) => (
                  <th key={h} style={{ padding: "10px 14px", fontSize: 11, textTransform: "uppercase", color: BRAND.sub, letterSpacing: 0.3 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.slug} style={{ borderTop: `1px solid ${BRAND.border}` }}>
                  <td style={{ padding: "10px 14px", fontWeight: 600, color: BRAND.navyText }}>{item.name}</td>
                  <td style={{ padding: "10px 14px" }}>{item.city || "—"}</td>
                  <td style={{ padding: "10px 14px" }}>{item.property_type}</td>
                  <td style={{ padding: "10px 14px" }}>{item.roof_type || "—"}</td>
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
                      disabled={publishingSlug === item.slug || item.missing_permissions.length > 0}
                      title={item.missing_permissions.length > 0 ? `Blocked: ${item.missing_permissions.join(", ")}` : undefined}
                      onClick={() => void handlePublish(item)}
                    >
                      {publishingSlug === item.slug ? "Publishing…" : "Publish"}
                    </Button>
                    {rowError[item.slug] && <ErrorMsg>{rowError[item.slug]}</ErrorMsg>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
