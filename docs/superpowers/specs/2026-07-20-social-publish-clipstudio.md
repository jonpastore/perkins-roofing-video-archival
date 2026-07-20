# Spec: Unified social publishing + platform-aware Clip Studio (2026-07-20)

Status: DESIGN (95% confidence). Owner decisions marked ⚖. Build lanes marked
[claude] (security/verify — stays on Claude) / [offload] (qwen3.6-coder or CF agents).

## 0. Current state (verified)
- Two social lanes: `jobs/social_job.py` (REAL, deployed, IG+TikTok, reads creds from
  **env**, path render→promote→social_job) and `jobs/distribute_job.py` (SCAFFOLD, mocked,
  5 more platforms via `adapters/distribution/*`, `core/publish_dispatch.py` state machine +
  **per-platform transcode-spec table**, second OAuth store).
- OAuth capture is real for all 6 platforms (`api/routes/connections.py`) → `SecretManagerOAuthStore`.
- `ScheduledContent.target` = comma-sep platform list already (checkbox backing exists).
- `core/publish_dispatch.py` PLATFORM_SPECS: aspect_ratio, codec_video/audio, min_resolution,
  length caps — the per-platform video-requirements source of truth (already written).
- Clip Studio (`web/src/pages/ClipStudio.tsx`, 1625 LOC): VideoPicker, ClipCard (hook/summary/
  caption/transcript/virality), brand intro/outro upload. No scene-cut/reframe/text/censor yet.
- Render: `jobs/render_job.py` produces 1080×1920 reels + SocialPost + ScheduledContent(kind=reel).

## 1. Unify the two publish lanes ⚖→UNIFY
Keep `social_job` as the ONE driver. Absorb from distribute_job/publish_dispatch:
- **Adopt `PLATFORM_SPECS`** (publish_dispatch) as the canonical per-platform video-requirements
  table. Move it to `core/platform_specs.py` (pure data + a `validate(meta, platform)->list[str]`).
- **Adopt the adapters** `adapters/distribution/{facebook,youtube_shorts,linkedin,x,pinterest}.py`
  into social_job's publisher registry (`_publisher(platform)`), replacing the mock dispatch.
- **Token source unification [claude — security]:** social_job's IG/TikTok adapters read env today;
  new adapters read `SecretManagerOAuthStore.get(platform, tenant_id)` (what connect writes).
  Keep env as fallback for IG's System-User token (permanent, not per-user OAuth). One resolver:
  `core/social_creds.py: creds_for(platform, tenant_id) -> dict` — store first, env fallback.
- **Delete** `jobs/distribute_job.py` + `core/publish_dispatch.py` state machine after the specs
  table + adapters are moved. Keep `adapters/distribution/oauth_store.py` only if it == the connect store.
- Per-platform idempotency (existing SocialPost dedup) is retained.

## 2. Multi-platform post = checkboxes [offload]
- Clip Studio + Scheduling: replace the single `target` <select> with a **checkbox group** over the
  platforms the tenant has CONNECTED (from `GET /connections`, `status==ok`). Disabled+greyed for
  unconnected, with an inline "connect in Marketing" hint. Writes `target` = comma-joined keys.
- One publish action fans out to every checked platform (social_job already loops `targets`).
- Pre-submit **requirements check**: call a new `POST /clips/{id}/preflight` [offload] that runs
  `platform_specs.validate()` against the clip's rendered meta and returns per-platform pass/fail
  (duration/aspect/resolution/size) so the checkbox row shows a ✓/⚠ per platform before scheduling.

## 3. Per-platform video conformance [offload, ffmpeg]
render_job gains a **conform pass** driven by `platform_specs`:
- Reframe/pad to target aspect (all 9:16 today → already met; keep the pass for future 1:1/16:9).
- Enforce max duration (hard-trim or reject with a clear error surfaced to the UI).
- Enforce codec (h264/aac) + max file size (re-encode bitrate ladder until under cap).
- Output one conformed asset per DISTINCT spec (dedupe: all platforms are 9:16 h264 today → 1 asset).
- Store conformed variants under `tenants/{id}/reels/{series}/{part}/{spec_hash}.mp4`.

## 4. Clip Studio creative features [offload, ffmpeg + STT already present]
All operate on the selected clip's [start,end] + its word-timestamped transcript (STT exists).
- **Platform preset buttons:** per-platform button injects a preset into the clip-generation prompt
  (hook length, caption style, hashtag density, on-screen-text cadence) from a `PLATFORM_PRESETS`
  table [offload, data]. "In addition to the content found" = preset augments, not replaces, the
  LLM clip suggestions.
- **Cut scenes:** ffmpeg scene detection (`select='gt(scene,0.4)'` or PySceneDetect) → candidate cut
  points shown on a timeline; user keeps/drops segments; render concatenates kept ranges.
- **Set focus (reframe):** subject-tracked crop to 9:16. MVP = static focal-point picker (user taps
  the region to keep) → ffmpeg `crop`. v2 = auto via face/saliency (a CF Workers-AI vision model or
  mediapipe) — flagged, not MVP. ponytail: ship the manual picker first.
- **Text with effects:** burn captions/overlays via ffmpeg ASS/`drawtext` — auto-caption track from
  the transcript (word timings → styled ASS with pop/fade), plus manual title cards. Effects = a small
  preset set (pop-in, fade, karaoke-highlight), NOT a general animation engine.
- **Auto-censor toxic phrases:** extend the existing `safety_denylist` + a toxicity check
  ([offload] CF Workers-AI text-classification or a wordlist) over the transcript word-timestamps →
  (a) **audio:** ffmpeg volume-mute/bleep at [t0,t1] of each flagged word; (b) **on-screen text:**
  mask the word in the caption track. Runs automatically in the conform pass; flagged spans logged.

## 5. Data model / API additions
- `core/platform_specs.py` (specs + validate + presets) [offload].
- `POST /clips/{id}/preflight` → per-platform pass/fail [offload].
- render_job conform pass + `reel_variants` (or reuse SocialPost.gcs_url per spec_hash) [offload].
- `censor_spans` persisted on the clip/SocialPost for auditability [offload].
- Clip Studio edit state: kept segments, focal point, caption edits, chosen platforms [offload].

## 6. Build order (most-efficient, token-aware)
1. [claude] `core/social_creds.py` resolver + wire social_job adapters (SECURITY — token source).
2. [offload] `core/platform_specs.py` (move table + validate + presets) — pure, testable.
3. [offload] Move distribution adapters into social_job registry; delete distribute_job + dispatch.
4. [offload] Checkbox multi-post UI (Clip Studio + Scheduling) off `GET /connections`.
5. [offload] `POST /clips/{id}/preflight` + per-platform ✓/⚠ row.
6. [offload] render_job conform pass (duration/codec/size) + auto-censor (audio mute + caption mask).
7. [offload] Clip Studio: scene-cut timeline, manual focal-point reframe, caption/text effects.
8. [claude] Review security (token store, censor correctness) + verify end-to-end.

## 7. Confidence / risks
- 95%: unification, checkbox, specs table, preflight, conform (duration/codec/size), audio censor —
  all deterministic, infra present.
- <95% (flagged, phased): auto subject-tracking reframe (model dep) → MVP manual picker; toxicity
  model choice → start wordlist + CF classifier behind a flag; text-effect richness → fixed preset set.
- External: live posting still blocked on Meta/TikTok/FB app review + creds (Jarvis #319).
