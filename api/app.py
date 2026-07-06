"""v2 FastAPI serving surface — auth-gated (Firebase ID token + core.authz role matrix).
This is the PROD entrypoint (replaces the unauthenticated app/api.py). Search/ask require an
authenticated sales|admin caller; /internal/promote is the Cloud Scheduler target, protected
at the Cloud Run IAM layer (scheduler-sa OIDC, run.invoker)."""
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.auth import current_claims, require_role
from api.routes.archive import router as archive_router
from api.routes.articles import router as articles_router
from api.routes.clips import router as clips_router
from api.routes.comments import router as comments_router
from api.routes.logs import router as logs_router
from api.routes.config import router as config_router
from api.routes.email import router as email_router
from api.routes.faq import router as faq_router
from api.routes.scheduling import router as scheduling_router
from api.routes.suggestions import router as suggestions_router
from api.routes.topics import router as topics_router
from api.routes.users import router as users_router
from api.routes.video import router as video_router
from app import answer as A
from app import retrieval as R
from app.config import settings

app = FastAPI(title="Perkins Video Intelligence API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(email_router)
app.include_router(video_router)
app.include_router(archive_router)
app.include_router(articles_router)
app.include_router(scheduling_router)
app.include_router(topics_router)
app.include_router(faq_router)
app.include_router(config_router)
app.include_router(users_router)
app.include_router(suggestions_router)
app.include_router(clips_router)
app.include_router(comments_router)
app.include_router(logs_router)


class Query(BaseModel):
    query: str
    k: int = 8


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/me")
def me(claims=Depends(current_claims)):
    """Effective identity for the signed-in user — the SPA reads its role from here so
    default-admins resolve server-side (the source of truth), not from the raw token claim."""
    return {"email": claims.get("email"), "role": claims.get("role") or None}


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
    import hmac
    import os
    expected = os.getenv("INTERNAL_SECRET", "")
    if not expected or not hmac.compare_digest(x_internal_secret or "", expected):
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

    from app.models import (Article, Chunk, FaqEntry, IngestionRun,
                            ScheduledContent, SessionLocal, Video)
    s = SessionLocal()
    try:
        errors = [
            {
                "video_id": r.video_id,
                "stage": r.stage,
                "error": (r.last_error or "")[:200],
                "title": (v.title if v else None),
                "youtube_url": (v.url if v and v.url else f"https://youtu.be/{r.video_id}"),
            }
            for r, v in (
                s.query(IngestionRun, Video)
                .outerjoin(Video, Video.id == IngestionRun.video_id)
                .filter(IngestionRun.status == "error")
                .limit(20)
            )
        ]
        queue = [
            {
                "video_id": r.video_id,
                "title": (v.title if v else None),
                "stage": r.stage,
                "status": r.status,
            }
            for r, v in (
                s.query(IngestionRun, Video)
                .outerjoin(Video, Video.id == IngestionRun.video_id)
                .filter(IngestionRun.status.in_(["pending", "running"]))
                .order_by(IngestionRun.updated_at.desc())
                .limit(50)
            )
        ]
        return {
            "videos": s.query(func.count(Video.id)).scalar(),
            "videos_embedded": s.query(func.count(func.distinct(Chunk.video_id))).scalar(),
            "videos_archived": s.query(func.count(Video.id)).filter(Video.archive_uri.isnot(None)).scalar(),
            "transcripts_done": s.query(func.count(IngestionRun.id)).filter(
                IngestionRun.stage == "transcript", IngestionRun.status == "done").scalar(),
            "articles": s.query(func.count(Article.slug)).scalar(),
            "faq_count": s.query(func.count(FaqEntry.id)).scalar(),
            "scheduled_content": s.query(func.count(ScheduledContent.id)).scalar(),
            "failed_stages": errors,
            "queue": queue,
        }
    finally:
        s.close()


class RetryRequest(BaseModel):
    video_id: str
    stage: str


@app.post("/status/retry")
def status_retry(body: RetryRequest, _claims=Depends(require_role("view_status"))):
    """Reset a failed IngestionRun back to pending so the next ingest run reprocesses it.

    Finds all IngestionRun rows matching video_id + stage with status='error',
    clears last_error, and sets status='pending'. Returns {reset: <count>}.
    404 if no matching error row exists.
    """
    from app.models import IngestionRun, SessionLocal

    with SessionLocal() as s:
        rows = (
            s.query(IngestionRun)
            .filter(
                IngestionRun.video_id == body.video_id,
                IngestionRun.stage == body.stage,
                IngestionRun.status == "error",
            )
            .all()
        )
        if not rows:
            raise HTTPException(status_code=404, detail="No failed stage found for that video_id + stage")
        for row in rows:
            row.status = "pending"
            row.last_error = None
        s.commit()

    return {"reset": len(rows)}
