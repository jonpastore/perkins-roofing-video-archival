import { useState } from "react";
import { BRAND, PageTitle } from "../ui";
import { ComposeEmail } from "./ComposeEmail";
import { Templates } from "./Templates";

type EmailTab = "compose" | "templates";

export function Email() {
  const [activeTab, setActiveTab] = useState<EmailTab>("compose");

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>Email</PageTitle>

      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          borderBottom: `1px solid ${BRAND.border}`,
          marginBottom: 24,
        }}
      >
        {(["compose", "templates"] as EmailTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "10px 20px",
              border: "none",
              borderBottom: activeTab === tab ? `2px solid ${BRAND.red}` : "2px solid transparent",
              background: "none",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: activeTab === tab ? 700 : 500,
              color: activeTab === tab ? BRAND.navyText : BRAND.sub,
              marginBottom: -1,
            }}
          >
            {tab === "compose" ? "Compose" : "Templates"}
          </button>
        ))}
      </div>

      {activeTab === "compose" && <ComposeEmail />}
      {activeTab === "templates" && <Templates />}
    </main>
  );
}
