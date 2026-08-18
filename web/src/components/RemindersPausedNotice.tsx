import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND } from "../ui";

export function RemindersPausedNotice() {
  const [paused, setPaused] = useState(true);

  useEffect(() => {
    apiFetch("/config/job-switches")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { proposal_reminders?: boolean } | null) => {
        if (!data) return;
        setPaused(data.proposal_reminders !== true);
      })
      .catch(() => undefined);
  }, []);

  if (!paused) return null;
  return (
    <div
      style={{
        marginBottom: 16,
        padding: "10px 14px",
        borderRadius: 8,
        border: `1px solid ${BRAND.border}`,
        background: "#fff8e8",
        fontSize: 13,
        color: BRAND.navyText,
        lineHeight: 1.45,
      }}
    >
      Customer proposal reminders are off. Open proposals will not get a follow-up email
      until an admin turns them on under Admin Config → Platform Settings.
    </div>
  );
}
