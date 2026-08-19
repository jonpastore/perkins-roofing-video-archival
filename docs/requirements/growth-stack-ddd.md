# DDD: Growth-stack in-repo support

- Cadence remains `core.content_cadence` (`off`|`dump`). The switch is a view of that mode.
- Inbox items are a projection. Persistence reuses `comment_drafts` (platform youtube|paa). No new table.
- Competitor value is a projection of `core.seo.score_article` + `aio_signals`. No second scorer.
- Weekly queue is `core.social_brief.rank_this_week` over existing cut/film/write ranks. No new table.
- Package gate is `core.clip_package.missing_package_fields`. Length 15–40s. Cleanup stays ffmpeg + DeepFilterNet path + vid.stab + PySceneDetect — not ComfyUI.
