# Perkins v2 platform image — one image, multiple entrypoints (Cloud Run service + Jobs).
#   Service (default):  uvicorn api.app:app          (auth-gated FastAPI)
#   Jobs override CMD:  python -m jobs.<name>         (ingest_worker, embed_job, render_job, article_job, social_job, archive_job, propose_series_job, promote_job)
FROM python:3.12-slim

# ffmpeg for the render/archive pipelines (yt-dlp merge + fuse)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# deno — REQUIRED by yt-dlp, not optional tooling. YouTube gates media URLs behind a JS
# "n-challenge"; yt-dlp solves it with `--remote-components ejs:github` (see
# adapters/yt_dlp.pull_video), which needs a JS runtime on PATH. Without it EVERY download
# exits 1, which is exactly what happened on archive-52md7 (2026-07-28): 15/15 errored while
# the container still exited 0. It worked on a developer laptop only because deno happened to
# be installed there — the same "only exists on one machine" fault as yt-dlp missing from
# requirements.txt.
# Copied from the official binary-only image rather than piping an install script through sh.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /srv
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The v2 layout: pure logic (core), I/O (adapters), serving (api), batch (jobs) + legacy app/
COPY core ./core
COPY adapters ./adapters
COPY api ./api
COPY jobs ./jobs
COPY scripts ./scripts
COPY app ./app
COPY assets ./assets

ENV PORT=8080 PERKINS_ENV=prod

# Run unprivileged — applies to the service default and every `python -m jobs.<name>`
# override. Created after COPY so /srv can be chowned to the non-root user.
RUN groupadd -r -g 10001 appgroup \
    && useradd -r -u 10001 -g appgroup appuser \
    && chown -R appuser:appgroup /srv
USER appuser

CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
