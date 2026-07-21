# 07-20 Zoom review — change list (local-whisper transcript → gpt-oss-120b extraction)

Source: transcript.txt (923 segs, large-v3 local) + 422 frames. Extraction by local gpt-oss-120b (free).
Triage: MANY already shipped this cycle (YouTube login, CompanyCam, low-slope TPO, commission %,
email restriction, reminder-off, speaker tracking, GCP-spend dashboard, article publish→prod, 10/day).
NEW/open items filed to Jarvis project perkins-buildout-2026-07. Raw list:

- **[00:34] UI — “Tim needs to log in through this interface to YouTube because you’re the channel owner.”
- **[00:57] UI — “Add me to the rest of the Noify accounts (fourth branch for Perkins Construction).”
- **[01:30] UI — “Create a copy button for Perkins Construction branch.”
- **[02:05] UI — “Reconnect to YouTube via the button shown.”
- **[02:22] UI — “Add X and LinkedIn credentials to the socials.”
- **[03:00] UI — “Set default commission rates (currently at 10%).”
- **[03:13] UI — “Add option to calculate commission as a percentage of contract or of calculated profit.”
- **[04:07] UI — “Enable low‑slope pricing (TPO) for the estimate.”
- **[04:16] UI — “Add additional email aliases using the ‘+’ trick for multiple accounts without new mailboxes.”
- **[06:32] UI — “Add CompanyCam integration (API token) for proposal pictures.”
- **[07:18] UI — “Allow posting comments back to YouTube as the logged‑in user.”
- **[08:21] UI — “Add a fourth branch (Perkins Construction) in branch management.”
- **[09:48] UI — “Provide a link to the price book tab in admin configuration.”
- **[10:24] UI — “Fix contractor license placeholder text in the proposal template.”
- **[11:09] UI — “Add FAQ and review prompt extraction logic to proposals.”
- **[12:13] UI — “Create a system prompt for AI that states the role as a roofing contractor and not a lawyer.”
- **[13:31] UI — “Add a copy button for Perkins Construction quotes.”
- **[14:05] UI — “Avoid editing platform settings; they are for internal use only.”
- **[15:05] articles/SEO — “Publish generated articles (with embedded images/videos and TOC) to the live site.”
- **[16:31] articles/SEO — “Move articles from staging to production after admin approval.”
- **[18:01] other — “Display platform metrics (GCP spend) on the dashboard.”
- **[20:01] articles/SEO — “Publish 10 articles per day, rotating clusters to maintain fresh content.”
- **[21:04] clips/video — “Enable speaker tracking, face detection, and reframing in the clip suggestion engine.”
- **[22:07] clips/video — “Continuously ingest new YouTube videos into Google Cloud Storage for processing.”
- **[23:13] other — “Note that storage is cheap; egress is the primary cost concern.”
- **[24:41] UI — “Create a GitHub account for the team with private repos for code.”
- **[25:30] UI — “Use Terraform for infrastructure as code and Ansible playbooks for configuration.”
- **[27:56] UI — “Add a button to connect to YouTube (login not yet clicked).”
- **[33:31] UI — “Restrict outbound emails to domain and approved Gmail accounts until testing is complete.”
- **[34:05] UI — “Turn off the reminder system that was prematurely notifying users.”
- **[35:46] estimator — “Add input for days of tear‑off and re‑installation in the estimate form.”
- **[36:12] estimator — “Fix missing shingle/tile/metal selection options in the estimate.”
- **[37:04] estimator — “Add repair options (shingle, tile, metal, flat roof) with time‑based pricing.”
- **[41:04] UI — “Add a configurable text‑area for custom scope‑of‑work prompts in admin.”
- **[42:06] UI — “Implement a note/comments field for custom variations on quotes.”
- **[44:12] UI — “Add a note area/button for additional comments or prompts on contracts.”
- **[45:31] estimator — “Create inputs for daily labor rates ($11.85 per man‑day, $14.35 per two‑man day).”
- **[46:12] other — “Integrate metal‑roofing warranty logic based on salination levels.”
- **[48:40] UI — “Add a YouTube video link for the aluminum roof example in the metal‑roofing section.”
- **[51:10] UI — “Create an educational page showing warranty comparisons and wind uplift data for metal roofs.”
- **[53:01] UI — “Develop a WordPress plugin to embed the educational content on a site page.”
