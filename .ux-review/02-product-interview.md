# Product-owner interview — Perkins Roofing operating platform

Status: COMPLETE
Phase: Product synthesis and interview
Last Updated: 2026-08-19
Inputs Used: `.ux-review/01-discovery.md`; owner answers in the active review; two August 2026 DeGenito–Perkins direction PDFs
Open Questions: None blocking UX strategy; sender identity remains a later Tim-owned policy decision
Blocking Findings: None
Next Recommended Phase: UX architecture and design directions

## Product synthesis

### What the product is

Perkins is becoming a branch operating system and control plane, not merely a video archive or marketing dashboard. It connects institutional knowledge and content, demand generation and attribution, lead response, estimating, proposals, electronic acceptance and payment into a measurable revenue lifecycle. Specialized systems remain around it: GHL for communication/automation/scheduling, CompanyCam for field media, a new public site for acquisition, and separate project-management software after the sale. CallRail is outside current scope unless later approved.

The strategic asset is the operating model: one place where corporate can see whether branches turn demand into revenue, branches can run their local pre-production work, and repeatable processes reduce dependence on Tim personally.

### Who it serves

- Corporate owner/brand leadership: Tim and authorized delegates who need cross-branch revenue, accountability, royalties, brand and operating oversight.
- Branch principals/managers: geographically scoped operators responsible for local lead response, appointments, estimates, proposals, customers and revenue.
- Multi-hat operating staff: estimators, salespeople, schedulers and back-office users whose responsibilities overlap in a small team.
- Marketing/content operators: people running the knowledge/content factory, publishing, attribution and campaign analysis.
- Customers/prospects: public-site visitors and proposal signers, with a possible future portal.
- Future franchisees: locally scoped businesses using Perkins processes without visibility into corporate or other branches unless explicitly granted.

### Core jobs-to-be-done

1. Capture and route every lead to the correct branch with reliable source attribution.
2. Make missed contact and appointment risk visible early enough for someone to recover the revenue.
3. Move a prospect from appointment through estimate, quote, proposal, signature and payment with little duplicate entry.
4. Give branch operators a focused view of their own pipeline, customers, financial outcomes and required actions.
5. Give corporate a cross-branch view of performance, exceptions, royalties and brand risk.
6. Turn field knowledge, media and completed work into reusable answers and marketing content with controlled automation.
7. Synchronize lifecycle events across the app and GHL without creating contradictory records.

### Most important workflows

1. Lead captured/called → attributed → routed → acknowledged/contacted → appointment scheduled and shown.
2. Appointment/inspection → estimate → quote → proposal sent → customer decision → payment/deposit.
3. Revenue-risk exception → branch ownership → escalation to Tim/corporate → resolution.
4. Branch performance review → pipeline/revenue/capacity/royalty interpretation → intervention.
5. Knowledge/media ingestion → content generation/review → controlled publishing and campaign reuse.
6. Customer/proposal/payment event → GHL stage synchronization and follow-up automation.

### Likely business priorities

1. Protect revenue by reducing uncontacted leads, missed appointments and stalled proposals.
2. Make branch performance accountable and comparable without exposing inappropriate corporate or peer-branch data.
3. Standardize a transferable operating system that scales beyond Tim and supports franchise growth.
4. Improve conversion and speed while preserving pricing, margin and brand controls.
5. Tie marketing spend to shown appointments and revenue, then scale only where branch capacity and economics support it.
6. Consolidate vendor workflows and institutional knowledge without forcing one tool to perform every specialized function.

### Major UX tensions

- Breadth versus focus: the platform spans marketing, knowledge and office operations, but most users need a narrow daily workspace.
- Lifecycle versus functional modules: the owner wants an event-driven funnel, while the existing product grew as feature areas.
- One source of truth versus specialist ownership: app-as-controller and GHL-as-lifecycle-manager can conflict unless authority is field/domain specific.
- Small-team flexibility versus least privilege: users wear several hats, but universal admin access defeats branch isolation and safe delegation.
- Corporate accountability versus branch privacy: Tim needs cross-branch intervention while branches should not see the whole system.
- Automation versus publication/financial risk: high-confidence AI can reduce work, but public content and consequential actions require explicit confidence and exception policies.
- Operational density versus simplicity: branch users need fast, information-rich work without inheriting the entire marketing factory.

### Technical constraints

- Existing auth/RLS provides a foundation, but effective permissions and cross-branch grants need a clearer server-enforced capability model.
- Styling and responsive behavior are distributed across large page modules, so future consistency work cannot be merely cosmetic.
- Authenticated UI evidence remains limited pending safe login access.
- Public proposal mutations have a known concurrency hazard that affects lifecycle truth and duplicate side effects.
- GHL configuration and actual stage/workflow semantics have not yet been inspected.
- External systems will deliver delayed, duplicate, partial and out-of-order events; event ownership and idempotency are product requirements.
- Post-sale production/project management is deliberately outside the current boundary.

## Decisions already supplied by the owner

- Revenue protection is the top priority; uncontacted leads and missed appointments are primary risks.
- Branch management owns local performance, with Tim ultimately accountable because compensation and brand risk follow revenue.
- Initial CallRail-attribution assumption — **superseded** by the 2026-08-20 clarification: CallRail is not approved and is out of scope.
- GHL handles automation, scheduling and lead lifecycle; app events should move GHL stages on proposal send, execution and payment.
- Branch users need operational/financial pre-production work plus FAQs/knowledge, not the corporate content factory.
- Corporate and explicitly authorized users require cross-branch views; branches otherwise remain geographically isolated.
- Chris initially receives broad access while helping define operating practice.
- Automate aggressively when confidence is at least 95%, while applying stronger gates to public-facing output.
- Post-sale execution remains out of scope.
- Branches pay a percentage of revenue to corporate.

## Round 1 answers and decision impact

- Lead paths are `web → app ↔ GHL` and `Facebook → GHL ↔ app`.
- GHL sub-accounts represent branch assignment.
- The app is authoritative for customer details. GHL is authoritative for branch calendars/appointments, communications and lead stage. CallRail is not approved and is out of scope.
- Email and phone are GHL's native duplicate keys. Editing an existing person's email instead of adding a spouse/contact can recreate a duplicate when the original identity returns through another channel.
- Changes can sync in either direction through workflows and webhooks, but conflict/loop policy remains unresolved.
- Funnel exceptions are first-class because they initiate recovery/drip campaigns; the happy path alone is insufficient.
- GHL should own speed-to-lead workflows and be inspected before defining new SLA behavior.
- Accountability chain is salesperson → sales manager → branch manager → Tim. Early-stage organizations may assign several of those responsibilities to one person.
- RBAC will remain comparatively broad in a small organization, while branch and sensitive-capability boundaries still require enforcement.

## Targeted GHL workflow inspection — 2026-08-19

### FACT

- Headless read-only inspection covered the Jupiter and Miami Perkins sub-accounts. No GHL configuration or contact data was changed.
- Both sub-accounts have the same 11 published workflow shapes with branch-specific calendar and pipeline identifiers: Facebook lead speed-to-lead/nurture; appointment confirmation/reminders; cancellation recovery; review request; long-term nurture; stale-lead alert; no-show recovery; quote follow-up; 30-minute escalation; post-job referral/annual check-up; and storm response.
- The GHL pipeline has six stages: `New Lead → Contacted / In Conversation → Inspection Booked → Inspection Complete / Quoted → Won → Lost / Nurture`.
- Facebook homeowner leads receive immediate automated SMS/email, create a New Lead opportunity, generate an internal notification requesting a call within five minutes, then receive a one-hour SMS, day-one email and day-three SMS before long-term nurture tagging. Renters receive a separate reply and DNC tag.
- Appointment booking adds `booked`, removes the contact from immediate/long-term nurture, moves the opportunity to Inspection Booked, and schedules 24-hour and two-hour reminders.
- Cancellation recovery waits 30 minutes before a rebook SMS. No-show recovery waits 15 minutes, then sends SMS, next-day email and adds long-term nurture.
- Quote follow-up begins at `Inspection Complete / Quoted` and sends follow-ups after 2, 5 and 10 cumulative days.
- Won triggers both review requests and post-job referral/annual-checkup sequences.
- `Stale Lead Alert` fires when an opportunity remains in New Lead for one day.
- `Uncalled Lead Escalation - 30 Min` does **not** inspect calls or human communication. It waits 30 minutes and checks only for absence of the `booked` tag. Its name and notification copy imply an uncalled lead, but its actual condition is “not booked.”
- Immediate, stale and 30-minute internal notifications use `userType: all`; they do not route through salesperson → sales manager → branch manager → Tim.
- Customer-facing speed-to-lead SMS/email messages identify the sender as Tim. This conflicts with the partnership document statement that automated texts should not pretend to be Tim.
- The current pipeline does not separately represent proposal sent, proposal accepted/executed, deposit received or paid. App-originated lifecycle events therefore have no direct one-to-one stage target today.
- Enrollment evidence is limited: Jupiter showed only a handful of historic enrollments and Miami showed zero in the workflow list. Configuration parity is verified; meaningful production effectiveness is not.

### INFERENCE

- GHL currently automates customer follow-up more completely than it enforces human accountability.
- Pipeline stage movement is being used as a proxy for completed work. If staff do not move cards promptly, alerts and reporting can be misleading.
- One `Lost / Nurture` stage cannot by itself explain which exception occurred or which recovery campaign should apply; tags, reasons or structured fields must carry that distinction.

## Integration-topology clarification — 2026-08-20

**Product-owner correction / decision:** GHL is in place for Perkins, but this application does not yet use it. The existing Perkins marketing sub-account should become Tim's corporate GHL account. Each branch should receive its own GHL sub-account/location. CallRail is **not approved** and is outside the current product scope.

This correction supersedes any earlier assumption that the app already integrates with GHL or that previously inspected sub-accounts define the approved target topology. Existing GHL workflows and data must be verified before moving or renaming any account; no GHL configuration change is authorized by this record.

**Recommended target model for later approval/planning:**

- One corporate GHL account/location for Tim's corporate marketing, portfolio oversight and cross-branch automation where appropriate.
- One GHL account/location for each geographically operated branch, owning its local calendar, communications and lead-stage workflow.
- App-side integration connections are scoped either `corporate` or to one `branch`; branch users never choose or supply another branch's credentials.
- Credentials are held server-side through a secret reference/connection record. An admin configuration page may show connection identity, health, last successful event and authorized remediation, but never exposes raw API keys to the browser, logs, or ordinary configuration data.
- The app remains authoritative for customer/contact/property, estimates, proposals, invoices, payment facts and operating visibility. GHL is authoritative for approved communication, calendar and opportunity/lifecycle automation.
- CallRail is neither assumed nor designed as a dependency until separately approved.

## Round 2 — contact identity and GHL operating truth

### 1. Customer versus contact identity

Problem: email/phone deduplication treats a person as a contact, while a roofing customer may be a household, property or project with a spouse and several contact methods.

Question: Should one app `Customer` represent the household/account and contain multiple named people/contacts, with each person linked to their own GHL contact?

### 2. Bidirectional edit conflicts

Problem: two-way sync can loop or overwrite newer data when the same field changes in both systems.

Question: Which fields may GHL change authoritatively versus merely propose back to the app? Should conflicts be app-wins, GHL-wins, latest-change-wins, or queued for review by field category?

### 3. Human speed-to-lead measurement

Problem: the current “uncalled” workflow measures booking, not a human call or response; automated SMS can make a contact look active while sales has done nothing.

Question: What event should satisfy the human-response SLA—first outbound call, answered call, personal SMS/email, any two-way conversation, or manual stage change? Should automated messages be excluded?

### 4. Lifecycle and exceptions in GHL

Problem: the current six-stage pipeline cannot distinguish proposal sent, accepted/executed, deposit/payment, or different loss/recovery reasons.

Question: Should GHL add explicit proposal/payment stages, or keep the coarse pipeline and store those milestones and exception reasons as structured fields/tags? Which exceptions require distinct drip campaigns?

### 5. Accountability routing

Problem: current alerts go to all users, so nobody is uniquely accountable and broad notifications will become noise.

Question: How is the responsible salesperson selected in each branch, and should escalation route to that person, then sales manager, branch manager and Tim—skipping duplicate recipients when one person holds several roles?

### 6. Customer-facing identity

Problem: the live workflows sign automated texts and emails as Tim, while the written direction says automation should not impersonate him.

Question: Should automated communication come from Tim, the assigned salesperson, a named branch representative, or “Perkins Roofing team”?

## Round 2 answers and decision impact

- Customer identity is already modeled in the app as `Customer → Contacts + Properties`, with corresponding UI. No new household/contact model is required.
- Automated initial response remains appropriate, but it does not satisfy human sales accountability. The app must expose human activity and absence of activity across email, notes, SMS and calls.
- GHL should gain explicit proposal and payment lifecycle stages. A prospect who tapers off before payment is a lost or at-risk revenue event with a reason, not merely an inactive record.
- Accepted-but-unpaid customers are a highest-priority sales exception. Sales should actively investigate why an accepted job has not converted to payment.
- Accountability escalation should be delivered through email notifications and digest reporting rather than an in-app alert cascade alone.
- Existing Tim-branded automation may continue for now. Tim should make the final sender-identity decision; the stated restriction is specifically against AI autonomously representing him.

## Round 3 — revenue-risk queue and reporting rules

### 1. Human-response deadline

Problem: GHL copy promises a call within five minutes, while the escalation waits 30 minutes and measures booking rather than human activity.

Question: What is the actual human-response SLA during business hours—5, 15 or 30 minutes—and what should happen to leads arriving after hours?

### 2. Activity versus meaningful contact

Problem: a note, unanswered call and two-way conversation are all activity, but they do not mean the same thing.

Question: Should the product distinguish `No human attempt`, `Attempted`, and `Connected`? Which events qualify for each state, and should a note alone ever clear an at-risk flag?

### 3. Revenue-risk priority

Problem: several exceptions compete for limited sales attention.

Question: Confirm or reorder this queue: `Accepted but unpaid → New lead with no human attempt → Appointment no-show/cancelled → Proposal sent with no response → Contacted but not booked → Long-term nurture`.

### 4. Required disposition reasons

Problem: `Lost / Nurture` does not explain what failed or select the correct recovery campaign.

Question: Which reasons should be mandatory before closing or nurturing an opportunity? Candidate set: unreachable, unqualified/renter, canceled, no-show, price, financing, competitor, deferred timing, scope mismatch, accepted but payment failed, and duplicate.

### 5. Email and digest cadence

Problem: notifying everyone immediately creates noise; waiting for a digest can hide urgent revenue leakage.

Question: Should the assigned salesperson receive immediate exception emails, the sales manager receive a daily unresolved digest, the branch manager receive a daily branch digest, and Tim receive a weekly cross-branch digest plus immediate notice only for accepted-but-unpaid or severely overdue items?

## Round 3 answers and decision impact

- During business hours, the assigned salesperson should receive repeated reminders until a verified human attempt occurs. At 60 minutes, ownership should move to another salesperson when possible; otherwise the sales manager should be alerted.
- A verified human outreach attempt satisfies the initial response SLA. Automated messages do not count as human activity. `Connected` remains analytically distinct from `Attempted`, even though either is no longer `No attempt`.
- Confirmed revenue-risk order: `Accepted but unpaid → New lead with no human attempt → Appointment no-show/cancelled → Proposal sent with no response → Contacted but not booked → Long-term nurture`.
- Terminal outcomes should be simplified to two primary classes: `Lost` and `Disqualified`.
- Confirmed notification policy: assigned salesperson receives immediate exception notices; sales manager and branch manager receive daily unresolved/branch digests; Tim receives a weekly cross-branch digest plus immediate notice for accepted-but-unpaid or severely overdue exceptions.

### Product-lead clarification

`Lost` and `Disqualified` are appropriate top-level outcomes, but they cannot replace a subordinate reason. Recovery behavior differs materially between price, competitor, deferred timing, unreachable, renter, duplicate and payment failure. The simple UX can expose two outcomes first, then require a short context-sensitive reason list for reporting and campaign selection.

## Round 4 — final workflow and information-architecture decisions

### 1. Reminder cadence and after-hours behavior

Problem: “repeat on that interval” is not yet a numeric rule, and an after-hours lead should not make a salesperson appear delinquent before the branch opens.

Recommended rule to confirm or correct: require the first human attempt within five business minutes; remind the salesperson every 15 minutes; at 60 minutes reassign to another available salesperson or alert the sales manager. After hours, send the automated acknowledgment immediately but start the human-response clock at the branch's next opening time.

### 2. Lost versus disqualified reasons

Problem: two terminal outcomes keep the funnel simple, but the system still needs a reason to choose recovery campaigns and explain lost revenue.

Recommended rule to confirm or correct: `Disqualified` covers renter/not decision-maker, out of service area, invalid/spam, duplicate and work outside scope. `Lost` covers unreachable, canceled/no-show, price, financing, competitor, deferred timing, proposal declined and accepted/payment failed. Require one reason after selecting the outcome, with an optional note.

### 3. Role-specific home experience

Problem: one generic dashboard cannot serve a salesperson trying to save today's revenue and Tim comparing branch performance equally well.

Recommended structure to confirm or correct: salespeople land on a prioritized personal work queue; sales/branch managers land on the branch risk queue plus team performance; Tim and authorized cross-branch users land on a portfolio view with branch comparison and drill-down. Multi-hat users can switch scope without changing accounts.

### 4. Primary device context

Problem: device priority materially changes density, navigation, task completion and what must work first in the redesign.

Question: For each group, where is most work actually done—phone, tablet, laptop/desktop, or a mix: salespeople/estimators in the field; sales and branch managers; Tim/corporate office users?

## Round 4 answers and decision impact

- The response policy is configurable, with these defaults: first human attempt within five business minutes; reminder every 15 minutes; at 60 minutes reassign to another available salesperson or alert the sales manager; after-hours human SLA begins at the branch's next opening time.
- Confirmed terminal model: users first select `Lost` or `Disqualified`, then provide a required context-specific reason and optional note. The reason drives reporting and the appropriate recovery or suppression behavior.
- Confirmed role-aware home experience: salesperson personal work queue; sales/branch manager branch risk and team performance; Tim/authorized corporate users cross-branch portfolio and drill-down; multi-hat users can switch scope without changing accounts.
- Primary devices are laptops and phones. Phones may expose a deliberately narrower, task-focused experience where rich datasets are unsuitable; full feature parity remains open.

### Product-lead recommendation on device parity

Prefer **workflow capability parity where it creates operational value**, not identical screen or feature density. A salesperson should be able to complete urgent field work from a phone without opening a laptop. Dense comparison, configuration, bulk operations and deep reporting should remain laptop-first unless evidence shows a meaningful mobile job. This keeps the mobile experience effective without maintaining two equally complex presentations of every administrative surface.

## Round 5 — configuration, mobile scope, identity safety and visual posture

### 1. SLA configuration authority

Problem: configurable response rules can undermine cross-branch accountability if every branch can silently relax them.

Recommended rule to confirm or correct: corporate owns the defaults and allowed range; a branch manager may adjust branch hours, reminder interval and reassignment target; changes are logged and visible to Tim. Only corporate may disable escalation or exceed the allowed response-time ceiling.

### 2. Phone-critical capabilities

Problem: “limited mobile” is only useful if it still covers the moments when field staff cannot wait for a laptop.

Recommended phone scope to confirm or correct: view prioritized work; call/text/open GHL communication; view customer, contacts and property; record an attempt/note; manage appointment status; capture estimate inputs/photos; review proposal status; collect or resend a signature/payment link. Keep configuration, bulk operations, deep reporting, content production and complex financial comparison laptop-first.

### 3. Contact-identity changes across systems

Problem: silently replacing an email or phone in GHL can detach the original person and later create a duplicate when that identity returns.

Recommended rule to confirm or correct: the app remains authoritative for the `Customer → Contacts → Properties` structure. A new email/phone from GHL is added or matched to a person when unambiguous; identity-changing or conflicting updates are flagged for review rather than overwriting or deleting the previous value. Sync operations carry source/time identifiers to prevent loops.

### 4. Visual posture and information density

Problem: the product must feel credible to roofing operators while supporting dense operational work; a marketing-heavy or generic SaaS appearance would obscure urgency.

Question: Should the application feel primarily like a restrained, high-density operations console with Perkins branding, or a more spacious and customer-friendly business application? Are there any products whose clarity, density or tone you want to emulate—or avoid?

## Round 5 answers and decision impact

- Confirmed SLA administration: corporate owns defaults and permitted bounds; branch managers may configure branch hours, reminder timing and reassignment targets within them; changes are logged and visible to authorized corporate users.
- Confirmed phone scope: urgent field and customer-facing workflows receive mobile capability parity, while configuration, bulk operations, content production, deep reporting and complex financial comparison remain laptop-first.
- Confirmed contact-identity policy: the app owns the customer/contact/property graph; unambiguous GHL values may be matched or added, but conflicting identity changes require review and never silently overwrite or discard prior contact information.
- Visual posture should balance form and function. The resulting direction should use purposeful information density for queues, lifecycle and reporting; calm spacing and progressive disclosure for comprehension; and restrained Perkins branding rather than decoration. Neither a cramped back-office interface nor an overly spacious marketing-style SaaS dashboard is appropriate.

## Round 6 — final lifecycle boundary

### Payment milestone and handoff

Problem: `Accepted` is not the same as financially committed, while “payment received” could mean a deposit, the full contract value, or any successful payment. The definition controls revenue-risk priority, GHL stage movement, reporting and the boundary with external project-management software.

Question: What event should mark the pre-production sale as won and ready for project-system handoff: proposal execution, required deposit received, any first payment received, full payment, or a configurable branch/job-type rule?

## Round 6 answer and decision impact

- The required deposit is configurable per branch.
- A sale becomes `Won` and ready for project-system handoff when the proposal is executed and that branch's required deposit has been successfully received.
- Proposal execution without the required deposit remains `Accepted — Payment Pending` and is the highest-priority revenue-risk exception.
- Full payment occurs later and does not block the pre-production handoff.

## Interview completion

The product-owner interview has resolved the decisions needed to begin UX architecture and design-direction work: domain ownership, lifecycle stages and exceptions, response SLA and escalation, accountability hierarchy, branch/corporate scope, terminal outcomes, notification cadence, role-aware home experiences, mobile/laptop priorities, contact-conflict behavior, visual posture, and the won/handoff boundary. No production implementation or redesign was performed in this phase.

## Round 1 — operating truth, accountability and access

### 1. Domain authority

Recommended boundary to confirm or correct:

- App: canonical branch/customer identity, estimates, quotes, proposals, acceptance/payment facts, knowledge, cross-system event ledger and corporate reporting.
- GHL: canonical communication activity, calendar/appointments and lead/opportunity workflow before quoting.
- CallRail: no current target ownership; it is unapproved and outside scope until separately approved.

Question: Is that the intended ownership model? In particular, when app and GHL disagree about a customer's contact details, assigned branch, appointment status or lead stage, which system wins for each field?

### 2. Canonical revenue lifecycle

Candidate lifecycle:

`Captured → Assigned → Contacted → Appointment booked → Appointment completed → Estimate created → Proposal sent → Accepted → Deposit/payment received → Project-system handoff`

Question: Is this the canonical funnel the product should organize around? Which side outcomes must be first-class—unqualified, unreachable, canceled, no-show, lost, revision requested, financing pending—and does “payment received” mean a deposit or full payment for the handoff?

### 3. Revenue-risk SLA and escalation

Question: What explicit promise defines an at-risk lead or appointment: time to acknowledge, time to first contact, number of attempts, and time to recover a no-show? Confirm whether escalation should progress from assigned person → branch manager → Tim, and whether clocks pause outside each branch's business hours.

Challenge: without an explicit SLA, the system can display activity but cannot reliably distinguish normal work from revenue leakage.

### 4. Capability and cross-branch access model

Recommendation: because three or four people wear several hats, grant composable capabilities rather than one exclusive job-title role, always constrained by branch scope unless a separate cross-branch grant exists.

Question: Should Chris's broad access be a named, reviewable cross-branch grant rather than permanent corporate-admin status? Which capabilities must remain separately grantable even for multi-hat users—margin/pricing, proposal approval, refunds/payments, publishing, user/security administration and corporate financial/royalty reporting?
