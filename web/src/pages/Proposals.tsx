import { useEffect, useState } from "react";
import {
  apiFetch,
  listQuotes,
  listQuotingCustomers,
  getQuotingCustomer,
  createProposalFromQuote,
  type QuoteListItem,
  type QuotingCustomer,
  type QuotingProperty,
} from "../api";
import { BRAND, FONT, Button, Card, PageTitle, inputStyle, Loading, ErrorMsg, StatusPill, StatCard, TierCard, SectionLabel } from "../ui";
import { ProposalBuilder } from "./ProposalBuilder";

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
  estimate_id?: number | null;
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
  amount?: number | string | null;
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

function signPublicUrl(): string {
  const envUrl = import.meta.env.VITE_SIGN_PUBLIC_URL as string | undefined;
  return (envUrl || "https://sign.perkinsroofing.net").replace(/\/$/, "");
}

function usd(n: number | string | undefined): string {
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (v == null || isNaN(v as number)) return "—";
  return (v as number).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0 });
}

const proposalIconButtonStyle: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 7,
  border: `1px solid ${BRAND.border}`,
  background: "#fff",
  color: BRAND.navyText,
  cursor: "pointer",
  fontFamily: FONT,
  fontSize: 15,
  fontWeight: 700,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 0,
};

function propertyLabel(p: QuotingProperty): string {
  return `${p.street}, ${p.city} ${p.state}${p.zip ? ` ${p.zip}` : ""}`;
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

type ProposalWorkspaceTab = "proposals" | "legacy";

// ── Main page ─────────────────────────────────────────────────────────────────

export function Proposals() {
  const [workspaceTab, setWorkspaceTab] = useState<ProposalWorkspaceTab>("proposals");
  const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">("all");
  const [proposals, setProposals] = useState<ProposalRow[]>([]);
  const [proposalTotal, setProposalTotal] = useState(0);
  const [statusCounts, setStatusCounts] = useState<Partial<Record<ProposalStatus, number>>>({});
  const [proposalPage, setProposalPage] = useState(1);
  const proposalPageSize = 100;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Embedded create drawer
  const [createOpen, setCreateOpen] = useState(false);

  // Detail drawer
  const [drawerProposal, setDrawerProposal] = useState<ProposalRow | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [editingProposal, setEditingProposal] = useState<ProposalRow | null>(null);
  const [editForm, setEditForm] = useState({ title: "", total: "", deposit: "", squares: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Legacy quotes tab
  const [legacyQuotes, setLegacyQuotes] = useState<QuoteListItem[]>([]);
  const [legacyLoading, setLegacyLoading] = useState(false);
  const [legacyError, setLegacyError] = useState<string | null>(null);
  const [legacySearch, setLegacySearch] = useState("");
  const [legacyTotal, setLegacyTotal] = useState<number | null>(null);
  const [importQuote, setImportQuote] = useState<QuoteListItem | null>(null);
  const [importCustomers, setImportCustomers] = useState<QuotingCustomer[]>([]);
  const [importProperties, setImportProperties] = useState<QuotingProperty[]>([]);
  const [importCustomerId, setImportCustomerId] = useState<number | "">("");
  const [importPropertyId, setImportPropertyId] = useState<number | "">("");
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // Per-row action state
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [revisingId, setRevisingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // PDF loading (fetch → blob → objectURL so auth header is included)
  const [pdfLoadingId, setPdfLoadingId] = useState<number | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  // Copy-to-clipboard feedback
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  function loadProposals(status?: ProposalStatus | "all", page = proposalPage) {
    setLoading(true);
    setError(null);
    const s = status ?? statusFilter;
    const qs = s !== "all"
      ? `?status=${s}&limit=${proposalPageSize}&page=${page}`
      : `?limit=${proposalPageSize}&page=${page}`;
    apiFetch(`/quoting/proposals${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ProposalRow[] | { items?: ProposalRow[]; total?: number; status_counts?: Partial<Record<ProposalStatus, number>> }) => {
        if (Array.isArray(data)) {
          setProposals(data);
          setProposalTotal(data.length);
        } else {
          setProposals(Array.isArray(data.items) ? data.items : []);
          setProposalTotal(typeof data.total === "number" ? data.total : 0);
          setStatusCounts(data.status_counts ?? {});
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadProposals();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function loadLegacyQuotes(search = legacySearch) {
    setLegacyLoading(true);
    setLegacyError(null);
    listQuotes({
      limit: 100,
      ...(search.trim() ? { search: search.trim() } : {}),
    })
      .then((data) => {
        setLegacyQuotes(Array.isArray(data.items) ? data.items : []);
        setLegacyTotal(typeof data.total === "number" ? data.total : null);
      })
      .catch((e: unknown) => setLegacyError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLegacyLoading(false));
  }

  useEffect(() => {
    if (workspaceTab === "legacy" && legacyQuotes.length === 0 && !legacyLoading) {
      loadLegacyQuotes();
    }
  }, [workspaceTab]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleTabChange(tab: ProposalStatus | "all") {
    setStatusFilter(tab);
    setProposalPage(1);
    setDrawerProposal(null);
    setEditingProposal(null);
    loadProposals(tab, 1);
  }

  function handleWorkspaceTabChange(tab: ProposalWorkspaceTab) {
    setWorkspaceTab(tab);
    setDrawerProposal(null);
    setEditingProposal(null);
    setCreateOpen(false);
    if (tab === "legacy" && legacyQuotes.length === 0) loadLegacyQuotes();
  }

  function openCreateDrawer() {
    setDrawerProposal(null);
    setEditingProposal(null);
    setCreateOpen(true);
  }

  function closeCreateDrawer() {
    setCreateOpen(false);
  }

  function handleProposalCreated() {
    closeCreateDrawer();
    setWorkspaceTab("proposals");
    setStatusFilter("all");
    loadProposals("all");
  }

  function openImportQuote(q: QuoteListItem) {
    setImportQuote(q);
    setImportError(null);
    setImportCustomerId("");
    setImportPropertyId("");
    setImportProperties([]);
    if (importCustomers.length === 0) {
      setImportLoading(true);
      listQuotingCustomers({ limit: 200 })
        .then((rows) => setImportCustomers(rows))
        .catch((e: unknown) => setImportError(e instanceof Error ? e.message : String(e)))
        .finally(() => setImportLoading(false));
    }
  }

  async function handleImportCustomerChange(id: number | "") {
    setImportCustomerId(id);
    setImportPropertyId("");
    setImportProperties([]);
    setImportError(null);
    if (!id) return;
    setImportLoading(true);
    try {
      const detail = await getQuotingCustomer(id);
      setImportProperties(detail.properties ?? []);
      if (detail.properties?.length === 1) setImportPropertyId(detail.properties[0].id);
    } catch (e: unknown) {
      setImportError(e instanceof Error ? e.message : String(e));
    } finally {
      setImportLoading(false);
    }
  }

  async function handleCreateFromLegacyQuote() {
    if (!importQuote) return;
    setImportLoading(true);
    setImportError(null);
    try {
      await createProposalFromQuote(importQuote.contract_id, {
        ...(importCustomerId ? { customer_id: importCustomerId as number } : {}),
        ...(importPropertyId ? { property_id: importPropertyId as number } : {}),
        title: importQuote.ContractName ?? `Knowify quote ${importQuote.contract_id}`,
      });
      setImportQuote(null);
      setWorkspaceTab("proposals");
      setStatusFilter("all");
      loadProposals("all");
    } catch (e: unknown) {
      setImportError(e instanceof Error ? e.message : String(e));
    } finally {
      setImportLoading(false);
    }
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

  function openEditProposal(proposal: ProposalRow) {
    const snap = (proposal.quote_snapshot ?? {}) as Record<string, unknown>;
    const tiers = (snap.tiers ?? {}) as Record<string, { total?: number }>;
    const legacy = tiers.legacy ?? {};
    const selectedTier = proposal.selected_tier && tiers[proposal.selected_tier]
      ? proposal.selected_tier
      : tiers.legacy
        ? "legacy"
        : tiers.good
          ? "good"
          : tiers.better
            ? "better"
            : tiers.best
              ? "best"
              : "";
    const selectedTierTotal = selectedTier ? tiers[selectedTier]?.total : undefined;
    const dp = (snap.deposit_policy ?? {}) as { amount?: number | string; value?: number | string };
    const total = Number(snap.total ?? selectedTierTotal ?? legacy.total ?? proposal.amount ?? 0);
    setEditingProposal(proposal);
    setEditError(null);
    setEditForm({
      title: proposal.title ?? "",
      total: Number.isFinite(total) && total > 0 ? String(total) : "",
      deposit: dp.amount != null ? String(dp.amount) : dp.value != null ? String(dp.value) : "",
      squares: snap.num_squares != null ? String(snap.num_squares) : "",
    });
    setCreateOpen(false);
    setDrawerProposal(null);
  }

  async function handleSaveEditProposal() {
    if (!editingProposal) return;
    setEditSaving(true);
    setEditError(null);
    try {
      const baseSnap = (editingProposal.quote_snapshot ?? {}) as Record<string, unknown>;
      const total = Number(editForm.total || 0);
      const deposit = editForm.deposit === "" ? null : Number(editForm.deposit);
      const squares = editForm.squares === "" ? baseSnap.num_squares : Number(editForm.squares);
      let linkedEstimateId = editingProposal.estimate_id ?? null;
      let revisedEstimateResult = (baseSnap.estimate_result ?? null) as Record<string, unknown> | null;
      let revisedEstimateInput = (baseSnap.estimate_input ?? null) as Record<string, unknown> | null;
      if (editingProposal.estimate_id && revisedEstimateInput && revisedEstimateResult) {
        const oldProjectTotal = Number(revisedEstimateResult.project_total ?? total);
        const oldProfit = Number(revisedEstimateResult.profit_dollars ?? 0);
        const estimateBody: Record<string, unknown> = {
          ...revisedEstimateInput,
          num_squares: Number(squares ?? revisedEstimateInput.num_squares ?? 0),
          parent_estimate_id: editingProposal.estimate_id,
          source_proposal_id: editingProposal.id,
        };
        if (Number.isFinite(total) && total > 0 && Number.isFinite(oldProjectTotal)) {
          estimateBody.profit_mode = "flat";
          estimateBody.flat_profit_dollars = Math.max(0, oldProfit + (total - oldProjectTotal));
        }
        const estRes = await apiFetch("/estimator/quote", {
          method: "POST",
          body: JSON.stringify(estimateBody),
        });
        if (!estRes.ok) {
          const err = await estRes.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `${estRes.status} ${estRes.statusText}`);
        }
        revisedEstimateResult = await estRes.json() as Record<string, unknown>;
        revisedEstimateInput = estimateBody;
        linkedEstimateId = Number((revisedEstimateResult as Record<string, unknown>).estimate_id ?? editingProposal.estimate_id);
      }
      const effectiveTotal = Number(revisedEstimateResult?.project_total ?? total);
      const existingTiers = (baseSnap.tiers ?? {}) as Record<string, unknown>;
      const currentLegacy = (existingTiers.legacy ?? {}) as Record<string, unknown>;
      const primaryTierKey = currentLegacy.total != null
        ? "legacy"
        : editingProposal.selected_tier && existingTiers[editingProposal.selected_tier]
          ? editingProposal.selected_tier
          : existingTiers.good
            ? "good"
            : existingTiers.better
              ? "better"
              : existingTiers.best
                ? "best"
                : "good";
      const currentPrimaryTier = (existingTiers[primaryTierKey] ?? {}) as Record<string, unknown>;
      const tiers = {
        ...existingTiers,
        [primaryTierKey]: {
          ...currentPrimaryTier,
          label: (currentPrimaryTier.label as string | undefined)
            ?? (primaryTierKey === "legacy" ? "Knowify Quote" : primaryTierKey),
          description: (currentPrimaryTier.description as string | undefined)
            ?? (editForm.title || editingProposal.title),
          total: effectiveTotal,
        },
      };
      const snapshot = {
        ...baseSnap,
        total: effectiveTotal,
        estimate_id: linkedEstimateId,
        estimate_input: revisedEstimateInput ?? baseSnap.estimate_input,
        estimate_result: revisedEstimateResult ?? baseSnap.estimate_result,
        num_squares: squares,
        tiers,
        deposit_policy: {
          ...((baseSnap.deposit_policy ?? {}) as Record<string, unknown>),
          mode: deposit && deposit > 0 ? "fixed" : "none",
          value: deposit ?? 0,
          amount: deposit ?? 0,
        },
      };
      const r = await apiFetch(`/quoting/proposals/${editingProposal.id}`, {
        method: "PUT",
        body: JSON.stringify({ title: editForm.title, quote_snapshot: snapshot, estimate_id: linkedEstimateId }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: ProposalRow = await r.json();
      setProposals((prev) => prev.map((p) => p.id === updated.id ? { ...p, ...updated, amount: effectiveTotal } : p));
      setEditingProposal(null);
      loadProposals(statusFilter, proposalPage);
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : String(e));
    } finally {
      setEditSaving(false);
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
      const revised: ProposalRow = await r.json();
      setWorkspaceTab("proposals");
      setStatusFilter("draft");
      setProposalPage(1);
      loadProposals("draft", 1);
      void openDrawer(revised);
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

  function workspaceTabStyle(tab: ProposalWorkspaceTab): React.CSSProperties {
    const active = workspaceTab === tab;
    return {
      padding: "9px 18px",
      border: `1px solid ${active ? BRAND.navy : BRAND.border}`,
      borderRadius: 999,
      background: active ? BRAND.navy : "#fff",
      color: active ? "#fff" : BRAND.sub,
      cursor: "pointer",
      fontSize: 13,
      fontWeight: 700,
      whiteSpace: "nowrap" as const,
    };
  }

  const countByStatus = (s: ProposalStatus | "all") => {
    if (s === "all") {
      return Object.values(statusCounts).reduce((sum, n) => sum + (Number(n) || 0), 0) || proposalTotal;
    }
    return statusCounts[s] ?? 0;
  };

  function renderRowActions(proposal: ProposalRow) {
    const id = proposal.id;
    return (
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        <button
          type="button"
          title="Details"
          aria-label="Details"
          onClick={() => openDrawer(proposal)}
          style={proposalIconButtonStyle}
        >
          ⓘ
        </button>
        {(proposal.status === "draft") && (
          <>
            <button
              type="button"
              title="Edit draft"
              aria-label="Edit draft"
              onClick={() => openEditProposal(proposal)}
              style={proposalIconButtonStyle}
            >
              ✎
            </button>
            <button
              type="button"
              title="Send"
              aria-label="Send"
              onClick={() => handleSend(id)}
              disabled={sendingId === id}
              style={proposalIconButtonStyle}
            >
              ✉
            </button>
          </>
        )}
        {(proposal.status === "sent" || proposal.status === "viewed" || proposal.status === "revision_requested") && (
          <button
            type="button"
            title="Create editable revision"
            aria-label="Create editable revision"
            onClick={() => handleRevise(id)}
            disabled={revisingId === id}
            style={proposalIconButtonStyle}
          >
            ↻
          </button>
        )}
        <button
          type="button"
          title="PDF"
          aria-label="PDF"
          onClick={() => handleViewPdf(id)}
          disabled={pdfLoadingId === id}
          style={{ ...proposalIconButtonStyle, fontSize: 10, fontWeight: 800 }}
        >
          PDF
        </button>
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
      ? `${signPublicUrl()}/p/${p.accept_token}`
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
                  <>
                    <Button variant="ghost" onClick={() => openEditProposal(p)} style={{ fontSize: 13 }}>
                      Edit draft
                    </Button>
                    <Button onClick={() => handleSend(p.id)} disabled={sendingId === p.id} style={{ fontSize: 13 }}>
                      {sendingId === p.id ? "Sending…" : "Send to customer"}
                    </Button>
                  </>
                )}
                {(p.status === "sent" || p.status === "viewed" || p.status === "revision_requested") && (
                  <Button variant="ghost" onClick={() => handleRevise(p.id)} disabled={revisingId === p.id} style={{ fontSize: 13 }}>
                    {revisingId === p.id ? "Creating…" : "Create editable revision"}
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

  function renderCreateDrawer() {
    if (!createOpen) return null;
    return (
      <div style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: "min(760px, 96vw)",
        height: "100vh",
        background: "#fff",
        borderLeft: `1px solid ${BRAND.border}`,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
        overflowY: "auto",
        zIndex: 200,
        fontFamily: FONT,
      }}>
        <div style={{ padding: "18px 24px", borderBottom: `1px solid ${BRAND.border}`, display: "flex", justifyContent: "space-between", alignItems: "center", position: "sticky", top: 0, background: "#fff", zIndex: 1 }}>
          <div>
            <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 16 }}>New Proposal</div>
            <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>Create a contract without leaving the Proposals workspace.</div>
          </div>
          <button onClick={closeCreateDrawer} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 22, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: 20 }}>
          <ProposalBuilder
            embedded
            onCreated={handleProposalCreated}
            onCancel={closeCreateDrawer}
          />
        </div>
      </div>
    );
  }

  function renderEditDrawer() {
    if (!editingProposal) return null;
    return (
      <div style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: "min(560px, 96vw)",
        height: "100vh",
        background: "#fff",
        borderLeft: `1px solid ${BRAND.border}`,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
        overflowY: "auto",
        zIndex: 200,
        fontFamily: FONT,
      }}>
        <div style={{ padding: "18px 24px", borderBottom: `1px solid ${BRAND.border}`, display: "flex", justifyContent: "space-between", alignItems: "center", position: "sticky", top: 0, background: "#fff", zIndex: 1 }}>
          <div>
            <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 16 }}>Edit Proposal #{editingProposal.id}</div>
            <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>Draft revision v{editingProposal.version_number}</div>
            {editingProposal.estimate_id && (
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                Linked estimate #{editingProposal.estimate_id}; pricing changes should be made as an estimate revision.
              </div>
            )}
          </div>
          <button onClick={() => setEditingProposal(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 22, color: BRAND.sub, lineHeight: 1 }}>×</button>
        </div>
        <div style={{ padding: 20, display: "grid", gap: 14 }}>
          <div>
            <SectionLabel>Title</SectionLabel>
            <input style={{ ...inputStyle, width: "100%" }} value={editForm.title} onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))} />
          </div>
          <div>
            <SectionLabel>Total</SectionLabel>
            <input type="number" step="0.01" min="0" style={{ ...inputStyle, width: "100%" }} value={editForm.total} onChange={(e) => setEditForm((f) => ({ ...f, total: e.target.value }))} />
          </div>
          <div>
            <SectionLabel>Deposit</SectionLabel>
            <input type="number" step="0.01" min="0" style={{ ...inputStyle, width: "100%" }} value={editForm.deposit} onChange={(e) => setEditForm((f) => ({ ...f, deposit: e.target.value }))} />
          </div>
          <div>
            <SectionLabel>Squares</SectionLabel>
            <input type="number" step="0.1" min="0" style={{ ...inputStyle, width: "100%" }} value={editForm.squares} onChange={(e) => setEditForm((f) => ({ ...f, squares: e.target.value }))} />
          </div>
          {editError && <ErrorMsg>Error: {editError}</ErrorMsg>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <Button variant="ghost" onClick={() => setEditingProposal(null)} disabled={editSaving}>Cancel</Button>
            <Button onClick={handleSaveEditProposal} disabled={editSaving || !editForm.title.trim()}>
              {editSaving ? "Saving…" : "Save draft"}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  function renderLegacyQuotes() {
    return (
      <div>
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>Legacy Quotes</div>
              <div style={{ fontSize: 12, color: BRAND.sub, marginTop: 2 }}>
                Knowify quote records that can be migrated into native Perkins proposals.
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                value={legacySearch}
                onChange={(e) => setLegacySearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") loadLegacyQuotes();
                }}
                placeholder="Search legacy quotes…"
                style={{ ...inputStyle, width: 220, fontSize: 13 }}
              />
              <Button variant="ghost" onClick={() => loadLegacyQuotes()} disabled={legacyLoading} style={{ fontSize: 13 }}>
                {legacyLoading ? "Loading…" : "Search"}
              </Button>
              <Button variant="ghost" onClick={() => loadLegacyQuotes("")} disabled={legacyLoading} style={{ fontSize: 13 }}>
                Refresh
              </Button>
            </div>
          </div>
        </Card>

        {legacyError && <ErrorMsg>Legacy quotes error: {legacyError}</ErrorMsg>}
        {legacyLoading && <Loading label="Loading legacy quotes…" />}

        {!legacyLoading && !legacyError && legacyQuotes.length === 0 && (
          <Card>
            <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
              No legacy quotes found.
            </p>
          </Card>
        )}

        {!legacyLoading && !legacyError && legacyQuotes.length > 0 && (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "10px 16px", borderBottom: `1px solid ${BRAND.border}`, fontSize: 12, color: BRAND.sub }}>
              Showing {legacyQuotes.length}{legacyTotal != null ? ` of ${legacyTotal}` : ""} legacy quotes.
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Contract</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Customer</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>State</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Current Sum</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Created</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Expires</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Signed</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {legacyQuotes.map((q) => (
                  <tr key={q.contract_id} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 16px", fontWeight: 600, color: BRAND.navyText, maxWidth: 260 }}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {q.ContractName ?? q.contract_id}
                      </div>
                      <div style={{ fontWeight: 400, fontSize: 12, color: BRAND.sub }}>{q.contract_id}</div>
                    </td>
                    <td style={{ padding: "10px 16px", color: BRAND.ink }}>
                      {q.ContactName ?? q.ClientId ?? "—"}
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ fontSize: 12, color: BRAND.sub, background: BRAND.bg, padding: "3px 8px", borderRadius: 999, fontWeight: 700 }}>
                        {q.BusinessState ?? q.ContractType ?? "—"}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", color: BRAND.navyText, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                      {usd(q.CurrentContractSum ?? q.OriginalContractSum ?? undefined)}
                    </td>
                    <td style={{ padding: "10px 16px", color: BRAND.sub, whiteSpace: "nowrap" }}>{fmtDate(q.DateCreated)}</td>
                    <td style={{ padding: "10px 16px", color: BRAND.sub, whiteSpace: "nowrap" }}>{fmtDate(q.ExpirationDate)}</td>
                    <td style={{ padding: "10px 16px", color: BRAND.sub }}>{q.IsSigned ? "Yes" : "No"}</td>
                    <td style={{ padding: "10px 16px" }}>
                      <Button
                        variant="ghost"
                        onClick={() => openImportQuote(q)}
                        style={{ fontSize: 12, padding: "5px 10px", whiteSpace: "nowrap" }}
                      >
                        Migrate → Native
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    );
  }

  function renderImportDialog() {
    if (!importQuote) return null;
    return (
      <div style={{
        position: "fixed",
        inset: 0,
        zIndex: 350,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}>
        <Card style={{ width: "min(560px, 96vw)", maxHeight: "90vh", overflowY: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 16 }}>
            <div>
              <div style={{ fontWeight: 800, color: BRAND.navyText, fontSize: 16 }}>Import legacy quote</div>
              <div style={{ color: BRAND.sub, fontSize: 12, marginTop: 3 }}>
                {importQuote.ContractName ?? importQuote.contract_id}
              </div>
            </div>
            <button
              onClick={() => setImportQuote(null)}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 22, color: BRAND.sub, lineHeight: 1 }}
              aria-label="Close import dialog"
            >
              ×
            </button>
          </div>

          <p style={{ margin: "0 0 14px", color: BRAND.sub, fontSize: 13, lineHeight: 1.5 }}>
            This will create a native draft proposal from the Knowify quote. Customer and property
            are auto-matched from the Knowify ClientId/project address when possible; choose them
            manually only if auto-match fails.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", marginBottom: 4 }}>Customer</label>
              <select
                value={importCustomerId}
                onChange={(e) => void handleImportCustomerChange(e.target.value ? Number(e.target.value) : "")}
                style={{ ...inputStyle, width: "100%" }}
              >
                <option value="">— Auto-match customer, or select —</option>
                {importCustomers.map((c) => (
                  <option key={c.id} value={c.id}>{c.display_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", marginBottom: 4 }}>Property</label>
              <select
                value={importPropertyId}
                onChange={(e) => setImportPropertyId(e.target.value ? Number(e.target.value) : "")}
                disabled={!importCustomerId || importProperties.length === 0}
                style={{ ...inputStyle, width: "100%" }}
              >
                <option value="">— Let backend match, or select property —</option>
                {importProperties.map((p) => (
                  <option key={p.id} value={p.id}>{propertyLabel(p)}</option>
                ))}
              </select>
            </div>
          </div>

          {importError && <div style={{ marginTop: 12 }}><ErrorMsg>{importError}</ErrorMsg></div>}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 }}>
            <Button variant="ghost" onClick={() => setImportQuote(null)} disabled={importLoading}>Cancel</Button>
            <Button onClick={handleCreateFromLegacyQuote} disabled={importLoading}>
              {importLoading ? "Migrating…" : "Migrate to native proposal"}
            </Button>
          </div>
        </Card>
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
    <main style={{ maxWidth: 1240, fontFamily: FONT }}>
      <PageTitle
        right={
          <Button onClick={openCreateDrawer} style={{ fontSize: 13 }}>
            + New Proposal
          </Button>
        }
      >
        Proposals
      </PageTitle>

      <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
        <button style={workspaceTabStyle("proposals")} onClick={() => handleWorkspaceTabChange("proposals")}>
          Proposals
        </button>
        <button style={workspaceTabStyle("legacy")} onClick={() => handleWorkspaceTabChange("legacy")}>
          Legacy Quotes
        </button>
      </div>

      {workspaceTab === "proposals" && (
        <>
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
        <Card style={{ padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 1040, borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: 150 }}>Proposal</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: 430 }}>Customer / Property</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, textAlign: "right" }}>Amount</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Created</th>
                <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600 }}>Sent</th>
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
                  <td style={{ padding: "12px 16px", color: BRAND.sub, fontVariantNumeric: "tabular-nums", verticalAlign: "top" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 800, color: BRAND.navyText }}>#{p.id}</span>
                      <span style={{ fontSize: 12, color: BRAND.sub }}>v{p.version_number}</span>
                    </div>
                    <div style={{ marginTop: 7 }}>{statusBadge(p.status)}</div>
                    <div title={p.title} style={{ marginTop: 6, fontSize: 12, color: BRAND.sub, maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.title}
                    </div>
                    {renderRowActions(p)}
                  </td>
                  <td style={{ padding: "12px 16px", fontWeight: 600, color: BRAND.navyText, verticalAlign: "top", lineHeight: 1.45 }}>
                    {p.customer_name ?? `#${p.customer_id}`}
                    {p.property_address && (
                      <div style={{ fontWeight: 400, fontSize: 13, color: BRAND.sub, marginTop: 3, maxWidth: 300, whiteSpace: "normal" }}>{p.property_address}</div>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", color: BRAND.navyText, fontWeight: 700, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", verticalAlign: "top" }}>
                    {usd(p.amount ?? 0)}
                  </td>
                  <td style={{ padding: "12px 16px", color: BRAND.sub, whiteSpace: "nowrap", verticalAlign: "top" }}>{fmtDate(p.created_at)}</td>
                  <td style={{ padding: "12px 16px", color: BRAND.sub, whiteSpace: "nowrap", verticalAlign: "top" }}>{fmtDate(p.sent_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "12px 16px", borderTop: `1px solid ${BRAND.border}`, fontSize: 13, color: BRAND.sub }}>
            <div>
              Showing {(proposalPage - 1) * proposalPageSize + 1}–{Math.min(proposalPage * proposalPageSize, proposalTotal)} of {proposalTotal}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Button
                variant="ghost"
                disabled={proposalPage <= 1 || loading}
                onClick={() => {
                  const next = Math.max(1, proposalPage - 1);
                  setProposalPage(next);
                  loadProposals(statusFilter, next);
                }}
                style={{ fontSize: 12, padding: "5px 10px" }}
              >
                Previous
              </Button>
              <Button
                variant="ghost"
                disabled={proposalPage * proposalPageSize >= proposalTotal || loading}
                onClick={() => {
                  const next = proposalPage + 1;
                  setProposalPage(next);
                  loadProposals(statusFilter, next);
                }}
                style={{ fontSize: 12, padding: "5px 10px" }}
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
        </>
      )}

      {workspaceTab === "legacy" && renderLegacyQuotes()}

      {/* Backdrop when drawer is open */}
      {(drawerProposal || createOpen || editingProposal) && (
        <div
          onClick={() => {
            setDrawerProposal(null);
            setCreateOpen(false);
            setEditingProposal(null);
          }}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 199,
          }}
        />
      )}

      {renderDrawer()}
      {renderCreateDrawer()}
      {renderEditDrawer()}
      {renderImportDialog()}
    </main>
  );
}
