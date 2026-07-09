"""Google Cloud Speech-to-Text v2 adapter (I/O, coverage-omitted).

Fully-cloud transcription — nothing runs on a local GPU and nothing is downloaded from YouTube.
Every source video is already archived to GCS (Video.archive_uri, the {project}-media bucket).
Speech-to-Text v2 will not decode a muxed video MP4 ("Audio data does not appear to be in a
supported format"), so the audio track is demuxed to a small 16 kHz mono FLAC with ffmpeg and
that is transcribed. Word-level timestamps + confidence are returned.

Contract matches adapters.stt_whisper.transcribe:
    {"source": "gcp_stt",
     "segments": [{"text", "start", "end"}],
     "words":    [{"word", "start", "confidence"}],
     "speech_ratio": float}
"""
import os
import subprocess
import tempfile

from core import metering


def _ffmpeg_bin():
    b = os.getenv("FFMPEG_BIN")
    if b:
        return b
    try:
        import imageio_ffmpeg  # noqa: PLC0415
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — fall back to a system ffmpeg on PATH
        return "ffmpeg"


def _parse_gs(uri):
    if not uri.startswith("gs://"):
        raise RuntimeError(f"expected a gs:// URI, got {uri!r}")
    bucket, _, key = uri[5:].partition("/")
    if not bucket or not key:
        raise RuntimeError(f"malformed gs:// URI: {uri!r}")
    return bucket, key


def _project():
    p = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not p:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for GCP STT")
    return p


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


def _load_gcs_results(uri):
    """Download + parse a Speech-to-Text v2 batch GCS-output object into BatchRecognizeResults."""
    from google.cloud.speech_v2.types import cloud_speech

    from adapters import storage

    bucket, key = _parse_gs(uri)
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "out.json")
        storage.download_file(bucket, key, local)
        with open(local, encoding="utf-8") as f:
            payload = f.read()
    return cloud_speech.BatchRecognizeResults.from_json(payload, ignore_unknown_fields=True)


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
    # Emit STT duration to per-tenant metering (no-op outside a tenant context).
    # Audio duration = end of the last segment; convert seconds → minutes.
    if segments:
        duration_secs = segments[-1]["end"]
        if duration_secs > 0:
            metering.add("stt_minutes", duration_secs / 60.0)
    return {"source": "gcp_stt", "segments": segments, "words": words,
            "speech_ratio": _speech_ratio(segments)}


def transcribe(video_id, gcs_uri, language_codes=("en-US",), model="long"):
    """Transcribe the archived video at *gcs_uri* via GCP Speech-to-Text v2, returning the
    normalized schema. Demuxes the audio track to a 16 kHz mono FLAC (STT won't read the video
    container), uploads it to a temp GCS object, batch-recognizes it, then deletes the temp
    object. No YouTube download. Raises if *gcs_uri* is missing: archive the video first."""
    if not gcs_uri:
        raise RuntimeError(f"no archive_uri for {video_id}; run archive_job before STT")

    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import cloud_speech

    from adapters import storage

    project = _project()
    region = os.getenv("GCP_REGION", "us-central1")
    bucket, key = _parse_gs(gcs_uri)
    tmp_key = f"stt-tmp/{video_id}.flac"

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        flac = os.path.join(tmp, "audio.flac")
        storage.download_file(bucket, key, src)
        try:
            subprocess.run(
                [_ffmpeg_bin(), "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", flac],
                check=True, capture_output=True,
                timeout=int(os.getenv("STT_FFMPEG_TIMEOUT", "1800")),
            )
        except subprocess.CalledProcessError as e:
            # str(CalledProcessError) is just the command; the real reason (e.g. "Output file does
            # not contain any stream" = the archived MP4 has no audio track) is in stderr. Surface it.
            tail = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-2:]
            raise RuntimeError(f"ffmpeg audio-demux failed for {video_id}: {' | '.join(tail)}") from e
        audio_uri = storage.upload_file(flac, bucket, tmp_key, content_type="audio/flac")

    out_prefix = f"stt-out/{video_id}/"
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
            files=[cloud_speech.BatchRecognizeFileMetadata(uri=audio_uri)],
            # Write results to GCS, not inline: inline is capped and only for small single-file
            # results, so a long video (up to STT's 8h limit) would overflow it. This path is
            # length-agnostic and is the fallback for ANY caption-less video, short or long.
            recognition_output_config=cloud_speech.RecognitionOutputConfig(
                gcs_output_config=cloud_speech.GcsOutputConfig(uri=f"gs://{bucket}/{out_prefix}"),
            ),
        )
        op = client.batch_recognize(request=request)
        # A long batch (a 97-min video takes ~40 min) legitimately runs a while; poll generously
        # but stay under the ingest job's 2h timeout so the process records an error, not a kill.
        response = op.result(timeout=float(os.getenv("STT_TIMEOUT", "5400")))
        file_result = response.results[audio_uri]
        # Batch reports per-file errors here rather than raising — surface them so ingest records
        # the stage as retryable, never silent-empty.
        if file_result.error and file_result.error.code:
            raise RuntimeError(f"gcp stt error: {file_result.error.message}")
        out_bucket, out_key = _parse_gs(file_result.uri)
        results = _load_gcs_results(file_result.uri)
        try:
            storage.delete_object(out_bucket, out_key)
        except Exception:  # noqa: BLE001 — output cleanup is best-effort
            pass
        return _normalize(results)
    finally:
        try:
            storage.delete_object(bucket, tmp_key)
        except Exception:  # noqa: BLE001 — temp-object cleanup is best-effort
            pass
