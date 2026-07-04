"""Pure channel-enumeration mapping — flat yt-dlp playlist entries → Video-shaped rows.
Classifies Shorts (by URL or ≤60s duration) so the ingest job can VAD-skip near-silent ones."""


def is_short(duration, url=""):
    """A video is a Short if its URL is a /shorts/ link or it runs ≤ 60 seconds."""
    if url and "/shorts/" in url:
        return True
    return duration is not None and duration <= 60


def to_video_rows(entries):
    """Map yt-dlp --flat-playlist entries to dicts {id,title,duration,url,is_short}.
    Entries without an id are skipped; a missing url defaults to the youtu.be short link."""
    rows = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        url = e.get("url") or f"https://youtu.be/{vid}"
        rows.append({
            "id": vid,
            "title": e.get("title"),
            "duration": e.get("duration"),
            "url": url,
            "is_short": is_short(e.get("duration"), url),
        })
    return rows
