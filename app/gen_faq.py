"""Extract a website FAQ bank from video content: turn each video's Content-Graph points
(claims/objections/topics, each timecoded) into homeowner Q&A pairs, grounded, with a deep
link to the exact second the answer is given. This is the batch ('functionalized') version of
the ask/search pipeline. Writes mockup/faq.json. Re-runnable; skips videos already done.

Prototype of the Phase-2 FAQ-bank (500+) feature — here we run a representative subset."""
import json, os, sqlite3
from .llm import chat

DB = os.path.join(os.path.dirname(__file__), "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "mockup", "faq.json")
N_VIDEOS = int(os.getenv("FAQ_VIDEOS", "30"))
PER_VIDEO = int(os.getenv("FAQ_PER_VIDEO", "4"))

def link(vid, sec): return f"https://youtu.be/{vid}?t={int(sec)}"

def faqs_for(vid, title):
    c = sqlite3.connect(DB)
    pts = c.execute("select kind,label,detail,start from content_graph where video_id=? "
                    "and kind in ('claims','objections','topics') and start is not null "
                    "order by start", (vid,)).fetchall()
    c.close()
    if len(pts) < 3: return []
    secs = {int(s) for *_, s in pts}
    pts_txt = "\n".join(f"[sec={int(s)}] ({k}) {l or ''} — {d or ''}".strip() for k, l, d, s in pts[:16])
    prompt = ("You write website FAQ entries for Perkins Roofing from their own video content. "
              f"Using ONLY the timecoded points below from the video titled '{title}', write up to "
              f"{PER_VIDEO} homeowner FAQ entries. Return ONLY JSON: "
              '{"faqs":[{"q":"...","a":"...","sec":<the sec= number of the point used>}]}. '
              "q = a natural question a homeowner would type; a = a concise 1-2 sentence answer in "
              "Tim's voice; sec = the [sec=...] value where that answer is covered. Skip points that "
              f"don't make a clear Q&A.\n\nPOINTS:\n{pts_txt}")
    d = chat(prompt, want_json=True)
    out = []
    for f in (d.get("faqs") or []):
        try:
            sec = int(f.get("sec"))
        except Exception:
            continue
        if sec not in secs or not f.get("q") or not f.get("a"):
            continue
        out.append({"q": f["q"].strip(), "a": f["a"].strip(), "video_id": vid,
                    "title": title, "link": link(vid, sec), "sec": sec})
    return out

def main():
    bank = []
    if os.path.exists(OUT): bank = json.load(open(OUT))
    done = {b["video_id"] for b in bank}
    c = sqlite3.connect(DB)
    vids = c.execute("select id,title from videos where id in (select distinct video_id from content_graph) "
                     "order by views desc limit ?", (N_VIDEOS,)).fetchall()
    c.close()
    for i, (vid, title) in enumerate(vids, 1):
        if vid in done:
            print(f"[{i}/{len(vids)}] skip {vid}"); continue
        try:
            fs = faqs_for(vid, title)
        except Exception as e:
            print(f"[{i}/{len(vids)}] {vid} ERROR {e}"); continue
        bank.extend(fs)
        json.dump(bank, open(OUT, "w"), indent=2)  # checkpoint
        print(f"[{i}/{len(vids)}] {vid}: +{len(fs)} faqs ({len(bank)} total)")
    print("wrote", OUT, "—", len(bank), "FAQ entries")

if __name__ == "__main__":
    main()
