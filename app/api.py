"""FastAPI serving layer (online). Ingestion runs as a separate Cloud Run Job in prod —
do NOT run ingestion in the request lifecycle (council requirement: split serving from ingest)."""
import json
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import answer as A
from . import ingest as I
from . import retrieval as R
from .models import SessionLocal, Video
from .observability import Cost

app = FastAPI(title="Perkins Video Intelligence API", version="1.0")
_HERE = os.path.dirname(__file__)
app.mount("/widget", StaticFiles(directory=os.path.join(_HERE, "widget"), html=True), name="widget")

class Query(BaseModel):
    query: str
    k: int = 8

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/search")
def search(q: Query):
    return R.search(q.query, q.k)

@app.post("/ask")
def ask(q: Query):
    return A.ask(q.query, q.k)

@app.get("/status")
def status():
    s = SessionLocal()
    n = s.query(Video).count()
    s.close()
    return {"videos_indexed": n, "cost": Cost.report(), "stages_sample": I.status()[:20]}

@app.get("/faq")
def faq():
    p = os.path.join(_HERE, "generated", "faq_seed.json")
    return json.load(open(p)) if os.path.exists(p) else []

# Dev convenience only — in prod this is a Cloud Run Job, not an HTTP endpoint.
@app.post("/ingest/{video_id}")
def ingest(video_id: str):
    return I.ingest_video(video_id)
