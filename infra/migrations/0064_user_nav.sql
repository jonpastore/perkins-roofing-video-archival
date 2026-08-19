-- Sidebar pins / folded sections / icon-rail live on the user profile so they
-- follow the signed-in account, not the browser.

ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS nav JSONB NOT NULL DEFAULT '{}'::jsonb;
