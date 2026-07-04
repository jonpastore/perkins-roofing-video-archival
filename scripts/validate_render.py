"""Behavioral validation for the Wave-3 ffmpeg render pipeline.

Sets FFMPEG_BIN to the imageio-ffmpeg bundled binary BEFORE importing any
adapter, so the module-level _FFMPEG constant is captured correctly. Generates
synthetic test fixtures via lavfi, runs adapters.ffmpeg.fuse, then asserts the
output has the correct dimensions and a positive duration.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/validate_render.py
"""
from __future__ import annotations

import os
import subprocess
import tempfile

# ── 1. Set FFMPEG_BIN before any adapter import ───────────────────────────────
import imageio_ffmpeg

_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["FFMPEG_BIN"] = _FFMPEG_EXE

# ── 2. Now import adapters (they read FFMPEG_BIN at module level) ─────────────
from adapters.ffmpeg import fuse, probe  # noqa: E402


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _make_clip(ffmpeg: str, out: str, duration: float = 2.0) -> None:
    """Generate a synthetic clip (lavfi color + sine tone)."""
    _run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i",
        f"color=c=blue:size=1920x1080:rate=30:duration={duration}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=48000:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        out,
    ])


def _make_image(ffmpeg: str, color: str, out: str) -> None:
    """Generate a solid-color 1080×1920 PNG."""
    _run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i",
        f"color=c={color}:size=1080x1920:rate=1:duration=1",
        "-vframes", "1",
        out,
    ])


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clip_path = os.path.join(tmp, "clip.mp4")
        title_img = os.path.join(tmp, "title.png")
        closing_img = os.path.join(tmp, "closing.png")
        out_path = os.path.join(tmp, "reel.mp4")

        print(f"[validate] ffmpeg binary: {_FFMPEG_EXE}")

        print("[validate] generating 2s test clip via lavfi ...")
        _make_clip(_FFMPEG_EXE, clip_path, duration=2.0)

        print("[validate] generating title/closing PNGs ...")
        _make_image(_FFMPEG_EXE, "red", title_img)
        _make_image(_FFMPEG_EXE, "green", closing_img)

        print("[validate] running adapters.ffmpeg.fuse ...")
        fuse(clip_path, title_img, closing_img, out_path, title_secs=1.0, closing_secs=1.0)

        print("[validate] probing output ...")
        info = probe(out_path)
        print(
            f"[validate] probe result: "
            f"width={info['width']} height={info['height']} "
            f"duration={info['duration']:.2f}s"
        )

        assert info["width"] == 1080, f"Expected width=1080, got {info['width']}"
        assert info["height"] == 1920, f"Expected height=1920, got {info['height']}"
        assert info["duration"] > 0, f"Expected duration>0, got {info['duration']}"

        print("RENDER OK")


if __name__ == "__main__":
    main()
