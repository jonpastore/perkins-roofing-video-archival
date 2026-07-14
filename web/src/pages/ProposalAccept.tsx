/**
 * Public proposal accept page — /p/{token}
 * No auth required. Mobile-first (390px baseline).
 * Fetches proposal data from the backend via token; presents tier selection,
 * optional items, ESIGN consent, typed-name, and submit.
 */
import { useEffect, useState } from "react";
import { BRAND, FONT, Spinner } from "../ui";
import {
  getAcceptPage,
  submitAccept,
  submitDecline,
  type AcceptPageData,
  type QuoteSnapshot,
} from "../api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0 });
}

// ── Sub-components ────────────────────────────────────────────────────────────

function AcceptPageShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#f7f8fa",
        fontFamily: FONT,
        padding: "0 0 48px",
      }}
    >
      {/* Top bar */}
      <div
        style={{
          background: BRAND.navy,
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <img
          src="/perkins-logo.png"
          alt="Perkins Roofing"
          style={{ height: 32, background: "#fff", borderRadius: 5, padding: "2px 5px" }}
        />
        <span style={{ color: "#fff", fontWeight: 700, fontSize: 15 }}>Perkins Roofing</span>
      </div>
      <div style={{ maxWidth: 520, margin: "0 auto", padding: "0 16px" }}>{children}</div>
    </div>
  );
}

function SectionCard({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "#fff",
        border: `1px solid ${BRAND.border}`,
        borderRadius: 12,
        padding: "20px 18px",
        marginTop: 16,
        boxShadow: "0 1px 3px rgba(16,24,40,0.06)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 12,
        fontWeight: 700,
        color: BRAND.sub,
        textTransform: "uppercase",
        letterSpacing: 0.4,
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

// ── Terminal states ───────────────────────────────────────────────────────────

function TerminalPage({ icon, headline, body }: { icon: string; headline: string; body: string }) {
  return (
    <AcceptPageShell>
      <SectionCard style={{ textAlign: "center", marginTop: 32, padding: "40px 24px" }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>{icon}</div>
        <h2 style={{ margin: "0 0 12px", fontSize: 20, color: BRAND.navyText }}>{headline}</h2>
        <p style={{ margin: 0, color: BRAND.sub, fontSize: 14, lineHeight: 1.6 }}>{body}</p>
      </SectionCard>
    </AcceptPageShell>
  );
}

// ── Tier selector ─────────────────────────────────────────────────────────────

type TierKey = string;

const TIER_STYLE: Record<string, { color: string; border: string }> = {
  good: { color: "#1a7f4b", border: "#d1fae5" },
  better: { color: BRAND.navyText, border: "#dbeafe" },
  best: { color: BRAND.red, border: "#fee2e2" },
  legacy: { color: BRAND.navyText, border: "#dbeafe" },
};

function orderedTierKeys(snapshot: QuoteSnapshot): TierKey[] {
  const keys = Object.keys(snapshot.tiers || {});
  const preferred = ["good", "better", "best", "legacy"];
  return [
    ...preferred.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !preferred.includes(key)).sort(),
  ];
}

function tierLabel(key: string): string {
  if (key === "good") return "Good";
  if (key === "better") return "Better";
  if (key === "best") return "Best";
  if (key === "legacy") return "Proposal";
  return key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface TierSelectorProps {
  snapshot: QuoteSnapshot;
  selected: TierKey | null;
  onSelect: (tier: TierKey) => void;
}

function TierSelector({ snapshot, selected, onSelect }: TierSelectorProps) {
  const tierKeys = orderedTierKeys(snapshot);
  if (tierKeys.length === 0) {
    return (
      <div style={{ color: BRAND.red, fontSize: 14 }}>
        This proposal is missing pricing information. Please contact Perkins Roofing for an updated link.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {tierKeys.map((key) => {
        const tier = snapshot.tiers[key];
        if (!tier) return null;
        const { color, border } = TIER_STYLE[key] || { color: BRAND.navyText, border: "#dbeafe" };
        const isSelected = selected === key;
        return (
          <label
            key={key}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              background: isSelected ? border : "#fafafa",
              border: `2px solid ${isSelected ? color : BRAND.border}`,
              borderRadius: 10,
              padding: "14px 16px",
              cursor: "pointer",
              transition: "border-color 0.15s, background 0.15s",
            }}
          >
            <input
              type="radio"
              name="tier"
              value={key}
              checked={isSelected}
              onChange={() => onSelect(key)}
              style={{ marginTop: 2, accentColor: color, width: 16, height: 16, flexShrink: 0 }}
            />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 700, fontSize: 15, color }}>{tier.label || tierLabel(key)}</span>
                <span style={{ fontWeight: 700, fontSize: 16, color, fontVariantNumeric: "tabular-nums" }}>
                  {usd(Number(tier.total || 0))}
                </span>
              </div>
              {tier.description && (
                <p style={{ margin: "4px 0 0", fontSize: 13, color: BRAND.sub, lineHeight: 1.5 }}>
                  {tier.description}
                </p>
              )}
            </div>
          </label>
        );
      })}
    </div>
  );
}

// ── Optional items ────────────────────────────────────────────────────────────

interface OptionalItemsProps {
  snapshot: QuoteSnapshot;
  selected: string[];
  onToggle: (id: string) => void;
}

function OptionalItems({ snapshot, selected, onToggle }: OptionalItemsProps) {
  const optionalItems = Array.isArray(snapshot.optional_items) ? snapshot.optional_items : [];
  if (optionalItems.length === 0) return null;
  return (
    <SectionCard>
      <SectionTitle>Optional Add-ons</SectionTitle>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {optionalItems.map((item) => {
          const checked = selected.includes(item.id);
          return (
            <label
              key={item.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                background: checked ? "#f0f4ff" : "#fafafa",
                border: `1px solid ${checked ? BRAND.navyText : BRAND.border}`,
                borderRadius: 8,
                padding: "12px 14px",
                cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(item.id)}
                style={{ width: 16, height: 16, accentColor: BRAND.navyText, flexShrink: 0 }}
              />
              <div style={{ flex: 1 }}>
                <span style={{ fontWeight: 600, fontSize: 14, color: BRAND.navyText }}>{item.label}</span>
                <span style={{ marginLeft: 8, fontSize: 13, color: BRAND.sub }}>
                  {usd(Number(item.unit_price || 0))}{Number(item.qty || 1) > 1 ? ` × ${Number(item.qty || 1)}` : ""}
                </span>
              </div>
              <span style={{ fontWeight: 700, fontSize: 14, color: BRAND.navyText, fontVariantNumeric: "tabular-nums" }}>
                {usd(Number(item.unit_price || 0) * Number(item.qty || 1))}
              </span>
            </label>
          );
        })}
      </div>
    </SectionCard>
  );
}

// ── Main accept page ──────────────────────────────────────────────────────────

type PageState = "loading" | "ready" | "submitting" | "accepted" | "declined" | "superseded" | "already_accepted" | "not_found" | "error";

interface ProposalAcceptProps {
  token: string;
}

export function ProposalAccept({ token }: ProposalAcceptProps) {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [data, setData] = useState<AcceptPageData | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  // Form state
  const [selectedTier, setSelectedTier] = useState<TierKey | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const [consentChecked, setConsentChecked] = useState(false);
  const [signedName, setSignedName] = useState("");
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [showDeclinePrompt, setShowDeclinePrompt] = useState(false);
  const [declineNote, setDeclineNote] = useState("");

  useEffect(() => {
    getAcceptPage(token)
      .then((d) => {
        if (d.status === "superseded") { setPageState("superseded"); return; }
        if (d.status === "accepted") { setPageState("already_accepted"); return; }
        if (d.status === "declined") { setPageState("declined"); return; }
        setData(d);
        const tierKeys = orderedTierKeys(d.quote_snapshot);
        if (tierKeys.length === 1) setSelectedTier(tierKeys[0]);
        setPageState("ready");
      })
      .catch((e: unknown) => {
        const status = (e as { status?: number }).status;
        if (status === 404) { setPageState("not_found"); return; }
        setLoadErr(e instanceof Error ? e.message : "Failed to load proposal.");
        setPageState("error");
      });
  }, [token]);

  function toggleOption(id: string) {
    setSelectedOptions((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function handleAccept() {
    if (!selectedTier) { setSubmitErr("Please select a proposal package."); return; }
    if (!consentChecked) { setSubmitErr("Please check the electronic signature consent box."); return; }
    if (!signedName.trim()) { setSubmitErr("Please type your full name to sign."); return; }

    setSubmitErr(null);
    setPageState("submitting");
    try {
      await submitAccept(token, {
        selected_tier: selectedTier,
        selected_options: selectedOptions,
        consent_electronic: true,
        signed_name: signedName.trim(),
      });
      setPageState("accepted");
    } catch (e: unknown) {
      setSubmitErr(e instanceof Error ? e.message : "Submission failed. Please try again.");
      setPageState("ready");
    }
  }

  async function handleDecline() {
    setPageState("submitting");
    try {
      await submitDecline(token, { note: declineNote.trim() || undefined });
      setPageState("declined");
    } catch {
      setPageState("ready");
      setShowDeclinePrompt(false);
    }
  }

  // ── Terminal renders ───────────────────────────────────────────────────────

  if (pageState === "loading") {
    return (
      <AcceptPageShell>
        <div style={{ textAlign: "center", marginTop: 60, color: BRAND.sub }}>
          <Spinner />
          <p style={{ marginTop: 12, fontSize: 14 }}>Loading proposal…</p>
        </div>
      </AcceptPageShell>
    );
  }

  if (pageState === "not_found") {
    return (
      <TerminalPage
        icon="🔍"
        headline="Proposal not found"
        body="This link is invalid or has expired. Please contact Perkins Roofing if you believe this is an error."
      />
    );
  }

  if (pageState === "superseded") {
    return (
      <TerminalPage
        icon="📋"
        headline="This proposal has been superseded"
        body="An updated proposal has been sent to you. Please use the link in your most recent email from Perkins Roofing."
      />
    );
  }

  if (pageState === "already_accepted") {
    return (
      <TerminalPage
        icon="✅"
        headline="You have already accepted this proposal"
        body="Your signed copy was emailed to you. Contact Perkins Roofing if you have any questions."
      />
    );
  }

  if (pageState === "accepted") {
    return (
      <TerminalPage
        icon="✅"
        headline="Proposal accepted!"
        body="Thank you! A signed copy of this proposal has been emailed to you. Perkins Roofing will be in touch shortly to discuss next steps."
      />
    );
  }

  if (pageState === "declined") {
    return (
      <TerminalPage
        icon="📩"
        headline="Proposal declined"
        body="We've received your response. A Perkins Roofing team member will reach out if you'd like to discuss any changes."
      />
    );
  }

  if (pageState === "error") {
    return (
      <AcceptPageShell>
        <SectionCard style={{ marginTop: 32, textAlign: "center" }}>
          <p style={{ color: BRAND.red, fontSize: 14 }}>Error: {loadErr}</p>
        </SectionCard>
      </AcceptPageShell>
    );
  }

  // ── Ready state ────────────────────────────────────────────────────────────

  if (!data) return null;
  const { title, customer_name, property_address, quote_snapshot, tenant_name } = data;

  // Compute total = selected tier + selected options
  const optionalItems = Array.isArray(quote_snapshot.optional_items) ? quote_snapshot.optional_items : [];
  const tierTotal = selectedTier && quote_snapshot.tiers[selectedTier]
    ? Number(quote_snapshot.tiers[selectedTier].total || 0)
    : null;
  const optionsTotal = selectedOptions.reduce((sum, id) => {
    const item = optionalItems.find((i) => i.id === id);
    return sum + (item ? Number(item.unit_price || 0) * Number(item.qty || 1) : 0);
  }, 0);
  const grandTotal = tierTotal !== null ? tierTotal + optionsTotal : null;

  const depositAmt =
    tierTotal !== null && quote_snapshot.deposit_policy?.mode === "percent"
      ? (tierTotal * Number(quote_snapshot.deposit_policy.value || 0)) / 100
      : quote_snapshot.deposit_policy?.mode === "fixed"
      ? Number(quote_snapshot.deposit_policy.value || 0)
      : null;

  return (
    <AcceptPageShell>
      {/* Proposal header */}
      <SectionCard style={{ marginTop: 24, borderTop: `4px solid ${BRAND.red}` }}>
        <h1 style={{ margin: "0 0 6px", fontSize: 20, color: BRAND.navyText, lineHeight: 1.3 }}>{title}</h1>
        <p style={{ margin: 0, fontSize: 14, color: BRAND.sub }}>{customer_name} · {property_address}</p>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: BRAND.sub }}>Prepared by {tenant_name}</p>
      </SectionCard>

      {/* Tier selection */}
      <SectionCard>
        <SectionTitle>Select your package</SectionTitle>
        <TierSelector snapshot={quote_snapshot} selected={selectedTier} onSelect={setSelectedTier} />
      </SectionCard>

      {/* Optional items */}
      <OptionalItems snapshot={quote_snapshot} selected={selectedOptions} onToggle={toggleOption} />

      {/* Price summary */}
      {grandTotal !== null && (
        <SectionCard>
          <SectionTitle>Summary</SectionTitle>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, color: BRAND.ink, marginBottom: 6 }}>
            <span>{quote_snapshot.tiers[selectedTier!]?.label || tierLabel(selectedTier!)} package</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{usd(tierTotal!)}</span>
          </div>
          {selectedOptions.map((id) => {
            const item = optionalItems.find((i) => i.id === id);
            if (!item) return null;
            return (
              <div key={id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, color: BRAND.sub, marginBottom: 4 }}>
                <span>{item.label}</span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{usd(Number(item.unit_price || 0) * Number(item.qty || 1))}</span>
              </div>
            );
          })}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 16,
            fontWeight: 700,
            color: BRAND.navyText,
            borderTop: `1px solid ${BRAND.border}`,
            paddingTop: 10,
            marginTop: 8,
          }}>
            <span>Total</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{usd(grandTotal)}</span>
          </div>
          {depositAmt !== null && (
            <div style={{ marginTop: 10, background: "#fffbe6", border: "1px solid #fde68a", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#92400e" }}>
                Deposit due: {usd(depositAmt)}
                {quote_snapshot.deposit_policy?.mode === "percent" ? ` (${quote_snapshot.deposit_policy.value}%)` : ""}
              </div>
              {quote_snapshot.deposit_policy?.instructions && (
                <div style={{ fontSize: 12, color: "#92400e", marginTop: 3 }}>
                  {quote_snapshot.deposit_policy.instructions}
                </div>
              )}
            </div>
          )}
        </SectionCard>
      )}

      {/* ESIGN consent + name */}
      <SectionCard>
        <SectionTitle>Electronic Signature</SectionTitle>

        <label
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            background: consentChecked ? "#f0f4ff" : "#fafafa",
            border: `1px solid ${consentChecked ? BRAND.navyText : BRAND.border}`,
            borderRadius: 8,
            padding: "14px 14px",
            cursor: "pointer",
            marginBottom: 16,
          }}
        >
          <input
            type="checkbox"
            checked={consentChecked}
            onChange={(e) => setConsentChecked(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: BRAND.navyText, flexShrink: 0, marginTop: 1 }}
          />
          <span style={{ fontSize: 13, color: BRAND.ink, lineHeight: 1.6 }}>
            I agree to conduct this transaction electronically pursuant to the Electronic Signatures in
            Global and National Commerce Act (ESIGN) and Florida Statute §668. I understand that by
            typing my name below and clicking "Accept Proposal," I am signing this proposal with the
            same legal effect as a handwritten signature.
          </span>
        </label>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
            Full name (type to sign)
          </label>
          <input
            type="text"
            value={signedName}
            onChange={(e) => setSignedName(e.target.value)}
            placeholder="Your full legal name"
            style={{
              display: "block",
              width: "100%",
              padding: "11px 14px",
              border: `1px solid ${BRAND.border}`,
              borderRadius: 8,
              fontSize: 15,
              fontFamily: "'Georgia', serif",
              boxSizing: "border-box",
              outline: "none",
              color: BRAND.navyText,
            }}
          />
        </div>

        {submitErr && (
          <p style={{ color: BRAND.red, fontSize: 13, margin: "0 0 12px" }}>{submitErr}</p>
        )}

        <button
          onClick={handleAccept}
          disabled={pageState === "submitting"}
          style={{
            display: "block",
            width: "100%",
            padding: "14px",
            background: pageState === "submitting" ? "#ccc" : "#1a7f4b",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            fontSize: 16,
            fontWeight: 700,
            cursor: pageState === "submitting" ? "not-allowed" : "pointer",
            fontFamily: FONT,
            boxShadow: pageState === "submitting" ? "none" : "0 2px 8px rgba(26,127,75,0.3)",
          }}
        >
          {pageState === "submitting" ? "Submitting…" : "Accept Proposal"}
        </button>
      </SectionCard>

      {/* Decline */}
      <div style={{ textAlign: "center", marginTop: 16 }}>
        {!showDeclinePrompt ? (
          <button
            onClick={() => setShowDeclinePrompt(true)}
            style={{ background: "none", border: "none", color: BRAND.sub, fontSize: 13, cursor: "pointer", textDecoration: "underline" }}
          >
            Decline this proposal
          </button>
        ) : (
          <SectionCard>
            <p style={{ margin: "0 0 10px", fontSize: 14, color: BRAND.navyText }}>
              Let us know why (optional) — we'll follow up to address any concerns.
            </p>
            <textarea
              value={declineNote}
              onChange={(e) => setDeclineNote(e.target.value)}
              placeholder="Price, scope, timing, other…"
              rows={3}
              style={{
                width: "100%",
                padding: "10px 12px",
                border: `1px solid ${BRAND.border}`,
                borderRadius: 8,
                fontSize: 13,
                fontFamily: FONT,
                boxSizing: "border-box",
                resize: "vertical",
                marginBottom: 10,
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={handleDecline}
                disabled={pageState === "submitting"}
                style={{
                  flex: 1,
                  padding: "10px",
                  background: "#fff",
                  color: BRAND.red,
                  border: `1px solid ${BRAND.red}`,
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: pageState === "submitting" ? "not-allowed" : "pointer",
                  fontFamily: FONT,
                }}
              >
                {pageState === "submitting" ? "…" : "Decline Proposal"}
              </button>
              <button
                onClick={() => setShowDeclinePrompt(false)}
                style={{
                  padding: "10px 16px",
                  background: "#fff",
                  color: BRAND.sub,
                  border: `1px solid ${BRAND.border}`,
                  borderRadius: 8,
                  fontSize: 14,
                  cursor: "pointer",
                  fontFamily: FONT,
                }}
              >
                Cancel
              </button>
            </div>
          </SectionCard>
        )}
      </div>

      <p style={{ textAlign: "center", fontSize: 11, color: "#aaa", marginTop: 32, padding: "0 20px" }}>
        This proposal is confidential and intended solely for the named recipient.
        By accepting, you agree to the terms outlined above and in any attached T&amp;C document.
      </p>
    </AcceptPageShell>
  );
}

// ── Route entry point — extracts token from path ──────────────────────────────

/**
 * Renders ProposalAccept for the current URL path `/p/{token}`.
 * Called directly from App.tsx before the auth gate.
 */
export function ProposalAcceptRoute() {
  // Extract token from pathname /p/{token}
  const token = window.location.pathname.replace(/^\/p\//, "").replace(/\/$/, "");
  if (!token) {
    return (
      <TerminalPage
        icon="🔍"
        headline="Proposal not found"
        body="This link is invalid. Please check the email you received from Perkins Roofing."
      />
    );
  }
  return <ProposalAccept token={token} />;
}
