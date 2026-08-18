-- CompanyCam signed playback URLs exceed varchar(1000) and crash companycam-sync
-- (StringDataRightTruncation on upsert_video). TEXT matches the rest of media URIs.
ALTER TABLE companycam_photos ALTER COLUMN url TYPE TEXT;
ALTER TABLE companycam_videos ALTER COLUMN url TYPE TEXT;
ALTER TABLE companycam_videos ALTER COLUMN thumbnail_url TYPE TEXT;
