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

from core.social_creds import creds_for

logger = logging.getLogger(__name__)

_PLATFORM_CREDS: dict[str, list[str]] = {
    "instagram": ["IG_USER_ID", "META_SYSTEM_USER_TOKEN"],
    "tiktok": ["TIKTOK_ACCESS_TOKEN", "TIKTOK_OPEN_ID"],
}

_SIGNED_URL_TTL = 3600  # seconds — enough for the platform to pull the video


def _publisher(platform: str, creds: dict, tenant_id: int):
    """Return an initialised publisher for *platform* using resolved *creds*
    (OAuth store first, env fallback — see core.social_creds.creds_for). Only the
    creds keys that are present are passed; absent ones let the adapter keep its env
    default, preserving the pre-store behaviour.

    For TikTok: if a refresh token is available, refresh the access token first and
    persist the rotated tokens back to Secret Manager (TikTok rotates the refresh_token,
    so the old one goes stale — without write-back, auth eventually breaks).
    """
    if platform == "instagram":
        from adapters.meta_ig import IgPublisher  # noqa: PLC0415
        kwargs = {k: creds[k] for k in ("ig_user_id", "access_token") if creds.get(k)}
        return IgPublisher(**kwargs)
    if platform == "tiktok":
        from adapters.tiktok import TikTokPublisher  # noqa: PLC0415
        kwargs = {k: creds[k] for k in ("access_token", "open_id") if creds.get(k)}
        _rt = creds.get("refresh_token") or os.environ.get("TIKTOK_REFRESH_TOKEN")
        if _rt:
            try:
                from adapters.tiktok import refresh_access_token  # noqa: PLC0415
                refreshed = refresh_access_token(refresh_token=_rt)
                kwargs["access_token"] = refreshed["access_token"]
                logger.info("social_job: TikTok access token refreshed via refresh_token")
                # Persist the rotated tokens so the next run reads the fresh refresh_token,
                # not the now-stale one. Non-fatal — a failed write must not block the post.
                try:
                    from adapters.distribution.oauth_store import (  # noqa: PLC0415
                        SINGLE_ACCOUNT,
                        SecretManagerOAuthStore,
                    )
                    # SINGLE_ACCOUNT, not the open_id: the store's path is account-scoped now, and
                    # core.social_creds reads it under SINGLE_ACCOUNT. Writing the open_id here
                    # would rotate a token into a secret nothing ever reads, and the next run
                    # would keep using the stale refresh_token.
                    SecretManagerOAuthStore(tenant_id=tenant_id).put(
                        "tiktok", SINGLE_ACCOUNT,
                        refreshed["access_token"], refreshed.get("refresh_token") or _rt,
                    )
                except Exception as store_exc:  # noqa: BLE001
                    logger.warning("social_job: TikTok token persist failed (non-fatal): %s", store_exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "social_job: TikTok token refresh failed (%s) — using resolved token", exc,
                )
        return TikTokPublisher(**kwargs)
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


#: generate_titles speaks "youtube"; the publish target and PLATFORM_PRESETS say "youtube_shorts".
#: One alias table rather than two vocabularies that drift — this repo's most-repeated defect is a
#: key shaped by its source instead of by what it varies over.
_COPY_PLATFORM = {"youtube_shorts": "youtube", "youtube": "youtube"}


def _copy_for_part(part: dict, clip_title: str) -> dict:
    """Per-platform copy for one part: {platform: {title, hashtags, description}}.

    Generated on FIRST PUBLISH and cached into parts_json, not at save time — the save endpoint is
    an interactive request and three LLM calls per part would hang it, and copy is only worth
    paying for on parts that actually ship.

    Grounding is the part's title and hook. ponytail: the transcript for [start,end] would ground
    it better, but that is a query this job does not otherwise need; revisit if the copy reads thin.
    """
    from core.clip_select import generate_titles  # noqa: PLC0415

    def _gen(prompt: str) -> str:
        from app.llm import chat  # noqa: PLC0415
        return chat(prompt, want_json=False)

    return generate_titles(
        {"title": clip_title, "text": part.get("hook") or clip_title},
        gen_fn=_gen,
    )


def _caption_for(platform: str, part: dict, fallback_title: str) -> str:
    """Caption for ONE platform, held to that platform's hashtag count.

    Was built once and reused for every target, so per-platform copy could not reach a platform
    even once something generated it. TikTok wants 5 tags and LinkedIn 2; one caption cannot be
    both.
    """
    from core.clip_select import CORE_HASHTAGS  # noqa: PLC0415
    from core.platform_specs import PLATFORM_PRESETS  # noqa: PLC0415
    from core.social import build_caption  # noqa: PLC0415

    per_platform = (part.get("copy") or {}).get(_COPY_PLATFORM.get(platform, platform)) or {}
    title = per_platform.get("title") or part.get("title") or fallback_title
    tags = per_platform.get("hashtags") or part.get("hashtags") or CORE_HASHTAGS

    # The ceiling, again in code rather than only in the prompt. generate_titles' prompt asks for
    # the right number; parse_title_output does not enforce it, and TikTok rejects an overrun.
    limit = (PLATFORM_PRESETS.get(platform) or {}).get("hashtag_count")
    if limit and len(tags) > int(limit):
        logger.info("social_job: trimmed %d hashtag(s) for %s", len(tags) - int(limit), platform)
        tags = tags[:int(limit)]

    return build_caption(title, tags)


def _run_for_tenant(db, tenant_id: int) -> dict:
    """Per-tenant social publish body. Called by for_each_tenant via run()."""
    from app.models import MiniSeries, ScheduledContent, SessionLocal, SocialPost  # noqa: PLC0415
    from core.social import already_posted  # noqa: PLC0415

    any_creds = any(creds_for(p, tenant_id) for p in _PLATFORM_CREDS)
    if not any_creds:
        logger.warning("social creds not configured — skipping")
        return {"published": 0, "skipped": 0, "errored": 0}

    due_rows = (
        db.query(ScheduledContent)
        .filter(
            ScheduledContent.kind == "reel",
            ScheduledContent.status == "awaiting_social",
        )
        .all()
    )

    published = 0
    skipped = 0
    errored = 0

    for sched in due_rows:
        try:
            db = SessionLocal()
            db.info["tenant_id"] = tenant_id
            did_claim = False
            try:
                # Atomically claim this row (awaiting_social -> publishing) so two
                # overlapping cron runs can't both post the same reel. A concurrent run
                # sees 0 rows affected and skips. did_claim gates the release in finally
                # so we never revert a claim another worker holds.
                did_claim = bool(
                    db.query(ScheduledContent)
                    .filter(
                        ScheduledContent.id == sched.id,
                        ScheduledContent.status == "awaiting_social",
                    )
                    .update({"status": "publishing"}, synchronize_session=False)
                )
                db.commit()
                if not did_claim:
                    skipped += 1
                    continue

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

                # Resolve the real reel title + hashtags from MiniSeries.parts_json.
                # Per-part hashtags are written by core.clip_select.generate_titles (A4)
                # when copy generation has run; otherwise the channel's core tags apply —
                # an empty list here was bug #343 (posts shipped with no hashtags at all).
                _title = ""
                _part: dict = {}
                try:
                    series = db.get(MiniSeries, post.series_id)
                    if series is not None:
                        parts = series.parts_json or []
                        if post.part < len(parts):
                            _part = parts[post.part] or {}
                            _title = _part.get("title") or series.title or ""
                        else:
                            _title = series.title or ""

                        # Generate the per-platform copy ONCE and cache it. Until this existed,
                        # generate_titles was never called anywhere outside tests while the comment
                        # here claimed it wrote these hashtags — so every post shipped with the
                        # three fixed CORE_HASHTAGS and the per-platform copy was unreachable.
                        if _part and not _part.get("copy"):
                            try:
                                copy = _copy_for_part(_part, _title)
                            except Exception as gen_exc:  # noqa: BLE001
                                # Never block a publish on copy generation. The fallback chain
                                # below still yields a valid caption.
                                logger.warning(
                                    "social_job: copy generation failed series=%d part=%d: %s",
                                    post.series_id, post.part, gen_exc,
                                )
                                copy = {}
                            if copy:
                                # Reassign the whole list — SQLAlchemy does not track in-place
                                # mutation of a JSON column, so mutating parts[i] in place would
                                # be silently dropped at commit.
                                new_parts = list(parts)
                                new_parts[post.part] = {**_part, "copy": copy}
                                series.parts_json = new_parts
                                _part = new_parts[post.part]
                                db.commit()
                                logger.info(
                                    "social_job: cached copy for series=%d part=%d platforms=%s",
                                    post.series_id, post.part, sorted(copy),
                                )
                except Exception as exc:  # noqa: BLE001
                    # Falling back is correct — a reel must still ship rather than be blocked on
                    # copy resolution — but doing it SILENTLY is how bug #343 (posts with no
                    # hashtags at all) went unnoticed. The reel goes out with a generic title and
                    # the three fixed CORE_HASHTAGS; say so, or nobody ever learns the real copy
                    # was never resolved.
                    logger.warning(
                        "social_job: copy resolution failed series=%d part=%d — publishing with "
                        "the generic title and core hashtags instead: %s",
                        post.series_id, post.part, exc,
                    )
                _title = _title or f"Perkins Roofing Part {post.part + 1}"
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

                    creds = creds_for(platform, tenant_id)
                    if not creds:
                        logger.warning(
                            "social_job: no creds for platform=%s — skipping", platform
                        )
                        skipped += 1
                        all_done = False
                        continue

                    try:
                        pub = _publisher(platform, creds, tenant_id)
                        external_id = pub.publish(
                            video_url=video_url,
                            # Per platform, not one caption reused across all of them.
                            caption=_caption_for(platform, _part, _title),
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

                # Mark ScheduledContent published only when all platforms succeeded.
                if all_done:
                    sc = db.get(ScheduledContent, sched.id)
                    if sc is not None:
                        sc.status = "published"
                        db.add(sc)
                    db.commit()

            finally:
                # Release our own claim on any non-published exit (early continue,
                # partial failure, or exception): a row we left in "publishing" goes
                # back to awaiting_social so the next cron retries it. Gated on did_claim
                # so we never touch a claim another worker holds.
                if did_claim:
                    try:
                        sc = db.get(ScheduledContent, sched.id)
                        if sc is not None and sc.status == "publishing":
                            sc.status = "awaiting_social"
                            db.add(sc)
                            db.commit()
                    except Exception:  # noqa: BLE001
                        db.rollback()
                db.close()

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "social_job: unhandled error for ScheduledContent id=%d: %s",
                sched.id,
                exc,
            )
            errored += 1

    return {"published": published, "skipped": skipped, "errored": errored}


def run() -> dict:
    """Iterate active tenants and publish due reels for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"published": 0, "skipped": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    totals = run()
    print(json.dumps(totals, indent=2))
    # EXIT NON-ZERO WHEN PUBLISHES FAILED. This was a hard-coded sys.exit(0) printed directly
    # under {"errored": N} — every Instagram and TikTok publish in a run could fail and the Cloud
    # Run Job execution still went green. A job that reports success while losing the customer's
    # posts is the same shape as the stale-deploy incident: nothing red anywhere to notice.
    # jobs/archive_job.py already exits 1 on failure; this brings the publishing job in line.
    sys.exit(1 if totals.get("errored") else 0)
