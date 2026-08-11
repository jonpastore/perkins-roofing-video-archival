# Perkins v2 platform image — one image, multiple entrypoints (Cloud Run service + Jobs).
#   Service (default):  uvicorn api.app:app          (auth-gated FastAPI)
#   Jobs override CMD:  python -m jobs.<name>         (ingest_worker, embed_job, render_job, article_job, social_job, archive_job, propose_series_job, promote_job)
FROM python:3.12-slim

# ffmpeg for the render/archive pipelines (yt-dlp merge + fuse).
# curl + ca-certificates are build-time only, for the wireproxy release fetch below — the slim
# base has neither, and the RUN that needs them fails without this.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# deno — REQUIRED by yt-dlp, not optional tooling. YouTube gates media URLs behind a JS
# "n-challenge"; yt-dlp solves it with `--remote-components ejs:github` (see
# adapters/yt_dlp.pull_video), which needs a JS runtime on PATH. Without it EVERY download
# exits 1, which is exactly what happened on archive-52md7 (2026-07-28): 15/15 errored while
# the container still exited 0. It worked on a developer laptop only because deno happened to
# be installed there — the same "only exists on one machine" fault as yt-dlp missing from
# requirements.txt.
# Copied from the official binary-only image rather than piping an install script through sh.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# wireproxy — userspace WireGuard exposing SOCKS5. Required because YouTube bot-blocks
# datacenter egress (15/15 downloads from Cloud Run, cookies verified loaded and irrelevant),
# and a kernel WireGuard tunnel needs a TUN device + NET_ADMIN that Cloud Run does not grant.
# Userspace needs no privileges at all — verified in a container with neither.
# See core/wireproxy.py for the measured exit-IP evidence.
# Version-pinned: the upstream repo has changed owner (pufferffish -> windtf), so an unpinned
# pull would track a moved namespace.
ARG WIREPROXY_VERSION=v1.1.3
RUN curl -fsSL "https://github.com/windtf/wireproxy/releases/download/${WIREPROXY_VERSION}/wireproxy_linux_amd64.tar.gz" \
      -o /tmp/wireproxy.tgz \
 && tar -xzf /tmp/wireproxy.tgz -C /usr/local/bin wireproxy \
 && chmod +x /usr/local/bin/wireproxy \
 && rm /tmp/wireproxy.tgz

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
# The coastline / tidal / zones assets core.salt_water reads. Same path as the repo so the module
# needs no environment-specific lookup — and without this COPY the estimator's salt-water check
# would import fine, deploy fine, and 500 on the first call with the file simply not there.
# ~24 MB; loaded lazily into numpy (~20 MB resident) on first use, not at import.
COPY wp-plugin/perkins-metal-warranty/assets ./wp-plugin/perkins-metal-warranty/assets

ENV PORT=8080 PERKINS_ENV=prod

# Run unprivileged — applies to the service default and every `python -m jobs.<name>`
# override. Created after COPY so /srv can be chowned to the non-root user.
RUN groupadd -r -g 10001 appgroup \
    && useradd -r -u 10001 -g appgroup appuser \
    && chown -R appuser:appgroup /srv
USER appuser

CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
