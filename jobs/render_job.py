"""Render job (I/O orchestration — coverage-omitted).

render_part() is the Cloud Run Job entrypoint for a single series part:

  1. Idempotency check — skip if a SocialPost with gcs_url already exists for
     this series_id + part_index.
  2. Obtain source video via _source_video_path(): prefers the archived GCS MP4
     (video.archive_uri) — downloads it to a temp file — and falls back to
     yt-dlp when archive_uri is null.
  3. Enforce ≤300s clip duration (raises ValueError on violation — preserves
     editorial intent; never silently truncates).
  4. Extract the part's clip in/out range (adapters.ffmpeg.clip).
  5. Generate title and closing cards via adapters.ffmpeg.make_card when
     title_img/closing_img are not supplied.
  6. Fuse title card + clip + closing card into a 1080×1920 reel
     (adapters.ffmpeg.fuse using core.render_spec).
  7. Upload the reel to the public GCS bucket and return the public URL.
  8. Persist/update a SocialPost row (series_id, part, platform, gcs_url,
     status="rendered").
  9. Insert a ScheduledContent row (kind="reel", ref_id=social_post.id,
     publish_at=utcnow(), target="instagram,tiktok", status="scheduled")
     so the scheduler.due selector can find it.

run() sweeps all approved MiniSeries and calls render_part for each unrendered
part, then is invoked by the Terraform `render` Cloud Run Job.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

from core import metering
from core.render_spec import ClipRenderSpec, get_clips, get_render_spec

logger = logging.getLogger(__name__)

# Public GCS bucket name follows the project convention.
# The bucket must be created with uniform public-read ACL before use.
_GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# Maximum allowed clip duration (seconds) per IG/TikTok spec.
_MAX_CLIP_SECS = 300

# Default platform recorded on SocialPost rows created by this job.
_DEFAULT_PLATFORM = "instagram,tiktok"

# Default closing card text used when no closing_img is supplied and the
# platform_config "REEL_CLOSING_TEXT" key is not set.
_CLOSING_TEXT_DEFAULT = "Perkins Roofing"


def _closing_text() -> str:
    """Return the configured reel closing brand text.

    Reads the REEL_CLOSING_TEXT key from platform_config (set via the Clip
    Studio settings panel / PUT /config).  Falls back to _CLOSING_TEXT_DEFAULT
    when the key is absent or empty.
    """
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415

        with PlatformSessionLocal() as db:
            row = db.get(PlatformConfig, "REEL_CLOSING_TEXT")
            if row and row.value and row.value.strip():
                return row.value.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("_closing_text: could not read platform_config: %s", exc)
    return _CLOSING_TEXT_DEFAULT


def _brand_video_config(scratch: str) -> tuple[str | None, str | None]:
    """Return (intro_path, outro_path) when BRAND_INTRO_VIDEO and BRAND_OUTRO_VIDEO are both set.

    Reads settings.BRAND_INTRO_VIDEO / BRAND_OUTRO_VIDEO (gs:// URIs, env-driven).
    Downloads each to *scratch* and returns their local paths.  Returns (None, None)
    when either setting is empty or a download fails.

    Security: only gs://<reels_bucket>/brand/… URIs are accepted (same policy as
    _brand_scene_config).
    """
    from app.config import settings  # noqa: PLC0415

    intro_uri = (settings.BRAND_INTRO_VIDEO or "").strip()
    outro_uri = (settings.BRAND_OUTRO_VIDEO or "").strip()
    if not intro_uri or not outro_uri:
        return None, None

    allowed_bucket = _reels_bucket()
    _BRAND_KEY_PREFIX = "brand/"

    def _download(gs_uri: str, label: str) -> str | None:
        if not gs_uri.startswith("gs://"):
            logger.warning("_brand_video_config: rejecting non-gs:// %s URI: %r", label, gs_uri)
            return None
        try:
            without_scheme = gs_uri[len("gs://"):]
            slash = without_scheme.index("/")
            bucket = without_scheme[:slash]
            key = without_scheme[slash + 1:]
            if bucket != allowed_bucket:
                logger.warning(
                    "_brand_video_config: rejecting foreign bucket %r (allowed: %r) for %s",
                    bucket, allowed_bucket, label,
                )
                return None
            if not key.startswith(_BRAND_KEY_PREFIX):
                logger.warning(
                    "_brand_video_config: rejecting key outside brand/ prefix for %s: %r",
                    label, gs_uri,
                )
                return None
            ext = os.path.splitext(key)[-1] or ".mp4"
            local_path = os.path.join(scratch, f"brand_{label}_{os.path.basename(key)}{'' if ext else '.mp4'}")
            from adapters.storage import open_read_stream  # noqa: PLC0415
            with open_read_stream(bucket, key) as stream:
                with open(local_path, "wb") as fh:
                    while True:
                        chunk = stream.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            return local_path
        except Exception as exc:  # noqa: BLE001
            logger.warning("_brand_video_config: failed to fetch %s %s: %s", label, gs_uri, exc)
            return None

    intro_path = _download(intro_uri, "intro")
    outro_path = _download(outro_uri, "outro")
    if intro_path is None or outro_path is None:
        return None, None
    return intro_path, outro_path


def _brand_scene_config(scratch: str) -> tuple[str | None, str | None]:
    """Return (title_img_path, closing_img_path) from platform_config when REEL_APPLY_BRAND_SCENES=true.

    Reads REEL_APPLY_BRAND_SCENES, REEL_TITLE_IMG, and REEL_CLOSING_IMG.
    Returns (None, None) when the flag is off or config is unavailable.
    When an img key holds a gs:// URI, downloads it into *scratch* (the render
    TemporaryDirectory) and returns the local path so the existing cleanup
    reclaims it — no temp-file leak.

    Security: only gs://<reels_bucket>/brand/... URIs are accepted.
    Any other bucket, key prefix, or non-gs:// value is logged and ignored.
    Local paths are only permitted when ALLOW_LOCAL_BRAND_PATHS=1 (dev flag,
    default off) AND the path is under _BRAND_LOCAL_DIR.
    """
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415

        with PlatformSessionLocal() as db:
            apply_row = db.get(PlatformConfig, "REEL_APPLY_BRAND_SCENES")
            if not (apply_row and apply_row.value and apply_row.value.strip().lower() == "true"):
                return None, None
            title_row = db.get(PlatformConfig, "REEL_TITLE_IMG")
            closing_row = db.get(PlatformConfig, "REEL_CLOSING_IMG")
            title_val = (title_row.value or "").strip() if title_row else ""
            closing_val = (closing_row.value or "").strip() if closing_row else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("_brand_scene_config: could not read platform_config: %s", exc)
        return None, None

    allowed_bucket = _reels_bucket()
    _BRAND_KEY_PREFIX = "brand/"
    _ALLOW_LOCAL = os.getenv("ALLOW_LOCAL_BRAND_PATHS", "0").strip() == "1"
    # Designated local brand dir — only used when the dev flag is on.
    _BRAND_LOCAL_DIR = os.path.realpath(
        os.getenv("BRAND_LOCAL_DIR", "/var/run/brand_scenes")
    )

    def _resolve(gs_uri: str) -> str | None:
        if not gs_uri:
            return None
        if not gs_uri.startswith("gs://"):
            # Non-gs:// path: only allow when dev flag is on AND path is under designated dir.
            if not _ALLOW_LOCAL:
                logger.warning(
                    "_brand_scene_config: rejecting non-gs:// path (ALLOW_LOCAL_BRAND_PATHS not set): %r",
                    gs_uri,
                )
                return None
            resolved = os.path.realpath(gs_uri)
            if not resolved.startswith(_BRAND_LOCAL_DIR + os.sep) and resolved != _BRAND_LOCAL_DIR:
                logger.warning(
                    "_brand_scene_config: rejecting local path outside brand dir %r: %r",
                    _BRAND_LOCAL_DIR,
                    gs_uri,
                )
                return None
            return resolved if os.path.exists(resolved) else None
        try:
            without_scheme = gs_uri[len("gs://"):]
            slash = without_scheme.index("/")
            bucket = without_scheme[:slash]
            key = without_scheme[slash + 1:]
            # Security: reject any bucket other than the project reels bucket.
            if bucket != allowed_bucket:
                logger.warning(
                    "_brand_scene_config: rejecting gs:// URI with foreign bucket %r (allowed: %r): %r",
                    bucket,
                    allowed_bucket,
                    gs_uri,
                )
                return None
            # Security: reject any key that doesn't live under brand/.
            if not key.startswith(_BRAND_KEY_PREFIX):
                logger.warning(
                    "_brand_scene_config: rejecting gs:// URI with key outside brand/ prefix: %r",
                    gs_uri,
                )
                return None
            ext = os.path.splitext(key)[-1] or ".png"
            # Download into the render scratch dir so TemporaryDirectory cleanup reclaims it.
            local_path = os.path.join(scratch, f"brand_{os.path.basename(key)}{'' if ext else '.png'}")
            from adapters.storage import open_read_stream  # noqa: PLC0415
            with open_read_stream(bucket, key) as stream:
                with open(local_path, "wb") as fh:
                    while True:
                        chunk = stream.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            return local_path
        except Exception as exc:  # noqa: BLE001
            logger.warning("_brand_scene_config: failed to fetch %s: %s", gs_uri, exc)
            return None

    return _resolve(title_val), _resolve(closing_val)


def _reels_bucket() -> str:
    project = _GOOGLE_CLOUD_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT env var is required for GCS upload"
        )
    return f"{project}-reels"


def _gcs_object_key(series_id: int, part_index: int, tenant_id: int = 1) -> str:
    from core.gcs_path import tenant_object_path  # noqa: PLC0415
    return tenant_object_path(tenant_id, f"renders/{series_id}/{part_index}.mp4")


def _gs_uri(bucket: str, key: str) -> str:
    return f"gs://{bucket}/{key}"


def _source_video_path(video_id: str, archive_uri: str | None, scratch: str) -> str:
    """Return a local path to the source MP4 for *video_id*.

    Prefers the archived GCS object (*archive_uri*) — streams it to a temp
    file in *scratch* — so renders source from already-archived media rather
    than re-downloading from YouTube.  Falls back to yt-dlp when *archive_uri*
    is None or the GCS download fails.

    Args:
        video_id:    YouTube video ID (used for the yt-dlp fallback).
        archive_uri: ``gs://bucket/key`` URI of the archived source MP4, or None.
        scratch:     Directory where the downloaded file should be placed.

    Returns:
        Absolute path to the local MP4 file.

    Raises:
        FileNotFoundError / RuntimeError: propagated from adapters on hard failure.
    """
    if archive_uri:
        # Parse gs://bucket/object/key
        without_scheme = archive_uri[len("gs://"):]
        slash = without_scheme.index("/")
        bucket = without_scheme[:slash]
        key = without_scheme[slash + 1:]

        local_path = os.path.join(scratch, f"{video_id}_archived.mp4")
        logger.info(
            "_source_video_path: downloading archived media %s -> %s",
            archive_uri,
            local_path,
        )
        try:
            from adapters.storage import open_read_stream  # noqa: PLC0415

            with open_read_stream(bucket, key) as stream:
                with open(local_path, "wb") as fh:
                    while True:
                        chunk = stream.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            return local_path
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_source_video_path: GCS download failed (%s), falling back to yt-dlp: %s",
                archive_uri,
                exc,
            )

    # Fallback: pull via yt-dlp
    from adapters.yt_dlp import pull_video  # noqa: PLC0415

    logger.info("_source_video_path: pulling via yt-dlp video_id=%s", video_id)
    return pull_video(video_id, scratch)


def _apply_track_a_engines(
    clip_path: str,
    spec: "ClipRenderSpec",
    scratch: str,
    series_id: int,
    part_index: int,
    *,
    video_id: str | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    db=None,
    hook_text: str | None = None,
    aspects: list[str] | None = None,
    tenant_id: int | None = None,
    brand_kit: dict | None = None,
) -> str:
    """Apply Track A engines to *clip_path* in TRD sequence; return output path.

    Engine order (TRD-F5 §7.3):
      speech_cleanup → reframe → captions → broll → music_mix → clip_fx
      → hook_overlay → (multi-aspect handled by caller via aspects list)

    Each engine is applied only when its spec flag/option enables it.  Absent or
    disabled options are no-ops so the function is fully backward-compatible when
    called with a default ClipRenderSpec.

    Provider-gated engines (broll/music) silently skip when keys are absent —
    they must never hard-fail a render.

    Args:
        clip_path:   Path to the extracted clip MP4 produced by ffmpeg_clip().
        spec:        ClipRenderSpec from the series' parts_json (may be defaults).
        scratch:     Temporary directory for intermediate outputs.
        series_id / part_index: Used to name intermediate files.
        video_id:    Source video ID used to query word timestamps (#326 fix).
        clip_start:  Clip start time in seconds (for word timestamp query).
        clip_end:    Clip end time in seconds (for word timestamp query).
        db:          Stamped SQLAlchemy session for tenant-scoped DB queries.
                     Must already have session.info["tenant_id"] set.  When
                     None, word loading is skipped silently.
        hook_text:   Hook text string to burn as first-2.5s title overlay.
                     Skipped when None or empty.
        aspects:     List of aspect ratio strings; currently only "square"
                     triggers a 1:1 1080×1080 second-pass render.  Ignored
                     here — caller handles multi-aspect from the returned path.
        tenant_id:   Tenant id (informational; session stamping is done by caller).
        brand_kit:   Optional brand kit dict (core.brand_kit.load_brand_kit) providing
                     caption font/primary-color overrides. None/empty -> no overrides,
                     captions use exactly the preset style (today's behaviour).

    Returns:
        Path to the (possibly transformed) clip MP4.  May be the original
        clip_path when no engines are enabled.
    """
    current = clip_path
    suffix = f"{series_id}_{part_index}"

    # ── A10: audio_enhance (Item 10) ─────────────────────────────────────────
    # opt-in: afftdn denoise + acompressor + loudnorm EBU R128 -14 LUFS.
    # Applied first so downstream engines see clean audio.
    if getattr(spec, "audio_enhance", False):
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from core.audio_enhance import build_enhance_cmd  # noqa: PLC0415

            out = os.path.join(scratch, f"enhanced_{suffix}.mp4")
            cmd = build_enhance_cmd(current, out)
            run_ffmpeg_cmd(cmd)
            current = out
            logger.info("audio_enhance applied: series=%d part=%d", series_id, part_index)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio_enhance skipped (non-fatal): %s", exc)

    # ── A6: speech_cleanup ────────────────────────────────────────────────────
    # Requires word-level timestamps from the transcript.  When not available
    # (no transcript or words key absent), log and skip silently.
    if spec.speech_cleanup:
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from core.speech_cleanup import build_cleanup_cmd, detect_fillers, keep_segments  # noqa: PLC0415

            words = _load_words_for_clip(
                video_id=video_id,
                clip_start=clip_start,
                clip_end=clip_end,
                db=db,
            )
            if words:
                filler_ranges = detect_fillers(words)
                clip_duration = words[-1]["end"] if words else 0.0
                segs = keep_segments(clip_duration, filler_ranges)
                if segs:
                    out = os.path.join(scratch, f"cleanup_{suffix}.mp4")
                    cmd = build_cleanup_cmd(current, out, segs)
                    run_ffmpeg_cmd(cmd)
                    current = out
                    logger.info("speech_cleanup applied: series=%d part=%d", series_id, part_index)
                else:
                    logger.info("speech_cleanup: no fillers found, skipping")
            else:
                logger.info("speech_cleanup: no word timestamps available, skipping")
        except Exception as exc:  # noqa: BLE001
            logger.warning("speech_cleanup skipped (non-fatal): %s", exc)

    # ── A-censor: auto-mute flagged spoken words (crude/toxic denylist) ───────
    # Automatic — runs whenever the transcript has flagged words; no-op otherwise.
    # Placed after the audio stages so it mutes clean audio, before video engines.
    # ponytail: crude denylist only; fold in the tenant safety_denylist via
    # TenantSettings when brand-specific terms (e.g. competitor names) need muting.
    try:
        from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
        from core.censor import censor_spans, mute_audio_filter  # noqa: PLC0415

        _cwords = _load_words_for_clip(
            video_id=video_id, clip_start=clip_start, clip_end=clip_end, db=db,
        )
        if _cwords:
            _denylist = _load_safety_denylist(tenant_id, db)
            # Word starts are source-relative; the clip was cut at clip_start, so
            # shift spans into the clip-local timeline the mute filter runs against.
            _offset = clip_start or 0.0
            _spans = [
                (max(0.0, s - _offset), max(0.0, e - _offset))
                for s, e in censor_spans(_cwords, extra_denylist=_denylist)
            ]
            _af = mute_audio_filter(_spans)
            if _af:
                out = os.path.join(scratch, f"censored_{suffix}.mp4")
                run_ffmpeg_cmd(["ffmpeg", "-y", "-i", current, "-af", _af, "-c:v", "copy", out])
                current = out
                logger.info(
                    "censor: muted %d span(s) series=%d part=%d",
                    len(_spans), series_id, part_index,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("censor skipped (non-fatal): %s", exc)

    # ── A2: reframe (9:16 crop — centre or speaker-tracked) ──────────────────
    if spec.reframe:
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415

            out = os.path.join(scratch, f"reframe_{suffix}.mp4")

            if getattr(spec, "speaker_tracking", False):
                # A2: real speaker tracking — YuNet face centroids sampled once per
                # second, EMA-smoothed + pan-speed-clamped. Ambiguous multi-speaker
                # frames yield None from pick_centroid → smoothing drifts toward the
                # last known position / centre instead of cutting a head (the
                # documented Opus Clip failure). If opencv or the model is
                # unavailable, NullFaceDetector keeps the old centre-crop behaviour.
                from core.speaker_track import (  # noqa: PLC0415
                    NullFaceDetector,
                    build_tracking_crop_filter,
                    smooth_centroids,
                )

                src_w, src_h, duration = 1920, 1080, 0.0
                try:
                    from adapters.speaker_detector import (  # noqa: PLC0415
                        YuNetFaceDetector,
                        probe_video,
                    )
                    src_w, src_h, duration = probe_video(current)
                    detector = YuNetFaceDetector()
                except Exception as det_exc:  # noqa: BLE001 — tracking is best-effort
                    logger.warning(
                        "speaker tracking unavailable (%s) — centre-crop fallback", det_exc
                    )
                    detector = NullFaceDetector()

                n_samples = max(1, int(duration)) if duration > 0 else 1
                segments_for_detect = [
                    {"start": float(i), "end": float(i + 1)} for i in range(n_samples)
                ]
                timestamps = [s["start"] + 0.5 for s in segments_for_detect]
                raw_centroids = detector.detect_centroids(current, segments_for_detect)
                smoothed = smooth_centroids(raw_centroids, timestamps=timestamps)
                crop_filter = build_tracking_crop_filter(
                    smoothed, timestamps, src_w=src_w, src_h=src_h
                )
            else:
                from core.reframe import crop_filter_9x16  # noqa: PLC0415
                _focus_x = float(getattr(spec, "focus_x", 0.5) or 0.5)
                crop_filter = crop_filter_9x16(1920, 1080, focus_x=_focus_x, ratio="9:16")

            cmd = [
                "ffmpeg", "-y", "-i", current,
                "-vf", crop_filter,
                "-c:v", "libx264", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-c:a", "copy",
                out,
            ]
            run_ffmpeg_cmd(cmd)
            current = out
            logger.info(
                "reframe applied: series=%d part=%d speaker_tracking=%s",
                series_id, part_index, getattr(spec, "speaker_tracking", False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reframe skipped (non-fatal): %s", exc)

    # ── A3: captions (burn-in) ────────────────────────────────────────────────
    # Requires ASS subtitle file generated from transcript segments.
    if spec.captions.style != "default" or spec.captions.position != "bottom":
        # Only apply when a non-default style is requested; default style is
        # applied by the brand-scene fuse step's loudnorm pass already.
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from core.captions import caption_events, to_ass_karaoke  # noqa: PLC0415

            words = _load_words_for_clip(
                video_id=video_id,
                clip_start=clip_start,
                clip_end=clip_end,
                db=db,
            )
            if words:
                # Mask censored words in the burned caption text too (audio is muted
                # separately by the censor engine above).
                from core.censor import mask_caption_words  # noqa: PLC0415
                words = mask_caption_words(words, extra_denylist=_load_safety_denylist(tenant_id, db))
                events = caption_events(words)
                _emoji_map: dict | None = None
                if getattr(spec, "emoji_highlights", False):
                    from core.captions_emoji import KEYWORD_EMOJI_MAP  # noqa: PLC0415
                    _emoji_map = KEYWORD_EMOJI_MAP
                # Brand-kit theming: optional font/primary-color override (None/empty
                # brand_kit -> both None -> to_ass_karaoke renders the preset unchanged).
                _bk = brand_kit or {}
                _brand_font = _bk.get("font_heading") or _bk.get("font_body") or None
                _brand_primary_color = _bk.get("primary_color") or None
                ass_content = to_ass_karaoke(
                    events, style=spec.captions.style, emoji_map=_emoji_map,
                    brand_font=_brand_font, brand_primary_color=_brand_primary_color,
                )
                ass_path = os.path.join(scratch, f"captions_{suffix}.ass")
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)
                out = os.path.join(scratch, f"captioned_{suffix}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", current,
                    "-vf", f"ass={ass_path}",
                    "-c:v", "libx264", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-c:a", "copy",
                    out,
                ]
                run_ffmpeg_cmd(cmd)
                current = out
                logger.info(
                    "captions applied: series=%d part=%d style=%s",
                    series_id, part_index, spec.captions.style,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("captions skipped (non-fatal): %s", exc)

    # ── A7: broll splice (#325 — wired) ──────────────────────────────────────
    # Provider-gated: only when PEXELS_API_KEY is present in env.
    pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
    if spec.broll_enabled(pexels_key_present=bool(pexels_key)):
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from adapters.pexels import build_broll_overlay_cmd, fetch_broll_clip  # noqa: PLC0415
            from core.broll import _derive_keyword  # noqa: PLC0415

            # Derive a roofing-tuned search keyword from the clip's part title or hook.
            part_text = hook_text or f"series {series_id} part {part_index}"
            broll_keyword = _derive_keyword(part_text)
            logger.info(
                "broll: source=%s keyword=%r series=%d part=%d",
                spec.broll.source, broll_keyword, series_id, part_index,
            )
            broll_path = fetch_broll_clip(broll_keyword, scratch)
            if broll_path:
                out = os.path.join(scratch, f"broll_{suffix}.mp4")
                cmd = build_broll_overlay_cmd(
                    current, broll_path, out,
                    overlay_start=2.0,
                    overlay_end=6.0,
                )
                run_ffmpeg_cmd(cmd)
                current = out
                logger.info("broll splice applied: series=%d part=%d", series_id, part_index)
            else:
                logger.info("broll: no clip downloaded — skipping splice (non-fatal)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("broll skipped (non-fatal): %s", exc)
    elif spec.broll.source != "none":
        logger.info(
            "broll: source=%s requested but PEXELS_API_KEY absent — skipping (never fail render)",
            spec.broll.source,
        )

    # ── A8: music_mix ─────────────────────────────────────────────────────────
    # Provider-gated: catalog must resolve to a local file path.
    if spec.music_enabled():
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from core.music_mix import build_music_mix_cmd  # noqa: PLC0415

            music_path = _resolve_music_track(spec.music.catalog, spec.music.track_id, scratch)
            if music_path:
                out = os.path.join(scratch, f"music_{suffix}.mp4")
                cmd = build_music_mix_cmd(current, music_path, out, music_gain_db=spec.music.volume_db)
                run_ffmpeg_cmd(cmd)
                current = out
                logger.info(
                    "music_mix applied: catalog=%s track=%s series=%d part=%d",
                    spec.music.catalog, spec.music.track_id, series_id, part_index,
                )
            else:
                logger.info(
                    "music_mix: track %r not found in catalog %r — skipping",
                    spec.music.track_id, spec.music.catalog,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("music_mix skipped (non-fatal): %s", exc)

    # ── A9–A11: clip_fx (transitions / overlays / floating text) ─────────────
    # #344 honesty fix: core/clip_fx.py's build_transition_filter (wipe/slide/
    # dissolve) is xfade-based and needs TWO clip streams — it cannot honestly
    # apply to this single-clip render, so those kinds were removed from
    # ClipRenderSpec/_VALID_TRANSITIONS and the ClipStudio UI dropdown. The
    # only transition kind left here is "fade", which genuinely is a single-
    # clip effect (ffmpeg's own `fade` filter, not xfade). Multi-clip xfade
    # transitions belong at the brand-fusion step (intro+clip+outro / future
    # multi-clip series) — see adapters.ffmpeg.fuse_videos and
    # core.clip_fx.build_concat_with_transitions for that future wiring.
    if spec.fx.transition not in ("cut", "none") or spec.fx.color_grade not in ("none", ""):
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415

            vf_parts: list[str] = []
            if spec.fx.transition not in ("cut", "none"):
                # Simple single-clip fade-in (0.5s) using ffmpeg fade filter.
                vf_parts.append("fade=t=in:st=0:d=0.5")
            if spec.fx.color_grade == "vivid":
                vf_parts.append("eq=saturation=1.4:contrast=1.05")
            elif spec.fx.color_grade == "warm":
                vf_parts.append("colortemperature=temperature=5000")
            elif spec.fx.color_grade == "cool":
                vf_parts.append("colortemperature=temperature=8000")

            if vf_parts:
                out = os.path.join(scratch, f"fx_{suffix}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", current,
                    "-vf", ",".join(vf_parts),
                    "-c:v", "libx264", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-c:a", "copy",
                    out,
                ]
                run_ffmpeg_cmd(cmd)
                current = out
                logger.info(
                    "clip_fx applied: transition=%s color_grade=%s series=%d part=%d",
                    spec.fx.transition, spec.fx.color_grade, series_id, part_index,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("clip_fx skipped (non-fatal): %s", exc)

    # ── A12: hook title overlay ───────────────────────────────────────────────
    # Burns the clip's hook text as a branded title band for the first 2.5 s.
    # Pure drawtext via core.hook_overlay (no external deps, never fail render).
    if hook_text and hook_text.strip():
        try:
            from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
            from core.hook_overlay import hook_drawtext_filter  # noqa: PLC0415

            vf_hook = hook_drawtext_filter(hook_text)
            out = os.path.join(scratch, f"hook_{suffix}.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", current,
                "-vf", vf_hook,
                "-c:v", "libx264", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-c:a", "copy",
                out,
            ]
            run_ffmpeg_cmd(cmd)
            current = out
            logger.info("hook_overlay applied: series=%d part=%d", series_id, part_index)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hook_overlay skipped (non-fatal): %s", exc)

    return current


def _load_words_for_clip(
    *,
    video_id: str | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    db=None,
) -> list[dict]:
    """Load word-level timestamps for the clip from the Word table.

    Queries Word rows for *video_id* whose start time falls within
    [clip_start, clip_end].  The ``end`` time for each word is computed as
    the start of the next word (with a small gap cap of 0.3 s for the last
    word so it doesn't extend indefinitely).

    The session *db* must already be stamped with session.info["tenant_id"]
    by the caller (render_part passes its own stamped session).  When *db*
    or *video_id* is None the function returns an empty list silently.

    Returns an empty list when no transcript is available — callers must
    handle this gracefully (skip the engine, never fail the render).
    """
    if db is None or not video_id:
        return []
    if clip_start is None or clip_end is None:
        return []
    try:
        from app.models import Word  # noqa: PLC0415

        rows = (
            db.query(Word)
            .filter(
                Word.video_id == video_id,
                Word.start >= clip_start,
                Word.start < clip_end,
            )
            .order_by(Word.start)
            .all()
        )
        if not rows:
            return []

        result: list[dict] = []
        for i, row in enumerate(rows):
            w_start = float(row.start or 0.0)
            if i + 1 < len(rows):
                w_end = float(rows[i + 1].start or w_start)
            else:
                w_end = min(w_start + 0.3, float(clip_end))
            result.append({
                "word": str(row.word or ""),
                "start": w_start,
                "end": w_end,
                "confidence": float(row.confidence or 1.0),
            })
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("_load_words_for_clip: DB query failed: %s", exc)
        return []


def _load_safety_denylist(tenant_id: int | None, db) -> list[str]:
    """Return the tenant's configured safety_denylist terms (brand/competitor names
    to censor on top of the crude denylist). Empty list on any miss — never fails."""
    if db is None or not tenant_id:
        return []
    try:
        from sqlalchemy import text  # noqa: PLC0415
        row = db.execute(
            text("SELECT settings FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        ).fetchone()
        settings = (row.settings if row and hasattr(row, "settings") else (row[0] if row else None)) or {}
        terms = settings.get("safety_denylist") if isinstance(settings, dict) else None
        return terms if isinstance(terms, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("_load_safety_denylist: read failed: %s", exc)
        return []


def _resolve_music_track(catalog: str, track_id: str, scratch: str) -> str | None:
    """Resolve a catalog + track_id to a local audio file path.

    Returns None when the track cannot be resolved (missing catalog key,
    file not found, network error) — callers must skip gracefully.

    Supported catalogs:
      - ``"pixabay"``: queries Pixabay Audio API (PIXABAY_API_KEY required).
                       track_id may be a numeric Pixabay ID or a mood keyword
                       (e.g. ``"upbeat"``, ``"calm"``).
      - All others:    returns None with a log message.
    """
    logger.info("_resolve_music_track: catalog=%r track_id=%r", catalog, track_id)
    if catalog == "pixabay":
        try:
            from adapters.pixabay_audio import resolve_track  # noqa: PLC0415
            return resolve_track(track_id, scratch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_resolve_music_track: pixabay resolve failed: %s", exc)
            return None
    logger.info("_resolve_music_track: catalog=%r not implemented — returns None", catalog)
    return None


def _upload_to_gcs(local_path: str, bucket_name: str, object_key: str) -> str:
    """Upload *local_path* to the private GCS bucket and return a gs:// URI.

    The reels bucket is private; social_job mints a short-TTL signed URL at
    publish time via adapters.storage.signed_get_url.

    Returns:
        GCS URI ``gs://{bucket}/{key}``.
    """
    try:
        from google.cloud import storage  # noqa: PLC0415
        from google.cloud.exceptions import GoogleCloudError  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; "
            "run: pip install google-cloud-storage"
        ) from exc

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_key)
        blob.upload_from_filename(local_path, content_type="video/mp4")
    except GoogleCloudError as exc:
        raise RuntimeError(
            f"GCS upload failed (bucket={bucket_name!r}, key={object_key!r}): {exc}"
        ) from exc

    return _gs_uri(bucket_name, object_key)


def render_part(
    series_id: int,
    part_index: int,
    *,
    title_img: str | None = None,
    closing_img: str | None = None,
    work_dir: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """Render one part of a MiniSeries and publish it to GCS.

    Args:
        series_id:   Primary key of the MiniSeries row.
        part_index:  Zero-based index into MiniSeries.parts_json.
        title_img:   Path to the title card image (PNG/JPG).  When None a card
                     is generated automatically from the MiniSeries title.
        closing_img: Path to the closing card image (PNG/JPG).  When None a
                     card reading "Perkins Roofing" is generated automatically.
        work_dir:    Scratch directory for intermediate files.  A temporary
                     directory is used when None (cleaned up on exit).

    Returns:
        Dict::

            {
                "skipped":      bool,   # True when idempotency guard fired
                "series_id":    int,
                "part_index":   int,
                "gcs_url":      str,    # public reel URL
                "social_post_id": int,
                "scheduled_content_id": int | None,
            }

    Raises:
        RuntimeError: on missing env vars, GCS errors, or invalid series data.
        ValueError: if the clip duration exceeds 300 s (editorial-intent guard).
        IndexError: if part_index is out of range for the series' parts_json.
    """
    from app.models import MiniSeries, ScheduledContent, SessionLocal, SocialPost  # noqa: PLC0415

    db = SessionLocal()
    if tenant_id is not None:
        db.info["tenant_id"] = tenant_id
    try:
        # ── 1. Idempotency check ─────────────────────────────────────────────
        # Any per-platform row with a non-null gcs_url means this part was
        # already rendered — return early using the first matching row.
        existing = (
            db.query(SocialPost)
            .filter(
                SocialPost.series_id == series_id,
                SocialPost.part == part_index,
                SocialPost.gcs_url.isnot(None),
            )
            .first()
        )
        if existing and existing.gcs_url:
            logger.info(
                "render_part skipped (already rendered): series=%d part=%d url=%s",
                series_id,
                part_index,
                existing.gcs_url,
            )
            return {
                "skipped": True,
                "series_id": series_id,
                "part_index": part_index,
                "gcs_url": existing.gcs_url,
                "social_post_id": existing.id,
                "scheduled_content_id": None,
            }

        # ── 2. Load series metadata ──────────────────────────────────────────
        from app.models import Video  # noqa: PLC0415

        series = db.get(MiniSeries, series_id)
        if series is None:
            raise RuntimeError(f"MiniSeries id={series_id} not found")
        if not series.approved:
            raise RuntimeError(
                f"MiniSeries id={series_id} has not been admin-approved"
            )

        parts = get_clips(series.parts_json)
        if part_index >= len(parts):
            raise IndexError(
                f"part_index={part_index} out of range for series {series_id} "
                f"(has {len(parts)} parts)"
            )
        part = parts[part_index]
        start = float(part["start"])
        end = float(part["end"])
        # Per-part source video (topic-driven multi-source series carry a video_id per
        # part); fall back to the series' single source for classic single-source series.
        video_id = part.get("video_id") or series.video_id
        series_title = series.title or f"Series {series_id}"

        # Load the render spec saved by Clip Studio (defaults reproduce current behaviour).
        render_spec = get_render_spec(series.parts_json)

        # Brand-kit caption theming: optional font/primary-color override, sourced from
        # the tenant's brand kit (core.brand_kit). Absent/empty brand kit -> no overrides,
        # captions render exactly as they do today.
        from core.brand_kit import load_brand_kit  # noqa: PLC0415
        brand_kit = load_brand_kit(tenant_id or 1, db) or {}

        # Load Video row here so we can check archive_uri in _source_video_path.
        video_row = db.get(Video, video_id)
        # Snapshot the archive_uri — the ORM object will be detached after db.close().
        video_archive_uri = getattr(video_row, "archive_uri", None) if video_row else None

    finally:
        db.close()

    # ── 3. Enforce ≤300s cap ─────────────────────────────────────────────────
    clip_duration = end - start
    if clip_duration > _MAX_CLIP_SECS:
        raise ValueError(
            f"Clip duration {clip_duration:.1f}s exceeds the {_MAX_CLIP_SECS}s limit "
            f"(series={series_id}, part={part_index}, start={start}, end={end}). "
            "Adjust the part boundaries in the MiniSeries before rendering."
        )

    # ── 4-7. Download + clip + fuse + upload ─────────────────────────────────
    _use_tmp = work_dir is None
    _tmp_ctx = tempfile.TemporaryDirectory() if _use_tmp else None
    scratch = _tmp_ctx.name if _tmp_ctx else work_dir

    try:
        from adapters.ffmpeg import clip as ffmpeg_clip  # noqa: PLC0415
        from adapters.ffmpeg import fuse as ffmpeg_fuse  # noqa: PLC0415
        from adapters.ffmpeg import fuse_videos as ffmpeg_fuse_videos  # noqa: PLC0415
        from adapters.ffmpeg import make_card  # noqa: PLC0415

        # 4. Obtain source video — prefer archived GCS MP4, fall back to yt-dlp.
        # video_archive_uri was snapshotted from the Video row in the DB block above.
        logger.info("_source_video_path: video_id=%s archive_uri=%s -> %s", video_id, video_archive_uri, scratch)
        src_path = _source_video_path(video_id, video_archive_uri, scratch)

        # 5. Extract clip
        clip_path = os.path.join(scratch, f"clip_{series_id}_{part_index}.mp4")
        logger.info("clip: %s [%.2f, %.2f] -> %s", src_path, start, end, clip_path)
        ffmpeg_clip(src_path, start, end, clip_path)

        # 5a. Track A engine sequence (spec-driven; null spec = no-ops → backward compat)
        # Open a stamped read-only session for word timestamp queries (Item 1/#326).
        # Kept open only for the duration of the engine sequence, then closed.
        from app.models import SessionLocal as _SL  # noqa: PLC0415
        _words_db = _SL()
        if tenant_id is not None:
            _words_db.info["tenant_id"] = tenant_id
        try:
            clip_path = _apply_track_a_engines(
                clip_path, render_spec, scratch, series_id, part_index,
                video_id=video_id,
                clip_start=start,
                clip_end=end,
                db=_words_db,
                hook_text=part.get("hook") or None,
                brand_kit=brand_kit,
            )
        finally:
            _words_db.close()

        # 6 + 7. Fuse — brand video path (BRAND_INTRO_VIDEO / BRAND_OUTRO_VIDEO) takes
        # precedence over the image-card path when both are configured.
        reel_path = os.path.join(scratch, f"reel_{series_id}_{part_index}.mp4")

        intro_video, outro_video = _brand_video_config(scratch)
        if intro_video is not None and outro_video is not None:
            logger.info("fuse_videos (brand intro/outro) -> %s", reel_path)
            ffmpeg_fuse_videos(intro_video, clip_path, outro_video, reel_path)
        else:
            # Fallback: generated-card path (existing behaviour).
            part_title = part.get("title") or series_title

            # Apply uploaded brand scene images when the caller did not explicitly supply them.
            if title_img is None or closing_img is None:
                brand_title, brand_closing = _brand_scene_config(scratch)
                if title_img is None:
                    title_img = brand_title
                if closing_img is None:
                    closing_img = brand_closing

            if title_img is None:
                title_img = os.path.join(scratch, f"title_{series_id}_{part_index}.png")
                logger.info("make_card (title): %r -> %s", part_title, title_img)
                make_card(part_title, title_img)

            if closing_img is None:
                closing_img = os.path.join(scratch, f"closing_{series_id}_{part_index}.png")
                _ct = _closing_text()
                logger.info("make_card (closing): %r -> %s", _ct, closing_img)
                make_card(_ct, closing_img)

            logger.info("fuse (image cards) -> %s", reel_path)
            ffmpeg_fuse(clip_path, title_img, closing_img, reel_path)

        # Emit render duration to per-tenant metering (no-op outside a tenant context).
        # clip_duration is the part's wall-clock length; convert seconds → minutes.
        metering.add("render_minutes", clip_duration / 60.0)

        # ── Multi-aspect export (Item 6 + 16:9 parity) ─────────────────────────
        # When the render spec includes "square" and/or "wide" in aspects, produce
        # an extra export from the finished reel (scale+pad, black bars — see
        # core.render_spec.aspect_export_vf). Each variant is uploaded to GCS
        # under a sibling key and recorded in a separate SocialPost row with
        # platform tagged as "{platform}:{aspect}".
        # Default: 9:16 only (no aspects field → no extra passes).
        aspects = list(render_spec.aspects) if hasattr(render_spec, "aspects") else []
        extra_aspect_gcs_urls: dict[str, str] = {}
        for _aspect in ("square", "wide"):
            if _aspect not in aspects:
                continue
            try:
                from adapters.ffmpeg import run_ffmpeg_cmd  # noqa: PLC0415
                from core.render_spec import aspect_export_vf  # noqa: PLC0415

                aspect_path = os.path.join(scratch, f"{_aspect}_{series_id}_{part_index}.mp4")
                run_ffmpeg_cmd([
                    "ffmpeg", "-y", "-i", reel_path,
                    "-vf", aspect_export_vf(_aspect),
                    "-c:v", "libx264", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-c:a", "copy",
                    aspect_path,
                ])
                aspect_key = _gcs_object_key(series_id, part_index, tenant_id=tenant_id or 1).replace(
                    ".mp4", f"_{_aspect}.mp4"
                )
                bucket_name_extra = _reels_bucket()
                extra_aspect_gcs_urls[_aspect] = _upload_to_gcs(aspect_path, bucket_name_extra, aspect_key)
                logger.info("%s export uploaded: %s", _aspect, extra_aspect_gcs_urls[_aspect])
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s export skipped (non-fatal): %s", _aspect, exc)

        # 8. Upload to GCS (private bucket — returns gs:// URI)
        bucket_name = _reels_bucket()
        object_key = _gcs_object_key(series_id, part_index, tenant_id=tenant_id or 1)
        logger.info("uploading to gs://%s/%s", bucket_name, object_key)
        gcs_url = _upload_to_gcs(reel_path, bucket_name, object_key)
        logger.info("upload complete: %s", gcs_url)

    finally:
        if _tmp_ctx:
            _tmp_ctx.cleanup()

    # ── 9. Persist SocialPost (one row per platform) + ScheduledContent ─────────
    # One SocialPost row per platform so social_job.already_posted works
    # uniformly — no combined "instagram,tiktok" rows.
    _platforms = [p.strip() for p in _DEFAULT_PLATFORM.split(",") if p.strip()]

    db = SessionLocal()
    if tenant_id is not None:
        db.info["tenant_id"] = tenant_id
    try:
        first_post_id: int | None = None
        for platform in _platforms:
            p_post = (
                db.query(SocialPost)
                .filter(
                    SocialPost.series_id == series_id,
                    SocialPost.part == part_index,
                    SocialPost.platform == platform,
                )
                .first()
            )
            if p_post is None:
                p_post = SocialPost(
                    series_id=series_id,
                    part=part_index,
                    platform=platform,
                )
                db.add(p_post)
            p_post.gcs_url = gcs_url  # gs:// URI — signed at publish time
            p_post.status = "rendered"
            db.flush()
            if first_post_id is None:
                first_post_id = p_post.id

        # Insert ScheduledContent row for the Wave-4 promoter.
        # publish_at=utcnow() so scheduler.due can select it immediately;
        # target records the destination platforms.
        sched = ScheduledContent(
            kind="reel",
            ref_id=str(first_post_id),
            publish_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="scheduled",
            target=_DEFAULT_PLATFORM,
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)

        logger.info(
            "persisted %d SocialPost rows ScheduledContent id=%d gcs_url=%s",
            len(_platforms),
            sched.id,
            gcs_url,
        )
        return {
            "skipped": False,
            "series_id": series_id,
            "part_index": part_index,
            "gcs_url": gcs_url,
            "social_post_id": first_post_id,
            "scheduled_content_id": sched.id,
        }
    finally:
        db.close()


def _run_for_tenant(
    db,
    tenant_id: int,
    limit: int | None = None,
    *,
    series_id: int | None = None,
) -> dict:
    """Per-tenant render sweep body. Called by for_each_tenant via run()."""
    from app.models import MiniSeries, SocialPost  # noqa: PLC0415
    from core.brand_kit import load_brand_kit  # noqa: PLC0415

    bk = load_brand_kit(tenant_id, db)
    logger.info("render: loaded brand kit for tenant %d (logo=%s)", tenant_id, bool(bk))

    if series_id is not None:
        query = db.query(MiniSeries).filter(
            MiniSeries.id == series_id,
            MiniSeries.approved == 1,
        )
    else:
        query = db.query(MiniSeries).filter(MiniSeries.approved == 1)
        if limit is not None:
            query = query.limit(limit)
    approved = query.all()

    work: list[tuple[int, int]] = []
    for series in approved:
        parts = get_clips(series.parts_json)
        for part_index in range(len(parts)):
            rendered = (
                db.query(SocialPost)
                .filter(
                    SocialPost.series_id == series.id,
                    SocialPost.part == part_index,
                    SocialPost.gcs_url.isnot(None),
                )
                .first()
            )
            if not rendered:
                work.append((series.id, part_index))

    rendered_count = 0
    skipped_count = 0
    errored_count = 0

    for sid, part_index in work:
        try:
            result = render_part(sid, part_index, tenant_id=tenant_id)
            if result["skipped"]:
                skipped_count += 1
            else:
                rendered_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("render_part error series=%d part=%d: %s", sid, part_index, exc)
            errored_count += 1

    return {"rendered": rendered_count, "skipped": skipped_count, "errored": errored_count}


def run(limit: int | None = None, *, series_id: int | None = None) -> dict:
    """Iterate active tenants and render approved MiniSeries parts for each.

    When *series_id* is given (or the env var ``RENDER_SERIES_ID`` is set),
    only that single series is processed per tenant.

    Args:
        limit:     Maximum number of *series* to process per tenant (full-sweep only).
        series_id: If set, render only this series (ignores *limit*).

    Returns:
        Dict::

            {
                "rendered": int,   # parts successfully rendered
                "skipped":  int,   # parts already rendered (idempotency)
                "errored":  int,   # parts that raised an exception
            }
    """
    _env_series_id = os.getenv("RENDER_SERIES_ID")
    if _env_series_id and series_id is None:
        series_id = int(_env_series_id)

    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"rendered": 0, "skipped": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, limit=limit, series_id=series_id)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    # RENDER_SERIES_ID env var is read inside run(); pass limit from argv only for full-sweep.
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(run(limit=_limit), indent=2))
