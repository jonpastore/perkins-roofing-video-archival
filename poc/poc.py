#!/usr/bin/env python3
"""
Perkins Roofing — Video Intelligence POC
Local proof-of-concept of the production pipeline, using only free compute:
  - yt-dlp                : pull video + word-level auto-captions (stands in for cloud STT)
  - cerberus Ollama       : nomic-embed-text (embeddings) + mistral-small3.2 (LLM)  [DEV ONLY]
  - SQLite + numpy        : stands in for Cloud SQL Postgres + pgvector

Proves end to end: ingest -> timed transcript (sentence + word) -> Content Graph
-> embeddings -> semantic timecoded search -> grounded RAG answer with youtu.be?t= links.

NOTE: cerberus is OUR dev box. The client build runs entirely in the client's own GCP
(managed Speech-to-Text + Vertex/Anthropic + Cloud SQL/pgvector). This POC only proves the
pipeline shape and the data model cheaply.

Usage:
  python3 poc.py ingest <video_id>
  python3 poc.py build  <video_id>
  python3 poc.py search "clay tiles"
  python3 poc.py ask    "what are red flags in a tile roof estimate?"
  python3 poc.py all    <video_id>          # ingest + build + demo queries
"""
import os, sys, json, glob, re, subprocess, sqlite3, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DB   = os.path.join(HERE, "perkins_poc.db")
OLLAMA = "http://cerberus-ai:11434"
EMBED_MODEL = "nomic-embed-text"
LLM_MODEL   = "mistral-small3.2:24b"
os.makedirs(DATA, exist_ok=True)

# ---------------------------------------------------------------- cerberus (Ollama)
def _post(path, payload, timeout=180):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def embed(texts):
    out = _post("/api/embed", {"model": EMBED_MODEL, "input": texts})
    return out["embeddings"]

def llm(prompt, want_json=False, timeout=240):
    opts = {"temperature": 0.1 if want_json else 0.4, "num_ctx": 8192}
    out = _post("/api/generate", {"model": LLM_MODEL, "prompt": prompt,
                                  "stream": False, "options": opts}, timeout=timeout)
    txt = out.get("response", "")
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    if want_json:
        a, b = txt.find("{"), txt.rfind("}")
        if a != -1 and b != -1:
            try: return json.loads(txt[a:b+1])
            except Exception: pass
        return {}
    return txt

# ---------------------------------------------------------------- db
SCHEMA = """
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, title TEXT, duration REAL, upload_date TEXT,
  views INTEGER, likes INTEGER, comments INTEGER, url TEXT);
CREATE TABLE IF NOT EXISTS sentences(
  id INTEGER PRIMARY KEY, video_id TEXT, text TEXT, start REAL, end REAL);
CREATE TABLE IF NOT EXISTS words(
  id INTEGER PRIMARY KEY, video_id TEXT, word TEXT, start REAL, confidence REAL);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, video_id TEXT, text TEXT, start REAL, end REAL, embedding TEXT);
CREATE TABLE IF NOT EXISTS content_graph(
  id INTEGER PRIMARY KEY, video_id TEXT, kind TEXT, label TEXT, detail TEXT, start REAL);
"""
def db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA); return c

# ---------------------------------------------------------------- ingest
def ingest(vid):
    url = f"https://www.youtube.com/watch?v={vid}"
    print(f"[ingest] {url}")
    cmd = ["yt-dlp", "--no-warnings",
           "-f", "18/best[ext=mp4][vcodec!=none][acodec!=none]",
           "--write-info-json", "--write-auto-subs", "--sub-langs", "en.*,en",
           "--sub-format", "json3", "--convert-subs", "none",
           "-o", os.path.join(DATA, "%(id)s.%(ext)s"), url]
    subprocess.run(cmd, check=True)
    mp4 = glob.glob(os.path.join(DATA, f"{vid}.mp4")) + glob.glob(os.path.join(DATA, f"{vid}.*"))
    print(f"[ingest] files: {sorted(set(os.path.basename(p) for p in mp4))}")
    return vid

def _find(vid, ext):
    g = glob.glob(os.path.join(DATA, f"{vid}*{ext}"))
    return g[0] if g else None

def parse_captions(vid):
    """json3 auto-captions -> sentences (caption lines) + words (per-token timing)."""
    path = _find(vid, ".json3")
    if not path: raise RuntimeError(f"no json3 captions for {vid}")
    j = json.load(open(path))
    sentences, words = [], []
    for ev in j.get("events", []):
        segs = ev.get("segs")
        if not segs: continue
        t0 = ev.get("tStartMs", 0) / 1000.0
        dur = ev.get("dDurationMs", 0) / 1000.0
        line = "".join(s.get("utf8", "") for s in segs).strip()
        if not line or line == "\n": continue
        for s in segs:
            w = s.get("utf8", "").strip()
            if w:
                words.append((vid, w, t0 + s.get("tOffsetMs", 0) / 1000.0, None))
        sentences.append((vid, line, t0, t0 + dur))
    return sentences, words

def chunk(sentences, size=6):
    out = []
    for i in range(0, len(sentences), size):
        grp = sentences[i:i+size]
        text = " ".join(s[1] for s in grp)
        out.append((text, grp[0][2], grp[-1][3]))
    return out

# ---------------------------------------------------------------- content graph
def extract_graph(vid, sentences):
    timed = "\n".join(f"[{int(s[2]//60):02d}:{int(s[2]%60):02d}] {s[1]}" for s in sentences)
    prompt = f"""You are extracting a knowledge index from a roofing video transcript.
Return ONLY JSON: {{"topics":[{{"label":"","ts":"mm:ss"}}],
"claims":[{{"detail":"","ts":"mm:ss"}}],
"objections":[{{"detail":"","ts":"mm:ss"}}],
"ctas":[{{"detail":"","ts":"mm:ss"}}]}}
Topics = roofing subjects discussed (materials, techniques, problems). Claims = recommendations/
warnings the speaker makes. Objections = concerns/red-flags addressed. CTAs = calls to action.
Use timecodes from the transcript. Be concise, max 8 per list.

TRANSCRIPT:
{timed[:9000]}"""
    g = llm(prompt, want_json=True)
    def secs(ts):
        try: m, s = ts.split(":"); return int(m)*60+int(s)
        except Exception: return 0
    rows = []
    for kind in ("topics","claims","objections","ctas"):
        for it in g.get(kind, []) or []:
            rows.append((vid, kind, it.get("label",""), it.get("detail",""), secs(it.get("ts","0:0"))))
    return rows

# ---------------------------------------------------------------- build
def build(vid):
    c = db()
    c.execute("DELETE FROM videos WHERE id=?", (vid,))            # idempotent rebuild
    for t in ("sentences","words","chunks","content_graph"):
        c.execute(f"DELETE FROM {t} WHERE video_id=?", (vid,))
    info_path = _find(vid, ".info.json")
    info = json.load(open(info_path)) if info_path else {}
    c.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?,?,?,?,?)",
        (vid, info.get("title",""), info.get("duration",0), info.get("upload_date",""),
         info.get("view_count"), info.get("like_count"), info.get("comment_count"),
         f"https://youtu.be/{vid}"))
    sents, words = parse_captions(vid)
    c.executemany("INSERT INTO sentences(video_id,text,start,end) VALUES(?,?,?,?)", sents)
    c.executemany("INSERT INTO words(video_id,word,start,confidence) VALUES(?,?,?,?)", words)
    print(f"[build] {len(sents)} sentences, {len(words)} words")
    chs = chunk(sents)
    vecs = embed([t for t,_,_ in chs])
    for (text,st,en),v in zip(chs, vecs):
        c.execute("INSERT INTO chunks(video_id,text,start,end,embedding) VALUES(?,?,?,?,?)",
                  (vid, text, st, en, json.dumps(v)))
    print(f"[build] {len(chs)} chunks embedded (dim={len(vecs[0])})")
    rows = extract_graph(vid, sents)
    c.executemany("INSERT INTO content_graph(video_id,kind,label,detail,start) VALUES(?,?,?,?,?)", rows)
    print(f"[build] content graph: {len(rows)} items")
    c.commit(); c.close()

# ---------------------------------------------------------------- search / ask
import numpy as np
def _matrix(c):
    rows = c.execute("SELECT video_id,text,start,end,embedding FROM chunks").fetchall()
    M = np.array([json.loads(r[4]) for r in rows], dtype=np.float32)
    return rows, M

def link(vid, start): return f"https://youtu.be/{vid}?t={int(start)}"

def search(query, k=5):
    c = db(); rows, M = _matrix(c)
    if not rows: raise SystemExit("no data — run build first")
    q = np.array(embed([query])[0], dtype=np.float32)
    sims = M @ q / (np.linalg.norm(M,axis=1)*np.linalg.norm(q)+1e-9)
    print(f'\nResults for "{query}":\n' + "="*60)
    for i in sims.argsort()[::-1][:k]:
        vid,text,st,en,_ = rows[i]
        print(f"[{sims[i]:.2f}] {link(vid,st)}")
        print(f"      {text[:140].strip()}…\n")
    c.close()

def ask(query, k=5):
    c = db(); rows, M = _matrix(c)
    if not rows: raise SystemExit("no data — run build first")
    q = np.array(embed([query])[0], dtype=np.float32)
    sims = M @ q / (np.linalg.norm(M,axis=1)*np.linalg.norm(q)+1e-9)
    ctx, vids = [], set()
    for i in sims.argsort()[::-1][:k]:
        vid,text,st,en,_ = rows[i]; vids.add(vid)
        ctx.append(f"(source {link(vid,st)}) {text}")
    # HYBRID: fuse the deterministic Content Graph (key points) for the matched video(s)
    gp = []
    for vid in vids:
        for kind,label,detail,st in c.execute(
            "SELECT kind,label,detail,start FROM content_graph WHERE video_id=? "
            "AND kind IN ('objections','claims','ctas')", (vid,)).fetchall():
            gp.append(f"(key point, source {link(vid,st)}) {label or detail}")
    prompt = ("Answer the homeowner's question using ONLY the material below. Cite the source "
              "link after each point. Prefer the KEY POINTS (they are verified facts from the "
              "video). If not covered, say so.\n\n"
              f"QUESTION: {query}\n\nKEY POINTS:\n" + "\n".join(gp[:20]) +
              "\n\nTRANSCRIPT EXCERPTS:\n" + "\n\n".join(ctx))
    print(f'\nQ: {query}\n' + "="*60)
    print(llm(prompt))
    c.close()

def demo(vid):
    print("\n" + "#"*60 + "\n# CONTENT GRAPH\n" + "#"*60)
    c = db()
    for kind in ("topics","claims","objections","ctas"):
        items = c.execute("SELECT label,detail,start FROM content_graph WHERE video_id=? AND kind=?",(vid,kind)).fetchall()
        print(f"\n{kind.upper()}:")
        for label,detail,st in items:
            print(f"  [{int(st//60):02d}:{int(st%60):02d}] {label or detail}  -> {link(vid,st)}")
    c.close()
    search("clay tile roof")
    ask("What are red flags to watch for in a tile roof estimate?")

# ---------------------------------------------------------------- batch (captions-only)
def ingest_captions(vid):
    url = f"https://www.youtube.com/watch?v={vid}"
    cmd = ["yt-dlp","--no-warnings","--skip-download","--write-info-json",
           "--write-auto-subs","--sub-langs","en.*,en","--sub-format","json3",
           "--convert-subs","none","-o",os.path.join(DATA,"%(id)s.%(ext)s"),url]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def batch(idfile):
    ids = [l.split('|')[0].strip() for l in open(idfile) if l.strip()]
    c = db(); done = {r[0] for r in c.execute("SELECT id FROM videos").fetchall()}; c.close()
    print(f"[batch] {len(ids)} ids, {len(done)} already done", flush=True)
    ok = fail = 0
    for i, vid in enumerate(ids, 1):
        if vid in done:
            continue
        try:
            ingest_captions(vid); build(vid); ok += 1
            print(f"[batch {i}/{len(ids)}] OK {vid}", flush=True)
        except Exception as e:
            fail += 1
            print(f"[batch {i}/{len(ids)}] FAIL {vid}: {str(e)[:80]}", flush=True)
    print(f"[batch] DONE ok={ok} fail={fail}", flush=True)

# ---------------------------------------------------------------- cli
if __name__ == "__main__":
    if len(sys.argv) < 2: print(__doc__); sys.exit(0)
    cmd = sys.argv[1]; arg = sys.argv[2] if len(sys.argv) > 2 else None
    if   cmd == "ingest": ingest(arg)
    elif cmd == "build":  build(arg)
    elif cmd == "search": search(arg)
    elif cmd == "ask":    ask(arg)
    elif cmd == "all":    ingest(arg); build(arg); demo(arg)
    elif cmd == "batch":  batch(arg)
    else: print(__doc__)
