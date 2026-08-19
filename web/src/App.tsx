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

const NAV_COLLAPSE_KEY = "perkins.nav.collapsed";
const NAV_PINS_KEY = "perkins.nav.pins";
const NAV_SECTIONS_KEY = "perkins.nav.sections";
const NAV_RAIL_PX = 56;
const NAV_OPEN_PX = 220;

// Stroke icons (24 viewBox). Collapsed rail is icon-only; title= carries the label.
const NAV_ICON: Record<string, string[]> = {
  dashboard: ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
  "search-ask": ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.35-4.35"],
  faq: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4", "M12 17h.01"],
  archive: ["M4 7h16v12H4z", "M8 7V5h8v2", "M8 12h8"],
  "contract-faq": ["M7 3h8l5 5v13H7z", "M15 3v5h5", "M10 13h6", "M10 17h4"],
  opportunities: ["M12 3l2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z"],
  articles: ["M5 4h10l4 4v12H5z", "M15 4v4h4", "M8 13h8", "M8 17h5"],
  portfolio: ["M3 8h18v11H3z", "M8 8V6h8v2", "M3 13l4-3 4 3 4-4 4 4"],
  scheduling: ["M5 5h14v14H5z", "M5 10h14", "M9 3v4", "M15 3v4"],
  "clip-studio": ["M6 7l5 5-5 5", "M13 17h6"],
  comments: ["M5 5h14v10H8l-3 3z"],
  email: ["M4 6h16v12H4z", "M4 7l8 6 8-6"],
  "video-approval": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M8 12l3 3 5-6"],
  customers: ["M16 19v-1a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v1", "M10 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M20 19v-1a3.5 3.5 0 0 0-2.5-3.3", "M17 9a2.5 2.5 0 1 0 0-4"],
  quoting: ["M6 4h12v16H6z", "M9 9h6", "M9 13h6", "M9 17h3"],
  proposals: ["M7 3h8l5 5v13H7z", "M15 3v5h5", "M9 14l2 2 4-4"],
  invoices: ["M7 3h10v18H7z", "M10 8h4", "M10 12h4", "M10 16h2"],
  payments: ["M3 8h18v10H3z", "M3 12h18", "M7 16h3"],
  "admin-config": ["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M19.4 15a7.7 7.7 0 0 0 .1-2l2-1.6-2-3.4-2.4.5a8 8 0 0 0-1.7-1L15 5h-6l-.4 2.5a8 8 0 0 0-1.7 1L8.5 8l-2 3.4 2 1.6a7.7 7.7 0 0 0 .1 2l-2 1.6 2 3.4 2.4-.5a8 8 0 0 0 1.7 1L9 21h6l.4-2.5a8 8 0 0 0 1.7-1l2.4.5 2-3.4z"],
  "legacy-data": ["M4 7a8 3 0 0 0 16 0A8 3 0 0 0 4 7z", "M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7"],
  logs: ["M6 5h12", "M6 10h12", "M6 15h8", "M6 20h10"],
  signout: ["M10 6H6v12h4", "M14 16l4-4-4-4", "M10 12h8"],
  collapse: ["M15 6l-6 6 6 6"],
  expand: ["M9 6l6 6-6 6"],
};

function NavIcon({ id }: { id: string }) {
  const paths = NAV_ICON[id] ?? ["M12 7v5", "M12 17h.01", "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z"];
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {paths.map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

function readStringList(key: string): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function readPins(): string[] {
  return readStringList(NAV_PINS_KEY);
}

function NavButton({
  id,
  label,
  active,
  onClick,
  badge,
  indent,
  collapsed,
  pinned,
  onPin,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: number;
  indent?: boolean;
  collapsed?: boolean;
  pinned?: boolean;
  onPin?: () => void;
}) {
  return (
    <button
      key={id}
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: collapsed ? "center" : "flex-start",
        width: "100%",
        textAlign: "left",
        padding: collapsed ? "10px 0" : indent ? "9px 10px 9px 20px" : "10px 10px 10px 14px",
        background: active ? BRAND.navyActive : "transparent",
        color: active ? "#fff" : "#c3c9d9",
        borderLeft: active ? `3px solid ${BRAND.red}` : "3px solid transparent",
        cursor: "pointer",
        fontSize: 14,
        fontWeight: active ? 600 : 400,
        border: "none",
        gap: 10,
        position: "relative",
      }}
    >
      <span style={{ display: "flex", flexShrink: 0, opacity: active ? 1 : 0.85 }}>
        <NavIcon id={id} />
      </span>
      <span
        style={{
          flex: 1,
          overflow: "hidden",
          whiteSpace: "nowrap",
          opacity: collapsed ? 0 : 1,
          width: collapsed ? 0 : "auto",
          transition: "opacity 0.15s ease",
        }}
      >
        {label}
      </span>
      {!collapsed && badge != null && badge > 0 && (
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
      {collapsed && badge != null && badge > 0 && (
        <span
          style={{
            position: "absolute",
            top: 4,
            right: 6,
            background: BRAND.red,
            color: "#fff",
            fontSize: 9,
            fontWeight: 700,
            borderRadius: 8,
            padding: "0 4px",
            lineHeight: 1.5,
            minWidth: 14,
            textAlign: "center",
          }}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
      {!collapsed && onPin && (
        <span
          role="button"
          tabIndex={0}
          title={pinned ? "Unpin — stays visible when this section is folded" : "Pin — stays visible when this section is folded"}
          aria-label={pinned ? `Unpin ${label}` : `Pin ${label}`}
          onClick={(e) => { e.stopPropagation(); onPin(); }}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onPin(); } }}
          style={{
            flexShrink: 0, fontSize: 12, padding: "0 2px",
            color: pinned ? "#fff" : "rgba(255,255,255,0.35)",
            cursor: "pointer",
          }}
        >
          {pinned ? "●" : "○"}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// SectionHeader — visual group label in the sidebar
// ---------------------------------------------------------------------------

function SectionHeader({
  label,
  rail,
  folded,
  onToggle,
}: {
  label: string;
  rail?: boolean;
  folded?: boolean;
  onToggle?: () => void;
}) {
  if (rail) {
    return (
      <div
        title={label}
        style={{
          margin: "8px 12px",
          height: 1,
          background: "rgba(255,255,255,0.16)",
        }}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!folded}
      title={folded ? `Expand ${label}` : `Collapse ${label}`}
      style={{
        margin: "14px 0 4px",
        padding: "4px 12px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        background: "none",
        border: "none",
        cursor: "pointer",
        color: "rgba(255,255,255,0.38)",
      }}
    >
      <span style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
      <span
        aria-hidden
        style={{ fontSize: 9, width: 10, flexShrink: 0 }}
      >
        {folded ? "▸" : "▾"}
      </span>
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <span style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
    </button>
  );
}

function AdminSectionDivider({
  rail,
  folded,
  onToggle,
}: {
  rail?: boolean;
  folded?: boolean;
  onToggle?: () => void;
}) {
  return <SectionHeader label="Admin" rail={rail} folded={folded} onToggle={onToggle} />;
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
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(NAV_COLLAPSE_KEY) === "1");
  const [pins, setPins] = useState<string[]>(readPins);
  const [foldedSections, setFoldedSections] = useState<string[]>(() => readStringList(NAV_SECTIONS_KEY));

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
    openSectionForTab(targetTab);
  }

  function handleTabClick(id: string) {
    setNavParams({});
    setTab(id);
    setSidebarOpen(false); // close mobile drawer on nav
    openSectionForTab(id);
  }

  function toggleSection(label: string) {
    setFoldedSections((prev) => {
      const next = prev.includes(label) ? prev.filter((x) => x !== label) : [...prev, label];
      localStorage.setItem(NAV_SECTIONS_KEY, JSON.stringify(next));
      return next;
    });
  }

  function openSectionForTab(id: string) {
    const labels: string[] = [];
    for (const section of sections) {
      if (section.tabs.some(([tid]) => tid === id)) labels.push(section.label);
    }
    if (adminSection?.tabs.some(([tid]) => tid === id)) labels.push(adminSection.label);
    if (labels.length === 0) return;
    setFoldedSections((prev) => {
      const next = prev.filter((x) => !labels.includes(x));
      if (next.length === prev.length) return prev;
      localStorage.setItem(NAV_SECTIONS_KEY, JSON.stringify(next));
      return next;
    });
  }

  function toggleCollapsed() {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem(NAV_COLLAPSE_KEY, next ? "1" : "0");
      return next;
    });
  }

  function togglePin(id: string) {
    setPins((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem(NAV_PINS_KEY, JSON.stringify(next));
      return next;
    });
  }

  // Collect all tab keys in a flat list for section rendering
  const allSectionTabs = sections.flatMap((s) => s.tabs);
  const allAdminTabs = adminSection?.tabs ?? [];
  const configPinnedIds = pinnedTabs.map(([id]) => id);
  const isPinned = (id: string) => configPinnedIds.includes(id) || pins.includes(id);
  const rail = collapsed && !sidebarOpen;

  const sidebarContent = (
    <>
      {/* Logo + title */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: rail ? 0 : 10,
          padding: rail ? "0 8px 14px" : "0 16px 18px",
          marginBottom: 10,
          borderBottom: "1px solid rgba(255,255,255,0.12)",
          justifyContent: rail ? "center" : "flex-start",
        }}
      >
        <img
          src="/perkins-logo.png"
          alt="Perkins Roofing"
          style={{ height: rail ? 26 : 36, background: "#fff", borderRadius: 6, padding: "3px 5px" }}
        />
        {!rail && <span style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.2 }}>{title}</span>}
      </div>

      <button
        type="button"
        className="sidebar-collapse-btn"
        aria-label={rail ? "Expand navigation" : "Collapse navigation"}
        title={rail ? "Expand menu" : "Collapse to icons"}
        onClick={toggleCollapsed}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: rail ? "center" : "flex-start",
          gap: 8,
          margin: rail ? "0 8px 10px" : "0 12px 10px",
          padding: rail ? "8px 0" : "6px 8px",
          background: "rgba(255,255,255,0.08)",
          color: "#c3c9d9",
          border: "none",
          borderRadius: 6,
          cursor: "pointer",
          fontSize: 12,
          fontWeight: 600,
          width: rail ? "auto" : undefined,
        }}
      >
        <NavIcon id={rail ? "expand" : "collapse"} />
        {!rail && "Collapse"}
      </button>

      {pinnedTabs.map(([id, label]) => (
        <NavButton
          key={id}
          id={id}
          label={label}
          active={tab === id}
          onClick={() => handleTabClick(id)}
          badge={badgeFor(id)}
          collapsed={rail}
          pinned={isPinned(id)}
          onPin={configPinnedIds.includes(id) ? undefined : () => togglePin(id)}
        />
      ))}

      {useSections
        ? sections.map((section) => {
            const folded = !rail && foldedSections.includes(section.label);
            return (
            <div key={section.label}>
              <SectionHeader
                label={section.label}
                rail={rail}
                folded={folded}
                onToggle={() => toggleSection(section.label)}
              />
              {section.tabs
                .filter(([id]) => !folded || id === tab || isPinned(id))
                .map(([id, label]) => (
                <NavButton
                  key={id}
                  id={id}
                  label={label}
                  active={tab === id}
                  onClick={() => handleTabClick(id)}
                  badge={badgeFor(id)}
                  indent
                  collapsed={rail}
                  pinned={isPinned(id)}
                  onPin={() => togglePin(id)}
                />
              ))}
            </div>
            );
          })
        : allSectionTabs.map(([id, label]) => (
            <NavButton
              key={id}
              id={id}
              label={label}
              active={tab === id}
              onClick={() => handleTabClick(id)}
              badge={badgeFor(id)}
              collapsed={rail}
              pinned={isPinned(id)}
              onPin={() => togglePin(id)}
            />
          ))}

      {adminSection && allAdminTabs.length > 0 && (
        <>
          <AdminSectionDivider
            rail={rail}
            folded={!rail && foldedSections.includes(adminSection.label)}
            onToggle={() => toggleSection(adminSection.label)}
          />
          {allAdminTabs
            .filter(([id]) => rail || !foldedSections.includes(adminSection.label) || id === tab || isPinned(id))
            .map(([id, label]) => (
            <NavButton
              key={id}
              id={id}
              label={label}
              active={tab === id}
              onClick={() => handleTabClick(id)}
              collapsed={rail}
              pinned={isPinned(id)}
              onPin={() => togglePin(id)}
            />
          ))}
        </>
      )}

      <div style={{ marginTop: "auto", padding: rail ? "14px 0 0" : "18px 16px 0" }}>
        <button
          onClick={signOutUser}
          title="Sign out"
          aria-label="Sign out"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: rail ? "center" : "flex-start",
            gap: 10,
            width: "100%",
            background: "none",
            border: "none",
            color: "#9aa3ba",
            cursor: "pointer",
            fontSize: 13,
            padding: rail ? "8px 0" : 0,
          }}
        >
          <NavIcon id="signout" />
          {!rail && "Sign out"}
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
            width: rail ? NAV_RAIL_PX : NAV_OPEN_PX,
            background: BRAND.navy,
            color: "#fff",
            display: "flex",
            flexDirection: "column",
            padding: "18px 0",
            flexShrink: 0,
            overflowY: "auto",
            overflowX: "hidden",
            position: "relative",
            zIndex: 1400,
            transition: "width 0.2s ease",
          }}
          className={`app-sidebar${sidebarOpen ? " sidebar-open" : ""}${rail ? " sidebar-collapsed" : ""}`}
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
          .sidebar-collapse-btn { display: none !important; }
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
