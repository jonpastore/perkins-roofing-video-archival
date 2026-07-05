# Perkins v2 platform image — one image, multiple entrypoints (Cloud Run service + Jobs).
#   Service (default):  uvicorn api.app:app          (auth-gated FastAPI)
#   Jobs override CMD:  python -m jobs.<name>         (ingest_worker, embed_job, render_job, article_job, social_job, archive_job, propose_series_job, promote_job)
FROM python:3.12-slim

# ffmpeg for the render/archive pipelines (yt-dlp merge + fuse)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The v2 layout: pure logic (core), I/O (adapters), serving (api), batch (jobs) + legacy app/
COPY core ./core
COPY adapters ./adapters
COPY api ./api
COPY jobs ./jobs
COPY app ./app

ENV PORT=8080 PERKINS_ENV=prod
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
