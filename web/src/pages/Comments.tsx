import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Button, Card, ErrorMsg, Loading, PageTitle, inputStyle } from "../ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CommentItem {
  id: number;
  video_id: string;
  video_title: string;
  video_url: string;
  comment_id: string;
  author: string;
  comment_text: string;
  published_at: string | null;
  needs_reply: boolean;
  draft_reply: string | null;
  status: string;
  created_at: string | null;
}

interface ListResponse {
  total: number;
  items: CommentItem[];
}

type StatusFilter = "all" | "pending" | "drafted" | "ready" | "dismissed";

const PAGE_SIZE = 50;

const STATUS_COLORS: Record<string, string> = {
  pending:   "#f59e0b",
  drafted:   BRAND.navy,
  ready:     "#16a34a",
  dismissed: "#9ca3af",
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function Comments() {
  const [items, setItems]             = useState<CommentItem[]>([]);
  const [total, setTotal]             = useState(0);
  const [offset, setOffset]           = useState(0);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [needsReplyOnly, setNeedsReplyOnly] = useState(true);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState<string | null>(null);
  const [crawling, setCrawling]       = useState(false);
  const [crawlMsg, setCrawlMsg]       = useState<string | null>(null);
  const [crawlLimit, setCrawlLimit]   = useState(20);
  const [savingId, setSavingId]       = useState<number | null>(null);
  const [draftingId, setDraftingId]   = useState<number | null>(null);
  const [drafts, setDrafts]           = useState<Record<number, string>>({});
  const [actionMsg, setActionMsg]     = useState<string | null>(null);

  function loadItems(status: StatusFilter, needsOnly: boolean, off: number) {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(off),
    });
    if (status !== "all") params.set("status", status);
    if (needsOnly) params.set("needs_reply", "true");

    apiFetch(`/comments?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: ListResponse) => {
        if (off === 0) {
          setItems(d.items);
        } else {
          setItems((prev) => [...prev, ...d.items]);
        }
        setTotal(d.total);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadItems(statusFilter, needsReplyOnly, 0);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleStatusChange(val: StatusFilter) {
    setStatusFilter(val);
    setOffset(0);
    loadItems(val, needsReplyOnly, 0);
  }

  function handleNeedsReplyToggle(val: boolean) {
    setNeedsReplyOnly(val);
    setOffset(0);
    loadItems(statusFilter, val, 0);
  }

  function handleLoadMore() {
    const next = offset + PAGE_SIZE;
    setOffset(next);
    loadItems(statusFilter, needsReplyOnly, next);
  }

  async function handleCrawl() {
    setCrawling(true);
    setCrawlMsg(null);
    try {
      const r = await apiFetch("/comments/crawl", {
        method: "POST",
        body: JSON.stringify({ limit: crawlLimit }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const d = await r.json();
      const errorSuffix = d.errors > 0
        ? ` Warning: ${d.errors} comment(s) failed to draft (LLM or fetch error).`
        : "";
      setCrawlMsg(
        `Crawled ${d.videos_processed} videos — ${d.comments_upserted} new comments, ` +
        `${d.flagged} flagged, ${d.drafted} drafted.${errorSuffix}`
      );
      setOffset(0);
      loadItems(statusFilter, needsReplyOnly, 0);
    } catch (e: unknown) {
      setCrawlMsg(`Crawl failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCrawling(false);
    }
  }

  async function handleRegenerate(item: CommentItem) {
    setDraftingId(item.id);
    setActionMsg(null);
    try {
      const r = await apiFetch(`/comments/${item.id}/draft`, { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const updated: CommentItem = await r.json();
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      setDrafts((prev) => ({ ...prev, [updated.id]: updated.draft_reply ?? "" }));
    } catch (e: unknown) {
      setActionMsg(`Regenerate failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDraftingId(null);
    }
  }

  async function handleSave(item: CommentItem, newStatus?: string) {
    setSavingId(item.id);
    setActionMsg(null);
    const body: { draft_reply?: string; status?: string } = {};
    if (drafts[item.id] !== undefined) body.draft_reply = drafts[item.id];
    if (newStatus) body.status = newStatus;

    try {
      const r = await apiFetch(`/comments/${item.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const updated: CommentItem = await r.json();
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    } catch (e: unknown) {
      setActionMsg(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingId(null);
    }
  }

  function draftValue(item: CommentItem): string {
    return drafts[item.id] !== undefined ? drafts[item.id] : (item.draft_reply ?? "");
  }

  const hasMore = offset + PAGE_SIZE < total;

  return (
    <main style={{ maxWidth: 960 }}>
      <PageTitle>Comment Reply Assistant</PageTitle>

      {/* Note about posting limitation */}
      <Card style={{ marginBottom: 20, background: "#fffbeb", borderLeft: `4px solid #f59e0b` }}>
        <p style={{ margin: 0, fontSize: 13, color: "#92400e" }}>
          <strong>Draft-only mode:</strong> This tool prepares reply drafts for Tim to review and
          copy-paste into YouTube. Direct posting to YouTube requires OAuth write scope not yet
          configured. Mark a reply <em>Ready</em> when it's approved to post.
        </p>
      </Card>

      {/* Crawl controls */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: BRAND.navyText }}>Crawl comments:</span>
          {[5, 10, 20, 50].map((n) => (
            <button
              key={n}
              onClick={() => setCrawlLimit(n)}
              style={{
                padding: "4px 12px", borderRadius: 6, fontSize: 13, cursor: "pointer",
                fontWeight: crawlLimit === n ? 700 : 400,
                background: crawlLimit === n ? BRAND.navy : "#fff",
                color: crawlLimit === n ? "#fff" : BRAND.navyText,
                border: `1px solid ${crawlLimit === n ? BRAND.navy : BRAND.border}`,
              }}
            >
              {n} videos
            </button>
          ))}
          <Button onClick={handleCrawl} disabled={crawling} style={{ fontSize: 13 }}>
            {crawling ? "Crawling…" : `Crawl ${crawlLimit} videos`}
          </Button>
        </div>
        {crawlMsg && (
          <p style={{
            margin: "10px 0 0", fontSize: 13,
            color: crawlMsg.startsWith("Warning:") || crawlMsg.includes("Warning:") ? "#b45309" : BRAND.sub,
          }}>{crawlMsg}</p>
        )}
      </Card>

      {/* Filters */}
      <Card style={{ marginBottom: 20, padding: "14px 20px" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 13, color: BRAND.ink, display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={needsReplyOnly}
              onChange={(e) => handleNeedsReplyToggle(e.target.checked)}
            />
            Needs reply only
          </label>
          <select
            value={statusFilter}
            onChange={(e) => handleStatusChange(e.target.value as StatusFilter)}
            style={{ ...inputStyle, minWidth: 130 }}
          >
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="drafted">Drafted</option>
            <option value="ready">Ready</option>
            <option value="dismissed">Dismissed</option>
          </select>
          <span style={{ fontSize: 13, color: BRAND.sub, whiteSpace: "nowrap" }}>
            {total} comment{total !== 1 ? "s" : ""}
          </span>
        </div>
      </Card>

      {actionMsg && (
        <p style={{ fontSize: 13, color: BRAND.red, marginBottom: 12 }}>{actionMsg}</p>
      )}

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && items.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No comments found. Use "Crawl" above to fetch comments from your YouTube videos.
          </p>
        </Card>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {items.map((item) => {
              const statusColor = STATUS_COLORS[item.status] ?? BRAND.sub;
              return (
                <Card
                  key={item.id}
                  style={{ borderLeft: `4px solid ${statusColor}` }}
                >
                  {/* Header: video link + author + status badge */}
                  <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 10 }}>
                    <div style={{ flex: 1 }}>
                      <a
                        href={item.video_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: BRAND.red, fontSize: 13, fontWeight: 600, textDecoration: "none" }}
                      >
                        ▶ {item.video_title}
                      </a>
                      <span style={{ fontSize: 12, color: BRAND.sub, marginLeft: 10 }}>
                        by {item.author || "unknown"}
                        {item.published_at ? ` · ${new Date(item.published_at).toLocaleDateString()}` : ""}
                      </span>
                    </div>
                    <span
                      style={{
                        fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: 10,
                        background: statusColor + "22", color: statusColor, whiteSpace: "nowrap",
                        textTransform: "capitalize",
                      }}
                    >
                      {item.status}
                    </span>
                  </div>

                  {/* Comment text */}
                  <p style={{
                    margin: "0 0 12px",
                    fontSize: 14, color: BRAND.navyText,
                    background: BRAND.bg, borderRadius: 6, padding: "10px 14px",
                    lineHeight: 1.6, whiteSpace: "pre-wrap",
                  }}>
                    {item.comment_text}
                  </p>

                  {/* Draft reply textarea */}
                  {item.status !== "dismissed" && (
                    <div style={{ marginBottom: 10 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, color: BRAND.sub, display: "block", marginBottom: 4 }}>
                        Draft reply
                      </label>
                      <textarea
                        rows={3}
                        value={draftValue(item)}
                        onChange={(e) =>
                          setDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))
                        }
                        placeholder="No draft yet — click Regenerate to generate one."
                        style={{
                          width: "100%",
                          boxSizing: "border-box",
                          fontSize: 13,
                          border: `1px solid ${BRAND.border}`,
                          borderRadius: 6,
                          padding: "8px 12px",
                          lineHeight: 1.6,
                          resize: "vertical",
                          fontFamily: "inherit",
                          color: BRAND.navyText,
                          background: "#fff",
                        }}
                      />
                    </div>
                  )}

                  {/* Action buttons */}
                  {item.status !== "dismissed" && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <Button
                        variant="ghost"
                        disabled={draftingId === item.id}
                        onClick={() => handleRegenerate(item)}
                        style={{ fontSize: 12, padding: "5px 12px" }}
                      >
                        {draftingId === item.id ? "Generating…" : "Regenerate"}
                      </Button>
                      <Button
                        disabled={savingId === item.id}
                        onClick={() => handleSave(item)}
                        style={{ fontSize: 12, padding: "5px 12px" }}
                      >
                        {savingId === item.id ? "Saving…" : "Save"}
                      </Button>
                      {item.status !== "ready" && (
                        <Button
                          disabled={savingId === item.id}
                          onClick={() => handleSave(item, "ready")}
                          style={{
                            fontSize: 12, padding: "5px 12px",
                            background: "#16a34a", borderColor: "#16a34a",
                          }}
                        >
                          Mark Ready
                        </Button>
                      )}
                      <Button
                        variant="danger"
                        disabled={savingId === item.id}
                        onClick={() => handleSave(item, "dismissed")}
                        style={{ fontSize: 12, padding: "5px 12px" }}
                      >
                        Dismiss
                      </Button>
                    </div>
                  )}

                  {item.status === "dismissed" && (
                    <Button
                      variant="ghost"
                      disabled={savingId === item.id}
                      onClick={() => handleSave(item, "pending")}
                      style={{ fontSize: 12, padding: "5px 12px" }}
                    >
                      Restore
                    </Button>
                  )}
                </Card>
              );
            })}
          </div>

          {hasMore && (
            <div style={{ textAlign: "center", marginTop: 20 }}>
              <Button variant="ghost" onClick={handleLoadMore} style={{ fontSize: 13 }}>
                Load more ({total - offset - items.length} remaining)
              </Button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
