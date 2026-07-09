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
  listTenants as _listTenants,
  provisionTenant as _provisionTenant,
  getTenantStatus as _getTenantStatus,
  resendTenantInvite as _resendInvite,
  offboardTenant as _offboardTenant,
  type Tenant,
  type TenantStatus,
} from "../api";


// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function statusBadge(status: Tenant["status"]) {
  if (status === "active") return <Badge tone="green">Active</Badge>;
  if (status === "provisioning") return <Badge tone="amber">Provisioning…</Badge>;
  if (status === "provisioning_failed") return <Badge tone="amber">Failed</Badge>;
  if (status === "offboarded") return <Badge tone="gray">Offboarded</Badge>;
  return <Badge tone="gray">{status}</Badge>;
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

// ── Provision form ────────────────────────────────────────────────────────────

interface ProvisionFormProps {
  onProvisioned: (id: number) => void;
  onCancel: () => void;
}

function ProvisionForm({ onProvisioned, onCancel }: ProvisionFormProps) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-derive slug from name (lowercase, hyphens)
  function handleNameChange(val: string) {
    setName(val);
    if (!slug || slug === slugify(name)) {
      setSlug(slugify(val));
    }
  }

  function slugify(s: string) {
    return s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !slug.trim() || !adminEmail.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await _provisionTenant({
        name: name.trim(),
        slug: slug.trim(),
        admin_email: adminEmail.trim(),
      });
      onProvisioned(result.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 20 }}>
      <div
        style={{
          fontSize: 15,
          fontWeight: 700,
          color: BRAND.navyText,
          marginBottom: 16,
        }}
      >
        New Tenant
      </div>
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <FieldLabel>Tenant name</FieldLabel>
            <input
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="Acme Roofing Co."
              required
              disabled={busy}
              style={{ ...inputStyle, width: "100%", fontSize: 13 }}
            />
          </div>
          <div>
            <FieldLabel>Slug (URL-safe, unique)</FieldLabel>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
              placeholder="acme-roofing"
              required
              pattern="^[a-z0-9][a-z0-9-]{1,}$"
              title="Lowercase letters, digits, and hyphens only"
              disabled={busy}
              style={{ ...inputStyle, width: "100%", fontSize: 13, fontFamily: "monospace" }}
            />
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <FieldLabel>Admin email</FieldLabel>
          <input
            type="email"
            value={adminEmail}
            onChange={(e) => setAdminEmail(e.target.value)}
            placeholder="admin@acmeroofing.com"
            required
            disabled={busy}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
          />
          <p style={{ margin: "4px 0 0", fontSize: 11, color: BRAND.sub }}>
            An invite link will be sent to this address. The user becomes the tenant admin.
          </p>
        </div>

        {error && <ErrorMsg>Error: {error}</ErrorMsg>}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !name.trim() || !slug.trim() || !adminEmail.trim()}>
            {busy ? "Provisioning…" : "Provision tenant"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ── Provisioning status poller ────────────────────────────────────────────────

interface StatusPollerProps {
  tenantId: number;
  tenantName: string;
  onDone: () => void;
}

function StatusPoller({ tenantId, tenantName, onDone }: StatusPollerProps) {
  const [status, setStatus] = useState<TenantStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const s = await _getTenantStatus(tenantId);
      setStatus(s);
      if (s.status === "active" || s.status === "provisioning_failed") {
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
  }, [tenantId]);

  useEffect(() => {
    poll();
    intervalRef.current = setInterval(poll, 3000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll]);

  function copyLink(link: string) {
    navigator.clipboard?.writeText(link).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Card style={{ marginTop: 20, borderLeft: `4px solid ${BRAND.navy}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: BRAND.navyText }}>
          Provisioning: {tenantName}
        </span>
        {status && statusBadge(status.status as Tenant["status"])}
        {!status && !error && <Loading label="Polling…" />}
      </div>

      {error && <ErrorMsg>{error}</ErrorMsg>}

      {status?.status === "active" && (
        <div>
          <p style={{ margin: "0 0 10px", fontSize: 13, color: BRAND.ink }}>
            Tenant provisioned. Invite sent to admin email.
          </p>
          {status.invite_link && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                readOnly
                value={status.invite_link}
                style={{
                  ...inputStyle,
                  flex: 1,
                  fontSize: 12,
                  fontFamily: "monospace",
                  background: BRAND.bg,
                }}
              />
              <Button
                variant="ghost"
                style={{ fontSize: 12, padding: "7px 14px", whiteSpace: "nowrap" }}
                onClick={() => copyLink(status.invite_link!)}
              >
                {copied ? "Copied!" : "Copy link"}
              </Button>
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <Button onClick={onDone} style={{ fontSize: 13 }}>
              Done
            </Button>
          </div>
        </div>
      )}

      {status?.status === "provisioning_failed" && (
        <div>
          <p style={{ margin: "0 0 8px", fontSize: 13, color: BRAND.red }}>
            Provisioning failed.{status.error ? ` Server: ${status.error}` : ""}
          </p>
          <p style={{ margin: "0 0 14px", fontSize: 12, color: BRAND.sub }}>
            The tenant row has been marked failed. You can retry by creating a new tenant or clean
            up the partial record manually in the database.
          </p>
          <Button variant="ghost" onClick={onDone} style={{ fontSize: 13 }}>
            Dismiss
          </Button>
        </div>
      )}

      {status?.status === "provisioning" && (
        <p style={{ margin: 0, fontSize: 13, color: BRAND.sub }}>
          GCIP tenant creation and invite in progress. This usually completes in under 30 seconds.
        </p>
      )}
    </Card>
  );
}

// ── Offboard confirm modal ────────────────────────────────────────────────────

interface OffboardModalProps {
  tenant: Tenant;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}

function OffboardModal({ tenant, onConfirm, onCancel, busy }: OffboardModalProps) {
  const [typed, setTyped] = useState("");
  const confirmed = typed === tenant.name;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        fontFamily: FONT,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: 28,
          maxWidth: 440,
          width: "90%",
          boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: 16, color: BRAND.red }}>
          Offboard tenant?
        </h3>
        <p style={{ margin: "0 0 8px", fontSize: 13, color: BRAND.ink, lineHeight: 1.6 }}>
          This will permanently offboard <strong>{tenant.name}</strong>. All tenant data,
          users, and GCIP configuration will be deleted. This cannot be undone.
        </p>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: BRAND.ink }}>
          Type the tenant name to confirm:
        </p>
        <input
          type="text"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={tenant.name}
          autoFocus
          disabled={busy}
          style={{ ...inputStyle, width: "100%", fontSize: 13, marginBottom: 20 }}
        />
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={onConfirm}
            disabled={!confirmed || busy}
          >
            {busy ? "Offboarding…" : "Offboard tenant"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Tenant row ────────────────────────────────────────────────────────────────

interface TenantRowProps {
  tenant: Tenant;
  onResendInvite: (id: number) => void;
  onOffboard: (tenant: Tenant) => void;
  resendingId: number | null;
}

function TenantRow({ tenant, onResendInvite, onOffboard, resendingId }: TenantRowProps) {
  const isOffboarded = tenant.status === "offboarded";
  const resending = resendingId === tenant.id;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 140px 120px 80px 180px",
        alignItems: "center",
        gap: 12,
        padding: "12px 16px",
        borderBottom: `1px solid ${BRAND.border}`,
        background: isOffboarded ? BRAND.bg : "#fff",
        opacity: isOffboarded ? 0.65 : 1,
      }}
    >
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: BRAND.navyText }}>
          {tenant.name}
        </div>
        <div style={{ fontSize: 11, color: BRAND.sub, fontFamily: "monospace", marginTop: 2 }}>
          {tenant.slug}
        </div>
        <div style={{ fontSize: 11, color: BRAND.sub, marginTop: 1 }}>
          {tenant.admin_email}
        </div>
      </div>

      <div>{statusBadge(tenant.status)}</div>

      <div style={{ fontSize: 12, color: BRAND.sub }}>
        {tenant.mau != null ? `${tenant.mau} MAU` : "—"}
      </div>

      <div style={{ fontSize: 12, color: BRAND.sub }}>{fmtDate(tenant.created_at ?? "")}</div>

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        {!isOffboarded && tenant.status === "active" && (
          <Button
            variant="ghost"
            style={{ fontSize: 12, padding: "5px 12px" }}
            disabled={resending}
            onClick={() => onResendInvite(tenant.id)}
          >
            {resending ? "Sending…" : "Resend invite"}
          </Button>
        )}
        {!isOffboarded && (
          <Button
            variant="danger"
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => onOffboard(tenant)}
          >
            Offboard
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Main TenantsConfig ────────────────────────────────────────────────────────

export function TenantsConfig() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // New tenant form visibility
  const [showForm, setShowForm] = useState(false);

  // After provisioning: show status poller for this tenant id
  const [pollingId, setPollingId] = useState<number | null>(null);
  const [pollingName, setPollingName] = useState<string>("");

  // Resend invite state
  const [resendingId, setResendingId] = useState<number | null>(null);
  const [resendError, setResendError] = useState<string | null>(null);
  const [resendSuccess, setResendSuccess] = useState<number | null>(null);

  // Offboard modal state
  const [offboardTarget, setOffboardTarget] = useState<Tenant | null>(null);
  const [offboarding, setOffboarding] = useState(false);
  const [offboardError, setOffboardError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    _listTenants()
      .then((ts) => {
        // Sort: active first, then by created_at desc
        const sorted = [...ts].sort((a, b) => {
          if (a.status === "offboarded" && b.status !== "offboarded") return 1;
          if (b.status === "offboarded" && a.status !== "offboarded") return -1;
          return new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime();
        });
        setTenants(sorted);
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function handleProvisioned(id: number) {
    // Find the tenant name from the form (we don't have it yet — reload after a tick
    // to get it, then start polling)
    const formName =
      (document.querySelector<HTMLInputElement>('input[placeholder="Acme Roofing Co."]')
        ?.value) ?? "New tenant";
    setShowForm(false);
    setPollingId(id);
    setPollingName(formName);
    load();
  }

  function handlePollDone() {
    setPollingId(null);
    setPollingName("");
    load();
  }

  async function handleResendInvite(id: number) {
    setResendingId(id);
    setResendError(null);
    setResendSuccess(null);
    try {
      await _resendInvite(id);
      setResendSuccess(id);
      setTimeout(() => setResendSuccess(null), 3000);
    } catch (err) {
      setResendError(err instanceof Error ? err.message : String(err));
    } finally {
      setResendingId(null);
    }
  }

  async function handleOffboardConfirm() {
    if (!offboardTarget) return;
    setOffboarding(true);
    setOffboardError(null);
    try {
      await _offboardTenant(offboardTarget.id);
      setOffboardTarget(null);
      load();
    } catch (err) {
      setOffboardError(err instanceof Error ? err.message : String(err));
      setOffboardTarget(null);
    } finally {
      setOffboarding(false);
    }
  }

  return (
    <div style={{ fontFamily: FONT }}>
      {/* Offboard confirmation modal */}
      {offboardTarget && (
        <OffboardModal
          tenant={offboardTarget}
          onConfirm={handleOffboardConfirm}
          onCancel={() => setOffboardTarget(null)}
          busy={offboarding}
        />
      )}

      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <div>
          <span style={{ fontSize: 16, fontWeight: 700, color: BRAND.navyText }}>
            Tenant Provisioning
          </span>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: BRAND.sub }}>
            Platform admin only. Each row is a licensee tenant on this platform instance.
          </p>
        </div>
        {!showForm && pollingId === null && (
          <Button onClick={() => setShowForm(true)} style={{ fontSize: 13 }}>
            + New Tenant
          </Button>
        )}
      </div>

      {/* Global error banners */}
      {offboardError && <ErrorMsg>Offboard error: {offboardError}</ErrorMsg>}
      {resendError && <ErrorMsg>Resend error: {resendError}</ErrorMsg>}
      {resendSuccess && (
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
          Invite resent.
        </div>
      )}

      {/* New tenant form */}
      {showForm && (
        <ProvisionForm
          onProvisioned={handleProvisioned}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Provisioning status poller */}
      {pollingId !== null && (
        <StatusPoller
          tenantId={pollingId}
          tenantName={pollingName}
          onDone={handlePollDone}
        />
      )}

      {/* Tenant list */}
      <Card style={{ marginTop: 20, padding: 0, overflow: "hidden" }}>
        {/* Column headers */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 140px 120px 80px 180px",
            gap: 12,
            padding: "10px 16px",
            background: BRAND.bg,
            borderBottom: `1px solid ${BRAND.border}`,
          }}
        >
          {["Tenant", "Status", "MAU", "Created", "Actions"].map((h) => (
            <div
              key={h}
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: BRAND.sub,
                textTransform: "uppercase",
                letterSpacing: 0.4,
                ...(h === "Actions" ? { textAlign: "right" } : {}),
              }}
            >
              {h}
            </div>
          ))}
        </div>

        {loading && (
          <div style={{ padding: 24 }}>
            <Loading label="Loading tenants…" />
          </div>
        )}
        {loadError && (
          <div style={{ padding: 16 }}>
            <ErrorMsg>Failed to load tenants: {loadError}</ErrorMsg>
            <Button variant="ghost" style={{ fontSize: 13, marginTop: 8 }} onClick={load}>
              Retry
            </Button>
          </div>
        )}

        {!loading && !loadError && tenants.length === 0 && (
          <div style={{ padding: "24px 16px", fontSize: 13, color: BRAND.sub }}>
            No tenants provisioned yet. Click "+ New Tenant" to onboard the first licensee.
          </div>
        )}

        {tenants.map((t) => (
          <TenantRow
            key={t.id}
            tenant={t}
            onResendInvite={handleResendInvite}
            onOffboard={setOffboardTarget}
            resendingId={resendingId}
          />
        ))}
      </Card>

      {/* F6-runtime note */}
      <div
        style={{
          marginTop: 16,
          padding: "10px 14px",
          borderRadius: 8,
          background: "#fffbf0",
          border: `1px solid #fcd34d`,
          fontSize: 12,
          color: "#92400e",
        }}
      >
        <strong>F6-runtime:</strong> Tenant provisioning requires live GCIP multi-tenancy. The POST
        endpoint creates a GCIP tenant and sends an invite via Firebase Admin SDK. Currently only
        Perkins (tenant 1) exists — this UI is built but exercised in full only after a second
        licensee is ready to onboard.
      </div>

    </div>
  );
}
// Re-export types so AdminConfig / others can import them without duplication
export type { Tenant, TenantStatus };
