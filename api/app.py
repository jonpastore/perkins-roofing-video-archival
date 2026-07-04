"""v2 FastAPI serving surface — auth-gated (Firebase ID token + core.authz role matrix).
This is the PROD entrypoint (replaces the unauthenticated app/api.py). Search/ask require an
authenticated sales|admin caller; /internal/promote is the Cloud Scheduler target, protected
at the Cloud Run IAM layer (scheduler-sa OIDC, run.invoker)."""
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from api.auth import require_role
from app import answer as A
from app import retrieval as R

app = FastAPI(title="Perkins Video Intelligence API", version="2.0")


class Query(BaseModel):
    query: str
    k: int = 8


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/search")
def search(q: Query, _claims=Depends(require_role("search"))):
    return R.search(q.query, q.k)


@app.post("/ask")
def ask(q: Query, _claims=Depends(require_role("ask"))):
    return A.ask(q.query, q.k)


@app.post("/internal/promote")
def promote():
    """Cloud Scheduler target — authenticated at the Cloud Run IAM layer (scheduler-sa OIDC).
    Stub returning promoted=0 until Wave 2 implements scheduled_content promotion; exists now
    so the scheduler cron does not point at a 404."""
    return {"promoted": 0}
