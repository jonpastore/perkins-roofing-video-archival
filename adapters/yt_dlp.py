"""yt-dlp adapter (I/O, coverage-omitted) — enumerate a channel's full upload set
(videos + shorts + streams tabs, de-duped) and pull audio for local Whisper STT."""
import glob
import json
import os
import subprocess

_TABS = ("videos", "shorts", "streams")


def _flat_list(url, limit=None):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--ignore-errors"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(url)
    out = subprocess.run(cmd, check=True, capture_output=True, timeout=600).stdout
    if not out.strip():
        return []
    return json.loads(out).get("entries", []) or []


def list_channel(channel_id, limit=None):
    """Enumerate videos + shorts + streams tabs de-duped by id. Shorts-tab entries are
    tagged with a /shorts/ url so core.enumerate.is_short classifies them correctly."""
    base = f"https://www.youtube.com/channel/{channel_id}"
    seen, merged = set(), []
    for tab in _TABS:
        try:
            entries = _flat_list(f"{base}/{tab}", limit=limit)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            # a tab may be absent (no streams), time out, or return junk — degrade to empty, keep others
            print(f"[warn] channel tab '{tab}' failed: {str(e)[:120]}")
            entries = []
        for e in entries:
            vid = e.get("id")
            if vid and vid not in seen:
                seen.add(vid)
                if tab == "shorts":
                    e["url"] = f"https://www.youtube.com/shorts/{vid}"
                merged.append(e)
    return merged


def pull_audio(video_id, dst_dir):
    """Download bestaudio as 16kHz mono wav; returns the file path (or None)."""
    out = os.path.join(dst_dir, f"{video_id}.%(ext)s")
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav",
         "--postprocessor-args", "-ar 16000 -ac 1",
         "-o", out, f"https://youtu.be/{video_id}"],
        check=True, capture_output=True, timeout=1800,
    )
    hits = glob.glob(os.path.join(dst_dir, f"{video_id}.wav"))
    return hits[0] if hits else None
