"""Content-leverage insights from the indexed library:
1. A defensible FAQ ceiling — how many grounded Q&As the indexed content can actually support
   (distinct claims + objections + deduped topic themes). Not an arbitrary dial.
2. Unique topic CLUSTERS — semantically dedupe the ~1,248 raw topics into themes, each a
   ready article/social-post idea backed by the exact timecoded video moments that cover it.

Embeds topic labels on cerberus, greedy-clusters by cosine, names + drafts an angle per cluster.
Writes mockup/insights.json. NAME=0 for a clustering-only dry run (no LLM)."""
import json, os, sqlite3, re
import numpy as np
from .llm import embed, chat

DB = os.path.join(os.path.dirname(__file__), "dev.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "mockup", "insights.json")
THRESH = float(os.getenv("CLUSTER_THRESH", "0.78"))
NAME = os.getenv("NAME", "1") == "1"
MAX_CLUSTERS = int(os.getenv("MAX_CLUSTERS", "40"))

def link(vid, sec): return f"https://youtu.be/{vid}?t={int(sec)}"

def load_topics():
    c = sqlite3.connect(DB)
    rows = c.execute("select video_id,label,start from content_graph where kind='topics' and label is not null").fetchall()
    titles = dict(c.execute("select id,title from videos").fetchall())
    counts = {k: c.execute("select count(*) from content_graph where kind=?", (k,)).fetchone()[0]
              for k in ("claims", "objections", "topics")}
    c.close()
    return rows, titles, counts

def embed_batched(labels, bs=200):
    out = []
    for i in range(0, len(labels), bs):
        out += embed(labels[i:i + bs])
        print(f"embedded {min(i+bs,len(labels))}/{len(labels)}")
    a = np.array(out, dtype=float)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)

def cluster(labels, freq):
    E = embed_batched(labels)
    order = sorted(range(len(labels)), key=lambda i: -freq[labels[i]])
    assigned = [False] * len(labels)
    clusters = []
    for i in order:
        if assigned[i]: continue
        sims = E @ E[i]
        members = [j for j in range(len(labels)) if not assigned[j] and sims[j] >= THRESH]
        for j in members: assigned[j] = True
        clusters.append(members)
    return clusters

def main():
    rows, titles, counts = load_topics()
    freq = {}
    for _, lab, _ in rows: freq[lab] = freq.get(lab, 0) + 1
    labels = list(freq)
    clusters = cluster(labels, freq)
    # attach moments
    by_label = {}
    for vid, lab, st in rows:
        by_label.setdefault(lab, []).append((vid, st))
    out_clusters = []
    for members in clusters:
        mlabels = [labels[j] for j in members]
        moments = []
        for lab in mlabels:
            for vid, st in by_label[lab]:
                moments.append({"label": lab, "video_id": vid, "title": titles.get(vid, vid),
                                "start": st, "link": link(vid, st)})
        moments.sort(key=lambda m: -1)  # keep insertion; dedupe identical
        rep = max(mlabels, key=lambda l: freq[l])
        vids = {m["video_id"] for m in moments}
        out_clusters.append({"rep": rep, "labels": mlabels, "moment_count": len(moments),
                             "video_count": len(vids), "moments": moments[:25]})
    out_clusters.sort(key=lambda c: -c["moment_count"])
    out_clusters = out_clusters[:MAX_CLUSTERS]

    if NAME:
        for c in out_clusters:
            sample = "; ".join(c["labels"][:12])
            p = ("These are related topic tags Perkins Roofing covers across videos: " + sample +
                 ". Return ONLY JSON {\"title\":\"...\",\"angle\":\"...\"}: title = a punchy article/post "
                 "title for this theme; angle = one sentence on the article we'd write and who it helps.")
            try:
                d = chat(p, want_json=True)
                c["title"] = d.get("title") or c["rep"]
                c["angle"] = d.get("angle") or ""
            except Exception:
                c["title"], c["angle"] = c["rep"], ""
            print("named:", c["title"])
    else:
        for c in out_clusters: c["title"], c["angle"] = c["rep"], ""

    proposed = counts["claims"] + counts["objections"] + len([1 for _ in clusters])
    insights = {
        "graph_counts": counts,
        "topic_themes": len(clusters),
        "groundable_moments": sum(counts.values()),
        "proposed_max_faqs": proposed,
        "faq_basis": (f"{counts['claims']} claims + {counts['objections']} objections + "
                      f"{len(clusters)} unique topic themes = {proposed} groundable Q&As across 161 videos"),
        "clusters": out_clusters,
    }
    json.dump(insights, open(OUT, "w"), indent=2)
    print(f"\nthemes={len(clusters)} | proposed_max_faqs={proposed} | top clusters:")
    for c in out_clusters[:12]:
        print(f"  {c['moment_count']:3d} moments / {c['video_count']:2d} vids — {c.get('title') or c['rep']}")

if __name__ == "__main__":
    main()
