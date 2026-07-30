-- 0051_gate_failures.sql
-- Persist WHY a project or an article was refused.
--
-- Both gates already compute this and then throw it away. core.article_criteria produces a full
-- compliance record that jobs/batch_article_job.py reduces to a log line, and
-- core.portfolio_criteria produces one that api/routes/portfolio.py returns in the 422 body and
-- nowhere else. So the moment the response is gone, nobody — human or agent — can answer "why is
-- this one not published?" without re-running the gate and hoping the inputs still match.
--
-- That is the difference between a gate that blocks and a gate that can be ACTED on. A queue of
-- refused items with their reasons attached is a work list: the generation loop can read it and
-- fix the specific criterion, and an editor can see "no scope matched" without opening a console.
--
-- Shape is the criteria list as the gate already emits it — [{key,label,ok,severity,detail,
-- evidence}] — filtered to the failing ones. Storing the gate's own structure rather than a
-- rendered string keeps it machine-correctable; a human-readable sentence is a lossy summary of
-- it, and building one here would drift from the checklist that actually decides.
--
-- Nullable with no default: NULL means "never gated", which is honestly different from [] meaning
-- "gated and clean". Code that cannot tell those apart reports unchecked items as passing.

ALTER TABLE portfolio_projects
    ADD COLUMN IF NOT EXISTS gate_failures    JSONB,
    ADD COLUMN IF NOT EXISTS gate_checked_at  TIMESTAMP;

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS gate_failures    JSONB,
    ADD COLUMN IF NOT EXISTS gate_checked_at  TIMESTAMP;

-- Finding the work list: "everything currently refused, worst first" is the query both the SPA
-- and any correction loop run, so index the refused rows rather than scanning every project.
CREATE INDEX IF NOT EXISTS ix_portfolio_projects_gate_failures
    ON portfolio_projects (tenant_id, gate_checked_at)
    WHERE gate_failures IS NOT NULL AND jsonb_array_length(gate_failures) > 0;

CREATE INDEX IF NOT EXISTS ix_articles_gate_failures
    ON articles (tenant_id, gate_checked_at)
    WHERE gate_failures IS NOT NULL AND jsonb_array_length(gate_failures) > 0;
