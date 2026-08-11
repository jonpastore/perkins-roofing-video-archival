-- Generated video descriptions for the approval queue.
--
-- The reviewer presses "Generate description" on a proposal; the API reads the transcript we
-- already hold in `segments`, renders VIDEO_DESCRIPTION_PROMPT against it, calls Vertex, and
-- stores the result HERE rather than handing it back as throwaway text. Same shape as the other
-- generated artefacts on this table (clips_generated_at, comments_crawled_at): the content plus
-- when it was made and what made it, so a description can be told apart from a hand-written one
-- and regenerated when the prompt changes.
--
-- description_model records the LLM that produced it. Without it, a description written under an
-- older prompt/model is indistinguishable from a current one, and "regenerate everything the old
-- model wrote" becomes impossible to express.

ALTER TABLE videos ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS description_generated_at TIMESTAMP;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS description_model TEXT;
