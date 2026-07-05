"""v2 FastAPI serving surface — auth-gated (Firebase ID token + core.authz role matrix).
This is the PROD entrypoint (replaces the unauthenticated app/api.py). Search/ask require an
authenticated sales|admin caller; /internal/promote is the Cloud Scheduler target, protected
at the Cloud Run IAM layer (scheduler-sa OIDC, run.invoker)."""
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from api.routes.archive import router as archive_router
from api.routes.email import router as email_router
from api.routes.video import router as video_router
from app import answer as A
from app import retrieval as R

app = FastAPI(title="Perkins Video Intelligence API", version="2.0")
app.include_router(email_router)
app.include_router(video_router)
app.include_router(archive_router)


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


def _require_internal(x_internal_secret: str = Header(default="")):
    """Guard for /internal/* cron targets. The service is GCP-IAM-open so the browser SPA can
    reach the Firebase-authed routes; the internal cron routes are protected here by a shared
    secret (INTERNAL_SECRET env, set on the scheduler headers). Denies if unset/mismatched."""
    import os
    expected = os.getenv("INTERNAL_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/internal/promote", dependencies=[Depends(_require_internal)])
def promote():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Promotes due scheduled_content."""
    from jobs.promote_job import run
    return run()


@app.post("/internal/social", dependencies=[Depends(_require_internal)])
def social():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Publishes awaiting_social reels."""
    from jobs.social_job import run
    return run()


@app.get("/status")
def status(_claims=Depends(require_role("view_status"))):
    """Admin observability (Req 6): corpus + pipeline + content counts, last errors."""
    from sqlalchemy import func

    from app.models import (Article, Chunk, IngestionRun, ScheduledContent,
                            SessionLocal, Video)
    s = SessionLocal()
    try:
        errors = [
            {"video_id": r.video_id, "stage": r.stage, "error": (r.last_error or "")[:200]}
            for r in s.query(IngestionRun).filter(IngestionRun.status == "error").limit(20)
        ]
        return {
            "videos": s.query(func.count(Video.id)).scalar(),
            "videos_embedded": s.query(func.count(func.distinct(Chunk.video_id))).scalar(),
            "videos_archived": s.query(func.count(Video.id)).filter(Video.archive_uri.isnot(None)).scalar(),
            "transcripts_done": s.query(func.count(IngestionRun.id)).filter(
                IngestionRun.stage == "transcript", IngestionRun.status == "done").scalar(),
            "articles": s.query(func.count(Article.slug)).scalar(),
            "scheduled_content": s.query(func.count(ScheduledContent.id)).scalar(),
            "failed_stages": errors,
        }
    finally:
        s.close()
