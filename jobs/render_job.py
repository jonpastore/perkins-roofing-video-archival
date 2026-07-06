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
        from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

        with SessionLocal() as db:
            row = db.get(PlatformConfig, "REEL_CLOSING_TEXT")
            if row and row.value and row.value.strip():
                return row.value.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("_closing_text: could not read platform_config: %s", exc)
    return _CLOSING_TEXT_DEFAULT


def _brand_scene_config() -> tuple[str | None, str | None]:
    """Return (title_img_path, closing_img_path) from platform_config when REEL_APPLY_BRAND_SCENES=true.

    Reads REEL_APPLY_BRAND_SCENES, REEL_TITLE_IMG, and REEL_CLOSING_IMG.
    Returns (None, None) when the flag is off or config is unavailable.
    When an img key holds a gs:// URI, downloads it to a temp file and returns
    the local path so render_part can pass it to make_card/fuse directly.
    """
    try:
        from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

        with SessionLocal() as db:
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

    def _resolve(gs_uri: str) -> str | None:
        if not gs_uri:
            return None
        if not gs_uri.startswith("gs://"):
            # Plain local path (dev/test convenience) — use as-is if it exists.
            return gs_uri if os.path.exists(gs_uri) else None
        try:
            without_scheme = gs_uri[len("gs://"):]
            slash = without_scheme.index("/")
            bucket = without_scheme[:slash]
            key = without_scheme[slash + 1:]
            ext = os.path.splitext(key)[-1] or ".png"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                local_path = tmp.name
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


def _gcs_object_key(series_id: int, part_index: int) -> str:
    return f"{series_id}/{part_index}.mp4"


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

        parts = series.parts_json or []
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
        from adapters.ffmpeg import make_card  # noqa: PLC0415

        # 4. Obtain source video — prefer archived GCS MP4, fall back to yt-dlp.
        # video_archive_uri was snapshotted from the Video row in the DB block above.
        logger.info("_source_video_path: video_id=%s archive_uri=%s -> %s", video_id, video_archive_uri, scratch)
        src_path = _source_video_path(video_id, video_archive_uri, scratch)

        # 5. Extract clip
        clip_path = os.path.join(scratch, f"clip_{series_id}_{part_index}.mp4")
        logger.info("clip: %s [%.2f, %.2f] -> %s", src_path, start, end, clip_path)
        ffmpeg_clip(src_path, start, end, clip_path)

        # 6. Generate cards if not supplied
        part_title = part.get("title") or series_title

        # Apply uploaded brand scenes when the caller did not explicitly supply images.
        if title_img is None or closing_img is None:
            brand_title, brand_closing = _brand_scene_config()
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

        # 7. Fuse
        reel_path = os.path.join(scratch, f"reel_{series_id}_{part_index}.mp4")
        logger.info("fuse -> %s", reel_path)
        ffmpeg_fuse(clip_path, title_img, closing_img, reel_path)

        # 8. Upload to GCS (private bucket — returns gs:// URI)
        bucket_name = _reels_bucket()
        object_key = _gcs_object_key(series_id, part_index)
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


def run(limit: int | None = None, *, series_id: int | None = None) -> dict:
    """Sweep approved MiniSeries and render any unrendered parts.

    When *series_id* is given (or the env var ``RENDER_SERIES_ID`` is set),
    only that single series is processed — used by the Cloud Run Admin API
    trigger so an admin can kick off a targeted render from the UI.  The
    existing full-sweep behaviour is preserved when neither is set.

    Args:
        limit:     Maximum number of *series* to process (full-sweep only).
        series_id: If set, render only this series (ignores *limit*).

    Returns:
        Dict::

            {
                "rendered": int,   # parts successfully rendered
                "skipped":  int,   # parts already rendered (idempotency)
                "errored":  int,   # parts that raised an exception
            }
    """
    # Env-var override (set by the Cloud Run job execution via containerOverrides).
    _env_series_id = os.getenv("RENDER_SERIES_ID")
    if _env_series_id and series_id is None:
        series_id = int(_env_series_id)

    from app.models import MiniSeries, SessionLocal, SocialPost  # noqa: PLC0415

    db = SessionLocal()
    try:
        if series_id is not None:
            # Targeted render — fetch only this series.
            query = db.query(MiniSeries).filter(
                MiniSeries.id == series_id,
                MiniSeries.approved == 1,
            )
        else:
            query = db.query(MiniSeries).filter(MiniSeries.approved == 1)
            if limit is not None:
                query = query.limit(limit)
        approved = query.all()
        # Snapshot: build list of (series_id, part_index) pairs to render
        work: list[tuple[int, int]] = []
        for series in approved:
            parts = series.parts_json or []
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
    finally:
        db.close()

    rendered_count = 0
    skipped_count = 0
    errored_count = 0

    for series_id, part_index in work:
        try:
            result = render_part(series_id, part_index)
            if result["skipped"]:
                skipped_count += 1
            else:
                rendered_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "render_part error series=%d part=%d: %s",
                series_id,
                part_index,
                exc,
            )
            errored_count += 1

    return {
        "rendered": rendered_count,
        "skipped": skipped_count,
        "errored": errored_count,
    }


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    # RENDER_SERIES_ID env var is read inside run(); pass limit from argv only for full-sweep.
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(run(limit=_limit), indent=2))
