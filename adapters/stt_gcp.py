"""Google Cloud Speech-to-Text v2 adapter (I/O, coverage-omitted).

Fully-cloud replacement for the cerberus Whisper node — nothing runs on a local GPU.
Flow: yt-dlp bestaudio -> GCS temp object -> Speech-to-Text v2 BatchRecognize (auto-decoding,
word-level timestamps + confidence) -> the normalized transcript schema.

Same contract as adapters.stt_whisper.transcribe(video_id):
    {"source": "gcp_stt",
     "segments": [{"text", "start", "end"}],
     "words":    [{"word", "start", "confidence"}],
     "speech_ratio": float}
"""
import os
import tempfile

from adapters import storage, yt_dlp


def _project():
    p = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not p:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for GCP STT")
    return p


def _bucket():
    # Reuse the private media bucket ({project}-media) unless STT_BUCKET overrides it.
    return os.getenv("STT_BUCKET") or f"{_project()}-media"


def _secs(d):
    """A Speech v2 Duration field (proto-plus exposes it as datetime.timedelta) -> float seconds."""
    if d is None:
        return 0.0
    if hasattr(d, "total_seconds"):
        return d.total_seconds()
    return getattr(d, "seconds", 0) + getattr(d, "nanos", 0) / 1e9


def _speech_ratio(segments):
    """Fraction of the spoken window actually covered by speech (merged, overlap-safe).

    Music-only/near-silent clips yield ~0 (no words) so core.vad.should_transcribe skips them.
    The measure is taken over the spoken window rather than true audio duration; that can only
    over-estimate, which is safe — it never wrongly drops a talky video below the VAD floor."""
    intervals = sorted((s["start"], s["end"]) for s in segments if s["end"] > s["start"])
    if not intervals:
        return 0.0
    merged = 0.0
    cs, ce = intervals[0]
    for a, b in intervals[1:]:
        if a <= ce:
            ce = max(ce, b)
        else:
            merged += ce - cs
            cs, ce = a, b
    merged += ce - cs
    span = intervals[-1][1] - intervals[0][0]
    return merged / span if span > 0 else 0.0


def _normalize(transcript):
    segments, words = [], []
    for res in transcript.results:
        if not res.alternatives:
            continue
        alt = res.alternatives[0]
        text = (alt.transcript or "").strip()
        if not text:
            continue
        w = [
            {"word": x.word, "start": _secs(x.start_offset),
             "confidence": (x.confidence if x.confidence else None)}
            for x in alt.words
        ]
        start = w[0]["start"] if w else 0.0
        segments.append({"text": text, "start": start, "end": _secs(res.result_end_offset)})
        words.extend(w)
    return {"source": "gcp_stt", "segments": segments, "words": words,
            "speech_ratio": _speech_ratio(segments)}


def transcribe(video_id, language_codes=("en-US",), model="long"):
    """Transcribe a YouTube video id via GCP Speech-to-Text v2. Returns the normalized schema."""
    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import cloud_speech

    project = _project()
    region = os.getenv("GCP_REGION", "us-central1")
    bucket = _bucket()
    key = f"stt-tmp/{video_id}.m4a"

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = yt_dlp.pull_audio(video_id, tmp)
        gs_uri = storage.upload_file(audio_path, bucket, key, content_type="audio/mp4")

    try:
        client = SpeechClient(
            client_options=ClientOptions(api_endpoint=f"{region}-speech.googleapis.com")
        )
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=list(language_codes),
            model=model,
            features=cloud_speech.RecognitionFeatures(
                enable_word_time_offsets=True,
                enable_word_confidence=True,
                enable_automatic_punctuation=True,
            ),
        )
        request = cloud_speech.BatchRecognizeRequest(
            recognizer=f"projects/{project}/locations/{region}/recognizers/_",
            config=config,
            files=[cloud_speech.BatchRecognizeFileMetadata(uri=gs_uri)],
            recognition_output_config=cloud_speech.RecognitionOutputConfig(
                inline_response_config=cloud_speech.InlineOutputConfig(),
            ),
        )
        op = client.batch_recognize(request=request)
        response = op.result(timeout=float(os.getenv("STT_TIMEOUT", "1800")))
        file_result = response.results[gs_uri]
        # Batch reports per-file errors (e.g. audio too long for an inline response) here rather
        # than raising — surface them so ingest records the stage as retryable, never silent-empty.
        if file_result.error and file_result.error.code:
            raise RuntimeError(f"gcp stt error: {file_result.error.message}")
        return _normalize(file_result.transcript)
    finally:
        try:
            storage.delete_object(bucket, key)
        except Exception:  # noqa: BLE001 — temp-object cleanup is best-effort
            pass
