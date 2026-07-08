"""Multi-platform distribution driver (I/O orchestration — coverage-omitted).

SCAFFOLD: mocked end-to-end — real posting blocked on app-review/creds for all new platforms.
The IG and TikTok adapters already exist (adapters/meta_ig.py, adapters/tiktok.py) and
will be wired through here once the social_job.py refactor lands.

Flow for a single finished clip:
  1. Resolve destinations (caller-supplied list of platform keys).
  2. Per destination:
       a. transcode_spec(platform)  — encoding requirements
       b. render_caption(template, vars)  — interpolate location/product/crew
       c. oauth_store.access_token(platform, account_id)  — get current token
       d. adapter.publish(video_url, caption, token)  — post (mocked)
       e. Drive the state machine: PENDING → IN_FLIGHT → PUBLISHED | FAILED
       f. On failure: retry with exponential backoff up to max_attempts
  3. Return a per-platform result dict.

Run (dry-run / scaffold smoke-test):
    .venv/bin/python -m jobs.distribute_job

Env vars required for live posting (not available yet — blocked on app-review):
    YOUTUBE_OAUTH_TOKEN, FACEBOOK_PAGE_TOKEN, LINKEDIN_TOKEN,
    X_BEARER_TOKEN, PINTEREST_TOKEN
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from core.publish_dispatch import (
    Status,
    backoff_seconds,
    next_status,
    render_caption,
    should_retry,
    transcode_spec,
)

logger = logging.getLogger(__name__)

# Default retry policy
_DEFAULT_MAX_ATTEMPTS = 3

# Platform → adapter module path (lazy import keeps the driver importable without optional deps)
_ADAPTER_MAP: dict[str, str] = {
    "youtube_shorts": "adapters.distribution.youtube_shorts",
    "facebook": "adapters.distribution.facebook",
    "linkedin": "adapters.distribution.linkedin",
    "x": "adapters.distribution.x",
    "pinterest": "adapters.distribution.pinterest",
    # instagram and tiktok remain in adapters/ root (existing adapters)
    # and will be unified here in a future refactor once creds land
}

_ADAPTER_CLASS: dict[str, str] = {
    "youtube_shorts": "YouTubeShortsAdapter",
    "facebook": "FacebookAdapter",
    "linkedin": "LinkedInAdapter",
    "x": "XAdapter",
    "pinterest": "PinterestAdapter",
}


@dataclass
class DistributeResult:
    """Result for a single clip → platform distribution attempt."""

    platform: str
    status: Status
    post_id: str | None = None
    url: str | None = None
    attempts: int = 0
    error: str | None = None
    spec: dict = field(default_factory=dict)


def _load_adapter(platform: str) -> Any:
    """Lazily import and instantiate the adapter for *platform*.

    Raises:
        ValueError: if *platform* is not in the supported map.
    """
    if platform not in _ADAPTER_MAP:
        raise ValueError(
            f"No adapter registered for platform={platform!r}. "
            f"Supported: {sorted(_ADAPTER_MAP)}"
        )
    import importlib  # noqa: PLC0415
    mod = importlib.import_module(_ADAPTER_MAP[platform])
    cls = getattr(mod, _ADAPTER_CLASS[platform])
    return cls()


def distribute(
    *,
    video_url: str,
    caption_template: str = "",
    caption_vars: dict[str, str] | None = None,
    destinations: list[str],
    account_id: str = "default",
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    oauth_store: Any = None,
    raw_caption_output: str | None = None,
    require_license: bool = False,
    _sleep_fn: Any = None,
) -> list[DistributeResult]:
    """Fan-out a finished clip to all selected destination platforms.

    Args:
        video_url:        Public HTTPS URL of the source clip (GCS signed URL recommended).
        caption_template: Caption template string with ``{location}``/``{product}``/``{crew}`` vars.
        caption_vars:     Variable substitutions for the template.
        destinations:     List of platform keys to post to, e.g. ``["youtube_shorts", "facebook"]``.
        account_id:       Account identifier for the OAuth store lookup (default ``"default"``).
        max_attempts:     Maximum publish attempts per platform before giving up (default 3).
        oauth_store:      OAuthStore instance (defaults to the module-level singleton).
        raw_caption_output: Optional raw v3 caption-prompt output (with FLAGS/CAPTION/HASHTAGS).
                          When given, it is parsed and flag-gated before fan-out; a BLOCKED
                          decision fails every destination and the parsed caption replaces the
                          template. See docs/prompts/social-caption-v3.md + core.caption_output.
        require_license:  If True, a MISSING_LICENSE flag blocks the post (FL ad compliance).
        _sleep_fn:        Override ``time.sleep`` for testing.

    Returns:
        List of :class:`DistributeResult`, one per destination.
    """
    from adapters.distribution.oauth_store import get_default_store  # noqa: PLC0415

    if oauth_store is None:
        oauth_store = get_default_store()
    sleep = _sleep_fn if _sleep_fn is not None else time.sleep
    caption_vars = caption_vars or {}

    results: list[DistributeResult] = []

    # If a raw v3 caption output is supplied, parse it and gate on its self-reported FLAGS
    # (compliance/completeness) BEFORE any platform work. BLOCKED (e.g. required-but-missing
    # license) short-circuits the whole fan-out; the parsed caption then replaces the template.
    fixed_caption: str | None = None
    if raw_caption_output is not None:
        from core.caption_output import BLOCKED, gate_caption, parse_caption_output  # noqa: PLC0415
        parts = parse_caption_output(raw_caption_output)
        decision, reason = gate_caption(parts, require_license=require_license)
        if decision == BLOCKED:
            logger.warning("distribute_job: caption flag-gate BLOCKED: %s", reason)
            return [DistributeResult(platform=p, status="FAILED", error=f"blocked: {reason}")
                    for p in destinations]
        fixed_caption = parts.caption  # REVIEW still publishes; caller can inspect flags upstream

    for platform in destinations:
        # Resolve transcode spec (pure — always succeeds for known platforms)
        try:
            spec = transcode_spec(platform)
        except KeyError as exc:
            logger.error("distribute_job: unknown platform %r: %s", platform, exc)
            results.append(DistributeResult(platform=platform, status="FAILED", error=str(exc)))
            continue

        # Caption source: a parsed v3 output (already flag-gated) wins; else render the template.
        caption = fixed_caption if fixed_caption is not None else render_caption(caption_template, caption_vars)

        # Content-safety gate (Track E) — the caption is a generated artifact and MUST pass
        # BEFORE it reaches any platform. Run per-platform because interpolation above can
        # introduce unsafe values. Fail-closed: block on non-pass.
        from adapters.safety import run_gate  # noqa: PLC0415
        gate_result = run_gate(caption, "social")
        if not gate_result.passed:
            logger.warning("distribute_job: caption BLOCKED for %r: %s", platform, gate_result.reason)
            results.append(DistributeResult(
                platform=platform,
                status="FAILED",
                error=f"blocked: {gate_result.reason}",
                spec={"aspect_ratio": spec.aspect_ratio, "max_length_seconds": spec.max_length_seconds},
            ))
            continue

        # Fetch OAuth token
        try:
            token = oauth_store.access_token(platform, account_id)
        except KeyError:
            # Attempt refresh before giving up
            try:
                token = oauth_store.refresh(platform, account_id)
            except KeyError as exc:
                logger.error("distribute_job: no token for platform=%r account=%r: %s", platform, account_id, exc)
                results.append(DistributeResult(
                    platform=platform,
                    status="FAILED",
                    error=f"No OAuth token: {exc}",
                    spec={"aspect_ratio": spec.aspect_ratio, "max_length_seconds": spec.max_length_seconds},
                ))
                continue

        # Load adapter
        try:
            adapter = _load_adapter(platform)
        except ValueError as exc:
            logger.error("distribute_job: adapter load failed for %r: %s", platform, exc)
            results.append(DistributeResult(platform=platform, status="FAILED", error=str(exc)))
            continue

        # Drive state machine with retry
        status: Status = "PENDING"
        attempt = 0
        post_id: str | None = None
        url: str | None = None
        last_error: str | None = None

        while True:
            status = next_status(status if status == "PENDING" else "PENDING", "start")
            # Note: after a FAILED attempt we reset to PENDING to allow re-entry via next_status.
            # The state machine only tracks per-attempt state; overall retry logic is here.
            try:
                response = adapter.publish(video_url, caption, token)
                post_id = response.get("post_id")
                url = response.get("url")
                status = next_status("IN_FLIGHT", "success")
                logger.info(
                    "distribute_job: posted platform=%r attempt=%d post_id=%r", platform, attempt, post_id
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                status = next_status("IN_FLIGHT", "fail")
                logger.warning(
                    "distribute_job: publish failed platform=%r attempt=%d: %s", platform, attempt, exc
                )
                if should_retry(attempt, max_attempts):
                    wait = backoff_seconds(attempt)
                    logger.info("distribute_job: retrying in %.0fs (attempt %d/%d)", wait, attempt + 1, max_attempts)
                    sleep(wait)
                    attempt += 1
                    status = "PENDING"  # reset for next loop iteration
                else:
                    break

        results.append(DistributeResult(
            platform=platform,
            status=status,
            post_id=post_id,
            url=url,
            attempts=attempt + 1,
            error=last_error if status == "FAILED" else None,
            spec={"aspect_ratio": spec.aspect_ratio, "max_length_seconds": spec.max_length_seconds},
        ))

    return results


def run() -> dict:
    """Smoke-test entry point using mock adapters and an in-memory token store.

    SCAFFOLD: mocked end-to-end — real posting blocked on app-review/creds.

    Returns:
        Summary dict: ``{"total": int, "published": int, "failed": int}``.
    """
    from adapters.distribution.oauth_store import OAuthStore  # noqa: PLC0415

    store = OAuthStore()
    platforms = ["youtube_shorts", "facebook", "linkedin", "x", "pinterest"]
    for p in platforms:
        store.put(p, "default", access_token=f"mock_token_{p}", ttl=3600)

    results = distribute(
        video_url="https://storage.googleapis.com/perkins-clips/sample-clip.mp4",
        caption_template="Expert {product} in {location} by {crew}. Call us today! #roofing #florida",
        caption_vars={"location": "Palm Beach County", "product": "metal roofing", "crew": "Team Perkins"},
        destinations=platforms,
        oauth_store=store,
    )

    published = sum(1 for r in results if r.status == "PUBLISHED")
    failed = sum(1 for r in results if r.status == "FAILED")
    for r in results:
        logger.info("  %s → %s (post_id=%s)", r.platform, r.status, r.post_id)

    return {"total": len(results), "published": published, "failed": failed}


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
    sys.exit(0)
