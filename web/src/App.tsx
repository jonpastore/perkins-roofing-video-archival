import { useState, useEffect, createContext, type ReactNode } from "react";
import type { User } from "firebase/auth";
import { signIn, signOutUser, getRole, onAuthChanged } from "./auth";
import { apiFetch } from "./api";
import { Archive } from "./pages/Archive";
import { SearchAsk } from "./pages/SearchAsk";
import { VideoApproval } from "./pages/VideoApproval";
import { Status } from "./pages/Status";
import { Articles } from "./pages/Articles";
import { Portfolio } from "./pages/Portfolio";
import { Scheduling } from "./pages/Scheduling";
import { Faq } from "./pages/Faq";
import { Opportunities } from "./pages/Opportunities";
import { ClipStudio } from "./pages/ClipStudio";
import { Comments } from "./pages/Comments";
import { Logs } from "./pages/Logs";
import { Email } from "./pages/Email";
import { Quoting } from "./pages/Quoting";
import { Squares } from "./pages/Squares";
import { Proposals } from "./pages/Proposals";
import { ProposalBuilder } from "./pages/ProposalBuilder";
import { Invoices } from "./pages/Invoices";
import { Customers } from "./pages/Customers";
import { Payments } from "./pages/Payments";
import { ContractFaq } from "./pages/ContractFaq";
import { AdminConfig } from "./pages/AdminConfig";
import { Knowify } from "./pages/Knowify";
import { ProposalAcceptRoute } from "./pages/ProposalAccept";
import { BRAND, FONT, Spinner } from "./ui";

// ---------------------------------------------------------------------------
// NavContext — lightweight cross-tab navigation
// ---------------------------------------------------------------------------

export interface NavParams {
  cluster?: string; // pillar_slug to pre-filter Articles tab
  [key: string]: string | undefined;
}

export interface NavContextValue {
  navigate: (tab: string, params?: NavParams) => void;
  params: NavParams;
}

export const NavContext = createContext<NavContextValue>({
  navigate: () => {},
  params: {},
});

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

// ---------------------------------------------------------------------------
// Shell config — two-level sidebar (sections + pinned + admin section)
// ---------------------------------------------------------------------------

interface SectionConfig {
  label: string;
  tabs: [string, string][]; // [tab_key, display_label]
}

interface ShellConfig {
  title: string;
  pinnedTabs: [string, string][];
  sections: SectionConfig[];
  adminSection?: SectionConfig;
  useSections: boolean; // false = flat list (sales role)
  defaultTab: string;
}

const ROLE_CONFIG: Partial<Record<Exclude<Role, null>, ShellConfig>> = {
  admin: {
    title: "Perkins Admin",
    pinnedTabs: [["dashboard", "Dashboard"]],
    useSections: true,
    sections: [
      {
        label: "Knowledge Base",
        tabs: [
          ["search-ask", "Search / Ask"],
          ["faq", "FAQ"],
          ["archive", "Video Archive"],
          ["contract-faq", "Contract-FAQ"],
        ],
      },
      {
        label: "Marketing",
        tabs: [
          ["opportunities", "Opportunities"],
          ["articles", "Articles"],
          ["portfolio", "Portfolio"],
          ["scheduling", "Scheduling"],
          ["clip-studio", "Clip Studio"],
          ["comments", "Comments"],
          ["email", "Email"],
          ["video-approval", "Video Approval"],
        ],
      },
      {
        label: "Sales",
        tabs: [
          ["customers", "Customers"],
          ["quoting", "Estimates"],
          ["proposals", "Proposals"],
          ["invoices", "Invoices"],
          ["payments", "Payments"],
        ],
      },
    ],
    adminSection: {
      label: "Admin",
      tabs: [
        ["admin-config", "Admin Config"],
        ["legacy-data", "Legacy Data"],
        ["logs", "Logs"],
      ],
    },
    defaultTab: "dashboard",
  },

  web_admin: {
    title: "Perkins Content",
    pinnedTabs: [["dashboard", "Dashboard"]],
    useSections: true,
    sections: [
      {
        label: "Knowledge Base",
        tabs: [
          ["search-ask", "Search / Ask"],
          ["faq", "FAQ"],
          ["archive", "Video Archive"],
          ["contract-faq", "Contract-FAQ"],
        ],
      },
      {
        label: "Marketing",
        tabs: [
          ["opportunities", "Opportunities"],
          ["articles", "Articles"],
          ["portfolio", "Portfolio"],
          ["scheduling", "Scheduling"],
          ["clip-studio", "Clip Studio"],
          ["comments", "Comments"],
          ["video-approval", "Video Approval"],
        ],
      },
      {
        label: "Sales",
        tabs: [
          ["customers", "Customers"],
          ["quoting", "Estimates"],
          ["proposals", "Proposals"],
          ["invoices", "Invoices"],
          ["payments", "Payments"],
        ],
      },
    ],
    adminSection: {
      label: "Admin",
      tabs: [
        ["legacy-data", "Legacy Data"],
      ],
    },
    defaultTab: "dashboard",
  },

  sales: {
    title: "Perkins Sales",
    pinnedTabs: [],
    useSections: false,
    sections: [
      {
        label: "",
        tabs: [
          ["search-ask", "Search / Ask"],
          ["email", "Email"],
          ["archive", "Video Archive"],
          ["customers", "Customers"],
          ["quoting", "Estimates"],
          ["proposals", "Proposals"],
          ["invoices", "Invoices"],
          ["payments", "Payments"],
          ["legacy-data", "Legacy Data"],
        ],
      },
    ],
    defaultTab: "search-ask",
  },

  // platform_admin deliberately has NO shell config in F1 (TRD-F1 §3c: skip render
  // until F4 ships the Tenants tab + per-sub-tab role gating). The backend authz
  // entry exists; a platform_admin claim signing in early sees the no-role screen.
};

// ---------------------------------------------------------------------------
// NavButton
// ---------------------------------------------------------------------------

function NavButton({
  id,
  label,
  active,
  onClick,
  badge,
  indent,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: number;
  indent?: boolean;
}) {
  return (
    <button
      key={id}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        width: "100%",
        textAlign: "left",
        padding: indent ? "9px 16px 9px 28px" : "11px 16px",
        background: active ? BRAND.navyActive : "transparent",
        color: active ? "#fff" : "#c3c9d9",
        borderLeft: active ? `3px solid ${BRAND.red}` : "3px solid transparent",
        cursor: "pointer",
        fontSize: 14,
        fontWeight: active ? 600 : 400,
        border: "none",
        gap: 8,
      }}
    >
      <span style={{ flex: 1 }}>{label}</span>
      {badge != null && badge > 0 && (
        <span
          style={{
            background: BRAND.red,
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            borderRadius: 10,
            padding: "1px 7px",
            lineHeight: 1.6,
            minWidth: 18,
            textAlign: "center",
            flexShrink: 0,
          }}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// SectionHeader — visual group label in the sidebar
// ---------------------------------------------------------------------------

function SectionHeader({ label }: { label: string }) {
  return (
    <div
      style={{
        margin: "14px 0 4px",
        padding: "0 16px",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          color: "rgba(255,255,255,0.38)",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
    </div>
  );
}

// AdminSectionDivider kept for backward compat with the visual — now delegates to SectionHeader.
function AdminSectionDivider() {
  return <SectionHeader label="Admin" />;
}

// ---------------------------------------------------------------------------
// Badge data
// ---------------------------------------------------------------------------

interface OpportunityCounts {
  article_topics: number;
  reels: number;
  faqs: number;
  unused_videos: number;
  pending_video_approvals?: number;
  scheduled_articles?: number;
  scheduled_content?: number;
  comment_drafts?: number;
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

function Shell({ config, role }: { config: ShellConfig; role: Role }) {
  const { title, pinnedTabs, sections, adminSection, useSections, defaultTab } = config;
  const [tab, setTab] = useState<string>(defaultTab);
  const [navParams, setNavParams] = useState<NavParams>({});
  const [oppCounts, setOppCounts] = useState<OpportunityCounts | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    apiFetch("/suggestions/counts")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: OpportunityCounts | null) => { if (d) setOppCounts(d); })
      .catch(() => { /* badge is best-effort */ });
  }, []);

  const oppBadge = oppCounts
    ? oppCounts.article_topics + oppCounts.reels + oppCounts.faqs
    : undefined;
  const approvalBadge = oppCounts?.pending_video_approvals;
  const scheduledArticlesBadge = oppCounts?.scheduled_articles;
  const scheduledContentBadge = oppCounts?.scheduled_content;
  const commentBadge = oppCounts?.comment_drafts;

  function badgeFor(id: string): number | undefined {
    if (id === "opportunities") return oppBadge;
    if (id === "articles") return scheduledArticlesBadge;
    if (id === "scheduling") return scheduledContentBadge;
    if (id === "video-approval") return approvalBadge;
    if (id === "comments") return commentBadge;
    return undefined;
  }

  function navigate(targetTab: string, params: NavParams = {}) {
    setNavParams(params);
    setTab(targetTab);
  }

  function handleTabClick(id: string) {
    setNavParams({});
    setTab(id);
    setSidebarOpen(false); // close mobile drawer on nav
  }

  // Collect all tab keys in a flat list for section rendering
  const allSectionTabs = sections.flatMap((s) => s.tabs);
  const allAdminTabs = adminSection?.tabs ?? [];

  const sidebarContent = (
    <>
      {/* Logo + title */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "0 16px 18px",
          marginBottom: 10,
          borderBottom: "1px solid rgba(255,255,255,0.12)",
        }}
      >
        <img
          src="/perkins-logo.png"
          alt="Perkins Roofing"
          style={{ height: 36, background: "#fff", borderRadius: 6, padding: "3px 5px" }}
        />
        <span style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.2 }}>{title}</span>
      </div>

      {/* Pinned tabs (e.g. Dashboard) */}
      {pinnedTabs.map(([id, label]) => (
        <NavButton
          key={id}
          id={id}
          label={label}
          active={tab === id}
          onClick={() => handleTabClick(id)}
          badge={badgeFor(id)}
        />
      ))}

      {/* Sections */}
      {useSections
        ? sections.map((section) => (
            <div key={section.label}>
              <SectionHeader label={section.label} />
              {section.tabs.map(([id, label]) => (
                <NavButton
                  key={id}
                  id={id}
                  label={label}
                  active={tab === id}
                  onClick={() => handleTabClick(id)}
                  badge={badgeFor(id)}
                  indent
                />
              ))}
            </div>
          ))
        : allSectionTabs.map(([id, label]) => (
            // Flat list for sales role (no section headers)
            <NavButton
              key={id}
              id={id}
              label={label}
              active={tab === id}
              onClick={() => handleTabClick(id)}
              badge={badgeFor(id)}
            />
          ))}

      {/* Admin section */}
      {adminSection && allAdminTabs.length > 0 && (
        <>
          <AdminSectionDivider />
          {allAdminTabs.map(([id, label]) => (
            <NavButton
              key={id}
              id={id}
              label={label}
              active={tab === id}
              onClick={() => handleTabClick(id)}
            />
          ))}
        </>
      )}

      {/* Sign out */}
      <div style={{ marginTop: "auto", padding: "18px 16px 0" }}>
        <button
          onClick={signOutUser}
          style={{ background: "none", border: "none", color: "#9aa3ba", cursor: "pointer", fontSize: 13 }}
        >
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <NavContext.Provider value={{ navigate, params: navParams }}>
      <div style={{ display: "flex", height: "100vh", fontFamily: FONT }}>

        {/* Mobile hamburger button — only visible < 768px */}
        <button
          aria-label="Open navigation"
          onClick={() => setSidebarOpen(true)}
          style={{
            display: "none",
            position: "fixed",
            top: 12,
            left: 12,
            zIndex: 1500,
            background: BRAND.navy,
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 20,
            cursor: "pointer",
          }}
          className="hamburger-btn"
        >
          ☰
        </button>

        {/* Mobile backdrop */}
        {sidebarOpen && (
          <div
            aria-hidden="true"
            onClick={() => setSidebarOpen(false)}
            style={{
              display: "none",
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.45)",
              zIndex: 1350,
            }}
            className="sidebar-backdrop"
          />
        )}

        {/* Sidebar — desktop: static; mobile: drawer overlay */}
        <nav
          aria-label="Main navigation"
          role="navigation"
          style={{
            width: 220,
            background: BRAND.navy,
            color: "#fff",
            display: "flex",
            flexDirection: "column",
            padding: "18px 0",
            flexShrink: 0,
            overflowY: "auto",
            position: "relative",
            zIndex: 1400,
          }}
          className={`app-sidebar${sidebarOpen ? " sidebar-open" : ""}`}
        >
          {sidebarContent}
        </nav>

        {/* Content area */}
        <div style={{ flex: 1, padding: 32, overflowY: "auto", background: "#f7f8fa" }}>
          <TabContent tab={tab} role={role} />
        </div>
      </div>

      {/* Inline responsive styles — pure CSS, no new dependencies */}
      <style>{`
        @media (max-width: 767px) {
          .hamburger-btn { display: block !important; }
          .sidebar-backdrop { display: block !important; }
          .app-sidebar {
            position: fixed !important;
            top: 0;
            left: 0;
            height: 100vh;
            z-index: 200;
            transform: translateX(-100%);
            transition: transform 0.22s ease;
          }
          .app-sidebar.sidebar-open {
            transform: translateX(0);
          }
        }
      `}</style>
    </NavContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// TabContent
// ---------------------------------------------------------------------------

function TabContent({ tab, role }: { tab: string; role: Role }) {
  return (
    <>
      {tab === "dashboard" && <Status />}
      {tab === "search-ask" && <SearchAsk />}
      {tab === "opportunities" && <Opportunities />}
      {tab === "articles" && <Articles />}
      {tab === "portfolio" && <Portfolio />}
      {tab === "faq" && <Faq />}
      {tab === "email" && <Email />}
      {tab === "scheduling" && <Scheduling />}
      {tab === "clip-studio" && <ClipStudio />}
      {tab === "comments" && <Comments />}
      {tab === "video-approval" && <VideoApproval />}
      {tab === "archive" && <Archive />}
      {tab === "logs" && <Logs />}
      {tab === "quoting" && <Quoting />}
      {tab === "squares" && <Squares />}
      {tab === "proposals" && <Proposals />}
      {tab === "proposal-gen" && <ProposalBuilder />}
      {tab === "invoices" && <Invoices />}
      {tab === "customers" && <Customers />}
      {tab === "payments" && <Payments />}
      {tab === "contract-faq" && <ContractFaq />}
      {tab === "admin-config" && <AdminConfig role={role} />}
      {tab === "legacy-data" && <Knowify />}
      {/* backward-compat: old "knowify" tab key still works */}
      {tab === "knowify" && <Knowify />}
      {/* status-view: Marketing > Status — renders the same Status component as dashboard */}
      {tab === "status-view" && <Status />}
      {/* Legacy backward-compat: users/config keys redirect into admin-config sub-tabs.
          These keys are no longer in the sidebar but may exist in saved client state. */}
      {tab === "users" && <AdminConfig role={role} />}
      {tab === "config" && <AdminConfig role={role} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Login / auth screens
// ---------------------------------------------------------------------------

function CenterCard({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        fontFamily: FONT,
        background: `linear-gradient(160deg, #f7f8fa 0%, #eef1f6 100%)`,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          padding: "44px 40px",
          boxShadow: "0 8px 30px rgba(27,42,82,0.12)",
          textAlign: "center",
          minWidth: 340,
          borderTop: `4px solid ${BRAND.red}`,
        }}
      >
        {children}
      </div>
    </div>
  );
}

function LoginScreen() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSignIn() {
    setLoading(true);
    setError(null);
    try {
      await signIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <CenterCard>
      <img
        src="/perkins-logo.png"
        alt="Perkins Roofing"
        style={{ height: 60, marginBottom: 20 }}
      />
      <p style={{ margin: "0 0 28px", color: BRAND.navyText, fontSize: 15, fontWeight: 600 }}>
        Sales and Marketing Platform
      </p>
      <button
        onClick={handleSignIn}
        disabled={loading}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          padding: "13px 28px",
          background: loading ? "#ccc" : BRAND.red,
          color: "#fff",
          border: "none",
          borderRadius: 8,
          cursor: loading ? "not-allowed" : "pointer",
          fontSize: 15,
          fontWeight: 600,
          boxShadow: loading ? "none" : "0 2px 8px rgba(239,60,26,0.35)",
        }}
        onMouseOver={(e) => { if (!loading) e.currentTarget.style.background = BRAND.redDark; }}
        onMouseOut={(e) => { if (!loading) e.currentTarget.style.background = BRAND.red; }}
      >
        {loading ? "Signing in…" : "Sign in with Google"}
      </button>
      {error && <p style={{ marginTop: 16, color: BRAND.red, fontSize: 13 }}>{error}</p>}
    </CenterCard>
  );
}

// ---------------------------------------------------------------------------
// App root
// ---------------------------------------------------------------------------

export default function App() {
  const isPublicProposalRoute = /^\/p\/[^/]+\/?$/.test(window.location.pathname);
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<Role>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
    if (isPublicProposalRoute) {
      setAuthReady(true);
      return;
    }
    const unsubscribe = onAuthChanged(async (u) => {
      setUser(u);
      if (u) {
        const r = await getRole();
        setRole(r as Role);
      } else {
        setRole(null);
      }
      setAuthReady(true);
    });
    return unsubscribe;
  }, [isPublicProposalRoute]);

  if (isPublicProposalRoute) return <ProposalAcceptRoute />;

  if (!authReady) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          height: "100vh",
          fontFamily: FONT,
          color: BRAND.navyText,
        }}
      >
        <Spinner />
        Loading…
      </div>
    );
  }

  if (!user) return <LoginScreen />;
  const shellConfig = role ? ROLE_CONFIG[role as Exclude<Role, null>] : undefined;
  if (role && shellConfig) {
    return <Shell config={shellConfig} role={role} />;
  }

  // Signed in but no recognized role
  return (
    <CenterCard>
      <img src="/perkins-logo.png" alt="Perkins Roofing" style={{ height: 52, marginBottom: 18 }} />
      <p style={{ margin: "0 0 6px", color: BRAND.navyText, fontWeight: 600, fontSize: 16 }}>
        Access pending
      </p>
      <p style={{ margin: "0 0 22px", color: "#667085", fontSize: 14, maxWidth: 300 }}>
        Your account doesn't have an assigned role yet. Contact your administrator.
      </p>
      <button
        onClick={signOutUser}
        style={{
          padding: "10px 22px",
          cursor: "pointer",
          background: "#fff",
          color: BRAND.navyText,
          border: `1px solid ${BRAND.navyText}`,
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
        }}
      >
        Sign out
      </button>
    </CenterCard>
  );
}
