"""One-shot: run the real grounded pipeline for a few homeowner questions and freeze the
results into a static JSON the Cloudflare mockup serves (no backend needed for client review)."""
import json
import os

from .answer import ask
from .models import SessionLocal, Video

QUESTIONS = [
    "What are the red flags in a metal roof estimate?",
    "What is the difference between snap lock and mechanically seamed standing seam metal roofs?",
    "What is the best roof for Florida hurricanes: shingle, tile, or metal?",
    "What should I look for when hiring a roofing contractor?",
    "What causes roof leaks?",
    "Should I repair or replace my roof?",
]

def title_map(vids):
    s = SessionLocal()
    m = {v.id: v.title for v in s.query(Video).filter(Video.id.in_(vids)).all()}
    s.close()
    return m

def main():
    out = []
    for q in QUESTIONS:
        r = ask(q)
        vids = [c.split("/")[-1].split("?")[0] for c in r.get("citations", [])]
        tm = title_map(set(vids))
        cites = [{"url": c, "title": tm.get(c.split("/")[-1].split("?")[0], "Perkins Roofing video")}
                 for c in r.get("citations", [])]
        out.append({"q": q, "answer": r["answer"], "abstained": r["abstained"],
                    "confidence": r["confidence"], "citations": cites})
        print(f"[{'ABSTAIN' if r['abstained'] else 'OK'} {r['confidence']}] {q}")
    p = os.path.join(os.path.dirname(__file__), "generated", "demo_answers.json")
    json.dump(out, open(p, "w"), indent=2)
    print("wrote", p)

if __name__ == "__main__":
    main()
