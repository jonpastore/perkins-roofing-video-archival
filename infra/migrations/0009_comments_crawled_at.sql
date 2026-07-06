-- Track when each video's YouTube comments were last crawled so the crawl cron can
-- rotate through the whole catalog (least-recently-crawled first) over successive runs.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS comments_crawled_at TIMESTAMP;
