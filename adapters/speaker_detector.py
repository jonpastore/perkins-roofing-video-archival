"""YuNet face-centroid detector (I/O — coverage-omitted).

Implements the ``core.speaker_track.FaceDetector`` protocol with OpenCV's YuNet
ONNX face detector (~230 KB model, committed at adapters/models/, CPU-only —
no runtime downloads, no GPU). Frame extraction uses ``cv2.VideoCapture`` seeks,
so there are no subprocess calls here at all.

Selection policy (which face to follow, when to refuse) is NOT here — it is the
pure ``core.speaker_track.pick_centroid``, tested at 100%. This module only
decodes frames and runs the detector.

Behavioral validation 2026-07-17: run against real channel frames (YouTube
thumbnails of Tim's videos) — single-speaker frames detect 1 face at 0.91-0.94
confidence with correct centroids; a roof-only frame returns no face (→ centre-
crop fallback), matching the design.
"""
from __future__ import annotations

import logging
import os

from core.speaker_track import pick_centroid

log = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx"
)


def probe_video(video_path: str) -> tuple[int, int, float]:
    """Return (width, height, duration_seconds) for *video_path* via cv2.

    Raises:
        RuntimeError: if the file cannot be opened as video.
    """
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"probe_video: cannot open {video_path!r}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        duration = (frames / fps) if fps > 0 else 0.0
        return w, h, duration
    finally:
        cap.release()


class YuNetFaceDetector:
    """Face-centroid detector backed by OpenCV FaceDetectorYN (YuNet).

    Satisfies ``core.speaker_track.FaceDetector``. One frame is sampled at each
    segment's midpoint; face selection is delegated to ``pick_centroid``.
    """

    def __init__(self, model_path: str | None = None):
        import cv2  # noqa: PLC0415

        self._cv2 = cv2
        path = model_path or _MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"YuNet model not found: {path!r}")
        # Input size is set per-frame in detect_centroids; (320, 320) is a placeholder.
        self._det = cv2.FaceDetectorYN.create(path, "", (320, 320))

    def detect_centroids(
        self,
        video_path: str,
        segments: list[dict],
    ) -> list[float | None]:
        """Sample each segment's midpoint frame → normalised x-centroid or None.

        Any per-segment failure (seek miss, decode error) yields None for that
        segment — the caller's smoothing gap-fills and the crop falls back
        toward centre, so a bad frame can never crash a render.
        """
        cv2 = self._cv2
        cap = cv2.VideoCapture(video_path)
        try:
            if not cap.isOpened():
                log.warning("speaker_detector: cannot open %r — all centroids None", video_path)
                return [None for _ in segments]

            out: list[float | None] = []
            for seg in segments:
                mid_ms = 1000.0 * (float(seg["start"]) + float(seg["end"])) / 2.0
                try:
                    cap.set(cv2.CAP_PROP_POS_MSEC, mid_ms)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        out.append(None)
                        continue
                    h, w = frame.shape[:2]
                    self._det.setInputSize((w, h))
                    _, faces = self._det.detect(frame)
                    tuples = [
                        (float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14]))
                        for f in (faces if faces is not None else [])
                    ]
                    out.append(pick_centroid(tuples, w))
                except Exception as exc:  # noqa: BLE001 — one bad frame must not kill the render
                    log.warning("speaker_detector: segment @%.1fms failed: %s", mid_ms, exc)
                    out.append(None)
            return out
        finally:
            cap.release()
