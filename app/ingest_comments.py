"""Prototype of the Phase-2 recurring comment pull. Scrapes comments via yt-dlp (no API key),
derives count + unique commenters + an LLM summary of what viewers are saying / asking — the
signal Perkins uses for engagement + content ideas. Writes mockup/comments.json.

Runs over the top-N indexed videos by comment count (the rest are handled by the recurring
job in production). Idempotent: skips videos already in the output file."""
import json, os, sqlite3, subprocess, glob, tempfile, sys
from .llm import chat

DB = os.path.join(os.path.dirname(__file__), "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "mockup", "comments.json")
TOP_N = int(os.getenv("COMMENTS_TOP_N", "40"))

def scrape(vid):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["yt-dlp", "--skip-download", "--write-comments",
                        "--extractor-args", "youtube:comment_sort=top;max_comments=120,all,0,0",
                        "-o", f"{td}/%(id)s.%(ext)s", f"https://youtu.be/{vid}"],
                       capture_output=True, timeout=180)
        f = glob.glob(f"{td}/{vid}*.info.json")
        if not f: return []
        d = json.load(open(f[0]))
        return d.get("comments") or []

def summarize(title, comments):
    texts = [c.get("text", "") for c in comments if c.get("text")]
    if len(texts) < 3:
        return "Too few comments to summarize."
    blob = "\n".join(f"- {t}" for t in texts[:80])
    prompt = ("You analyze YouTube comments for a roofing company to find engagement and content "
              "opportunities. In 3-4 sentences summarize what viewers are saying and asking on this "
              f"video ('{title}'). Note any buying-intent questions, recurring themes, or content "
              f"ideas Perkins could make. Comments:\n{blob}")
    return chat(prompt)

def main():
    done = {}
    if os.path.exists(OUT):
        done = {d["id"]: d for d in json.load(open(OUT))}
    c = sqlite3.connect(DB)
    vids = c.execute("select id,title,comments from videos where comments>=2 order by comments desc limit ?",
                     (TOP_N,)).fetchall()
    out = list(done.values())
    for i, (vid, title, cc) in enumerate(vids, 1):
        if vid in done:
            print(f"[{i}/{len(vids)}] skip {vid} (cached)"); continue
        try:
            cm = scrape(vid)
            authors = {c.get("author_id") or c.get("author") for c in cm if (c.get("author_id") or c.get("author"))}
            rec = {"id": vid, "title": title, "count": len(cm), "reported_count": cc,
                   "unique_commenters": len(authors),
                   "top": [{"author": c.get("author"), "text": (c.get("text") or "")[:240],
                            "likes": c.get("like_count")} for c in cm[:5]],
                   "summary": summarize(title, cm)}
        except Exception as e:
            rec = {"id": vid, "title": title, "count": 0, "reported_count": cc,
                   "unique_commenters": 0, "top": [], "summary": f"(ingest error: {e})"}
        out.append(rec)
        json.dump(out, open(OUT, "w"), indent=2)  # checkpoint each video
        print(f"[{i}/{len(vids)}] {vid}: {rec['count']} comments, {rec['unique_commenters']} unique")
    print("wrote", OUT)

if __name__ == "__main__":
    main()
