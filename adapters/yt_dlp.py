"""yt-dlp adapter (I/O, coverage-omitted) — enumerate a channel's full upload set
(videos + shorts + streams tabs, de-duped) and pull audio for local Whisper STT.

Also provides pull_video() for downloading the best available MP4 for render jobs."""
import json
import os
import subprocess
import sys

_TABS = ("videos", "shorts", "streams")

# Present as a current desktop Chrome so YouTube serves the full format set (and is less likely to
# gate on "confirm you're not a bot"). Override with YTDLP_USER_AGENT if it ever needs bumping.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Invoke yt-dlp as the venv module so we get the up-to-date version (with --remote-components /
# EJS n-challenge support), not whatever stale `yt-dlp` sits on PATH.
_YTDLP = [sys.executable, "-m", "yt_dlp"]


def _flat_list(url, limit=None):
    cmd = [*_YTDLP, "--flat-playlist", "-J", "--ignore-errors"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(url)
    out = subprocess.run(cmd, check=True, capture_output=True, timeout=600).stdout
    if not out.strip():
        return []
    return json.loads(out).get("entries", []) or []


def list_channel(channel_id, limit=None):
    """Enumerate videos + shorts + streams tabs de-duped by id. Shorts-tab entries are tagged
    with a /shorts/ url so core.enumerate.is_short classifies them. Returns (entries, failed_tabs)
    so the caller can detect a partial enumeration instead of silently under-counting."""
    base = f"https://www.youtube.com/channel/{channel_id}"
    seen, merged, failed = set(), [], []
    for tab in _TABS:
        try:
            entries = _flat_list(f"{base}/{tab}", limit=limit)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            print(f"[warn] channel tab '{tab}' failed: {str(e)[:120]}")
            failed.append(tab)
            entries = []
        for e in entries:
            vid = e.get("id")
            if vid and vid not in seen:
                seen.add(vid)
                if tab == "shorts":
                    e["url"] = f"https://www.youtube.com/shorts/{vid}"
                merged.append(e)
    return merged, failed


def pull_video(video_id: str, dst: str) -> str:
    """Download the best available MP4 for *video_id* into directory *dst*.

    Uses yt-dlp format selection ``bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best``
    to prefer native MP4 containers, avoiding a post-merge transcode where possible.

    Args:
        video_id: YouTube video ID (e.g. ``"dQw4w9WgXcQ"``).
        dst:      Directory path where the downloaded file will be placed.

    Returns:
        Absolute path to the downloaded MP4 file.

    Raises:
        subprocess.CalledProcessError: if yt-dlp exits non-zero.
        subprocess.TimeoutExpired: if the download takes longer than 900s.
        FileNotFoundError: if no MP4 file is found in *dst* after the download.
    """
    os.makedirs(dst, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = os.path.join(dst, f"{video_id}.%(ext)s")
    cmd = [
        *_YTDLP,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--no-playlist",
        # YouTube's JS "n-challenge": without solving it, YouTube returns storyboard images only
        # ("Only images are available"). yt-dlp solves it with a JS runtime (deno, on PATH) + the
        # EJS challenge-solver script. This is the actual fix — not an IP throttle.
        "--remote-components", "ejs:github",
        # Auth + pacing for bulk archive (browser cookies clear the bot-check; sleep avoids re-flag).
        "--retries", "3", "--sleep-interval", os.getenv("YTDLP_SLEEP", "0"),
        # Present as a modern Chrome so YouTube serves the full (video+audio) format set.
        "--user-agent", os.getenv("YTDLP_USER_AGENT", _CHROME_UA),
        url,
    ]
    cookies_browser = os.getenv("COOKIES_FROM_BROWSER")
    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]
    # yt-dlp needs ffmpeg to merge separate video+audio streams into one MP4. Point it at the
    # binary from FFMPEG_BIN (or the bundled imageio-ffmpeg) so hosts without a system ffmpeg
    # (this box, minimal Cloud Run images) still produce a merged file instead of failing.
    ffmpeg_bin = os.getenv("FFMPEG_BIN")
    if not ffmpeg_bin:
        try:
            import imageio_ffmpeg  # noqa: PLC0415
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 — fall back to a system ffmpeg on PATH
            ffmpeg_bin = None
    if ffmpeg_bin:
        cmd += ["--ffmpeg-location", ffmpeg_bin]
    subprocess.run(cmd, check=True, capture_output=True, timeout=900)

    # Locate the downloaded file (ext may vary on fallback formats)
    for fname in os.listdir(dst):
        if fname.startswith(video_id) and fname.endswith(".mp4"):
            return os.path.join(dst, fname)

    raise FileNotFoundError(
        f"pull_video: no MP4 found in {dst!r} after downloading {video_id!r}"
    )
