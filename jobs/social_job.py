"""Social publishing job (I/O orchestration — coverage-omitted).

Selects ScheduledContent rows with kind="reel" status="awaiting_social",
mints a short-TTL signed URL for the reel's GCS object, then calls the
matching platform publisher for each target platform — unless already_posted
says we've already done it (idempotency).

Run:
    .venv/bin/python -m jobs.social_job

Env vars required for live posting (not needed for a pre-creds dry run):
    IG_USER_ID, META_SYSTEM_USER_TOKEN   — Instagram
    TIKTOK_ACCESS_TOKEN, TIKTOK_OPEN_ID  — TikTok

If any social credential env var is absent the job logs a warning and returns
cleanly so it is safe to schedule before the Meta/TikTok app review lands.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

_PLATFORM_CREDS: dict[str, list[str]] = {
    "instagram": ["IG_USER_ID", "META_SYSTEM_USER_TOKEN"],
    "tiktok": ["TIKTOK_ACCESS_TOKEN", "TIKTOK_OPEN_ID"],
}

_SIGNED_URL_TTL = 3600  # seconds — enough for the platform to pull the video


def _creds_present(platform: str) -> bool:
    return all(os.environ.get(k) for k in _PLATFORM_CREDS.get(platform, []))


def _publisher(platform: str):
    """Return an initialised publisher for *platform*.

    For TikTok: if TIKTOK_REFRESH_TOKEN is set, refresh the access token first
    and use the returned access_token for this publish call.  The rotated
    refresh_token must be persisted back to Secret Manager in prod (not yet
    wired — see TODO below).
    """
    if platform == "instagram":
        from adapters.meta_ig import IgPublisher  # noqa: PLC0415
        return IgPublisher()
    if platform == "tiktok":
        from adapters.tiktok import TikTokPublisher  # noqa: PLC0415
        refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN")
        if refresh_token:
            try:
                from adapters.tiktok import refresh_access_token  # noqa: PLC0415
                refreshed = refresh_access_token()
                new_token = refreshed["access_token"]
                logger.info("social_job: TikTok access token refreshed via refresh_token")
                # TODO: persist refreshed["refresh_token"] back to Secret Manager in prod
                return TikTokPublisher(access_token=new_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "social_job: TikTok token refresh failed (%s) — falling back to env token",
                    exc,
                )
        return TikTokPublisher()
    raise ValueError(f"Unknown platform: {platform!r}")


def _gcs_key_from_url(gcs_url: str) -> tuple[str, str]:
    """Parse a GCS public URL or gs:// URI into (bucket, key).

    Accepts:
      - ``https://storage.googleapis.com/{bucket}/{key}``
      - ``gs://{bucket}/{key}``
    """
    if gcs_url.startswith("gs://"):
        rest = gcs_url[len("gs://"):]
    elif gcs_url.startswith("https://storage.googleapis.com/"):
        rest = gcs_url[len("https://storage.googleapis.com/"):]
    else:
        raise ValueError(f"Cannot parse GCS URL: {gcs_url!r}")
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"Malformed GCS URL (missing bucket or key): {gcs_url!r}")
    return bucket, key


def run() -> dict:
    """Publish all due reels to their target social platforms.

    Returns:
        Dict::

            {
                "published": int,   # platform posts successfully created
                "skipped":   int,   # already posted (idempotency) or no-creds
                "errored":   int,   # rows that raised an exception
            }
    """
    from app.models import MiniSeries, ScheduledContent, SessionLocal, SocialPost  # noqa: PLC0415
    from core.social import already_posted, build_caption  # noqa: PLC0415

    # Check whether any social credentials are present at all.
    any_creds = any(_creds_present(p) for p in _PLATFORM_CREDS)
    if not any_creds:
        logger.warning("social creds not configured — skipping")
        return {"published": 0, "skipped": 0, "errored": 0}

    db = SessionLocal()
    try:
        due_rows = (
            db.query(ScheduledContent)
            .filter(
                ScheduledContent.kind == "reel",
                ScheduledContent.status == "awaiting_social",
            )
            .all()
        )
    finally:
        db.close()

    published = 0
    skipped = 0
    errored = 0

    for sched in due_rows:
        try:
            db = SessionLocal()
            try:
                # Resolve the SocialPost (ref_id is the social_post pk as a string)
                post = db.get(SocialPost, int(sched.ref_id))
                if post is None:
                    logger.error(
                        "social_job: ScheduledContent id=%d ref_id=%r has no SocialPost row",
                        sched.id,
                        sched.ref_id,
                    )
                    errored += 1
                    continue

                # Determine target platforms from ScheduledContent.target
                targets = [t.strip() for t in (sched.target or "").split(",") if t.strip()]
                if not targets:
                    logger.warning(
                        "social_job: ScheduledContent id=%d has no target platforms — skipping",
                        sched.id,
                    )
                    skipped += 1
                    continue

                # Fetch all existing SocialPost rows for this series/part to check idempotency
                existing_posts = (
                    db.query(SocialPost)
                    .filter(
                        SocialPost.series_id == post.series_id,
                        SocialPost.part == post.part,
                    )
                    .all()
                )

                # Mint a signed GET URL (no attachment disposition) for platform ingestion
                from adapters.storage import signed_get_url  # noqa: PLC0415
                bucket, key = _gcs_key_from_url(post.gcs_url)
                video_url = signed_get_url(bucket, key, _SIGNED_URL_TTL)

                # Resolve the real reel title from MiniSeries.parts_json
                _title = ""
                try:
                    series = db.get(MiniSeries, post.series_id)
                    if series is not None:
                        parts = series.parts_json or []
                        if post.part < len(parts):
                            _title = parts[post.part].get("title") or series.title or ""
                        else:
                            _title = series.title or ""
                except Exception:  # noqa: BLE001
                    pass
                caption = build_caption(_title or f"Perkins Roofing Part {post.part + 1}", [])
                idempotency_key = f"series-{post.series_id}-part-{post.part}"

                all_done = True
                for platform in targets:
                    if already_posted(existing_posts, platform):
                        logger.info(
                            "social_job: series=%d part=%d platform=%s already posted — skip",
                            post.series_id,
                            post.part,
                            platform,
                        )
                        skipped += 1
                        continue

                    if not _creds_present(platform):
                        logger.warning(
                            "social_job: no creds for platform=%s — skipping", platform
                        )
                        skipped += 1
                        all_done = False
                        continue

                    try:
                        pub = _publisher(platform)
                        external_id = pub.publish(
                            video_url=video_url,
                            caption=caption,
                            idempotency_key=idempotency_key,
                        )
                    except Exception as pub_exc:  # noqa: BLE001
                        logger.error(
                            "social_job: publish failed series=%d part=%d platform=%s: %s",
                            post.series_id,
                            post.part,
                            platform,
                            pub_exc,
                        )
                        errored += 1
                        all_done = False
                        continue

                    # Persist external_id on a per-platform SocialPost row
                    platform_post = (
                        db.query(SocialPost)
                        .filter(
                            SocialPost.series_id == post.series_id,
                            SocialPost.part == post.part,
                            SocialPost.platform == platform,
                        )
                        .first()
                    )
                    if platform_post is None:
                        # First time for this platform: create a dedicated row.
                        # If the unique constraint fires (concurrent worker), treat
                        # it as "already claimed" and skip — do NOT re-post.
                        try:
                            platform_post = SocialPost(
                                series_id=post.series_id,
                                part=post.part,
                                platform=platform,
                                gcs_url=post.gcs_url,
                            )
                            db.add(platform_post)
                            db.flush()
                        except IntegrityError:
                            db.rollback()
                            logger.warning(
                                "social_job: unique constraint on series=%d part=%d platform=%s "
                                "— already claimed by concurrent worker, skipping",
                                post.series_id,
                                post.part,
                                platform,
                            )
                            skipped += 1
                            all_done = False
                            continue

                    platform_post.external_id = external_id
                    platform_post.status = "posted"
                    db.add(platform_post)
                    # Commit per successful platform so external_id is durable
                    # before the next platform is attempted — a mid-loop crash
                    # and retry will skip already-posted platforms cleanly.
                    db.commit()
                    published += 1
                    logger.info(
                        "social_job: posted series=%d part=%d platform=%s external_id=%s",
                        post.series_id,
                        post.part,
                        platform,
                        external_id,
                    )

                    # Refresh existing_posts so subsequent platforms see this row
                    existing_posts = (
                        db.query(SocialPost)
                        .filter(
                            SocialPost.series_id == post.series_id,
                            SocialPost.part == post.part,
                        )
                        .all()
                    )

                # Mark ScheduledContent published only when all platforms succeeded
                if all_done:
                    sc = db.get(ScheduledContent, sched.id)
                    if sc is not None:
                        sc.status = "published"
                        db.add(sc)
                    db.commit()

            finally:
                db.close()

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "social_job: unhandled error for ScheduledContent id=%d: %s",
                sched.id,
                exc,
            )
            errored += 1

    return {"published": published, "skipped": skipped, "errored": errored}


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
    sys.exit(0)
