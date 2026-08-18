"""YouTube videos.insert (Shorts) — metadata + resumable upload, no live I/O in tests."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

UPLOAD_INIT = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
_UA = "perkins-platform/1.0 (+https://perkinsroofing.net)"


def short_metadata(caption: str) -> dict:
    title = (caption or "Perkins Roofing").strip().split("\n", 1)[0][:100]
    desc = caption if "#Shorts" in (caption or "") else f"{caption or ''}\n#Shorts".strip()
    return {
        "snippet": {"title": title, "description": desc},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }


def upload_short(
    *,
    video_bytes: bytes,
    caption: str,
    access_token: str,
    urlopen=None,
) -> dict:
    if not access_token:
        raise RuntimeError("YouTube upload requires an OAuth access token")
    if not video_bytes:
        raise RuntimeError("YouTube upload requires video bytes")
    opener = urlopen or urllib.request.urlopen
    meta = json.dumps(short_metadata(caption)).encode()
    init = urllib.request.Request(
        UPLOAD_INIT,
        data=meta,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes)),
            "User-Agent": _UA,
        },
    )
    try:
        with opener(init, timeout=30) as resp:
            session = resp.headers.get("Location") or ""
        if not session:
            raise RuntimeError("YouTube upload session missing Location")
        put = urllib.request.Request(
            session,
            data=video_bytes,
            method="PUT",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "User-Agent": _UA,
            },
        )
        with opener(put, timeout=300) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"YouTube videos.insert HTTP {exc.code}") from exc
    vid = body.get("id") or ""
    if not vid:
        raise RuntimeError("YouTube videos.insert returned no video id")
    return {
        "post_id": vid,
        "platform": "youtube_shorts",
        "url": f"https://www.youtube.com/shorts/{vid}",
    }
