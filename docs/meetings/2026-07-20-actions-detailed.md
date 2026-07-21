# 07-20 Zoom — detailed action items with frame references

Source: local whisper transcript + gpt-oss extraction. Frames at `Zoom/2026-07-20…/video1660583751_frames/` (fps=1/8 → frame = floor(sec/8)+1).


### 00:10 – Add Reminders for Live Site  
- **CATEGORY:** UI  
- **DETAIL:** “reminders to me for when we go live and talk to the main perkinsroofing.net site” – add a checklist or banner reminding to switch from staging to live.  
- **SCREEN:** Admin dashboard top bar where “important reminders” would appear.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00002.jpg

### 00:34 – YouTube Login Integration  
- **CATEGORY:** socials  
- **DETAIL:** “tim need to log in through this interface to youtube because you're the channel owner… test that and make sure it’s pulling new videos.”  
- **SCREEN:** YouTube connection button in the admin UI.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00005.jpg

### 01:16 – Add User to Additional Noify Accounts  
- **CATEGORY:** infra  
- **DETAIL:** “add me to the rest of the noify accounts… there is a fourth one for the general contracting company.”  
- **SCREEN:** Noify account management page.  
- **NEEDS_SCREENSHOT:** no

### 01:48 – Add Fourth Branch “Perkins Construction”  
- **CATEGORY:** branches  
- **DETAIL:** “create a fourth branch called Perkins Construction (general contractor).”  
- **SCREEN:** Branch management list (Miami, Jupiter, Naples).  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00014.jpg

### 02:12 – Re‑connect to YouTube Button Location  
- **CATEGORY:** socials  
- **DETAIL:** “this is where the button is… we need to reconnect to youtube.”  
- **SCREEN:** YouTube integration section with reconnect button.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00017.jpg

### 02:28 – Obtain Login Credentials for Social Integrations  
- **CATEGORY:** infra  
- **DETAIL:** “need all the login credentials because I can’t make any headway with the socials.”  
- **SCREEN:** Credentials input modal (likely under Social Settings).  
- **NEEDS_SCREENSHOT:** no

### 02:35 – Add X (Twitter) and LinkedIn Accounts  
- **CATEGORY:** socials  
- **DETAIL:** “added in x and linkedin… will have to do that tomorrow morning.”  
- **SCREEN:** Social accounts configuration page.  
- **NEEDS_SCREENSHOT:** no

### 03:00 – Set Default Commission Rates (10%)  
- **CATEGORY:** estimator  
- **DETAIL:** “set defaults for commission rates at like 10.”  
- **SCREEN:** Commission settings in pricing admin.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00023.jpg

### 04:01 – Enable Low‑Slope Pricing (“tpo”)  
- **CATEGORY:** estimator  
- **DETAIL:** “enable low slope pricing for tpo.”  
- **SCREEN:** Pricing rules list, low‑slope toggle.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00031.jpg

### 04:22 – Use “plus trick” for Multiple Emails per Account  
- **CATEGORY:** infra  
- **DETAIL:** “john+naples@perkinsroofing.net routes to john@perkinsroofing.net – use for branch‑specific routing.”  
- **SCREEN:** Email account creation dialog.  
- **NEEDS_SCREENSHOT:** no

### 06:06 – Add CompanyCam Integration API Token  
- **CATEGORY:** projects  
- **DETAIL:** “add me to CompanyCam… they have an API… I can drop links to pictures.”  
- **SCREEN:** CompanyCam API key entry field.  
- **NEEDS_SCREENSHOT:** no

### 07:35 – Create Price Book Tab in Admin (fourth tab)  
- **CATEGORY:** estimator  
- **DETAIL:** “admin configuration → bottom section → fourth tab called price book.”  
- **SCREEN:** Admin left sidebar → Price Book tab.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00057.jpg

### 10:13 – Fix Contractor License Hint Text  
- **CATEGORY:** UI  
- **DETAIL:** “contractor license field shows hint text instead of actual data.”  
- **SCREEN:** Contractor license input field in admin.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00077.jpg

### 10:41 – Add Proposal Template (terms & conditions)  
- **CATEGORY:** proposal  
- **DETAIL:** “need to get the proposal template with 49 terms & conditions and load it.”  
- **SCREEN:** Proposal template editor.  
- **NEEDS_SCREENSHOT:** no

### 12:06 – Adjust AI Prompt Structure for Contracts  
- **CATEGORY:** other  
- **DETAIL:** “system prompt and user prompt – need to edit to explain we’re a roofing contractor, not a lawyer.”  
- **SCREEN:** AI prompt configuration UI.  
- **NEEDS_SCREENSHOT:** no

### 13:55 – Add Copy Button for Branch Templates  
- **CATEGORY:** UI  
- **DETAIL:** “maybe create a copy button for Perkins Construction branch.”  
- **SCREEN:** Branch list with action buttons.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00105.jpg

### 15:38 – Publish Articles to Staging Site  
- **CATEGORY:** articles/SEO  
- **DETAIL:** “articles are ready to go – need to publish to staging then production.”  
- **SCREEN:** Articles management page with Publish toggle.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00118.jpg

### 16:57 – Show Platform Metrics (GCP spend)  
- **CATEGORY:** infra  
- **DETAIL:** “add a dashboard section showing GCP spend last 30 days.”  
- **SCREEN:** Dashboard metrics widget.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00128.jpg

### 20:01 – Schedule Article Publishing (10 per day)  
- **CATEGORY:** articles/SEO  
- **DETAIL:** “release 10 articles a day per cluster – pillar + 1‑2 supporting each.”  
- **SCREEN:** Publishing scheduler UI.  
- **NEEDS_SCREENSHOT:** no

### 22:07 – Automate YouTube Ingestion to Cloud Storage  
- **CATEGORY:** clips/video  
- **DETAIL:** “once tim logs in, constantly ingest YouTube videos to GCS, then pipeline generates suggestions.”  
- **SCREEN:** Ingestion settings page.  
- **NEEDS_SCREENSHOT:** no

### 23:13 – Clarify Storage vs Egress Costs  
- **CATEGORY:** infra  
- **DETAIL:** “storage cheap; egress $0.23/GB – note that cost only matters for large media downloads.”  
- **SCREEN:** Cost overview panel.  
- **NEEDS_SCREENSHOT:** no

### 24:05 – Add “Copy” Button for Branch Configurations  
- **CATEGORY:** UI  
- **DETAIL:** “maybe add a copy button for branch settings (similar to price book copy).”  
- **SCREEN:** Branch settings list.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00181.jpg

### 25:04 – Create GitHub Repo for Codebase (private)  
- **CATEGORY:** infra  
- **DETAIL:** “create a free private GitHub repo, push all code, include Terraform and Ansible.”  
- **SCREEN:** GitHub organization/repo creation page (outside app).  
- **NEEDS_SCREENSHOT:** no

### 27:40 – Test “Connect to YouTube” Button  
- **CATEGORY:** socials  
- **DETAIL:** “tim should click ‘connect to youtube’ button – currently not clicked.”  
- **SCREEN:** YouTube connection button in admin.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00208.jpg

### 31:12 – Attach Lumber Schedule PDF to Contracts  
- **CATEGORY:** proposal  
- **DETAIL:** “attach lumber schedule PDF to contracts – need to send file to be attached.”  
- **SCREEN:** Contract attachment uploader.  
- **NEEDS_SCREENSHOT:** no

### 34:00 – Enable Email Outbound for Domain Only  
- **CATEGORY:** infra  
- **DETAIL:** “outbound emails blocked except to domain and a few Gmail accounts – need to expand when ready.”  
- **SCREEN:** Email routing settings.  
- **NEEDS_SCREENSHOT:** no

### 35:00 – Add Days for Re‑installation (new field)  
- **CATEGORY:** estimator  
- **DETAIL:** “add field for days of re‑installation of new roof at bottom of estimate form.”  
- **SCREEN:** Estimate form UI (bottom section).  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00263.jpg

### 37:04 – Fix Commission Calculation (percent of profit vs job)  
- **CATEGORY:** estimator  
- **DETAIL:** “commission error – need to correctly calculate percent of profit or percent of job.”  
- **SCREEN:** Commission calculation logic screen.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00279.jpg

### 38:05 – Add Repair Section with Time & Material Inputs  
- **CATEGORY:** estimator  
- **DETAIL:** “repair quotes need time (days/men) and material cost inputs; simple calculation.”  
- **SCREEN:** Repair estimate form.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00286.jpg

### 45:03 – Add Labor Rate Inputs ($11.85 per man‑day, $14.35 for two men)  
- **CATEGORY:** estimator  
- **DETAIL:** “$11.85 for one man per day, $14.35 for two men – need UI inputs for these rates.”  
- **SCREEN:** Labor rate configuration page.  
- **NEEDS_SCREENSHOT:** yes
- **SCREENSHOT:** frame_00338.jpg

### 46:12 – Integrate Metal‑Roof Warranty Logic (salination)  
- **CATEGORY:** other  
- **DETAIL:** “warranty depends on water salination (salt vs brackish) – need logic to select appropriate warranty.”  
- **SCREEN:** Warranty rules editor.  
- **
