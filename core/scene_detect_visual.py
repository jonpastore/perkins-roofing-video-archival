"""Visual scene detection via ffmpeg's scene-change filter.

Complements core.scene_detect (speech-gap boundaries from the transcript). This runs
ffmpeg's ``select='gt(scene,THR)'`` over a video range and parses the printed frame
metadata into scene-change timestamps — for camera/B-roll cuts a talking-head gap
detector can't see. The runner needs a local ffmpeg and a readable source (path or
signed URL); callers must handle its absence gracefully.
"""
from __future__ import annotations

import re
import subprocess

_PTS = re.compile(r"pts_time:([\d.]+)")
_SCD = re.compile(r"lavfi\.scd\.time=([\d.]+)")


def parse_scene_timestamps(ffmpeg_output: str, min_gap: float = 1.0) -> list[float]:
    """Parse scene-change timestamps from ffmpeg metadata output.

    Accepts both ``pts_time:<float>`` (select+metadata) and ``lavfi.scd.time=<float>``
    (scdet) forms. Returns a sorted list, collapsing detections within *min_gap* seconds.
    """
    if not ffmpeg_output:
        return []
    hits: list[float] = []
    for pat in (_PTS, _SCD):
        for m in pat.finditer(ffmpeg_output):
            try:
                hits.append(float(m.group(1)))
            except ValueError:
                continue
    kept: list[float] = []
    for ts in sorted(set(hits)):
        if not kept or ts - kept[-1] >= min_gap:
            kept.append(ts)
    return kept


def build_scene_detect_cmd(
    src: str, threshold: float = 0.4, start: float | None = None, end: float | None = None,
) -> list[str]:
    """ffmpeg arg list that prints scene-change metadata (no output file). *src* may be a
    path or a signed URL; *start*/*end* trim the analysed range (fast -ss seek before -i)."""
    cmd = ["ffmpeg"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-i", src, "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-", "-an", "-f", "null", "-"]
    return cmd


def detect_scenes(
    src: str, threshold: float = 0.4, start: float | None = None,
    end: float | None = None, timeout: float = 60.0,
) -> list[float]:
    """Run ffmpeg scene detection over *src* and return scene-change timestamps.

    Timestamps are relative to *start* (ffmpeg resets the clock after -ss). Raises on a
    missing ffmpeg or a non-zero/timed-out run — callers fall back to speech-gap detection.
    """
    cmd = build_scene_detect_cmd(src, threshold=threshold, start=start, end=end)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return parse_scene_timestamps(proc.stderr + proc.stdout)
