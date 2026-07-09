"""Offline ingestion worker — runs as a Cloud Run Job (NOT in the API request lifecycle;
council requirement: split serving from ingestion). Dev: `python3 -m app.worker <id|idfile>...`
Prod: a Pub/Sub push subscription invokes this with the video_id message body."""
import os
import sys

from .ingest import ingest_video
from .observability import Cost, log


def process(ids):
    for vid in ids:
        log("ingest_start", video_id=vid)
        try:
            st = ingest_video(vid)
            log("ingest_done", video_id=vid, stages={r["stage"]: r["status"] for r in st})
        except Exception as e:
            log("ingest_error", video_id=vid, error=str(e)[:200])
    log("ingest_batch_complete", count=len(ids), cost=Cost.report())

def main(argv):
    ids = []
    for a in argv:
        if os.path.isfile(a):
            ids += [l.strip() for l in open(a) if l.strip()]
        else:
            ids.append(a)
    process(ids)

if __name__ == "__main__":
    main(sys.argv[1:])
