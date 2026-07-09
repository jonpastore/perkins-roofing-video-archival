"""One-off dev utility: import the overnight POC corpus (poc/perkins_poc.db) into the
production app schema (app/dev.db) so the eval harness can run against the real 161-video
library without re-transcribing. Reuses already-computed embeddings + Content Graph."""
import json
import os
import sqlite3

from .config import settings
from .models import Chunk, GraphNode, SessionLocal, Video, init_db

POC = os.path.join(os.path.dirname(__file__), "..", "poc", "perkins_poc.db")

def run():
    init_db()
    src = sqlite3.connect(POC)
    s = SessionLocal()
    for t in (Chunk, GraphNode, Video):
        s.query(t).delete()
    s.commit()
    for row in src.execute("SELECT id,title,duration,upload_date,views,likes,comments,url FROM videos"):
        s.add(Video(id=row[0], title=row[1], duration=row[2], upload_date=row[3],
                    views=row[4], likes=row[5], comments=row[6], url=row[7]))
    g = 0
    for vid, kind, label, detail, start in src.execute(
            "SELECT video_id,kind,label,detail,start FROM content_graph"):
        s.add(GraphNode(video_id=vid, kind=kind, label=label, detail=detail, start=start, version="v1")); g += 1
    n = 0
    for vid, text, start, end, emb in src.execute(
            "SELECT video_id,text,start,end,embedding FROM chunks"):
        s.add(Chunk(video_id=vid, text=text, start=start, end=end,
                    embedding=json.loads(emb), embed_model=settings.EMBED_MODEL, version="v1")); n += 1
        if n % 2000 == 0:
            s.commit()
    s.commit()
    vids = s.query(Video).count()
    s.close(); src.close()
    print(f"imported: {vids} videos, {g} graph nodes, {n} chunks")

if __name__ == "__main__":
    run()
