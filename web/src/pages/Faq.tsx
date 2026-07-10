import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg, hms, ytLink } from "../ui";
import { ComposeEmailModal } from "../components/ComposeEmailModal";

// Render an FAQ answer: turn `[link n](url)` markdown citations into clickable links.
function renderAnswer(text: string): ReactNode[] {
  const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  const out: ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(
      <a key={i++} href={m[2]} target="_blank" rel="noopener noreferrer"
        style={{ color: BRAND.red, fontWeight: 600, textDecoration: "none" }}>
        {m[1]}
      </a>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

interface FaqItem {
  id: number;
  question: string;
  answer: string | null;
  status: string;
  video_id: string;
  video_title: string;
  url: string;
  start: number;
}

interface FaqListResponse {
  total: number;
  items: FaqItem[];
}

interface Coverage {
  mined: number;
  answered: number;
  uncovered_nodes: number;
}

interface PublishResult {
  page_id: number;
  page_url: string;
  published: number;
  action: "created" | "updated";
}

interface EstimateResult {
  count: number;
  mine_cost_usd: number;
  answer_cost_usd: number;
  model: string;
  caps: { mine_max: number; answer_batch_max: number };
}

// Unmined FAQ candidates from /suggestions?bucket=faqs
interface UnminedFaqItem {
  question: string;
  video_id: string;
  title: string;
  t: number | null;
}

const MINE_BATCH_OPTIONS = [50, 100, 200] as const;
const ANSWER_BATCH_OPTIONS = [25, 50, 100] as const;
const UNMINED_PAGE_SIZE = 50;

type FaqTab = "answered" | "unmined";

function fmt$( n: number): string {
  return `$${n.toFixed(4)}`;
}

function mmss(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const PAGE_SIZE = 50;

export function Faq() {
  // Tab state: "answered" = mined+answered FAQ list; "unmined" = candidates from /suggestions
  const [activeTab, setActiveTab] = useState<FaqTab>("answered");

  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [items, setItems] = useState<FaqItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [answeredFilter, setAnsweredFilter] = useState<"all" | "yes" | "no">("all");
  const [loading, setLoading] = useState(true);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mining, setMining] = useState(false);
  const [generatingBatch, setGeneratingBatch] = useState(false);
  const [answeringId, setAnsweringId] = useState<number | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<PublishResult | null>(null);
  const [mineBatchSize, setMineBatchSize] = useState<number>(200);
  const [answerBatchSize, setAnswerBatchSize] = useState<number>(25);
  const [mineEstimate, setMineEstimate] = useState<EstimateResult | null>(null);
  const [answerEstimate, setAnswerEstimate] = useState<EstimateResult | null>(null);
  const filterTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Unmined tab state
  const [unminedItems, setUnminedItems] = useState<UnminedFaqItem[]>([]);
  const [unminedTotal, setUnminedTotal] = useState(0);
  const [unminedPage, setUnminedPage] = useState(0);
  const [unminedLoading, setUnminedLoading] = useState(false);
  const [unminedError, setUnminedError] = useState<string | null>(null);

  const fetchUnmined = useCallback((page: number) => {
    setUnminedLoading(true);
    setUnminedError(null);
    const off = page * UNMINED_PAGE_SIZE;
    apiFetch(`/suggestions?bucket=faqs&limit=${UNMINED_PAGE_SIZE}&offset=${off}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: { faqs?: UnminedFaqItem[]; faqs_total?: number }) => {
        setUnminedItems(d.faqs ?? []);
        setUnminedTotal(d.faqs_total ?? 0);
      })
      .catch((e: unknown) => setUnminedError(e instanceof Error ? e.message : String(e)))
      .finally(() => setUnminedLoading(false));
  }, []);

  useEffect(() => {
    if (activeTab === "unmined") fetchUnmined(unminedPage);
  }, [activeTab, unminedPage, fetchUnmined]);

  function loadCoverage() {
    setCoverageLoading(true);
    apiFetch("/faq/coverage")
      .then((r) => r.json())
      .then((d: Coverage) => setCoverage(d))
      .catch(() => setCoverage(null))
      .finally(() => setCoverageLoading(false));
  }

  function fetchEstimate(count: number, setter: (e: EstimateResult) => void) {
    apiFetch(`/faq/estimate?count=${count}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: EstimateResult | null) => { if (d) setter(d); })
      .catch(() => {});
  }

  useEffect(() => { fetchEstimate(mineBatchSize, setMineEstimate); }, [mineBatchSize]);
  useEffect(() => { fetchEstimate(answerBatchSize, setAnswerEstimate); }, [answerBatchSize]);

  function loadItems(q: string, ans: "all" | "yes" | "no", off: number) {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(off),
      answered: ans,
    });
    if (q) params.set("q", q);
    apiFetch(`/faq?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: FaqListResponse) => {
        setItems(d.items);
        setTotal(d.total);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadCoverage();
    loadItems("", "all", 0);
    fetchEstimate(mineBatchSize, setMineEstimate);
    fetchEstimate(answerBatchSize, setAnswerEstimate);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleFilterChange(val: string) {
    setFilter(val);
    if (filterTimer.current) clearTimeout(filterTimer.current);
    filterTimer.current = setTimeout(() => {
      setOffset(0);
      loadItems(val, answeredFilter, 0);
    }, 350);
  }

  function handleAnsweredChange(val: "all" | "yes" | "no") {
    setAnsweredFilter(val);
    setOffset(0);
    loadItems(filter, val, 0);
  }

  function handleLoadMore() {
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    apiFetch(`/faq?limit=${PAGE_SIZE}&offset=${nextOffset}&answered=${answeredFilter}${filter ? `&q=${encodeURIComponent(filter)}` : ""}`)
      .then((r) => r.json())
      .then((d: FaqListResponse) => {
        setItems((prev) => [...prev, ...d.items]);
        setTotal(d.total);
      });
  }

  async function handleMine() {
    setMining(true);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/mine", { method: "POST", body: JSON.stringify({ limit: mineBatchSize }) });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const d = await r.json();
      setActionMsg(`Mined ${d.mined} new questions and answered ${d.answered ?? 0}. ${d.remaining_uncovered} content items still available.`);
      loadCoverage();
      setOffset(0);
      loadItems(filter, answeredFilter, 0);
    } catch (e: unknown) {
      setActionMsg(`Mine failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMining(false);
    }
  }

  async function handleGenerateBatch() {
    setGeneratingBatch(true);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/answer-batch", { method: "POST", body: JSON.stringify({ limit: answerBatchSize }) });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const d = await r.json();
      setActionMsg(`Generated ${d.answered} answers. ${d.remaining} still unanswered.`);
      loadCoverage();
      setOffset(0);
      loadItems(filter, answeredFilter, 0);
    } catch (e: unknown) {
      setActionMsg(`Generate failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGeneratingBatch(false);
    }
  }

  async function handleAnswerOne(item: FaqItem) {
    setAnsweringId(item.id);
    try {
      const r = await apiFetch(`/faq/${item.id}/answer`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const updated: FaqItem = await r.json();
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      loadCoverage();
    } catch (e: unknown) {
      setActionMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAnsweringId(null);
    }
  }

  async function handlePublishWordPress() {
    setPublishing(true);
    setPublishResult(null);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/publish-wordpress", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const d: PublishResult = await r.json();
      setPublishResult(d);
    } catch (e: unknown) {
      setActionMsg(`Publish failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPublishing(false);
    }
  }

  // Email compose state
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set());
  const [emailModalBody, setEmailModalBody] = useState<string | null>(null);

  function toggleCheck(id: number) {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    const answered = items.filter((i) => i.answer);
    const allChecked = answered.length > 0 && answered.every((i) => checkedIds.has(i.id));
    if (allChecked) {
      setCheckedIds(new Set());
    } else {
      setCheckedIds(new Set(answered.map((i) => i.id)));
    }
  }

  function buildFaqEmailBody(): string {
    const esc = (s: string) =>
      (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const selected = items.filter((i) => checkedIds.has(i.id) && i.answer);
    const qas = selected
      .map(
        (i) =>
          `<li style="margin-bottom:16px;">` +
          `<p style="margin:0 0 6px;font-weight:bold;">${esc(i.question)}</p>` +
          `<p style="margin:0;color:#333;">${esc(i.answer ?? "")}</p>` +
          `<p style="margin:4px 0 0;font-size:12px;"><a href="${esc(i.url)}">▶ ${esc(i.video_title)} @ ${mmss(i.start)}</a></p>` +
          `</li>`
      )
      .join("\n");
    return [
      "<p>Hi,</p>",
      "<p>Here are some answers from Tim Perkins' roofing knowledge base that I thought might help:</p>",
      `<ul style="padding-left:20px;">${qas}</ul>`,
      "<p>Let me know if you have any other questions!</p>",
      "<p>Best,<br>Tim Perkins Roofing</p>",
    ].join("\n");
  }

  const answeredItems = items.filter((i) => i.answer);
  const allAnsweredChecked =
    answeredItems.length > 0 && answeredItems.every((i) => checkedIds.has(i.id));
  const someAnsweredChecked = answeredItems.some((i) => checkedIds.has(i.id));

  const hasMore = offset + PAGE_SIZE < total;

  const unminedTotalPages = Math.max(1, Math.ceil(unminedTotal / UNMINED_PAGE_SIZE));

  function tabStyle(t: FaqTab): React.CSSProperties {
    const active = activeTab === t;
    return {
      padding: "8px 18px",
      border: "none",
      borderBottom: active ? `2px solid ${BRAND.red}` : "2px solid transparent",
      background: "none",
      cursor: "pointer",
      fontSize: 14,
      fontWeight: active ? 700 : 500,
      color: active ? BRAND.navyText : BRAND.sub,
      marginBottom: -1,
    };
  }

  return (
    <main style={{ maxWidth: 960 }}>
      <PageTitle>FAQ Builder</PageTitle>

      {/* Tab switcher */}
      <div style={{ display: "flex", borderBottom: `1px solid ${BRAND.border}`, marginBottom: 20 }}>
        <button style={tabStyle("answered")} onClick={() => setActiveTab("answered")}>
          Answered
          {coverage && (
            <span style={{
              marginLeft: 7, fontSize: 11, fontWeight: 700, padding: "1px 7px",
              borderRadius: 10, background: "#eef1f5", color: BRAND.sub,
            }}>
              {coverage.answered}
            </span>
          )}
        </button>
        <button style={tabStyle("unmined")} onClick={() => setActiveTab("unmined")}>
          Unmined questions
          {unminedTotal > 0 && (
            <span style={{
              marginLeft: 7, fontSize: 11, fontWeight: 700, padding: "1px 7px",
              borderRadius: 10, background: "#fff3e0", color: "#b45309",
            }}>
              {unminedTotal}
            </span>
          )}
        </button>
      </div>

      {/* ── UNMINED TAB ─────────────────────────────────────── */}
      {activeTab === "unmined" && (
        <div>
          <p style={{ fontSize: 13, color: BRAND.sub, margin: "0 0 16px" }}>
            These are candidate questions mined from video content (objections and claims) whose
            source video is not yet referenced in any article. Use the{" "}
            <strong>mine & answer</strong> controls on the Answered tab to pull them into the FAQ.
          </p>
          {unminedLoading && <Loading label="Loading candidates…" />}
          {unminedError && <ErrorMsg>Could not load candidates: {unminedError}</ErrorMsg>}
          {!unminedLoading && !unminedError && unminedItems.length === 0 && (
            <Card>
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
                No unmined candidates — all content is covered by articles.
              </p>
            </Card>
          )}
          {!unminedLoading && !unminedError && unminedItems.length > 0 && (
            <>
              <div style={{ fontSize: 12, color: BRAND.sub, marginBottom: 10 }}>
                {unminedTotal} candidate{unminedTotal !== 1 ? "s" : ""} · page {unminedPage + 1} of {unminedTotalPages}
              </div>
              <Card style={{ padding: 0, overflow: "hidden", marginBottom: 12 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                  <thead>
                    <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                      <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Question</th>
                      <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, whiteSpace: "nowrap" }}>
                        Source clip
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {unminedItems.map((f, i) => (
                      <tr key={`${f.video_id}-${f.t}-${i}`} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                        <td style={{ padding: "10px 16px" }}>{f.question}</td>
                        <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                          <a
                            href={ytLink(f.video_id, f.t)}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: BRAND.navyText, fontWeight: 500, textDecoration: "none" }}
                          >
                            {f.title} @ {hms(f.t)}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              {unminedTotalPages > 1 && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                  <button
                    onClick={() => setUnminedPage((p) => Math.max(0, p - 1))}
                    disabled={unminedPage === 0}
                    style={{
                      background: "none", border: `1px solid ${BRAND.border}`, borderRadius: 6,
                      padding: "3px 12px", cursor: unminedPage === 0 ? "not-allowed" : "pointer",
                      color: unminedPage === 0 ? BRAND.sub : BRAND.navyText, fontWeight: 600,
                    }}
                  >
                    Prev
                  </button>
                  <span style={{ color: BRAND.sub }}>
                    Page {unminedPage + 1} of {unminedTotalPages}
                  </span>
                  <button
                    onClick={() => setUnminedPage((p) => Math.min(unminedTotalPages - 1, p + 1))}
                    disabled={unminedPage >= unminedTotalPages - 1}
                    style={{
                      background: "none", border: `1px solid ${BRAND.border}`, borderRadius: 6,
                      padding: "3px 12px",
                      cursor: unminedPage >= unminedTotalPages - 1 ? "not-allowed" : "pointer",
                      color: unminedPage >= unminedTotalPages - 1 ? BRAND.sub : BRAND.navyText,
                      fontWeight: 600,
                    }}
                  >
                    Next
                  </button>
                </div>
              )}
              <p style={{ fontSize: 12, color: BRAND.sub, margin: "12px 0 0", fontStyle: "italic" }}>
                Switch to the <button
                  onClick={() => setActiveTab("answered")}
                  style={{ background: "none", border: "none", cursor: "pointer", color: BRAND.navyText, fontWeight: 700, fontSize: 12, padding: 0, textDecoration: "underline" }}
                >Answered tab</button> to mine and batch-answer these questions.
              </p>
            </>
          )}
        </div>
      )}

      {/* ── ANSWERED TAB ────────────────────────────────────── */}
      {activeTab === "answered" && <>

      {/* Coverage summary bar */}
      <Card style={{ marginBottom: 20 }}>
        {coverageLoading ? (
          <Loading label="Loading coverage…" />
        ) : coverage ? (
          <>
            {/* Empty-state: no questions mined yet but content is available */}
            {coverage.mined === 0 && coverage.uncovered_nodes > 0 && (
              <div style={{
                background: "#fff8e1",
                border: "1px solid #ffe082",
                borderRadius: 8,
                padding: "16px 20px",
                marginBottom: 16,
              }}>
                <p style={{ margin: "0 0 10px", fontWeight: 700, fontSize: 15, color: BRAND.navyText }}>
                  No questions mined yet — {coverage.uncovered_nodes.toLocaleString()} content items available
                </p>
                <p style={{ margin: "0 0 12px", fontSize: 13, color: BRAND.ink }}>
                  The content graph has been built from your videos. Click below to extract FAQ questions
                  from claims and objections found in the content.
                </p>
                <Button onClick={handleMine} disabled={mining} style={{ fontSize: 14 }}>
                  {mining ? "Mining & answering…" : `Mine & answer ${mineBatchSize} questions now`}
                </Button>
              </div>
            )}

            <div style={{ fontSize: 14, color: BRAND.ink, marginBottom: 12 }}>
              <strong style={{ color: BRAND.navyText }}>{coverage.mined}</strong> questions mined
              {" · "}
              <strong style={{ color: BRAND.navyText }}>{coverage.answered}</strong> answered
              {" · "}
              <strong style={{ color: BRAND.navyText }}>{coverage.uncovered_nodes.toLocaleString()}</strong> available to mine
            </div>

            {/* Mine batch controls */}
            {coverage.uncovered_nodes > 0 && (
              <div style={{ background: BRAND.bg, borderRadius: 8, padding: "12px 16px", marginBottom: 12 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600 }}>Mine questions:</span>
                  {MINE_BATCH_OPTIONS.map((n) => (
                    <button
                      key={n}
                      onClick={() => setMineBatchSize(n)}
                      style={{
                        padding: "4px 12px", borderRadius: 6, fontSize: 13, cursor: "pointer",
                        fontWeight: mineBatchSize === n ? 700 : 400,
                        background: mineBatchSize === n ? BRAND.navy : "#fff",
                        color: mineBatchSize === n ? "#fff" : BRAND.navyText,
                        border: `1px solid ${mineBatchSize === n ? BRAND.navy : BRAND.border}`,
                      }}
                    >
                      {n}
                    </button>
                  ))}
                  <Button onClick={handleMine} disabled={mining || coverage.uncovered_nodes === 0} style={{ fontSize: 13 }}>
                    {mining ? "Mining & answering…" : `Mine & answer ${mineBatchSize}`}
                  </Button>
                </div>
                <p style={{ margin: 0, fontSize: 12, color: BRAND.sub }}>
                  {mineEstimate
                    ? <>Mining {mineBatchSize} questions ~ <strong>{fmt$(mineEstimate.mine_cost_usd)}</strong> (estimate, {mineEstimate.model})</>
                    : <Loading label="Loading estimate…" />}
                  {coverage.uncovered_nodes > 500 && mineEstimate && (
                    <> · Mining all {coverage.uncovered_nodes.toLocaleString()} ~ <strong>{fmt$(mineEstimate.mine_cost_usd / mineBatchSize * coverage.uncovered_nodes)}</strong> (estimate)</>
                  )}
                </p>
              </div>
            )}

            {/* Backlog answer controls — secondary, collapsed by default */}
            {coverage.mined > coverage.answered && (
              <details style={{ marginBottom: 12 }}>
                <summary style={{
                  fontSize: 13, color: BRAND.sub, cursor: "pointer", userSelect: "none",
                  padding: "6px 0", listStyle: "none", display: "flex", alignItems: "center", gap: 6,
                }}>
                  <span style={{ fontSize: 11, color: BRAND.sub }}>&#9654;</span>
                  Clear answer backlog ({(coverage.mined - coverage.answered).toLocaleString()} already-mined questions without answers)
                </summary>
                <div style={{ background: BRAND.bg, borderRadius: 8, padding: "12px 16px", marginTop: 6 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                    <span style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600 }}>Backlog batch size:</span>
                    {ANSWER_BATCH_OPTIONS.map((n) => (
                      <button
                        key={n}
                        onClick={() => setAnswerBatchSize(n)}
                        style={{
                          padding: "4px 12px", borderRadius: 6, fontSize: 13, cursor: "pointer",
                          fontWeight: answerBatchSize === n ? 700 : 400,
                          background: answerBatchSize === n ? BRAND.navy : "#fff",
                          color: answerBatchSize === n ? "#fff" : BRAND.navyText,
                          border: `1px solid ${answerBatchSize === n ? BRAND.navy : BRAND.border}`,
                        }}
                      >
                        {n}
                      </button>
                    ))}
                    <Button onClick={handleGenerateBatch} disabled={generatingBatch} variant="ghost" style={{ fontSize: 13 }}>
                      {generatingBatch ? "Generating…" : `Generate answers for ${answerBatchSize} backlog questions`}
                    </Button>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: BRAND.sub }}>
                    {answerEstimate
                      ? <>Answering {answerBatchSize} questions ~ <strong>{fmt$(answerEstimate.answer_cost_usd)}</strong> (estimate, {answerEstimate.model})</>
                      : <Loading label="Loading estimate…" />}
                    {coverage.mined - coverage.answered > 100 && answerEstimate && (
                      <> · All {(coverage.mined - coverage.answered).toLocaleString()} backlog ~ <strong>{fmt$(answerEstimate.answer_cost_usd / answerBatchSize * (coverage.mined - coverage.answered))}</strong> (estimate)</>
                    )}
                  </p>
                </div>
              </details>
            )}

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {coverage.answered > 0 && (
                <Button
                  onClick={handlePublishWordPress}
                  disabled={publishing}
                  variant="ghost"
                  style={{ whiteSpace: "nowrap", fontSize: 13 }}
                >
                  {publishing
                    ? "Publishing…"
                    : `Publish FAQ to website (${coverage.answered} answered)`}
                </Button>
              )}
            </div>

            {publishResult && (
              <p style={{ margin: "10px 0 0", fontSize: 13, color: BRAND.ink }}>
                FAQ page {publishResult.action} on WordPress ({publishResult.published} Q&amp;As).{" "}
                <a
                  href={publishResult.page_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: BRAND.red, fontWeight: 600 }}
                >
                  View page
                </a>
              </p>
            )}
          </>
        ) : (
          <p style={{ margin: 0, fontSize: 14, color: BRAND.sub }}>Coverage unavailable.</p>
        )}
        {actionMsg && (
          <p style={{ margin: "10px 0 0", fontSize: 13, color: BRAND.sub }}>{actionMsg}</p>
        )}
      </Card>

      {/* Filters */}
      <Card style={{ marginBottom: 20, padding: "14px 20px" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value)}
            placeholder="Search questions…"
            style={{ ...inputStyle, flex: 1, minWidth: 180 }}
          />
          <select
            value={answeredFilter}
            onChange={(e) => handleAnsweredChange(e.target.value as "all" | "yes" | "no")}
            style={{ ...inputStyle, minWidth: 130 }}
          >
            <option value="all">All</option>
            <option value="yes">Answered</option>
            <option value="no">Unanswered</option>
          </select>
          <span style={{ fontSize: 13, color: BRAND.sub, whiteSpace: "nowrap" }}>
            {total} question{total !== 1 ? "s" : ""}
          </span>
        </div>
      </Card>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && items.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            {filter
              ? `No questions found for "${filter}".`
              : coverage && coverage.mined === 0 && coverage.uncovered_nodes > 0
              ? `Use the "Mine questions now" button above to generate FAQ questions from your content.`
              : "No questions found. Use \"Mine more\" to generate from content."}
          </p>
        </Card>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          {/* Email action bar — shown when any answered item is on the page */}
          {answeredItems.length > 0 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 12, marginBottom: 12,
              padding: "10px 16px", background: BRAND.bg, borderRadius: 8,
              border: `1px solid ${BRAND.border}`,
            }}>
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}>
                <input
                  type="checkbox"
                  checked={allAnsweredChecked}
                  ref={(el) => { if (el) el.indeterminate = someAnsweredChecked && !allAnsweredChecked; }}
                  onChange={toggleAll}
                  style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer" }}
                />
                <span style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>
                  Select answered Q&As
                </span>
              </label>
              {someAnsweredChecked && (
                <Button
                  style={{ fontSize: 13, padding: "6px 14px", marginLeft: "auto" }}
                  onClick={() => setEmailModalBody(buildFaqEmailBody())}
                >
                  Email selected ({checkedIds.size})
                </Button>
              )}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {items.map((item) => (
              <Card
                key={item.id}
                style={{ borderLeft: `4px solid ${checkedIds.has(item.id) ? BRAND.red : item.status === "answered" ? BRAND.navy : BRAND.border}` }}
              >
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  {/* Checkbox — only shown for answered items */}
                  {item.answer ? (
                    <input
                      type="checkbox"
                      checked={checkedIds.has(item.id)}
                      onChange={() => toggleCheck(item.id)}
                      style={{ width: 15, height: 15, accentColor: BRAND.red, cursor: "pointer", flexShrink: 0, marginTop: 3 }}
                    />
                  ) : (
                    <div style={{ width: 15, flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: "0 0 6px", fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>
                      {item.question}
                    </p>
                    {item.answer ? (
                      <p style={{ margin: "0 0 8px", color: BRAND.ink, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                        {renderAnswer(item.answer)}
                      </p>
                    ) : (
                      <p style={{ margin: "0 0 8px", color: BRAND.sub, fontSize: 13, fontStyle: "italic" }}>
                        No answer yet.
                      </p>
                    )}
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: BRAND.red, fontSize: 13, textDecoration: "none", fontWeight: 600 }}
                    >
                      ▶ {item.video_title} @ {mmss(item.start)}
                    </a>
                  </div>
                  {item.status !== "answered" && (
                    <Button
                      variant="ghost"
                      disabled={answeringId === item.id}
                      onClick={() => handleAnswerOne(item)}
                      style={{ fontSize: 12, padding: "6px 12px", whiteSpace: "nowrap", flexShrink: 0 }}
                    >
                      {answeringId === item.id ? "Generating…" : "Generate answer"}
                    </Button>
                  )}
                </div>
              </Card>
            ))}
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

      {/* Email compose modal — opened when user clicks "Email selected" */}
      {emailModalBody !== null && (
        <ComposeEmailModal
          initialBody={emailModalBody}
          onClose={() => setEmailModalBody(null)}
        />
      )}

      </> /* end answered tab */}
    </main>
  );
}
