-- 0052_bid_projects.sql
-- A BID PROJECT: one job site, many structures, quoted together.
--
-- Jarvis #430/#449. Tim's Evergrene bid prices 9 buildings at 650 Evergrene Pkwy as ONE project.
-- We had no container for that, so every building was a standalone job and each one paid the full
-- once-per-project fee set AND its own $2,500 profit floor. Measured against the live jupiter
-- config (scripts/evergrene_gap_analysis.py): every building over by +10% to +85%, $24,000 of
-- once-per-project fees charged eight times, and $116,420 of project scope (General Conditions +
-- add-on blocks) with nowhere to live at all. The bid netted to -9% only because the over-charge
-- and the missing scope masked each other.
--
-- NAME. `companycam_projects` and `portfolio_projects` already exist, so a bare `projects` would
-- be the third unrelated thing called that. "Bid" is what this actually is and what Tim calls it
-- ("Evergrene Project Bid Spreadsheet") — a bid covering several structures. It is not an
-- `estimate` (one building's calculation) and not a `proposal` (the customer document); it OWNS
-- both.
--
-- Project-level money is JSONB rather than its own table on purpose: general_conditions is a short
-- list of labelled amounts a human types once per bid, it is never queried across projects, and a
-- child table would buy joins we would not use. If it ever needs per-line status or approval, that
-- is the moment to promote it.

CREATE TABLE IF NOT EXISTS bid_projects (
    id                      SERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    -- Evergrene is ONE address with nine structures, so a project usually hangs off one property.
    -- Nullable because a bid can exist before the property record does.
    property_id             INTEGER REFERENCES properties(id),
    name                    VARCHAR(300) NOT NULL,
    branch                  VARCHAR(100),
    code_zone               VARCHAR(10),

    -- General Conditions: site-wide costs that exist because the JOB exists, not because any one
    -- building does. Tim's Evergrene block is green fence + telehandler ($22,800) and a full-time
    -- PM ($9,000), marked up x1.15 to $36,570. Shape: [{"label": str, "amount": number}].
    general_conditions      JSONB NOT NULL DEFAULT '[]',
    general_conditions_markup NUMERIC(6,4) NOT NULL DEFAULT 1.0,

    -- Scope blocks that belong to the project rather than to a building. Tim attaches his to the
    -- Clubhouse ($42,050 sloped add-ons + $31,000 tile add-ons); carrying them here instead means
    -- the customer sees them as project scope and one building does not absorb someone else's
    -- cedar nailer. Same shape as general_conditions.
    add_on_blocks           JSONB NOT NULL DEFAULT '[]',

    -- Which normally-per-job fixed fees this project charges ONCE. Defaults to the three that are
    -- unambiguously per-site: you pull one permit, deliver to one site, and the bonus-values line
    -- is a per-contract figure. tile_dumpster is deliberately NOT here — a dump load is real and
    -- per-building. stories_3_5_delivery_chute is per structure, since a chute serves a building.
    once_per_project_fees   JSONB NOT NULL DEFAULT
                            '["permit_processing", "new_bonus_values", "delivery_plywood_vents"]',

    -- How the profit floor applies across the project.
    --   'project'  ONE floor for the whole bid (default). On Evergrene the natural margin is
    --              ~$30,363 so the floor never binds, which is what Tim actually did.
    --   'week'     weeks-on-site x weekly floor, per #449. MEASURED: on Evergrene that is 17
    --              weeks x $2,500 = $42,500 against Tim's own $30,363 — +40%. Available, not
    --              default, because the spec has not been reconciled with his bid yet.
    --   'building' the pre-project behaviour: every building pays its own floor. Kept so the
    --              change is reversible per project without a deploy.
    profit_floor_basis      VARCHAR(20) NOT NULL DEFAULT 'project',

    status                  VARCHAR(30) NOT NULL DEFAULT 'draft',
    notes                   TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT now(),
    updated_at              TIMESTAMP NOT NULL DEFAULT now(),
    created_by              VARCHAR(320),
    CONSTRAINT ck_bid_projects_floor_basis
        CHECK (profit_floor_basis IN ('project', 'week', 'building')),
    CONSTRAINT ck_bid_projects_gc_markup
        CHECK (general_conditions_markup >= 1.0 AND general_conditions_markup <= 3.0)
);

CREATE INDEX IF NOT EXISTS ix_bid_projects_tenant ON bid_projects (tenant_id);
CREATE INDEX IF NOT EXISTS ix_bid_projects_property ON bid_projects (tenant_id, property_id);

ALTER TABLE bid_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE bid_projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bid_projects_tenant_isolation ON bid_projects;
CREATE POLICY bid_projects_tenant_isolation ON bid_projects
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);

-- Estimates and proposals join a project. Both nullable: a single-building quote has no project
-- and must keep behaving exactly as it does today.
ALTER TABLE estimates  ADD COLUMN IF NOT EXISTS bid_project_id INTEGER REFERENCES bid_projects(id);
ALTER TABLE proposals  ADD COLUMN IF NOT EXISTS bid_project_id INTEGER REFERENCES bid_projects(id);

-- A label for the structure within the bid ("Bus Stop", "Clubhouse Sloped"). Without it a project
-- is a list of nine anonymous estimates and nobody can tell which roof is which.
ALTER TABLE estimates  ADD COLUMN IF NOT EXISTS structure_name VARCHAR(200);

CREATE INDEX IF NOT EXISTS ix_estimates_bid_project ON estimates (bid_project_id);
CREATE INDEX IF NOT EXISTS ix_proposals_bid_project ON proposals (bid_project_id);
