import { useState, useEffect, type ReactNode } from "react";
import type { User } from "firebase/auth";
import { signIn, signOutUser, getRole, onAuthChanged } from "./auth";
import { apiFetch } from "./api";
import { Archive } from "./pages/Archive";
import { SearchAsk } from "./pages/SearchAsk";
import { Templates } from "./pages/Templates";
import { ComposeEmail } from "./pages/ComposeEmail";
import { VideoApproval } from "./pages/VideoApproval";
import { Status } from "./pages/Status";
import { Articles } from "./pages/Articles";
import { Scheduling } from "./pages/Scheduling";
import { Faq } from "./pages/Faq";
import { Opportunities } from "./pages/Opportunities";
import { Settings } from "./pages/Settings";
import { Users } from "./pages/Users";
import { ClipStudio } from "./pages/ClipStudio";
import { BRAND, FONT } from "./ui";

type Role = "admin" | "web_admin" | "sales" | null;

// Tab config: regular tabs + optional admin-only tabs rendered in a separate group.
interface ShellConfig {
  title: string;
  tabs: [string, string][];
  adminTabs?: [string, string][];
  defaultTab: string;
}

const ROLE_CONFIG: Record<Exclude<Role, null>, ShellConfig> = {
  admin: {
    title: "Perkins Admin",
    tabs: [
      ["dashboard", "Dashboard"],
      ["search-ask", "Search / Ask"],
      ["opportunities", "Content Opportunities"],
      ["articles", "Articles"],
      ["faq", "FAQ"],
      ["templates", "Email Templates"],
      ["compose-email", "Compose Email"],
      ["scheduling", "Content Scheduling"],
      ["clip-studio", "Clip Studio"],
      ["video-approval", "Video Approval"],
      ["archive", "Archive"],
    ],
    adminTabs: [
      ["users", "Users"],
      ["config", "Config"],
    ],
    defaultTab: "dashboard",
  },
  web_admin: {
    title: "Perkins Content",
    tabs: [
      ["dashboard", "Dashboard"],
      ["search-ask", "Search / Ask"],
      ["opportunities", "Content Opportunities"],
      ["articles", "Articles"],
      ["faq", "FAQ"],
      ["scheduling", "Content Scheduling"],
      ["clip-studio", "Clip Studio"],
      ["video-approval", "Video Approval"],
      ["archive", "Archive"],
    ],
    defaultTab: "dashboard",
  },
  sales: {
    title: "Perkins Sales",
    tabs: [
      ["search-ask", "Search / Ask"],
      ["templates", "Email Templates"],
      ["compose-email", "Compose Email"],
      ["archive", "Archive"],
    ],
    defaultTab: "search-ask",
  },
};

function NavButton({ id, label, active, onClick, badge }: { id: string; label: string; active: boolean; onClick: () => void; badge?: number }) {
  return (
    <button
      key={id}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        width: "100%",
        textAlign: "left",
        padding: "11px 16px",
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

function AdminSectionDivider() {
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
        Admin
      </span>
      <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
    </div>
  );
}

interface OpportunityCounts {
  article_topics: number;
  reels: number;
  faqs: number;
  unused_videos: number;
}

// Shared console shell: branded sidebar + content area.
function Shell({ config }: { config: ShellConfig }) {
  const { title, tabs, adminTabs, defaultTab } = config;
  const [tab, setTab] = useState<string>(defaultTab);
  const [oppCounts, setOppCounts] = useState<OpportunityCounts | null>(null);

  useEffect(() => {
    apiFetch("/suggestions/counts")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: OpportunityCounts | null) => { if (d) setOppCounts(d); })
      .catch(() => { /* badge is best-effort */ });
  }, []);

  const oppBadge = oppCounts
    ? oppCounts.article_topics + oppCounts.reels + oppCounts.faqs
    : undefined;

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: FONT }}>
      <nav
        style={{
          width: 220,
          background: BRAND.navy,
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          padding: "18px 0",
        }}
      >
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
        {tabs.map(([id, label]) => (
          <NavButton
            key={id}
            id={id}
            label={label}
            active={tab === id}
            onClick={() => setTab(id)}
            badge={id === "opportunities" ? oppBadge : undefined}
          />
        ))}
        {adminTabs && adminTabs.length > 0 && (
          <>
            <AdminSectionDivider />
            {adminTabs.map(([id, label]) => (
              <NavButton key={id} id={id} label={label} active={tab === id} onClick={() => setTab(id)} />
            ))}
          </>
        )}
        <div style={{ marginTop: "auto", padding: "18px 16px 0" }}>
          <button
            onClick={signOutUser}
            style={{ background: "none", border: "none", color: "#9aa3ba", cursor: "pointer", fontSize: 13 }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <div style={{ flex: 1, padding: 32, overflowY: "auto", background: "#f7f8fa" }}>
        <TabContent tab={tab} />
      </div>
    </div>
  );
}

function TabContent({ tab }: { tab: string }) {
  return (
    <>
      {tab === "dashboard" && <Status />}
      {tab === "search-ask" && <SearchAsk />}
      {tab === "opportunities" && <Opportunities />}
      {tab === "articles" && <Articles />}
      {tab === "faq" && <Faq />}
      {tab === "templates" && <Templates />}
      {tab === "compose-email" && <ComposeEmail />}
      {tab === "scheduling" && <Scheduling />}
      {tab === "clip-studio" && <ClipStudio />}
      {tab === "video-approval" && <VideoApproval />}
      {tab === "archive" && <Archive />}
      {tab === "users" && <Users />}
      {tab === "config" && <Settings />}
    </>
  );
}

// Centered branded card used by the login + no-role screens
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
        Video Content Console
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

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<Role>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
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
  }, []);

  if (!authReady) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          fontFamily: FONT,
          color: BRAND.navyText,
        }}
      >
        Loading…
      </div>
    );
  }

  if (!user) return <LoginScreen />;
  if (role && role in ROLE_CONFIG) return <Shell config={ROLE_CONFIG[role as Exclude<Role, null>]} />;

  // Signed in but no recognized role
  return (
    <CenterCard>
      <img src="/perkins-logo.png" alt="Perkins Roofing" style={{ height: 52, marginBottom: 18 }} />
      <p style={{ margin: "0 0 6px", color: BRAND.navyText, fontWeight: 600, fontSize: 16 }}>
        Access pending
      </p>
      <p style={{ margin: "0 0 22px", color: "#667085", fontSize: 14, maxWidth: 300 }}>
        Your account doesn’t have an assigned role yet. Contact your administrator.
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
