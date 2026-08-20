const risks = [
  {
    id: "martinez",
    branch: "Jupiter",
    name: "Marisol Martinez",
    property: "1426 Seabrook Way · Jupiter",
    risk: "Accepted — payment pending",
    priority: "critical",
    owner: "Sam R.",
    initials: "SR",
    action: "Call about required deposit",
    due: "37 min overdue",
    amount: "$18,400 contract",
    proposal: "PR-1048 · signed 9:12 AM",
    deposit: "$1,840 required · link delivered",
    payment: "Payment link delivered 9:13 AM · provider confirmation pending",
    activity: [
      ["Proposal accepted", "9:12 AM · app", "human"],
      ["Deposit link delivered", "9:13 AM · GHL", "sync"],
      ["No payment confirmation yet", "9:13 AM · payment provider", "sync"],
    ],
  },
  {
    id: "li",
    branch: "Jupiter",
    name: "Evan Li",
    property: "84 Seagate Drive · Jupiter",
    risk: "No human attempt",
    priority: "critical",
    owner: "You",
    initials: "JP",
    action: "Make first contact",
    due: "3 min left",
    amount: "$12,600 estimate",
    proposal: "Facebook lead · 2 min ago",
    activity: [
      ["Lead captured from Facebook", "2 min ago · GHL", "sync"],
      ["Automated acknowledgment sent", "2 min ago · GHL", "sync"],
      ["Awaiting human outreach", "now · app", "sync"],
    ],
  },
  {
    id: "douglas",
    branch: "Jupiter",
    name: "Heather Douglas",
    property: "311 Ocean Dunes Rd · Juno",
    risk: "Appointment cancelled",
    priority: "high",
    owner: "Tara M.",
    initials: "TM",
    action: "Offer a new time",
    due: "Due in 18 min",
    amount: "$9,800 estimate",
    proposal: "Inspection cancelled today",
    activity: [
      ["Customer cancelled inspection", "8:40 AM · GHL", "sync"],
      ["Recovery message scheduled", "8:55 AM · GHL", "sync"],
      ["No human rebook attempt", "now · app", "sync"],
    ],
  },
  {
    id: "ortiz",
    branch: "Jupiter",
    name: "Carlos Ortiz",
    property: "12 Coralberry Ct · Jupiter",
    risk: "Proposal needs follow-up",
    priority: "high",
    owner: "You",
    initials: "JP",
    action: "Review open questions",
    due: "Due today",
    amount: "$21,300 contract",
    proposal: "Proposal sent 5 days ago",
    activity: [
      ["Proposal viewed twice", "Yesterday · signing service", "sync"],
      ["Personal call logged", "3 days ago · app", "human"],
      ["No response since", "now · app", "sync"],
    ],
  },
  {
    id: "bennett",
    branch: "Jupiter",
    name: "Ruth Bennett",
    property: "708 Loxahatchee Dr · Tequesta",
    risk: "No-show recovery",
    priority: "high",
    owner: "Jared C.",
    initials: "JC",
    action: "Rebook inspection",
    due: "Due today",
    amount: "$14,100 estimate",
    proposal: "No-show at 10:00 AM",
    activity: [
      ["Inspection no-show", "10:15 AM · GHL", "sync"],
      ["Automated recovery sent", "10:30 AM · GHL", "sync"],
      ["Awaiting human call", "now · app", "sync"],
    ],
  },
  {
    id: "moore",
    branch: "Jupiter",
    name: "Diana Moore",
    property: "19 Atlantic Ave · Palm Beach",
    risk: "Connected, not booked",
    priority: "medium",
    owner: "Sam R.",
    initials: "SR",
    action: "Confirm inspection time",
    due: "Tomorrow",
    amount: "$16,800 estimate",
    proposal: "Spoke yesterday · no calendar hold",
    activity: [
      ["Two-way call completed", "Yesterday · app", "human"],
      ["Interested in inspection", "Yesterday · app", "human"],
      ["No appointment set", "now · app", "sync"],
    ],
  },
  {
    id: "reyes",
    branch: "Miami",
    name: "Ava Reyes",
    property: "88 Bay Harbor Dr · Miami",
    risk: "No human attempt",
    priority: "critical",
    owner: "Nia P.",
    initials: "NP",
    action: "Make first contact",
    due: "8 min overdue",
    amount: "$15,200 estimate",
    proposal: "Website lead · 13 min ago",
    activity: [
      ["Lead captured from website", "13 min ago · GHL", "sync"],
      ["Automated acknowledgment sent", "12 min ago · GHL", "sync"],
      ["Awaiting human outreach", "now · app", "sync"],
    ],
  },
  {
    id: "cho",
    branch: "Miami",
    name: "Daniel Cho",
    property: "230 Coral Gate · Miami",
    risk: "No human attempt",
    priority: "high",
    owner: "Luis G.",
    initials: "LG",
    action: "Make first contact",
    due: "Due in 4 min",
    amount: "$11,900 estimate",
    proposal: "Inbound inquiry · 1 min ago",
    activity: [
      ["Inbound inquiry recorded", "1 min ago · source system", "sync"],
      ["Lead created", "1 min ago · CRM", "sync"],
      ["Awaiting human outreach", "now · app", "sync"],
    ],
  },
  {
    id: "montgomery",
    branch: "Jupiter",
    name: "Charlotte Anne Montgomery-Smythe",
    property: "2147 North County Road 211, Building B · Palm Beach Gardens",
    risk: "Policy review required",
    priority: "high",
    owner: "You",
    initials: "JP",
    action: "Open payment review",
    due: "Due today",
    amount: "$38,975.42 contract",
    proposal: "PR-1061 · signed yesterday",
    deposit: "$3,897.54 required · evidence received",
    payment: "Policy review required · no eligibility decision",
    activity: [
      [
        "Provider payment evidence received",
        "Yesterday · payment provider",
        "sync",
      ],
      ["Configured policy is unavailable", "Today · app", "sync"],
      ["Commercial action blocked for review", "Now · app", "human"],
    ],
  },
  {
    id: "fischer",
    branch: "Naples",
    name: "Maya Fischer",
    property: "15 Gulfshore Blvd · Naples",
    risk: "Appointment capacity watch",
    priority: "medium",
    owner: "Mina D.",
    initials: "MD",
    action: "Confirm inspection capacity",
    due: "Tomorrow",
    amount: "$17,500 estimate",
    proposal: "Inspection requested tomorrow",
    activity: [
      ["Calendar slot requested", "Today · GHL", "sync"],
      ["Capacity review required", "now · app", "sync"],
    ],
  },
];

const scenarios = {
  manager: {
    eyebrow: "BRANCH OPERATIONS",
    title: "Protect today’s revenue",
    scope: "Jupiter Branch",
    metrics: ["$42,600", "92%", "7", "3 / 4"],
  },
  sales: {
    eyebrow: "YOUR WORK",
    title: "Make the next right move",
    scope: "Jupiter · Sales",
    metrics: ["$34,700", "100%", "3", "—"],
  },
  corporate: {
    eyebrow: "CORPORATE PORTFOLIO",
    title: "See branch risk before it costs revenue",
    scope: "All branches",
    metrics: ["$88,900", "89%", "19", "3 / 4"],
  },
  platform: {
    eyebrow: "PLATFORM OPERATIONS",
    title: "Keep product operations safe and observable",
    scope: "Platform Admin",
    metrics: ["3", "98%", "12", "—"],
  },
};
let selected = "martinez",
  demoState = "normal",
  activeScenario = "manager",
  activeBranch = "Jupiter",
  activeFilter = "all",
  attemptPending = false;
const queue = document.querySelector("#queue"),
  record = document.querySelector("#recordContent"),
  dialog = document.querySelector("#activityDialog"),
  toast = document.querySelector("#toast"),
  emptyState = document.querySelector("#emptyState"),
  stateButton = document.querySelector("#stateButton"),
  mobileMenu = document.querySelector(".mobile-menu");
const statusClass = (priority) =>
  priority === "critical"
    ? "critical"
    : priority === "high"
      ? "high"
      : "medium";
const isPhone = () => window.matchMedia("(max-width: 640px)").matches;
function scopedRiskList() {
  return risks.filter((r) => {
    if (activeScenario === "sales") return r.owner === "You";
    if (activeScenario === "corporate")
      return activeBranch === "All" || r.branch === activeBranch;
    return r.branch === "Jupiter";
  });
}
function matchesFilter(r) {
  if (activeFilter === "mine") return r.owner === "You";
  if (activeFilter === "due") return r.priority !== "medium";
  if (activeFilter === "payment")
    return Boolean(r.deposit) || r.risk.toLowerCase().includes("payment");
  return true;
}
function riskList() {
  return scopedRiskList().filter(matchesFilter);
}
function queueMarkup(list) {
  return list
    .map(
      (r, i) =>
        `<button class="risk-row ${selected === r.id ? "selected" : ""}" type="button" data-id="${r.id}" aria-label="Open ${r.name}; ${r.risk}; owner ${r.owner}; next action ${r.action}; ${r.due}; priority ${r.priority}"><div class="risk-customer"><span class="priority ${statusClass(r.priority)}">${i + 1}</span><span><span class="customer-name">${r.name}</span><span class="risk-detail">${r.property}</span><span class="status ${statusClass(r.priority)}">${r.risk}</span></span></div><span class="owner"><span class="initials">${r.initials}</span>${r.owner}</span><span class="next-action">${r.action}<small>${r.due}</small></span></button>`,
    )
    .join("");
}
function stateMarkup() {
  if (demoState === "loading")
    return '<div class="empty-state"><h3>Refreshing risk queue…</h3><p>Keeping the last confirmed action context while GHL activity is checked.</p></div>';
  if (demoState === "error")
    return '<div class="empty-state"><div class="empty-icon">!</div><h3>GHL activity is delayed</h3><p>Queue order is based on the last verified event at 10:18 AM. Retry checks the integration without changing the record.</p><button class="outline-button" type="button" data-state-action="retry">Retry sync</button></div>';
  if (demoState === "identity")
    return '<div class="empty-state"><div class="empty-icon">!</div><h3>Contact match needs review</h3><p>GHL supplied an email that conflicts with the existing contact. No identity data was overwritten.</p><button class="outline-button" type="button" data-state-action="identity">Review contact match</button></div>';
  return '<div class="empty-state"><div class="empty-icon">✓</div><h3>No urgent revenue risk</h3><p>Keep the pipeline moving or review long-term nurture.</p><button class="outline-button" type="button" data-state-action="pipeline">Open pipeline</button></div>';
}
function updateCopy(list) {
  let copy = "";
  if (activeScenario === "platform")
    copy =
      "Review platform health and restricted remediation. Customer data requires an explicit audited support scope.";
  else if (activeScenario === "sales")
    copy = `${list.length} customer${list.length === 1 ? "" : "s"} ${list.length === 1 ? "is" : "are"} waiting on you. Record a real outcome, then keep the follow-up visible.`;
  else if (activeScenario === "corporate")
    copy =
      activeBranch === "All"
        ? "Miami has two items requiring branch-manager follow-up. Open a branch to inspect its exceptions."
        : `${list.length} exception${list.length === 1 ? "" : "s"} in ${activeBranch}. Corporate drill-down is authorized and auditable.`;
  else
    copy = `${list.length} item${list.length === 1 ? "" : "s"} need attention in Jupiter${activeFilter === "all" ? ". Start with the accepted job waiting on its required deposit." : `. ${activeFilter === "payment" ? "Payment decisions stay blocked until their status is clear." : "Use the selected work view to act without losing ownership context."}`}`;
  document.querySelector("#introCopy").textContent = copy;
}
function renderQueue() {
  const list = riskList(),
    scoped = scopedRiskList(),
    filters = document.querySelectorAll(".filter"),
    current = list.find((r) => r.id === selected) || list[0];
  if (current) selected = current.id;
  document.querySelector("#queueCount").textContent = list.length;
  document.querySelector("#navRiskCount").textContent = scoped.length;
  filters.forEach((button) => {
    const filter = button.dataset.filter,
      count =
        filter === "all"
          ? scoped.length
          : scoped.filter((r) =>
              filter === "mine"
                ? r.owner === "You"
                : filter === "due"
                  ? r.priority !== "medium"
                  : Boolean(r.deposit) ||
                    r.risk.toLowerCase().includes("payment"),
            ).length;
    button.querySelector("span").textContent = count;
    button.classList.toggle("active", filter === activeFilter);
    button.setAttribute("aria-pressed", String(filter === activeFilter));
  });
  updateCopy(list);
  renderRecord(current);
  if (demoState === "normal" && list.length) {
    queue.hidden = false;
    queue.innerHTML = queueMarkup(list);
    emptyState.hidden = true;
    queue.querySelectorAll(".risk-row").forEach((el) =>
      el.addEventListener("click", () => {
        selected = el.dataset.id;
        renderQueue();
        if (isPhone()) {
          openMobileRecord(el);
        }
      }),
    );
  } else {
    queue.hidden = true;
    emptyState.hidden = false;
    emptyState.innerHTML = stateMarkup();
    emptyState
      .querySelector("[data-state-action]")
      ?.addEventListener("click", handleStateAction);
  }
}
function openAttempt(r) {
  if (!r) return;
  document.querySelector("#dialogContext").textContent =
    `${r.name} · ${r.property}`;
  dialog.showModal();
  document.querySelector("#attemptChannel").focus();
}
function renderRecord(r) {
  if (!r) {
    record.innerHTML = "";
    return;
  }
  const payment = r.deposit
    ? `<div class="record-field"><span>Required deposit</span><strong>${r.deposit}</strong></div><div class="record-field"><span>Payment status</span><strong>${r.payment}</strong></div>`
    : "";
  const identity = `<p class="identity-cue">Canonical person · Current operational relationship: ${r.branch} Branch</p><p class="identity-note">Cross-branch associations require an authorized, audited link.</p>`;
  const messageProvenance = `<section class="record-section"><h3>Automated outreach</h3><div class="message-provenance"><strong>Perkins Roofing — ${r.branch} Team</strong><small>Approved team sender · template provenance is retained with the communication event.</small></div></section>`;
  const policyReview = r.risk === "Policy review required";
  const actions = policyReview
    ? '<button class="primary-button review-action" type="button">Open payment review</button><button class="outline-button review-action" type="button">View payment evidence</button><p class="action-note">Only an authorized review may resolve this state. No customer outreach or commercial handoff is initiated here.</p>'
    : `<button class="primary-button contact-action" type="button" data-contact="Call">Call ${r.name.split(" ")[0]}</button><button class="outline-button contact-action" type="button" data-contact="Open CRM conversation">Open CRM conversation</button><button class="outline-button activity-trigger" type="button">Record human outcome</button>`;
  record.innerHTML = `<button class="sheet-close" type="button" aria-label="Back to revenue risk queue">← Back to queue</button><div class="record-top"><p class="eyebrow">CUSTOMER & PROPERTY</p><h2 id="recordTitle" tabindex="-1">${r.name}</h2><p>${r.property}</p>${identity}<span class="status ${statusClass(r.priority)}">${r.risk}</span></div><section class="record-section"><h3>What matters now</h3><div class="record-grid"><div class="record-field"><span>Potential revenue</span><strong>${r.amount}</strong></div><div class="record-field"><span>Owner</span><strong>${r.owner}</strong></div><div class="record-field"><span>Lifecycle</span><strong>${r.proposal}</strong></div><div class="record-field"><span>Next action</span><strong>${r.action}</strong></div>${payment}</div></section><section class="record-section"><h3>Activity & sync</h3><div class="activity">${r.activity.map((a) => `<div class="activity-item ${a[2]}">${a[0]}<small>${a[1]}</small></div>`).join("")}</div></section>${messageProvenance}<div class="record-actions">${actions}</div>`;
  record.querySelector(".sheet-close").addEventListener("click", () => {
    closeMobileRecord();
  });
  record
    .querySelectorAll(".contact-action")
    .forEach((button) =>
      button.addEventListener("click", () =>
        toastMessage(
          `${button.dataset.contact} action is represented in this prototype; record the verified outcome next.`,
        ),
      ),
    );
  record
    .querySelector(".activity-trigger")
    ?.addEventListener("click", () => openAttempt(r));
  record
    .querySelectorAll(".review-action")
    .forEach((button) =>
      button.addEventListener("click", () =>
        toastMessage(
          `${button.textContent} is restricted to an authorized review; commercial action remains blocked.`,
        ),
      ),
    );
}
let mobileRecordTrigger = null;
const mobileRecordBackground = () =>
  document.querySelectorAll(
    ".skip-link, .topbar, .content > :not(.workspace-grid), .workspace-grid > .queue-panel",
  );
function openMobileRecord(trigger) {
  const panel = document.querySelector(".record-panel");
  mobileRecordTrigger = trigger;
  mobileRecordBackground().forEach((element) => {
    element.inert = true;
    element.setAttribute("aria-hidden", "true");
  });
  panel.classList.add("mobile-open");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-labelledby", "recordTitle");
  window.setTimeout(() => document.querySelector("#recordTitle")?.focus(), 0);
}
function closeMobileRecord(returnFocus = true) {
  const panel = document.querySelector(".record-panel");
  panel.classList.remove("mobile-open");
  panel.removeAttribute("role");
  panel.removeAttribute("aria-modal");
  mobileRecordBackground().forEach((element) => {
    element.inert = false;
    element.removeAttribute("aria-hidden");
  });
  if (returnFocus) mobileRecordTrigger?.focus();
  mobileRecordTrigger = null;
}
function setScenario(next) {
  activeScenario = next;
  activeBranch = next === "corporate" ? "All" : "Jupiter";
  activeFilter = "all";
  const s = scenarios[next];
  document.querySelector("#roleEyebrow").textContent = s.eyebrow;
  document.querySelector("#title").textContent = s.title;
  document.querySelector("#scopeLabel").textContent = s.scope;
  document.querySelector("#workspaceName").textContent = s.scope;
  document.querySelector("#pageLabel").textContent =
    next === "platform" ? "Platform Operations" : "Today";
  document.querySelector("#integrationLabel").textContent =
    next === "platform" ? "Platform status current" : "Queue current";
  document.querySelector("#scenarioSummary").textContent =
    `Review scenario: ${next === "manager" ? "Branch manager" : next === "sales" ? "Salesperson" : next === "corporate" ? "Corporate" : "Platform admin"}`;
  [...document.querySelectorAll(".metric-strip strong")].forEach(
    (el, i) => (el.textContent = s.metrics[i]),
  );
  document.querySelectorAll(".scenario").forEach((b) => {
    const active = b.dataset.scenario === next;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", String(active));
  });
  document.querySelector(".corporate-metric").style.display =
    next === "sales" || next === "platform" ? "none" : "";
  document.querySelector(".metric-strip").hidden = next === "platform";
  document.querySelector("#portfolioSummary").hidden = next !== "corporate";
  document.querySelector("#platformPreview").hidden = next !== "platform";
  document.querySelector(".workspace-grid").hidden = next === "platform";
  document.querySelectorAll("[data-visible-to]").forEach((item) => {
    item.hidden = !item.dataset.visibleTo.split(" ").includes(next);
  });
  document.querySelector(".record-panel").classList.remove("mobile-open");
  renderQueue();
  toastMessage(
    next === "corporate"
      ? "Portfolio view loaded — select a branch for its exceptions."
      : next === "platform"
        ? "Platform-admin navigation preview loaded — mock data only."
        : "Scenario updated — mock data only.",
  );
}
function selectBranch(branch) {
  activeBranch = branch;
  const metrics = {
      Jupiter: ["$42,600", "92%", "7", "On target"],
      Miami: ["$27,100", "76%", "5", "Manager follow-up"],
      Naples: ["$17,500", "89%", "4", "Capacity watch"],
    }[branch],
    notes = {
      Jupiter: [
        "↑ $18,400 needs action",
        "5-minute business-hours target",
        "2 awaiting outcome",
        "Jupiter is on target",
      ],
      Miami: [
        "↑ $15,200 needs action",
        "5-minute business-hours target",
        "1 awaiting outcome",
        "Two unattempted leads",
      ],
      Naples: [
        "↑ $17,500 needs action",
        "5-minute business-hours target",
        "4 inspections tomorrow",
        "Capacity review required",
      ],
    }[branch];
  document.querySelector("#scopeLabel").textContent = `${branch} Branch`;
  document.querySelector("#workspaceName").textContent = `${branch} Branch`;
  [...document.querySelectorAll(".metric-strip strong")].forEach(
    (el, i) => (el.textContent = metrics[i]),
  );
  [...document.querySelectorAll(".metric-strip small")].forEach(
    (el, i) => (el.textContent = notes[i]),
  );
  selected = riskList()[0]?.id || selected;
  renderQueue();
  toastMessage(
    `${branch} branch exceptions loaded — mock corporate drill-down.`,
  );
}
function handleStateAction(event) {
  const action = event.currentTarget.dataset.stateAction;
  if (action === "retry") {
    demoState = "loading";
    renderQueue();
    window.setTimeout(() => {
      demoState = "normal";
      renderQueue();
      toastMessage(
        "Integration check complete — showing last confirmed queue.",
      );
    }, 650);
  } else if (action === "identity") {
    demoState = "normal";
    selected = "li";
    renderQueue();
    toastMessage(
      "Identity review is required before any contact data is changed.",
    );
  } else toastMessage("Pipeline is outside this focused prototype.");
}
function toastMessage(message) {
  toast.hidden = false;
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(window.toastTimer);
  window.toastTimer = window.setTimeout(() => {
    toast.classList.remove("show");
    toast.hidden = true;
  }, 3600);
}
document.querySelectorAll("[data-prototype-unavailable]").forEach((control) =>
  control.addEventListener("click", (event) => {
    event.preventDefault();
    closeMobileNav(false);
    toastMessage(
      `${control.dataset.prototypeUnavailable} is a documented workspace boundary in this focused prototype.`,
    );
  }),
);
document
  .querySelectorAll(".scenario")
  .forEach((button) =>
    button.addEventListener("click", () =>
      setScenario(button.dataset.scenario),
    ),
  );
document.querySelectorAll(".filter").forEach((button) =>
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    demoState = "normal";
    renderQueue();
    toastMessage(
      `${button.textContent.trim().replace(/\s+\d+$/, "")} view applied — mock data only.`,
    );
  }),
);
document
  .querySelectorAll("[data-branch]")
  .forEach((button) =>
    button.addEventListener("click", () => selectBranch(button.dataset.branch)),
  );
stateButton.addEventListener("click", () => {
  demoState =
    demoState === "normal"
      ? "loading"
      : demoState === "loading"
        ? "error"
        : demoState === "error"
          ? "identity"
          : demoState === "identity"
            ? "empty"
            : "normal";
  stateButton.textContent =
    demoState === "normal"
      ? "View states"
      : demoState === "loading"
        ? "Show integration error"
        : demoState === "error"
          ? "Show contact conflict"
          : demoState === "identity"
            ? "Show empty state"
            : "Restore queue";
  renderQueue();
});
const drawerClose = document.querySelector(".drawer-close"),
  drawerScrim = document.querySelector(".drawer-scrim"),
  surface = document.querySelector(".surface");
function closeMobileNav(returnFocus = true) {
  document.body.classList.remove("nav-open");
  mobileMenu.setAttribute("aria-expanded", "false");
  mobileMenu.setAttribute("aria-label", "Open navigation");
  drawerScrim.hidden = true;
  surface.inert = false;
  if (returnFocus) mobileMenu.focus();
}
function openMobileNav() {
  document.body.classList.add("nav-open");
  mobileMenu.setAttribute("aria-expanded", "true");
  mobileMenu.setAttribute("aria-label", "Close navigation");
  drawerScrim.hidden = false;
  surface.inert = true;
  drawerClose.focus();
}
mobileMenu.addEventListener("click", () =>
  document.body.classList.contains("nav-open")
    ? closeMobileNav()
    : openMobileNav(),
);
drawerClose.addEventListener("click", () => closeMobileNav());
drawerScrim.addEventListener("click", () => closeMobileNav());
document
  .querySelectorAll("#primaryNav a")
  .forEach((link) =>
    link.addEventListener("click", () => closeMobileNav(false)),
  );
document.addEventListener("keydown", (event) => {
  const mobileRecord = document.querySelector(".record-panel");
  if (mobileRecord.classList.contains("mobile-open")) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMobileRecord();
      return;
    }
    if (event.key === "Tab") {
      const focusable = [
          ...mobileRecord.querySelectorAll(
            "button:not([disabled]), [href], select, textarea",
          ),
        ],
        first = focusable[0],
        last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    return;
  }
  if (!document.body.classList.contains("nav-open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeMobileNav();
    return;
  }
  if (event.key === "Tab") {
    const focusable = [
      drawerClose,
      ...document.querySelectorAll(
        ".sidebar a,.sidebar button:not([disabled])",
      ),
    ].filter((item, index, array) => array.indexOf(item) === index);
    const first = focusable[0],
      last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
document.querySelector("#activityForm").addEventListener("submit", (event) => {
  event.preventDefault();
  if (attemptPending) return;
  const item = risks.find((r) => r.id === selected),
    button = document.querySelector("#saveAttempt");
  attemptPending = true;
  button.textContent = "Recording…";
  button.disabled = true;
  window.setTimeout(() => {
    const outcome = document.querySelector("#attemptOutcome").value,
      priorRisk = item.activity.find((a) => a[0] === "Awaiting human outreach");
    if (priorRisk) {
      priorRisk[0] = "No-human-attempt risk superseded";
      priorRisk[1] = "just now · app";
    }
    item.activity.unshift([
      "GHL activity sync pending",
      "just now · app event queued",
      "sync",
    ]);
    item.activity.unshift([
      outcome === "connected"
        ? "Two-way conversation recorded"
        : "Human outreach attempt recorded",
      "just now · verified user entry",
      "human",
    ]);
    item.risk =
      outcome === "connected"
        ? "Connected — follow-up due"
        : "Attempted — follow-up due";
    item.priority = "medium";
    item.action = "Complete scheduled follow-up";
    item.due = "Follow up tomorrow";
    dialog.close();
    button.textContent = "Log attempt";
    button.disabled = false;
    attemptPending = false;
    renderQueue();
    toastMessage(
      outcome === "connected"
        ? "Conversation recorded in app · GHL sync pending."
        : "Attempt recorded in app · follow-up remains visible.",
    );
  }, 600);
});
renderQueue();
