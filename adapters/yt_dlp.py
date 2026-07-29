"""yt-dlp adapter (I/O, coverage-omitted) — enumerate a channel's full upload set
(videos + shorts + streams tabs, de-duped) and pull audio for local Whisper STT.

Also provides pull_video() for downloading the best available MP4 for render jobs."""
import json
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger(__name__)

# The one error that rotating egress can fix. Anything else (private video, removed, 404) will
# fail identically on every exit, so retrying across tunnels would just waste the timeout.
_BOT_BLOCK_RE = re.compile(r"Sign in to confirm you.{1,3}re not a bot", re.IGNORECASE)

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
        RuntimeError: if yt-dlp exits non-zero — the message carries yt-dlp's stderr.
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
    # Cookies are OPTIONAL and are NOT the fix for the bot-block. Measured 2026-07-29: with the
    # channel-owner jar verified loaded ("using cookie jar ... 6791 bytes") Cloud Run still got
    # 15/15 "Sign in to confirm you're not a bot". The block is on the egress IP, not the
    # identity — see core/wireproxy for the actual fix. Every successful download in testing was
    # UNAUTHENTICATED, so this can be left unset; it is kept only as an escape hatch.
    #
    # ⚠️ If it IS set: a YouTube cookie jar is a full Google session. SID/SAPISID are scoped to
    # .google.com, so it also authenticates Gmail/Drive/Cloud Console. Channel-owning account
    # only, never a personal one.
    #
    # The branch is logged because a bot-block is otherwise ambiguous: "no cookies sent" and
    # "cookies sent and rejected" produce an IDENTICAL yt-dlp error, and the container runs as
    # non-root (appuser), so an unreadable mount would silently skip the flag and look the same.
    cookies_file = os.getenv("YTDLP_COOKIES_FILE")
    if cookies_file:
        try:
            size = os.path.getsize(cookies_file)
            with open(cookies_file, "rb") as fh:  # readability, not just existence
                fh.read(1)
        except OSError as exc:
            log.warning("yt-dlp: YTDLP_COOKIES_FILE=%s is set but UNREADABLE (%s) — "
                        "proceeding WITHOUT cookies", cookies_file, exc)
        else:
            if size > 0:
                cmd += ["--cookies", cookies_file]
                log.info("yt-dlp: using cookie jar %s (%d bytes)", cookies_file, size)
            else:
                log.warning("yt-dlp: cookie jar %s is EMPTY — proceeding without cookies",
                            cookies_file)

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
    _run_ytdlp(cmd, video_id)

    # Locate the downloaded file (ext may vary on fallback formats)
    for fname in os.listdir(dst):
        if fname.startswith(video_id) and fname.endswith(".mp4"):
            return os.path.join(dst, fname)

    raise FileNotFoundError(
        f"pull_video: no MP4 found in {dst!r} after downloading {video_id!r}"
    )


def _ytdlp_error(proc, video_id: str) -> RuntimeError:
    """Build the exception for a failed yt-dlp run, carrying the real reason.

    capture_output swallows stderr and CalledProcessError's str() prints only the command, so a
    failure used to surface as "returned non-zero exit status 1" with no cause — that cost a
    full diagnosis round on 2026-07-28. RuntimeError, because nothing catches
    CalledProcessError from here and callers log "%s".
    """
    err = (proc.stderr or b"").decode("utf-8", "replace").strip()
    # Prefer the ERROR lines. Taking the tail alone reported a trailing WARNING ("No title found
    # in player responses") while the real cause sat earlier in the stream and was cut off.
    fatal = [ln for ln in err.splitlines() if ln.lstrip().startswith("ERROR")]
    detail = " | ".join(fatal) if fatal else err
    return RuntimeError(
        f"yt-dlp failed for {video_id} (exit {proc.returncode}): "
        f"{detail[-1500:] or '(no stderr)'}"
    )


def _run_ytdlp(cmd: list[str], video_id: str) -> None:
    """Run yt-dlp, rotating egress across WireGuard configs on a bot-block.

    With no configs mounted this is a single direct attempt — unchanged behaviour for dev boxes,
    which are residential and need no tunnel.

    Only a bot-block triggers rotation. A private/removed video fails identically on every exit,
    so rotating for it would burn the job's timeout for nothing.
    """
    from core.wireproxy import Tunnel, load_configs  # noqa: PLC0415

    configs = load_configs()
    if not configs:
        proc = subprocess.run(cmd, capture_output=True, timeout=900)  # noqa: S603
        if proc.returncode != 0:
            raise _ytdlp_error(proc, video_id)
        return

    last: RuntimeError | None = None
    for i, config in enumerate(configs, 1):
        try:
            with Tunnel(config) as tunnel:
                log.info("yt-dlp: %s via egress %d/%d (%s)",
                         video_id, i, len(configs), tunnel.proxy_url)
                proc = subprocess.run(  # noqa: S603
                    [*cmd, "--proxy", tunnel.proxy_url], capture_output=True, timeout=900,
                )
                if proc.returncode == 0:
                    return
                last = _ytdlp_error(proc, video_id)
        except RuntimeError as exc:  # tunnel failed to start — try the next config
            log.warning("yt-dlp: egress %d/%d unusable: %s", i, len(configs), exc)
            last = exc
            continue

        if not _BOT_BLOCK_RE.search(str(last)):
            raise last  # not an egress problem; another exit will not help
        log.warning("yt-dlp: egress %d/%d bot-blocked for %s — rotating", i, len(configs), video_id)

    raise RuntimeError(
        f"yt-dlp: all {len(configs)} egress config(s) exhausted for {video_id}. "
        f"VPN ranges get blocked over time — refresh the wireguard-configs secret. "
        f"Last error: {last}"
    )
