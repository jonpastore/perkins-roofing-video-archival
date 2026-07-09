import { useState } from "react";
import { BRAND, FONT } from "../ui";
import { Users } from "./Users";
import { Settings } from "./Settings";
import { EstimatingConfig } from "./EstimatingConfig";
import { MarketingConfig } from "./MarketingConfig";
import { KbConfig } from "./KbConfig";
import { TenantsConfig } from "./TenantsConfig";
import { SsoPanel } from "./SsoPanel";

type Role = "admin" | "web_admin" | "sales" | "platform_admin" | null;

interface AdminConfigProps {
  role: Role;
}

interface SubTab {
  key: string;
  label: string;
}

function PlaceholderCard({ message }: { message: string }) {
  return (
    <div
      style={{
        background: "#fff",
        border: `1px solid ${BRAND.border}`,
        borderRadius: 12,
        padding: "40px 32px",
        textAlign: "center",
        color: "#9aa3ba",
        fontSize: 15,
        marginTop: 24,
      }}
    >
      {message}
    </div>
  );
}

export function AdminConfig({ role }: AdminConfigProps) {
  const subTabs: SubTab[] = [
    { key: "kb", label: "Knowledge Base" },
    { key: "marketing", label: "Marketing" },
    { key: "estimating", label: "Estimating" },
    { key: "quoting", label: "Quoting" },
    { key: "users-roles", label: "Users & Roles" },
    // platform_admin only — hidden for all current roles
    ...(role === "platform_admin" ? [{ key: "tenants", label: "Tenants" }] : []),
    // F4 TODO: when platform_admin gets a shell, gate the non-tenants sub-tabs
    // away from it (authz grants it only admin_tenants + admin_users).
    { key: "settings", label: "Platform Settings" },
  ];

  const [activeSubTab, setActiveSubTab] = useState<string>(subTabs[0].key);

  return (
    <div style={{ fontFamily: FONT }}>
      <h2 style={{ margin: "0 0 20px", color: BRAND.navyText, fontSize: 22 }}>Admin Config</h2>

      {/* Horizontal sub-tab bar */}
      <div
        style={{
          display: "flex",
          gap: 2,
          borderBottom: `2px solid ${BRAND.border}`,
          marginBottom: 24,
          overflowX: "auto",
        }}
      >
        {subTabs.map((t) => {
          const active = activeSubTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setActiveSubTab(t.key)}
              style={{
                padding: "10px 18px",
                background: "none",
                border: "none",
                borderBottom: active ? `2px solid ${BRAND.red}` : "2px solid transparent",
                marginBottom: -2,
                color: active ? BRAND.navyText : "#667085",
                fontWeight: active ? 600 : 400,
                fontSize: 14,
                cursor: "pointer",
                whiteSpace: "nowrap",
                fontFamily: FONT,
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Sub-tab content */}
      {activeSubTab === "kb" && <KbConfig role={role} />}
      {activeSubTab === "marketing" && <MarketingConfig role={role} />}
      {activeSubTab === "estimating" && <EstimatingConfig role={role} />}
      {activeSubTab === "quoting" && (
        <PlaceholderCard message="Quoting config — coming in F3 (proposal templates, T&C library, deposit policy, reminder cadence)" />
      )}
      {activeSubTab === "users-roles" && (
        <>
          <Users />
          <SsoPanel />
        </>
      )}
      {activeSubTab === "tenants" && role === "platform_admin" && (
        <TenantsConfig />
      )}
      {activeSubTab === "settings" && <Settings />}
    </div>
  );
}
