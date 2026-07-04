"""yt-dlp adapter (I/O, coverage-omitted) — enumerate a channel's full upload set
(videos + shorts + streams tabs, de-duped) and pull audio for local Whisper STT."""
import json
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
