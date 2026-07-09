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
import {
  listSsoProviders as _listSsoProviders,
  addSsoProvider as _addSsoProvider,
  deleteSsoProvider as _deleteSsoProvider,
  type SsoProvider,
} from "../api";

// ── Types ─────────────────────────────────────────────────────────────────────

export type IdpType = "saml" | "oidc";


interface SamlPayload {
  type: "saml";
  display_name: string;
  entity_id: string;
  sso_url: string;
  certificate_pem: string;
}

interface OidcPayload {
  type: "oidc";
  display_name: string;
  issuer_url: string;
  client_id: string;
  client_secret: string;
}

type AddProviderPayload = SamlPayload | OidcPayload;


// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
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

function HelpText({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ margin: "3px 0 0", fontSize: 11, color: BRAND.sub, lineHeight: 1.4 }}>
      {children}
    </p>
  );
}

// ── Delete confirm modal ──────────────────────────────────────────────────────

interface DeleteModalProps {
  provider: SsoProvider;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}

function DeleteModal({ provider, onConfirm, onCancel, busy }: DeleteModalProps) {
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
          maxWidth: 400,
          width: "90%",
          boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: 16, color: BRAND.navyText }}>
          Remove identity provider?
        </h3>
        <p style={{ margin: "0 0 20px", fontSize: 13, color: BRAND.ink, lineHeight: 1.6 }}>
          Remove <strong>{provider.display_name}</strong> ({provider.type.toUpperCase()})? Users
          currently signed in via this IdP will be unable to sign in again until a replacement is
          configured. Email/password sign-in remains available.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Removing…" : "Remove"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Provider row ──────────────────────────────────────────────────────────────

interface ProviderRowProps {
  provider: SsoProvider;
  onDelete: (provider: SsoProvider) => void;
}

function ProviderRow({ provider, onDelete }: ProviderRowProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "12px 16px",
        borderBottom: `1px solid ${BRAND.border}`,
        background: "#fff",
      }}
    >
      <Badge tone={provider.type === "saml" ? "blue" : "green"}>
        {provider.type.toUpperCase()}
      </Badge>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: BRAND.navyText }}>
          {provider.display_name}
        </div>
        <div style={{ fontSize: 11, color: BRAND.sub, fontFamily: "monospace", marginTop: 2 }}>
          {provider.type === "saml"
            ? `Entity ID: ${provider.entity_id ?? "—"}`
            : `Issuer: ${provider.issuer_url ?? "—"}  |  Client ID: ${provider.client_id ?? "—"}`}
        </div>
      </div>
      <div style={{ fontSize: 11, color: BRAND.sub, whiteSpace: "nowrap" }}>
        Added {fmtDate(provider.created_at ?? "")}
      </div>
      <Button
        variant="danger"
        style={{ fontSize: 12, padding: "5px 12px" }}
        onClick={() => onDelete(provider)}
      >
        Remove
      </Button>
    </div>
  );
}

// ── Add provider form ─────────────────────────────────────────────────────────

interface AddProviderFormProps {
  onAdded: () => void;
  onCancel: () => void;
}

function AddProviderForm({ onAdded, onCancel }: AddProviderFormProps) {
  const [type, setType] = useState<IdpType>("saml");
  const [displayName, setDisplayName] = useState("");

  // SAML fields
  const [entityId, setEntityId] = useState("");
  const [ssoUrl, setSsoUrl] = useState("");
  const [certPem, setCertPem] = useState("");

  // OIDC fields
  const [issuerUrl, setIssuerUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function isValid(): boolean {
    if (!displayName.trim()) return false;
    if (type === "saml") return !!(entityId.trim() && ssoUrl.trim() && certPem.trim());
    return !!(issuerUrl.trim() && clientId.trim() && clientSecret.trim());
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValid()) return;
    setBusy(true);
    setError(null);
    try {
      const payload: AddProviderPayload =
        type === "saml"
          ? {
              type: "saml",
              display_name: displayName.trim(),
              entity_id: entityId.trim(),
              sso_url: ssoUrl.trim(),
              certificate_pem: certPem.trim(),
            }
          : {
              type: "oidc",
              display_name: displayName.trim(),
              issuer_url: issuerUrl.trim(),
              client_id: clientId.trim(),
              client_secret: clientSecret.trim(),
            };
      await _addSsoProvider(payload);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 16 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: BRAND.navyText, marginBottom: 16 }}>
        Add Identity Provider
      </div>
      <form onSubmit={handleSubmit}>
        {/* Type selector */}
        <div style={{ marginBottom: 16 }}>
          <FieldLabel>Protocol</FieldLabel>
          <div style={{ display: "flex", gap: 8 }}>
            {(["saml", "oidc"] as IdpType[]).map((t) => {
              const active = type === t;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setType(t)}
                  style={{
                    padding: "7px 22px",
                    fontSize: 13,
                    fontWeight: 600,
                    border: `1px solid ${active ? BRAND.navy : BRAND.border}`,
                    borderRadius: 6,
                    cursor: "pointer",
                    background: active ? BRAND.navy : "#fff",
                    color: active ? "#fff" : BRAND.sub,
                    fontFamily: FONT,
                    transition: "background 0.1s, color 0.1s",
                  }}
                >
                  {t.toUpperCase()}
                </button>
              );
            })}
          </div>
          <HelpText>
            {type === "saml"
              ? "SAML 2.0 — for Microsoft Entra, Okta, Google Workspace SAML, and similar enterprise IdPs."
              : "OpenID Connect — for Okta OIDC, Auth0, Google, and OIDC-compliant providers."}
          </HelpText>
        </div>

        {/* Display name (common) */}
        <div style={{ marginBottom: 14 }}>
          <FieldLabel>Display name</FieldLabel>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={type === "saml" ? "Contoso Entra SAML" : "Okta OIDC"}
            required
            disabled={busy}
            style={{ ...inputStyle, width: "100%", fontSize: 13 }}
          />
          <HelpText>Shown on the sign-in button. Keep it short and recognizable.</HelpText>
        </div>

        {/* SAML fields */}
        {type === "saml" && (
          <>
            <div style={{ marginBottom: 14 }}>
              <FieldLabel>Entity ID (Issuer)</FieldLabel>
              <input
                type="url"
                value={entityId}
                onChange={(e) => setEntityId(e.target.value)}
                placeholder="https://sts.windows.net/tenant-id/"
                required
                disabled={busy}
                style={{ ...inputStyle, width: "100%", fontSize: 13 }}
              />
            </div>
            <div style={{ marginBottom: 14 }}>
              <FieldLabel>SSO URL (IdP Single Sign-On URL)</FieldLabel>
              <input
                type="url"
                value={ssoUrl}
                onChange={(e) => setSsoUrl(e.target.value)}
                placeholder="https://login.microsoftonline.com/tenant-id/saml2"
                required
                disabled={busy}
                style={{ ...inputStyle, width: "100%", fontSize: 13 }}
              />
            </div>
            <div style={{ marginBottom: 14 }}>
              <FieldLabel>X.509 Certificate (PEM)</FieldLabel>
              <textarea
                value={certPem}
                onChange={(e) => setCertPem(e.target.value)}
                placeholder={"-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"}
                required
                rows={6}
                disabled={busy}
                style={{
                  ...inputStyle,
                  width: "100%",
                  fontSize: 12,
                  fontFamily: "monospace",
                  resize: "vertical",
                }}
              />
              <HelpText>
                Download from your IdP metadata XML. Include the full PEM block including header
                and footer lines.
              </HelpText>
            </div>
          </>
        )}

        {/* OIDC fields */}
        {type === "oidc" && (
          <>
            <div style={{ marginBottom: 14 }}>
              <FieldLabel>Issuer URL</FieldLabel>
              <input
                type="url"
                value={issuerUrl}
                onChange={(e) => setIssuerUrl(e.target.value)}
                placeholder="https://your-org.okta.com"
                required
                disabled={busy}
                style={{ ...inputStyle, width: "100%", fontSize: 13 }}
              />
              <HelpText>
                The base URL of the OIDC provider. GCIP will fetch the discovery document at
                {" "}<code>/.well-known/openid-configuration</code>.
              </HelpText>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 14 }}>
              <div>
                <FieldLabel>Client ID</FieldLabel>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="0oa1b2c3d4e5f6g7h8i9"
                  required
                  disabled={busy}
                  style={{ ...inputStyle, width: "100%", fontSize: 13 }}
                />
              </div>
              <div>
                <FieldLabel>Client secret</FieldLabel>
                <input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder="••••••••••••"
                  required
                  disabled={busy}
                  autoComplete="new-password"
                  style={{ ...inputStyle, width: "100%", fontSize: 13 }}
                />
                <HelpText>Stored encrypted in GCIP. Never logged or returned by the API.</HelpText>
              </div>
            </div>
          </>
        )}

        {error && <ErrorMsg>Error: {error}</ErrorMsg>}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !isValid()}>
            {busy ? "Adding…" : "Add provider"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ── Main SsoPanel ─────────────────────────────────────────────────────────────

export function SsoPanel() {
  const [providers, setProviders] = useState<SsoProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SsoProvider | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    _listSsoProviders()
      .then(setProviders)
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await _deleteSsoProvider(deleteTarget.idp_id);
      setDeleteTarget(null);
      load();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }

  function handleAdded() {
    setShowForm(false);
    load();
  }

  return (
    <div style={{ fontFamily: FONT, marginTop: 24 }}>
      {/* Delete confirm modal */}
      {deleteTarget && (
        <DeleteModal
          provider={deleteTarget}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
          busy={deleting}
        />
      )}

      {/* Section header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: BRAND.navyText }}>
            Single Sign-On (SSO)
          </div>
          <p style={{ margin: "3px 0 0", fontSize: 12, color: BRAND.sub }}>
            Configure SAML or OIDC identity providers for this tenant. Users can then sign in via
            their corporate IdP. Billing: $0.015/MAU for SSO users (GCIP).
          </p>
        </div>
        {!showForm && (
          <Button onClick={() => setShowForm(true)} style={{ fontSize: 13 }}>
            + Add Identity Provider
          </Button>
        )}
      </div>

      {deleteError && <ErrorMsg>Remove error: {deleteError}</ErrorMsg>}

      {/* Provider list */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        {/* Column headers */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "10px 16px",
            background: BRAND.bg,
            borderBottom: `1px solid ${BRAND.border}`,
          }}
        >
          {["Type", "Provider", "Added", ""].map((h, i) => (
            <div
              key={i}
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: BRAND.sub,
                textTransform: "uppercase",
                letterSpacing: 0.4,
                flex: i === 1 ? 1 : undefined,
                minWidth: i === 0 ? 64 : undefined,
              }}
            >
              {h}
            </div>
          ))}
        </div>

        {loading && (
          <div style={{ padding: 20 }}>
            <Loading label="Loading providers…" />
          </div>
        )}
        {loadError && (
          <div style={{ padding: 16 }}>
            <ErrorMsg>Failed to load providers: {loadError}</ErrorMsg>
            <Button variant="ghost" style={{ fontSize: 13, marginTop: 8 }} onClick={load}>
              Retry
            </Button>
          </div>
        )}

        {!loading && !loadError && providers.length === 0 && (
          <div style={{ padding: "20px 16px", fontSize: 13, color: BRAND.sub }}>
            No identity providers configured. Click "+ Add Identity Provider" to set up SAML or
            OIDC for this tenant.
          </div>
        )}

        {providers.map((p) => (
          <ProviderRow key={p.idp_id} provider={p} onDelete={setDeleteTarget} />
        ))}
      </Card>

      {/* Add provider form */}
      {showForm && (
        <AddProviderForm onAdded={handleAdded} onCancel={() => setShowForm(false)} />
      )}

      {/* F6-runtime note */}
      <div
        style={{
          marginTop: 14,
          padding: "10px 14px",
          borderRadius: 8,
          background: "#fffbf0",
          border: `1px solid #fcd34d`,
          fontSize: 12,
          color: "#92400e",
        }}
      >
        <strong>F6-runtime:</strong> SSO configuration requires a live GCIP multi-tenant setup.
        Adding a provider calls the GCIP Admin SDK per-tenant. This panel is visible to tenant
        admins; it has no effect until GCIP tenancy is live.
      </div>

    </div>
  );
}
