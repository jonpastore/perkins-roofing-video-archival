# TRD-F1 — Information Architecture Reorg (Sidebar)

**Wave:** F1  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Date:** 2026-07-08  
**Estimate:** 1–2 sessions  
**Depends on:** F0 (thin tenancy must be merged first)  
**Blocks:** F3 (mobile acceptance criterion references F1's sidebar structure)  

---

## 1. Scope & non-goals

### In scope
- Two-level sidebar: four content sections (Knowledge Base, Marketing, Estimating, Quoting) plus Admin
- All existing tab keys preserved as internal route identifiers — no broken bookmarks, no lost state
- Section group headers in the sidebar nav (collapsible on mobile)
- Admin config-tab shell: six tabs (KB / Marketing / Estimating / Quoting / Users & Roles / Tenants) — the Tenants tab is platform_admin only (hidden for all current roles); the other five are admin-only shells with placeholder content for now
- Existing `Users` and `Settings` pages fold into Admin → Users & Roles tab
- Role gating: which sections and tabs are visible per role, using the existing `admin / web_admin / sales` roles
- New section-scoped authz action names defined (backend enforcement added per-endpoint as F2/F3 wire up)
- Mobile: sidebar collapses to a hamburger; owner sales flow (Estimator → Quoting) must work on a phone
- `npm run build` (tsc + vite) stays green throughout

### Non-goals (explicitly deferred)
- Actual page content for placeholder tabs (Quoting section → F3; Admin config tab content → F2/F3/F5)
- Backend enforcement of new section-scoped actions on existing endpoints (those endpoints remain gated by their current action; new actions gate new endpoints in F2/F3)
- GCIP / tenant resolution UI → F4/F6
- Tenant provisioning UI → F6
- Per-tenant SSO → F6
- Any new pages other than the Admin config shell

---

## 2. Current route → new section mapping

This is the exact mapping from the `ROLE_CONFIG` tab keys in `web/src/App.tsx` (commit `b19b34b`) to their new section homes. **Tab key strings are frozen** — they are the internal identifiers used by `useState` / `handleTabClick` / `navigate()`. Only the sidebar grouping changes.

| Tab key (frozen) | Current label | New section | New label (if changed) | Notes |
|---|---|---|---|---|
| `dashboard` | Dashboard | (top-level, above sections) | Dashboard | Pinned above section groups; visible to all roles |
| `search-ask` | Search / Ask | Knowledge Base | Search / Ask | |
| `faq` | FAQ | Knowledge Base | FAQ | |
| `archive` | Archive | Knowledge Base | Archive / Corpus | Label update |
| `opportunities` | Content Opportunities | Marketing | Opportunities | |
| `articles` | Articles | Marketing | Articles | |
| `scheduling` | Content Scheduling | Marketing | Scheduling | Label update |
| `clip-studio` | Clip Studio | Marketing | Clip Studio | |
| `comments` | Comments | Marketing | Comments | |
| `email` | Email | Marketing | Email | |
| `video-approval` | Video Approval | Marketing | Video Approval | |
| `estimator` | Estimator | Estimating | Estimator | |
| *(new)* | — | Quoting | Quoting | Placeholder page; tab key `quoting` |
| `users` | Users | Admin | Users & Roles | Folds into Admin config shell |
| `config` | Config | Admin | Config (Settings) | Folds into Admin config shell |
| `logs` | Logs | Admin | Logs | Stays in Admin section |

**New tab keys added in F1:**
- `quoting` — placeholder page component (`Quoting.tsx`) with "Coming in F3" message
- `admin-config` — Admin config shell component (`AdminConfig.tsx`) with six sub-tabs

**Removed from top-level tab list** (absorbed):
- `users` and `config` no longer appear as standalone sidebar items; they become sub-tabs inside `admin-config`

---

## 3. UI architecture

### 3a. New sidebar structure

The sidebar gains a two-level layout: section group headers + item rows. The existing `NavButton` component and `AdminSectionDivider` component are reused; section group headers follow the same visual pattern as `AdminSectionDivider` but are labelled with the section name.

```
[Logo + title]
─────────────────
Dashboard            ← pinned top, always visible

KNOWLEDGE BASE
  Search / Ask
  FAQ
  Archive / Corpus
  Contract-FAQ        ← placeholder, tab key: contract-faq (admin/web_admin only)

MARKETING
  Opportunities       ← badge: opp count
  Articles
  Scheduling
  Clip Studio
  Comments            ← badge: comment_drafts
  Email
  Video Approval      ← badge: pending approvals
  Status              ← tab key: dashboard (reused; see note below)

ESTIMATING
  Estimator

QUOTING
  Quoting             ← placeholder, tab key: quoting

── Admin ──          ← AdminSectionDivider (unchanged visual)
  Admin Config        ← tab key: admin-config (replaces users + config as sidebar items)
  Logs
─────────────────
[Sign out]
```

**Note on `Status` / `dashboard`:** The current `dashboard` tab renders `<Status />`. Under the new IA, "Status" is a Marketing-level operational view (pipeline health, social post queue). It remains mapped to tab key `dashboard` and renders `<Status />` unchanged. It appears at the bottom of the Marketing section for admin/web_admin roles; the sales role does not see it (sales sees Estimator directly).

**`contract-faq` placeholder:** Tab key `contract-faq`, renders a `<ContractFaq />` stub component with "Coming soon" text. Visible to admin and web_admin only (not sales). This is in Knowledge Base per the plan §2.

### 3b. `ROLE_CONFIG` redesign

The existing flat `tabs` + `adminTabs` structure in `ROLE_CONFIG` is replaced with a section-aware structure. To preserve backward compatibility with `navigate()` and `handleTabClick()`, the underlying tab key system is unchanged — only the rendering layer changes.

New structure:

```typescript
interface SectionConfig {
  label: string;           // display name of the section group header
  tabs: [string, string][]; // [tab_key, display_label]
}

interface ShellConfig {
  title: string;
  pinnedTabs: [string, string][];   // rendered above sections (Dashboard)
  sections: SectionConfig[];        // the four content sections
  adminSection?: SectionConfig;     // rendered after AdminSectionDivider
  defaultTab: string;
}
```

**`admin` role config:**

```typescript
{
  title: "Perkins Admin",
  pinnedTabs: [["dashboard", "Dashboard"]],
  sections: [
    {
      label: "Knowledge Base",
      tabs: [
        ["search-ask", "Search / Ask"],
        ["faq", "FAQ"],
        ["archive", "Archive / Corpus"],
        ["contract-faq", "Contract-FAQ"],
      ],
    },
    {
      label: "Marketing",
      tabs: [
        ["opportunities", "Opportunities"],
        ["articles", "Articles"],
        ["scheduling", "Scheduling"],
        ["clip-studio", "Clip Studio"],
        ["comments", "Comments"],
        ["email", "Email"],
        ["video-approval", "Video Approval"],
        ["status-view", "Status"],  // see note: renders <Status />, key distinct from "dashboard"
      ],
    },
    {
      label: "Estimating",
      tabs: [["estimator", "Estimator"]],
    },
    {
      label: "Quoting",
      tabs: [["quoting", "Quoting"]],
    },
  ],
  adminSection: {
    label: "Admin",
    tabs: [
      ["admin-config", "Admin Config"],
      ["logs", "Logs"],
    ],
  },
  defaultTab: "dashboard",
}
```

**`web_admin` role config:** Same sections as admin except:
- No `email` tab (web_admin cannot email)
- No `admin-config` tab (no config access)
- `logs` removed from admin section
- `contract-faq` placeholder visible (web_admin manages KB content)

**`sales` role config:** No sections; flat list (sales role sees a simplified view):
- Pinned: none
- Single implicit section containing: `search-ask`, `email`, `estimator`, `quoting`
- No Admin section

**Implementation note:** The `sales` role can keep the existing flat rendering (no section headers) since it has so few tabs. A simple flag `useSections: boolean` on `ShellConfig` handles this without branching the render path.

### 3c. Admin config shell — `AdminConfig.tsx`

New component at `web/src/pages/AdminConfig.tsx`. Six sub-tabs rendered as a horizontal tab bar inside the content area (not the sidebar — the sidebar just shows "Admin Config"):

| Sub-tab key | Label | Content in F1 | Future content |
|---|---|---|---|
| `kb` | Knowledge Base | Placeholder ("Config coming in F5") | Corpus sources, ingest controls, abstain threshold, FAQ policy |
| `marketing` | Marketing | Placeholder | Brand kit, voice samples, caption prompts, social accounts, safety-gate denylist |
| `estimating` | Estimating | Placeholder ("Config coming in F2") | Branches, pricing-config editor, code-zone defaults, measurement provider |
| `quoting` | Quoting | Placeholder ("Config coming in F3") | Proposal templates, T&C library, deposit policy, reminder cadence |
| `users-roles` | Users & Roles | Embeds existing `<Users />` component (zero regression) | Per-tenant default admins |
| `tenants` | Tenants | Hidden — rendered only for `platform_admin` role (does not exist yet; skip render in F1) | Tenant provisioning, GCIP tenant, invite admin, usage metering |

The `tenants` sub-tab is conditionally rendered: `role === 'platform_admin'` (which no current user has — so it is invisible in F1). This avoids any stub-visible leak and requires no future removal surgery when `platform_admin` is added in F4.

The existing `<Settings />` component (currently at tab key `config`) is embedded as a sub-component inside `AdminConfig.tsx` or rendered as an additional sub-tab (implementation choice: embed under the most relevant config sub-tab, or add a "Platform Settings" sub-tab). The simplest correct approach: add a seventh sub-tab `settings` / "Platform Settings" that embeds `<Settings />`, visible to admin only. This preserves Settings functionality with zero regression.

### 3d. Mobile sidebar

The sidebar must collapse on narrow viewports (< 768px breakpoint). Implementation:

- A hamburger button (`☰`) appears in the top-left corner when the viewport is < 768px
- The sidebar overlays as a drawer (position: fixed, z-index: 200, width: 280px) when open
- Tapping any nav item closes the drawer
- A backdrop overlay closes the drawer on tap-outside
- The content area fills 100% width when the sidebar is closed
- This is pure CSS + React state (`sidebarOpen: boolean`) — no new dependencies

The owner flow that must work on mobile: navigate to Estimating → Estimator → fill in a quote → navigate to Quoting → create/send proposal. Both sections must be reachable from the collapsed sidebar.

---

## 4. APIs & contracts

F1 is SPA-heavy. No new API endpoints are required in F1.

### 4a. New authz action names (defined now, enforced per-endpoint in F2/F3)

**§11 is the single normative registry of all section-scoped action strings.** This section
summarises the role assignments; implementors must use §11's exact strings in `core/authz.py`
and all `require_role()` calls. Do not add strings here that are not in §11.

Role summary (exact strings from §11):

- **`web_admin`** gains: `kb_search`, `kb_ask`, `kb_faq_read`, `kb_faq_manage`,
  `kb_archive_read`, `kb_archive_manage`, `kb_contract_faq_read`,
  `marketing_opportunities`, `marketing_articles`, `marketing_schedule`,
  `marketing_clips`, `marketing_comments`, `marketing_video_approval`, `marketing_status`,
  `estimating_view`, `estimating_manage`,
  `quoting_view`, `quoting_create`, `quoting_send`,
  `admin_users`.
- **`sales`** gains: `kb_search`, `kb_ask`, `estimating_view`,
  `quoting_view`, `quoting_create`, `quoting_send`.
- **`admin`**: retains `"*"` wildcard — covers all new actions automatically.
- **`platform_admin`**: `admin_tenants`, `admin_users` (see §11 and TRD-F4 for
  session/impersonation mechanics).

These new actions do not replace the existing fine-grained actions (`search`, `ask`,
`manage_articles`, etc.) — both coexist. Existing endpoints keep their existing action
checks. New F2/F3 endpoints use section-scoped actions from §11.

### 4b. `ROLE_CONFIG` / `ShellConfig` type contract (TypeScript)

The new `ShellConfig` interface (§3b) is the internal contract between `App.tsx` and `Shell`. It is not an API — it is a module-level type. No external API change.

---

## 5. New files

| File | Purpose |
|---|---|
| `web/src/pages/AdminConfig.tsx` | Admin config shell with six sub-tabs |
| `web/src/pages/Quoting.tsx` | Placeholder Quoting section page |
| `web/src/pages/ContractFaq.tsx` | Placeholder Contract-FAQ page |

### Modified files

| File | Change |
|---|---|
| `web/src/App.tsx` | Replace `ShellConfig` type + `ROLE_CONFIG` + `Shell` render logic with section-aware version; add mobile sidebar; import three new pages |
| `core/authz.py` | Add section-scoped action names to `_MATRIX` for `web_admin` and `sales` |

---

## 6. TEST PLAN — fail-first TDD sequence

**Web test infrastructure:** `web/package.json` has NO test runner (`vitest`, `jest`, or `@testing-library/react` are absent). The web gate for F1 is therefore:

1. `npm run build` (tsc + vite build) — must stay green at every step
2. `scripts/validate_f1_routes.py` — a hermetic behavioral check (see below)
3. Manual QA checklist (see below) — required for R1's "behavioral validation for new I/O code" clause

**Backend test gate:** `pytest tests/ --cov=core --cov-fail-under=97 -q` — must stay green. The authz additions to `core/authz.py` are tested via `tests/test_f1_authz.py`.

### Red tests to write BEFORE implementation

**Group 1 — Backend authz additions (`tests/test_f1_authz.py`)**

```
test_web_admin_can_kb_search
    can("web_admin", "kb_search") == True
    Red reason: "kb_search" not in web_admin matrix yet.

test_web_admin_can_marketing_clips
    can("web_admin", "marketing_clips") == True
    Red reason: not in matrix.

test_web_admin_can_estimating_manage
    can("web_admin", "estimating_manage") == True
    Red reason: not in matrix.

test_sales_can_quoting_create
    can("sales", "quoting_create") == True
    Red reason: not in matrix.

test_sales_cannot_kb_faq_manage
    can("sales", "kb_faq_manage") == False
    Red reason (inverted — passes before implementation, so write it AFTER the
    positive tests are green to confirm the matrix boundary is tight).

test_admin_can_all_section_actions
    For each new action name, can("admin", action) == True (covered by wildcard).
    Red reason: actions don't exist yet, but wildcard means this is vacuously
    True — this test validates the wildcard still works after the refactor.

test_unknown_role_denied_all_section_actions
    can("unknown_role", "kb_search") == False
    Red reason: defensive; passes before implementation (unknown role always denied).
    Write it to nail down the boundary explicitly.
```

**Group 2 — TypeScript build gate (run as a subprocess in a validate script)**

```
test_npm_build_passes_after_app_tsx_change
    subprocess.run(["npm", "run", "build"], cwd="web/", check=True)
    Red reason: new imports (AdminConfig, Quoting, ContractFaq) referenced before
    the files are created → tsc error.
```

**Group 3 — Route completeness behavioral check (`scripts/validate_f1_routes.py`)**

Write this script before touching `App.tsx`. It parses the TypeScript source (as text) and asserts:

```python
REQUIRED_TAB_KEYS = [
    "dashboard", "search-ask", "faq", "archive", "contract-faq",
    "opportunities", "articles", "scheduling", "clip-studio",
    "comments", "email", "video-approval", "estimator",
    "quoting", "admin-config", "logs",
    # legacy keys that must still render something (no 404-equivalent):
    "users", "config",   # absorbed into admin-config; users key retired from sidebar
                          # but TabContent must still handle them or redirect gracefully
]

# Assert every key appears in TabContent's render switch in App.tsx
# Assert every key in the admin role's section list appears in REQUIRED_TAB_KEYS
# Assert no tab key that existed in the OLD config is missing from the new config
```

**Manual QA checklist (R1 behavioral validation — must be signed off before F1 done):**

- [ ] Sign in as `admin` — all four sections visible in sidebar; each section header is labelled correctly
- [ ] Click every tab in every section — correct page renders, no blank screen
- [ ] Click "Admin Config" — six sub-tabs render; "Users & Roles" sub-tab shows the Users page correctly (invite, role-set, delete still work)
- [ ] Click "Users & Roles" — existing Users UI fully functional (no regression)
- [ ] Click "Platform Settings" sub-tab inside Admin Config — Settings page renders
- [ ] Sign in as `web_admin` — Knowledge Base, Marketing, Estimating sections visible; no Admin section; no Email tab
- [ ] Sign in as `sales` — only Search/Ask, Email, Estimator, Quoting visible; no section headers (flat list)
- [ ] Mobile (devtools 390px viewport): hamburger appears; tap opens sidebar drawer; tap a tab — drawer closes, page renders; owner flow Estimator → Quoting reachable
- [ ] Old bookmarks: navigate to `/?tab=articles` (if URL routing exists) or simulate by setting React state — page still renders Articles (tab key preserved)
- [ ] `npm run build` — green with zero TypeScript errors

---

## 7. Implementation steps

TDD order — write the failing test first for each group before implementing:

1. Write `tests/test_f1_authz.py` Group 1 tests (all red except the two boundary tests). Run: `pytest tests/test_f1_authz.py -x`.
2. Update `core/authz.py`: add section-scoped actions to `web_admin` and `sales` matrices. Run Group 1 tests → green.
3. Run full suite: `pytest tests/ --cov=core --cov-fail-under=97 -q` — must be green.
4. Write `scripts/validate_f1_routes.py` (Group 3 script). Run it against the current `App.tsx` — it should fail because the new tab keys don't exist yet.
5. Create placeholder page components:
   - `web/src/pages/Quoting.tsx` — renders a card: "Quoting — Coming in F3"
   - `web/src/pages/ContractFaq.tsx` — renders a card: "Contract FAQ — Coming in F5"
   - `web/src/pages/AdminConfig.tsx` — six sub-tabs; `users-roles` embeds `<Users />`; `settings` embeds `<Settings />`; others render placeholder cards
6. Run `npm run build` from `web/` — should fail (App.tsx not yet updated → new imports missing).
7. Rewrite `web/src/App.tsx`:
   - Add new `ShellConfig` / `SectionConfig` types
   - Replace `ROLE_CONFIG` entries with section-aware configs (§3b)
   - Update `Shell` component to render section group headers + items
   - Add mobile sidebar collapse logic (hamburger + drawer)
   - Update `TabContent` to handle new tab keys (`quoting`, `admin-config`, `contract-faq`)
   - Remove `users` and `config` from sidebar (they are now sub-tabs inside `admin-config`), but keep them in `TabContent` as no-ops or redirects for defensive backward compat
   - Import new page components
8. Run `npm run build` — must be green (Group 2 test passes).
9. Run `scripts/validate_f1_routes.py` — must pass (Group 3).
10. Complete manual QA checklist.
11. Run full backend suite: `pytest tests/ --cov=core --cov-fail-under=97 -q` — still green.
12. Run `ruff check core adapters api jobs` — clean.
13. Commit on `feat/f1-ia-reorg`.

---

## 8. Exit gate

All of the following must be true before F1 is "done":

- [ ] `pytest tests/test_f1_authz.py` — all Group 1 tests green
- [ ] `pytest tests/ --cov=core --cov-fail-under=97 -q` — green (full suite unbroken)
- [ ] `ruff check core adapters api jobs` — clean
- [ ] `npm run build` (from `web/`) — zero TypeScript errors, zero vite build errors
- [ ] `scripts/validate_f1_routes.py` — passes (all tab keys present, all sections mapped)
- [ ] Manual QA checklist — all items checked (documented in wave notes)
- [ ] R2: architect + critic review — no unaddressed HIGH findings
- [ ] R4: `scripts/drift_check.sh` — clean (F1 is pure SPA + authz; no infra changes)

---

## 9. Rollout / rollback

### Deploy
F1 is a Firebase Hosting deploy (SPA-only; no API change):

```bash
# Must have a clean git tree (R3-ENFORCE)
cd web && npm run build
firebase deploy --only hosting --project video-archival-and-content-gen
```

### Rollback
Firebase Hosting supports instant rollback to a previous deploy via the console or CLI:

```bash
firebase hosting:channel:deploy --project video-archival-and-content-gen
# or via console: Hosting → Release history → Roll back
```

No database changes in F1. Rollback is instantaneous and zero-risk.

No API changes in F1. The authz additions to `core/authz.py` are backward-compatible (additive only — no existing action removed or renamed). If the web rollback is needed, the authz additions are harmless on the backend (they gate endpoints that don't exist yet).

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Old `config` / `users` tab keys in saved user state (localStorage) produce a blank pane | Keep `TabContent` handling `users` and `config` keys as fallbacks that redirect to `admin-config`. |
| Section header labels conflict with existing `AdminSectionDivider` visual style | Reuse `AdminSectionDivider` pattern for section headers with section-name label. Minor visual tweak only. |
| `web_admin` role loses the `email` tab silently | Test plan explicitly checks sign-in as web_admin and confirms Email is absent. Add to manual QA. |
| Sales role loses section headers (flat list) while admin gets sections | `useSections` flag on `ShellConfig` handles this in one render branch. Sales role explicitly tested. |
| Mobile drawer blocks keyboard on iOS Safari | Use `role="dialog"` + `aria-modal` on the drawer; trap focus. Acceptable for MVP. |
| `AdminConfig.tsx` embedding `<Users />` causes a double-render / stale state issue | Users component must not hold singleton state that breaks on re-mount. Verify in QA checklist. |
| TypeScript strict mode rejects new `ShellConfig` shape | Write the new interface first; compiler will catch any gap immediately. `npm run build` gate enforces this. |
| `platform_admin` Tenants sub-tab leaks visible placeholder | Conditional render `{role === 'platform_admin' && <TenantSubTab />}` — no current user has this role, so it never renders. Verified in manual QA. |

---

## 11. Section-scoped action reference (normative)

Full list of new action strings added to `core/authz.py` in F1. These are the canonical names — F2/F3/F4/F5 endpoints use exactly these strings in their `require_role()` calls.

| Action | Granted to | Meaning |
|---|---|---|
| `kb_search` | admin, web_admin, sales | Read-only KB search/ask |
| `kb_ask` | admin, web_admin, sales | Ask the KB (same gate as kb_search; separate for future rate-limiting) |
| `kb_faq_read` | admin, web_admin | View FAQ entries |
| `kb_faq_manage` | admin, web_admin | Create/edit/delete FAQ entries |
| `kb_archive_read` | admin, web_admin | Browse archive/corpus |
| `kb_archive_manage` | admin, web_admin | Trigger backfill, poll KPIs |
| `kb_contract_faq_read` | admin, web_admin | View contract FAQ |
| `marketing_opportunities` | admin, web_admin | View content opportunities |
| `marketing_articles` | admin, web_admin | Manage articles (replaces `manage_articles` for new endpoints) |
| `marketing_schedule` | admin, web_admin | Manage content scheduling |
| `marketing_clips` | admin, web_admin | Manage Clip Studio / mini series |
| `marketing_comments` | admin, web_admin | Manage comment drafts |
| `marketing_email` | admin | Email compose/send (web_admin excluded — matches existing behavior) |
| `marketing_video_approval` | admin, web_admin | Approve/reject video clips |
| `marketing_status` | admin, web_admin | View pipeline status dashboard |
| `estimating_view` | admin, web_admin, sales | View estimator |
| `estimating_manage` | admin, web_admin | Edit pricing config, branches (F2 gate) |
| `quoting_view` | admin, web_admin, sales | View quotes/proposals |
| `quoting_create` | admin, web_admin, sales | Create a new quote |
| `quoting_send` | admin, web_admin, sales | Send a proposal |
| `quoting_manage_templates` | admin, web_admin | Manage proposal templates (extended to web_admin by TRD-F3 §2) |
| `quoting_manage_settings` | admin, web_admin | Manage tenant quoting settings (added by TRD-F3 §2) |
| `admin_users` | admin | Manage users/roles (replaces `manage_users` for new endpoints) |
| `admin_config` | admin | Manage platform config |
| `admin_tenants` | platform_admin | Tenant provisioning (F4/F6; no current user has this) |

**`platform_admin` role contract:** The `platform_admin` role is granted exactly two cross-tenant
action strings: `admin_tenants` and `admin_users`. It does not inherit `"*"` and cannot perform
any tenant-operational action (quoting, corpus writes, pricing edits, etc.). The full
session/impersonation mechanics — how a `platform_admin` session sets `app.tenant_id` for
read-only inspection, and the audit trail for that — are defined in TRD-F4.

Note: existing action strings (`search`, `ask`, `manage_articles`, `manage_estimates`, `manage_users`, `manage_config`, `email_compose`, `email_proof`, `email_send`, `manage_templates`, `manage_scheduling`, `approve_video`, `manage_archive`, `view_status`, `article_read`) remain in the matrix and continue to gate existing endpoints. They are not removed.
