"""Freeze the indexed library into static JSON for the Cloudflare mock — Phase 1 surface:
video list + per-video Content-Graph topics with timecoded deep links. All real dev.db data."""
import json, os, sqlite3

DB = os.path.join(os.path.dirname(__file__), "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "mockup", "library.json")

def link(vid, start): return f"https://youtu.be/{vid}?t={int(start or 0)}"

def main():
    c = sqlite3.connect(DB)
    vids = c.execute("select id,title,duration,views,likes,comments,upload_date from videos order by upload_date desc").fetchall()
    out = []
    for vid, title, dur, views, likes, comments, up in vids:
        rows = c.execute("select kind,label,detail,start from content_graph where video_id=? order by start", (vid,)).fetchall()
        topics = [{"label": l, "start": s, "link": link(vid, s)} for k, l, d, s in rows if k == "topics" and l]
        counts = {}
        for k, *_ in rows: counts[k] = counts.get(k, 0) + 1
        out.append({"id": vid, "title": title, "duration": dur, "views": views, "likes": likes,
                    "comments": comments, "upload_date": up, "url": f"https://youtu.be/{vid}",
                    "topics": topics, "graph_counts": counts})
    json.dump(out, open(OUT, "w"), indent=2)
    print(f"wrote {len(out)} videos, {sum(len(v['topics']) for v in out)} topics -> {OUT}")

if __name__ == "__main__":
    main()
