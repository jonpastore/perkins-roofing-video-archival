"""Avatar generation job — I/O orchestration (coverage-omitted).

End-to-end pipeline (mocked end to end — real render blocked on API keys):
  1. Retrieve grounding snippets from the 841-video corpus (app.retrieval.search)
  2. Build LLM prompt           (core.avatar_script.build_script_prompt)
  3. Call LLM for script draft  (adapters.llm.get_default)
  4. Parse script               (core.avatar_script.parse_script)
  5. Content-safety gate        (adapters.safety.run_gate) — BLOCK on fail
  6. ElevenLabs TTS             (adapters.elevenlabs.ElevenLabsVoice.tts)
  7. HeyGen avatar render       (adapters.heygen.HeyGenAvatar.render)

The gate in step 5 is fail-closed: if the script does not pass the
content-safety gate the job raises RuntimeError and does NOT proceed to
render.  Nothing publishes without PASS (E1 requirement).

# SCAFFOLD: mocked end to end — real render blocked on API keys.
# Mark unverified-until-keys: ElevenLabs TTS + HeyGen render return mock
# responses; the rest of the pipeline (retrieval, LLM, safety gate) is
# live against real infrastructure once env vars are configured.

Environment variables (all adapters read from env — never hardcoded):
  GOOGLE_CLOUD_PROJECT  — required for Vertex LLM + retrieval
  GCP_REGION            — optional, defaults to us-central1
  ELEVENLABS_API_KEY    — required for real TTS (scaffold: mocked)
  ELEVENLABS_VOICE_ID   — pre-existing voice ID (skip clone when provided)
  HEYGEN_API_KEY        — required for real render (scaffold: mocked)
  HEYGEN_AVATAR_ID      — Tim's photoreal avatar ID
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _run_for_tenant(
    db,
    tenant_id: int,
    topic: str,
    *,
    retrieval_k: int = 8,
    voice_id: str | None = None,
    avatar_id: str | None = None,
    llm=None,
) -> dict:
    """Per-tenant avatar generation body. Called by for_each_tenant via run().

    Args:
        db:          Session with tenant_id stamped (for_each_tenant contract).
        tenant_id:   Active tenant being processed.
        topic:       The subject for the avatar video.
        retrieval_k: Number of corpus chunks to retrieve for grounding.
        voice_id:    Optional pre-existing ElevenLabs voice ID.
        avatar_id:   Optional HeyGen avatar ID.
        llm:         Optional LLM instance; falls back to adapters.llm.get_default().

    Returns:
        Dict with topic, title, script_text, est_seconds, gate_passed, job_id, url.

    Raises:
        RuntimeError: if the content-safety gate blocks the script.
        RuntimeError: if the LLM returns an unrecoverable script.
    """
    import os  # noqa: PLC0415

    from adapters.elevenlabs import ElevenLabsVoice  # noqa: PLC0415
    from adapters.heygen import HeyGenAvatar  # noqa: PLC0415
    from adapters.safety import run_gate  # noqa: PLC0415
    from core.avatar_script import (  # noqa: PLC0415
        build_script_prompt,
        parse_script,
        script_gate_input,
    )

    # ── 1. Retrieval — ground the script in Tim's corpus ─────────────────────
    grounding_snippets: list[dict] = []
    try:
        from app.retrieval import search  # noqa: PLC0415
        results = search(topic, k=retrieval_k)
        grounding_snippets = [{"text": r["text"], "link": r.get("link", "")} for r in results]
        logger.info("avatar_job: retrieved %d snippets for topic=%r", len(grounding_snippets), topic)
    except Exception as exc:  # noqa: BLE001
        logger.warning("avatar_job: retrieval failed for topic=%r, continuing: %s", topic, exc)

    # ── 2. Build LLM prompt ───────────────────────────────────────────────────
    prompt = build_script_prompt(topic, grounding_snippets)

    # ── 3. Call LLM ──────────────────────────────────────────────────────────
    if llm is None:
        from adapters.llm import get_default  # noqa: PLC0415
        llm = get_default()

    raw = llm.chat(prompt, want_json=True)

    # ── 4. Parse script ───────────────────────────────────────────────────────
    script = parse_script(raw)
    if not script["parse_ok"]:
        raise RuntimeError(
            f"avatar_job: LLM returned an unrecoverable script for topic={topic!r} — "
            f"script_text={script['script_text'][:80]!r}"
        )
    logger.info(
        "avatar_job: script parsed ok title=%r est_seconds=%d",
        script["title"],
        script["est_seconds"],
    )

    # ── 5. Content-safety gate — BLOCK on fail ────────────────────────────────
    gate_text = script_gate_input(script)
    gate_result = run_gate(gate_text, "avatar_script")
    if not gate_result.passed:
        raise RuntimeError(
            f"avatar_job: content-safety gate BLOCKED topic={topic!r} — "
            f"layer={gate_result.layer} reason={gate_result.reason}"
        )
    logger.info("avatar_job: safety gate PASSED layer=%s score=%s", gate_result.layer, gate_result.score)

    # ── 6. ElevenLabs TTS ─────────────────────────────────────────────────────
    # SCAFFOLD: mocked — real API wiring blocked on keys.
    resolved_voice_id = (
        voice_id
        or os.environ.get("ELEVENLABS_VOICE_ID", "")
        or "mock-voice-id-tim-perkins"
    )
    el = ElevenLabsVoice()
    audio_bytes = el.tts(script["script_text"], resolved_voice_id)
    logger.info(
        "avatar_job: TTS complete voice_id=%r audio_bytes=%d",
        resolved_voice_id,
        len(audio_bytes),
    )

    # ── 7. HeyGen avatar render ───────────────────────────────────────────────
    # SCAFFOLD: mocked — real API wiring blocked on keys.
    hg = HeyGenAvatar()
    render_result = hg.render(
        script["script_text"],
        voice_audio=audio_bytes,
        avatar_id=avatar_id,
    )
    logger.info(
        "avatar_job: render submitted job_id=%r url=%r",
        render_result.get("job_id"),
        render_result.get("url"),
    )

    return {
        "topic": topic,
        "title": script["title"],
        "script_text": script["script_text"],
        "est_seconds": script["est_seconds"],
        "gate_passed": gate_result.passed,
        "job_id": render_result.get("job_id", ""),
        "url": render_result.get("url", ""),
    }


def run(
    topic: str,
    *,
    retrieval_k: int = 8,
    voice_id: str | None = None,
    avatar_id: str | None = None,
    llm=None,
) -> dict:
    """Iterate active tenants and generate a Tim avatar video for *topic* for each.

    # SCAFFOLD: mocked end to end — real render blocked on API keys.

    Args:
        topic:        The subject for the avatar video (e.g. "roof-age insurance
                      nonrenewal in Florida").
        retrieval_k:  Number of corpus chunks to retrieve for grounding.
        voice_id:     Optional pre-existing ElevenLabs voice ID.  When omitted,
                      falls back to ELEVENLABS_VOICE_ID env var, then mock.
        avatar_id:    Optional HeyGen avatar ID.  When omitted, falls back to
                      HEYGEN_AVATAR_ID env var, then mock default.
        llm:          Optional LLM instance (VertexLLM or compatible).
                      Falls back to adapters.llm.get_default().

    Returns:
        Result dict from the last tenant processed (single-tenant reality);
        keys: topic, title, script_text, est_seconds, gate_passed, job_id, url.

    Raises:
        RuntimeError: if the content-safety gate blocks the script.
        RuntimeError: if the LLM returns an unrecoverable script.
    """
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    results: list[dict] = []

    def _fn(db, tenant_id: int) -> None:
        results.append(_run_for_tenant(db, tenant_id, topic,
                                       retrieval_k=retrieval_k,
                                       voice_id=voice_id,
                                       avatar_id=avatar_id,
                                       llm=llm))

    for_each_tenant(SessionLocal, _fn)
    return results[-1] if results else {}
