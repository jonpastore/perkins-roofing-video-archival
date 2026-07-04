"""Pure VAD gate — decide whether a clip has enough speech to be worth graph/embed work.
Near-silent Shorts (music-only) fall below the threshold and are skipped to bound cost/noise."""


def should_transcribe(speech_ratio, min_ratio=0.15):
    """True when the measured speech-to-duration ratio meets the minimum."""
    return speech_ratio >= min_ratio
