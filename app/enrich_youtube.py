"""Enrich the static demo data with authoritative YouTube Data API fields: exact publish
timestamp (date+time, shown in ET) and fresh view/like/comment counts. Reads YOUTUBE_API_KEY
from env (piped from 1Password — never hardcoded). Updates mockup/library.json + channel.json.
4 API calls for 161 videos (videos.list, 50 ids/call). Re-run anytime to refresh."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(__file__)
LIB = os.path.join(HERE, "..", "mockup", "library.json")
CHAN = os.path.join(HERE, "..", "mockup", "channel.json")
CHANNEL_ID = "UChJZpBYXOuR0j1EHJugv5hg"
ET = ZoneInfo("America/New_York")

def api(path, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = f"https://www.googleapis.com/youtube/v3{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)

def fmt_et(iso):  # "2026-06-03T14:12:05Z" -> ("20260603", "Jun 3, 2026 · 2:12 PM ET")
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    return dt.strftime("%Y%m%d"), dt.strftime("%-b %-d, %Y · %-I:%M %p ET")

def main():
    lib = json.load(open(LIB))
    by_id = {v["id"]: v for v in lib}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        d = api("/videos", part="snippet,statistics", id=",".join(batch))
        for it in d.get("items", []):
            v = by_id[it["id"]]; sn = it["snippet"]; st = it["statistics"]
            v["upload_date"], v["posted"] = fmt_et(sn["publishedAt"])
            v["published_at"] = sn["publishedAt"]
            v["views"] = int(st.get("viewCount", 0))
            v["likes"] = int(st.get("likeCount", 0)) if "likeCount" in st else v.get("likes")
            v["comments"] = int(st.get("commentCount", 0)) if "commentCount" in st else v.get("comments")
        print(f"enriched {min(i+50,len(ids))}/{len(ids)}")
    lib.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    json.dump(lib, open(LIB, "w"), indent=2)

    ch = json.load(open(CHAN))
    cd = api("/channels", part="statistics", id=CHANNEL_ID)["items"][0]["statistics"]
    ch["subscribers"] = int(cd["subscriberCount"])
    ch["total_videos"] = int(cd["videoCount"])
    ch["total_views"] = int(cd["viewCount"])
    ch["shorts"] = ch["total_videos"] - ch["long_form"]
    ch["last_sync"] = datetime.now(ET).strftime("%-b %-d, %Y · %-I:%M %p ET")
    json.dump(ch, open(CHAN, "w"), indent=2)
    print("updated channel.json:", {k: ch[k] for k in ("subscribers", "total_videos", "total_views")})

if __name__ == "__main__":
    main()
