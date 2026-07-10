import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, FONT, Button, Card, PageTitle, inputStyle, Loading, ErrorMsg, StatusPill, StatCard, TierCard, SectionLabel } from "../ui";

// ── Types ─────────────────────────────────────────────────────────────────────

type ProposalStatus =
  | "draft"
  | "sent"
  | "viewed"
  | "accepted"
  | "declined"
  | "superseded"
  | "revision_requested";

interface ProposalEvent {
  id: number;
  proposal_id: number;
  event_type: string;
  occurred_at: string | null;
  actor_email: string | null;
  metadata: Record<string, unknown> | null;
}

interface ProposalRow {
  id: number;
  tenant_id: number;
  customer_id: number;
  property_id: number;
  template_id: number | null;
  root_id: number | null;
  parent_id: number | null;
  version_number: number;
  title: string;
  quote_snapshot: Record<string, unknown> | null;
  selected_tier: string | null;
  selected_options: unknown[] | null;
  status: ProposalStatus;
  accept_token: string | null;
  accepted_by_name: string | null;
  accepted_at: string | null;
  consent_electronic: boolean | null;
  signed_pdf_gcs: string | null;
  created_by: string | null;
  sent_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  // Joined fields from list endpoint
  customer_name?: string;
  property_address?: string;
  // Events — present only on detail fetch
  events?: ProposalEvent[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(status: ProposalStatus) {
  return <StatusPill status={status} />;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function usd(n: number | string | undefined): string {
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (v == null || isNaN(v as number)) return "—";
  return (v as number).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0 });
}

const STATUS_TABS: Array<{ key: ProposalStatus | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "draft", label: "Draft" },
  { key: "sent", label: "Sent" },
  { key: "viewed", label: "Viewed" },
  { key: "accepted", label: "Accepted" },
  { key: "declined", label: "Declined" },
  { key: "revision_requested", label: "Revision req." },
];

// ── Main page ─────────────────────────────────────────────────────────────────

export function Proposals() {
  const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">("all");
  const [proposals, setProposals] = useState<ProposalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail drawer
  const [drawerProposal, setDrawerProposal] = useState<ProposalRow | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);

  // Per-row action state
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [revisingId, setRevisingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // PDF loading (fetch → blob → objectURL so auth header is included)
  const [pdfLoadingId, setPdfLoadingId] = useState<number | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  // Copy-to-clipboard feedback
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  function loadProposals(status?: ProposalStatus | "all") {
    setLoading(true);
    setError(null);
    const s = status ?? statusFilter;
    const qs = s !== "all" ? `?status=${s}&limit=100` : "?limit=100";
    apiFetch(`/quoting/proposals${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ProposalRow[]) => setProposals(data ?? []))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadProposals();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleTabChange(tab: ProposalStatus | "all") {
    setStatusFilter(tab);
    setDrawerProposal(null);
    loadProposals(tab);
  }

  async function openDrawer(proposal: ProposalRow) {
    setDrawerProposal(proposal);
    setDrawerError(null);
    setDrawerLoading(true);
    try {
      const r = await apiFetch(`/quoting/proposals/${proposal.id}`);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data: ProposalRow = await r.json();
      setDrawerProposal(data);
    } catch (e: unknown) {
      setDrawerError(e instanceof Error ? e.message : String(e));
    } finally {
      setDrawerLoading(false);
    }
  }

  async function handleSend(id: number) {
    setSendingId(id);
    setActionError(null);
    try {
      const r = await apiFetch(`/quoting/proposals/${id}/send`, { method: "POST", body: JSON.stringify({}) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: ProposalRow = await r.json();
      setProposals((prev) => prev.map((p) => p.id === id ? { ...p, ...updated } : p));
      if (drawerProposal?.id === id) setDrawerProposal((prev) => prev ? { ...prev, ...updated } : prev);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setSendingId(null);
    }
  }

  async function handleRevise(id: number) {
    setRevisingId(id);
    setActionError(null);
    try {
      const r = await apiFetch(`/quoting/proposals/${id}/revise`, { method: "POST", body: JSON.stringify({}) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      // Revise creates a new proposal; reload the full list
      loadProposals();
      setDrawerProposal(null);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setRevisingId(null);
    }
  }

  async function handleViewPdf(id: number) {
    setPdfLoadingId(id);
    setPdfError(null);
    try {
      const r = await apiFetch(`/quoting/proposals/${id}/pdf`);
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      // Revoke after a short delay so the new tab has time to load
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (e: unknown) {
      setPdfError(e instanceof Error ? e.message : String(e));
    } finally {
      setPdfLoadingId(null);
    }
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedToken(text);
      setTimeout(() => setCopiedToken(null), 2000);
    } catch {
      // Fallback for environments without clipboard API
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopiedToken(text);
      setTimeout(() => setCopiedToken(null), 2000);
    }
  }

  function tabStyle(tab: ProposalStatus | "all"): React.CSSProperties {
    const active = statusFilter === tab;
    return {
      padding: "8px 16px",
      border: "none",
      borderBottom: active ? `2px solid ${BRAND.red}` : "2px solid transparent",
      background: "none",
      cursor: "pointer",
      fontSize: 13,
      fontWeight: active ? 700 : 500,
      color: active ? BRAND.navyText : BRAND.sub,
      marginBottom: -1,
      whiteSpace: "nowrap" as const,
    };
  }

  const countByStatus = (s: ProposalStatus | "all") => {
    if (s === "all") return proposals.length;
    return proposals.filter((p) => p.status === s).length;
  };

  function renderRowActions(proposal: ProposalRow) {
    const id = proposal.id;
    return (
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Button variant="ghost" onClick={() => openDrawer(proposal)} style={{ fontSize: 12, padding: "5px 10px" }}>
          Details
        </Button>
        {(proposal.status === "draft") && (
          <Button
            onClick={() => handleSend(id)}
            disabled={sendingId === id}
            style={{ fontSize: 12, padding: "5px 10px" }}
          >
            {sendingId === id ? "Sending…" : "Send"}
          </Button>
        )}
        {(proposal.status === "sent" || proposal.status === "viewed" || proposal.status === "revision_requested") && (
          <Button
            variant="ghost"
            onClick={() => handleRevise(id)}
            disabled={revisingId === id}
            style={{ fontSize: 12, padding: "5px 10px" }}
          >
            {revisingId === id ? "Revising…" : "Revise"}
          </Button>
        )}
        <Button
          variant="ghost"
          onClick={() => handleViewPdf(id)}
          disabled={pdfLoadingId === id}
          style={{ fontSize: 12, padding: "5px 10px" }}
        >
          {pdfLoadingId === id ? "Loading…" : "PDF"}
        </Button>
      </div>
    );
  }

  // ── Drawer ─────────────────────────────────────────────────────────────────

  function renderDrawer() {
    if (!drawerProposal) return null;
    const p = drawerProposal;
    const snap = (p.quote_snapshot ?? {}) as Record<string, unknown>;
    const tiers = (snap.tiers ?? {}) as Record<string, { label?: string; total?: number }>;
    const depositPolicy = (snap.deposit_policy ?? {}) as { amount?: number | string; mode?: string; value?: number; instructions?: string };
    const events = (p.events ?? []) as ProposalEvent[];

    const acceptUrl = p.accept_token
      ? `${window.location.origin}/p/${p.accept_token}`
      : null;

    return (
      <div style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: 420,
        height: "100vh",
        background: "#fff",
        borderLeft: `1px solid ${BRAND.border}`,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.10)",
        overflowY: "auto",
        zIndex: 200,
        fontFamily: FONT,
      }}>
        <div style={{ padding: "20px 24px", borderBottom: `1px solid ${BRAND.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>Proposal #{p.id}</div>
          <button onClick={() => setDrawerProposal(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>

        {drawerLoading && <div style={{ padding: 24 }}><Loading label="Loading proposal…" /></div>}
        {drawerError && <div style={{ padding: 24 }}><ErrorMsg>Error: {drawerError}</ErrorMsg></div>}

        {!drawerLoading && (
          <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
            {/* Status + meta */}
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                {statusBadge(p.status)}
                <span style={{ fontSize: 11, color: BRAND.sub, background: BRAND.bg, padding: "2px 8px", borderRadius: 10, fontWeight: 600 }}>v{p.version_number}</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 700, color: BRAND.navyText, marginBottom: 6 }}>{p.title}</div>
              {p.customer_name && (
                <div style={{ fontSize: 13, color: BRAND.sub, display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 14 }}>👤</span>{p.customer_name}
                </div>
              )}
              {p.property_address && (
                <div style={{ fontSize: 13, color: BRAND.sub, display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
                  <span style={{ fontSize: 14 }}>📍</span>{p.property_address}
                </div>
              )}
              <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 8, display: "flex", gap: 10, flexWrap: "wrap" }}>
                <span>Created {fmtDate(p.created_at)}</span>
                {p.sent_at && <span>Sent {fmtDate(p.sent_at)}</span>}
                {p.accepted_at && <span>Accepted {fmtDate(p.accepted_at)}</span>}
              </div>
            </div>

            {/* Quote snapshot summary — tier cards */}
            {Object.keys(tiers).length > 0 && (
              <div>
                <SectionLabel>Pricing Tiers</SectionLabel>
                <div style={{ display: "flex", gap: 8 }}>
                  {Object.entries(tiers).map(([key, tier]) => (
                    <TierCard
                      key={key}
                      label={tier.label ?? key}
                      value={usd(tier.total)}
                      recommended={key === "better"}
                      selected={p.selected_tier === key}
                    />
                  ))}
                </div>
                {p.selected_tier && (
                  <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 6 }}>
                    Customer selected: <strong style={{ color: BRAND.navyText, textTransform: "capitalize" }}>{p.selected_tier}</strong>
                  </div>
                )}
              </div>
            )}

            {/* Deposit */}
            {(depositPolicy.amount != null || depositPolicy.value != null) && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Deposit</div>
                <div style={{ fontSize: 13, color: BRAND.ink }}>
                  {depositPolicy.mode === "percent"
                    ? `${depositPolicy.value}%`
                    : depositPolicy.mode === "fixed"
                    ? usd(depositPolicy.amount)
                    : "None"}
                  {depositPolicy.instructions && (
                    <div style={{ color: BRAND.sub, marginTop: 4 }}>{depositPolicy.instructions}</div>
                  )}
                </div>
              </div>
            )}

            {/* Accepted by */}
            {p.accepted_by_name && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Accepted by</div>
                <div style={{ fontSize: 13, color: BRAND.ink }}>
                  {p.accepted_by_name} · {fmtDateTime(p.accepted_at)}
                </div>
              </div>
            )}

            {/* Accept token + URL */}
            {p.accept_token && p.status !== "accepted" && p.status !== "declined" && p.status !== "superseded" && acceptUrl && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>Accept link</div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    readOnly
                    value={acceptUrl}
                    style={{ ...inputStyle, flex: 1, fontSize: 11, padding: "6px 8px", color: BRAND.sub }}
                    onClick={(e) => (e.target as HTMLInputElement).select()}
                  />
                  <Button variant="ghost" onClick={() => copyToClipboard(acceptUrl)} style={{ fontSize: 11, padding: "6px 10px", whiteSpace: "nowrap" }}>
                    {copiedToken === acceptUrl ? "Copied!" : "Copy"}
                  </Button>
                </div>
              </div>
            )}

            {/* Actions */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {actionError && <ErrorMsg>Error: {actionError}</ErrorMsg>}
              {pdfError && <ErrorMsg>PDF error: {pdfError}</ErrorMsg>}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {p.status === "draft" && (
                  <Button onClick={() => handleSend(p.id)} disabled={sendingId === p.id} style={{ fontSize: 13 }}>
                    {sendingId === p.id ? "Sending…" : "Send to customer"}
                  </Button>
                )}
                {(p.status === "sent" || p.status === "viewed" || p.status === "revision_requested") && (
                  <Button variant="ghost" onClick={() => handleRevise(p.id)} disabled={revisingId === p.id} style={{ fontSize: 13 }}>
                    {revisingId === p.id ? "Revising…" : "Create revision"}
                  </Button>
                )}
                <Button variant="ghost" onClick={() => handleViewPdf(p.id)} disabled={pdfLoadingId === p.id} style={{ fontSize: 13 }}>
                  {pdfLoadingId === p.id ? "Loading PDF…" : "View PDF"}
                </Button>
              </div>
            </div>

            {/* Event history — timeline */}
            {events.length > 0 && (
              <div>
                <SectionLabel>Timeline</SectionLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 0, position: "relative" }}>
                  {/* vertical line */}
                  <div style={{
                    position: "absolute", left: 7, top: 8, bottom: 8, width: 2,
                    background: BRAND.border, borderRadius: 2,
                  }} />
                  {events.map((ev, idx) => (
                    <div key={ev.id} style={{
                      display: "flex", gap: 14, padding: "8px 0",
                      borderBottom: idx < events.length - 1 ? `1px solid ${BRAND.border}` : "none",
                      fontSize: 12, position: "relative",
                    }}>
                      <div style={{
                        width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
                        background: "#fff", border: `2px solid ${BRAND.navy}`, marginTop: 1,
                        zIndex: 1,
                      }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: BRAND.navyText, textTransform: "capitalize" }}>
                          {ev.event_type.replace(/_/g, " ")}
                        </div>
                        {ev.actor_email && (
                          <div style={{ color: BRAND.sub, fontSize: 11 }}>{ev.actor_email}</div>
                        )}
                      </div>
                      <div style={{ color: BRAND.sub, whiteSpace: "nowrap", fontSize: 11, paddingTop: 2 }}>
                        {fmtDateTime(ev.occurred_at)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  // KPI computations
  const allProposals = proposals; // we compute from the full in-memory list
  const kpiDraft    = allProposals.filter((p) => p.status === "draft").length;
  const kpiSent     = allProposals.filter((p) => p.status === "sent" || p.status === "viewed").length;
  const kpiAccepted = allProposals.filter((p) => p.status === "accepted").length;
  const kpiPipeline = (() => {
    let total = 0;
    for (const p of allProposals) {
      const snap = (p.quote_snapshot ?? {}) as Record<string, unknown>;
      const tiers = (snap.tiers ?? {}) as Record<string, { total?: number }>;
      const betterTier = tiers["better"] ?? tiers["good"] ?? null;
      if (betterTier?.total) total += betterTier.total;
    }
    return total;
  })();

  return (
    <main style={{ maxWidth: 960, fontFamily: FONT }}>
      <PageTitle>Proposals</PageTitle>

      {/* KPI row */}
      {allProposals.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
          <StatCard label="Draft" value={kpiDraft} />
          <StatCard label="Sent / Viewed" value={kpiSent} />
          <StatCard label="Accepted" value={kpiAccepted} />
          <StatCard
            label="Pipeline"
            value={kpiPipeline > 0 ? kpiPipeline.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0 }) : "—"}
            sub="Better-tier total"
          />
        </div>
      )}

      {/* Status tabs */}
      <div style={{ display: "flex", borderBottom: `1px solid ${BRAND.border}`, marginBottom: 20, overflowX: "auto" }}>
        {STATUS_TABS.map(({ key, label }) => {
          const count = countByStatus(key);
          return (
            <button key={key} style={tabStyle(key)} onClick={() => handleTabChange(key)}>
              {label}
              {count > 0 && (
                <span style={{
                  marginLeft: 6, fontSize: 11, fontWeight: 700, padding: "1px 6px",
                  borderRadius: 10, background: "#eef1f5", color: BRAND.sub,
                }}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {actionError && <ErrorMsg>Action error: {actionError}</ErrorMsg>}
      {pdfError && <ErrorMsg>PDF error: {pdfError}</ErrorMsg>}

      {loading && <Loading label="Loading proposals…" />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && proposals.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            {statusFilter !== "all"
              ? `No ${statusFilter} proposals.`
              : "No proposals yet. Build a quote in the Quoting tab and create a draft."}
          </p>
        </Card>
      )}

      {!loading && !error && proposals.length > 0 && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>#</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Customer</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Title</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Status</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Ver.</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Created</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Sent</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {proposals.map((p) => (
                <tr
                  key={p.id}
                  style={{
                    borderBottom: `1px solid ${BRAND.border}`,
                    background: drawerProposal?.id === p.id ? "#f7f8fa" : undefined,
                  }}
                >
                  <td style={{ padding: "10px 16px", color: BRAND.sub, fontVariantNumeric: "tabular-nums" }}>{p.id}</td>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: BRAND.navyText }}>
                    {p.customer_name ?? `#${p.customer_id}`}
                    {p.property_address && (
                      <div style={{ fontWeight: 400, fontSize: 12, color: BRAND.sub }}>{p.property_address}</div>
                    )}
                  </td>
                  <td style={{ padding: "10px 16px", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.title}
                  </td>
                  <td style={{ padding: "10px 16px" }}>{statusBadge(p.status)}</td>
                  <td style={{ padding: "10px 16px", color: BRAND.sub }}>v{p.version_number}</td>
                  <td style={{ padding: "10px 16px", color: BRAND.sub, whiteSpace: "nowrap" }}>{fmtDate(p.created_at)}</td>
                  <td style={{ padding: "10px 16px", color: BRAND.sub, whiteSpace: "nowrap" }}>{fmtDate(p.sent_at)}</td>
                  <td style={{ padding: "10px 16px" }}>{renderRowActions(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Backdrop when drawer is open */}
      {drawerProposal && (
        <div
          onClick={() => setDrawerProposal(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 199,
          }}
        />
      )}

      {renderDrawer()}
    </main>
  );
}
